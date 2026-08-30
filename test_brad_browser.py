#!/usr/bin/env python3
"""Browser-backed benchmark for Brad comment collection.

Uses a dedicated persistent Playwright profile stored locally in
``brad_browser_profile``. This test targets the benchmark post and combines
rendered DOM extraction with Instagram's own structured comment objects.

The important rule: comments are deduplicated by Instagram comment ID whenever
available. A single account may leave any number of distinct comments.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

POST_URL = "https://www.instagram.com/p/Dclt_nKkUVg/"
POST_CODE = "Dclt_nKkUVg"
PROFILE_DIR = Path("brad_browser_profile").resolve()
DEBUG_DIR = Path("brad_data/browser_debug")

EXPAND_TEXT = re.compile(
    r"(view all .*comments|view more comments|load more comments|more comments|"
    r"view .*repl(?:y|ies)|more repl(?:y|ies)|see .*repl(?:y|ies))",
    re.I,
)


def click_expanders(page) -> int:
    """Click visible comment/reply expansion controls once."""
    clicked = 0
    candidates = page.locator("button, [role='button'], span, div")
    count = min(candidates.count(), 4000)
    for i in range(count):
        item = candidates.nth(i)
        try:
            if not item.is_visible():
                continue
            text = (item.inner_text(timeout=150) or "").strip()
            if not text or len(text) > 90 or not EXPAND_TEXT.search(text):
                continue
            item.click(timeout=700)
            page.wait_for_timeout(250)
            clicked += 1
        except Exception:
            pass
    return clicked


def scroll_comment_surfaces(page) -> None:
    """Advance the page and independently scrollable Instagram panels."""
    page.evaluate(
        r"""
        () => {
          window.scrollBy(0, Math.max(window.innerHeight * 0.8, 600));
          const els = [...document.querySelectorAll('div, section, main, article')];
          for (const el of els) {
            if (el.scrollHeight > el.clientHeight + 150 && el.clientHeight > 180) {
              const step = Math.max(el.clientHeight * 0.8, 500);
              el.scrollTop = Math.min(el.scrollTop + step, el.scrollHeight);
            }
          }
        }
        """
    )


def extract_dom_rows(page) -> list[dict]:
    """Extract rendered comment-like records, including Instagram comment IDs."""
    return page.evaluate(
        r"""
        () => {
          const root = document.querySelector('article') || document.body;
          const rows = [];
          const seen = new Set();

          function usernameFrom(el) {
            const links = [...el.querySelectorAll('a[href^="/"]')];
            for (const a of links) {
              const href = a.getAttribute('href') || '';
              const m = href.match(/^\/([^/?#]+)\/?$/);
              if (!m) continue;
              const u = m[1];
              if (['p', 'reel', 'reels', 'explore', 'accounts'].includes(u)) continue;
              return u;
            }
            return '';
          }

          function commentIdFrom(el) {
            const links = [...el.querySelectorAll('a[href*="/c/"]')];
            for (const a of links) {
              const href = a.getAttribute('href') || '';
              const m = href.match(/\/c\/(\d+)\/?/);
              if (m) return m[1];
            }
            return '';
          }

          function usefulText(el) {
            const clone = el.cloneNode(true);
            for (const bad of clone.querySelectorAll('svg, img, video')) bad.remove();
            return (clone.innerText || '').trim();
          }

          function add(el, source) {
            if (!el) return;
            const username = usernameFrom(el);
            const text = usefulText(el);
            if (!username || !text || text.length > 5000) return;
            const timeEl = el.querySelector('time');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText || '') : '';
            const comment_id = commentIdFrom(el);
            const normalizedText = text.replace(/\s+/g, ' ').trim();
            const key = comment_id || (username + '\n' + timestamp + '\n' + normalizedText);
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({
              comment_id,
              parent_comment_id: '',
              username,
              text,
              timestamp,
              likes: null,
              child_comment_count: null,
              is_reply: null,
              source
            });
          }

          for (const time of root.querySelectorAll('time')) {
            let el = time.parentElement;
            let best = null;
            for (let depth = 0; el && depth < 8; depth++, el = el.parentElement) {
              if (!root.contains(el)) break;
              const u = usernameFrom(el);
              const t = usefulText(el);
              if (u && t && t.length < 5000) {
                best = el;
                if (commentIdFrom(el)) break;
                if (el.matches('li, [role="listitem"]')) break;
              }
            }
            add(best, 'dom-time-anchor');
          }

          for (const el of root.querySelectorAll('li, [role="listitem"]')) {
            add(el, 'dom-listitem');
          }

          return rows;
        }
        """
    )


def extract_structured_comments(page) -> list[dict]:
    """Find Instagram XDTCommentDict objects embedded in JSON script payloads."""
    raw = page.evaluate(
        r"""
        () => {
          const out = [];
          const seen = new Set();

          function visit(value) {
            if (!value || typeof value !== 'object') return;
            if (Array.isArray(value)) {
              for (const item of value) visit(item);
              return;
            }

            const looksLikeComment =
              value.__typename === 'XDTCommentDict' ||
              (value.pk && typeof value.text === 'string' && value.user && value.user.username);

            if (looksLikeComment) {
              const id = String(value.pk || value.id || '');
              if (id && !seen.has(id)) {
                seen.add(id);
                out.push({
                  comment_id: id,
                  parent_comment_id: value.parent_comment_id ? String(value.parent_comment_id) : '',
                  username: value.user?.username || '',
                  text: value.text || '',
                  created_at: value.created_at || null,
                  likes: value.comment_like_count ?? null,
                  child_comment_count: value.child_comment_count ?? null,
                  is_edited: value.is_edited ?? null
                });
              }
            }

            for (const child of Object.values(value)) visit(child);
          }

          for (const script of document.querySelectorAll('script[type="application/json"]')) {
            const text = script.textContent || '';
            if (!text || text.length > 20000000) continue;
            try {
              visit(JSON.parse(text));
            } catch (_) {}
          }
          return out;
        }
        """
    )

    rows: list[dict] = []
    for item in raw:
        created_at = item.get("created_at")
        timestamp = ""
        if isinstance(created_at, (int, float)):
            timestamp = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        parent = item.get("parent_comment_id") or ""
        rows.append(
            {
                "comment_id": item.get("comment_id", ""),
                "parent_comment_id": parent,
                "username": item.get("username", ""),
                "text": item.get("text", ""),
                "timestamp": timestamp,
                "likes": item.get("likes"),
                "child_comment_count": item.get("child_comment_count"),
                "is_reply": bool(parent),
                "is_edited": item.get("is_edited"),
                "source": "instagram-structured-json",
            }
        )
    return rows


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def row_key(row: dict) -> tuple[str, ...]:
    """Use Instagram comment ID first; fall back only for caption/odd DOM rows."""
    comment_id = str(row.get("comment_id") or "")
    if comment_id:
        return ("comment_id", comment_id)
    return (
        "fallback",
        row.get("username", ""),
        row.get("timestamp", ""),
        normalize_text(row.get("text", "")),
    )


def merge_rows(archive: dict[tuple[str, ...], dict], rows: list[dict]) -> int:
    """Merge rows, preferring richer structured Instagram data for a known ID."""
    added = 0
    for row in rows:
        key = row_key(row)
        if key not in archive:
            archive[key] = row
            added += 1
            continue

        existing = archive[key]
        if row.get("source") == "instagram-structured-json":
            merged = dict(existing)
            for field, value in row.items():
                if value not in (None, ""):
                    merged[field] = value
            archive[key] = merged
    return added


def capture_all_sources(page, archive: dict[tuple[str, ...], dict]) -> tuple[int, int, int]:
    dom = extract_dom_rows(page)
    structured = extract_structured_comments(page)
    added = merge_rows(archive, dom)
    added += merge_rows(archive, structured)
    return len(dom), len(structured), added


def load_more(page, rounds: int = 300) -> list[dict]:
    """Expand, capture, and scroll until no new comment IDs appear."""
    archive: dict[tuple[str, ...], dict] = {}
    quiet_rounds = 0

    dom_n, structured_n, added = capture_all_sources(page, archive)
    print(
        f"Initial capture: DOM {dom_n}, structured {structured_n}, "
        f"new +{added}, total unique {len(archive)}"
    )

    for round_no in range(1, rounds + 1):
        _, _, added_before = capture_all_sources(page, archive)
        clicked = click_expanders(page)
        page.wait_for_timeout(350)
        _, _, added_click = capture_all_sources(page, archive)
        scroll_comment_surfaces(page)
        page.wait_for_timeout(800)
        dom_n, structured_n, added_scroll = capture_all_sources(page, archive)

        new_rows = added_before + added_click + added_scroll
        comment_ids = sum(1 for row in archive.values() if row.get("comment_id"))
        replies = sum(1 for row in archive.values() if row.get("parent_comment_id"))

        print(
            f"Loading round {round_no}: DOM {dom_n}, structured {structured_n}, "
            f"new +{new_rows}, unique IDs {comment_ids}, replies {replies}, "
            f"expand clicks {clicked}"
        )

        if new_rows == 0 and clicked == 0:
            quiet_rounds += 1
        else:
            quiet_rounds = 0

        if quiet_rounds >= 8:
            print("No new comment IDs or expansion controls for 8 rounds; stopping.")
            break

    capture_all_sources(page, archive)
    return list(archive.values())


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)

        print(f"Opened Brad benchmark post {POST_CODE} in the dedicated Instabrad browser.")
        print("If Instagram asks you to log in, log into @weirdasshouses in that browser.")
        input("Once you can see Instagram normally, press Return here. The script will take over... ")

        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        print("Automatically expanding, capturing, and scrolling comments/replies now...")
        rows = load_more(page)

        comments = [row for row in rows if row.get("comment_id")]
        replies = [row for row in comments if row.get("parent_comment_id")]
        top_level = [row for row in comments if not row.get("parent_comment_id")]

        print(
            f"Archived {len(comments)} unique Instagram comment IDs: "
            f"{len(top_level)} top-level, {len(replies)} replies."
        )
        for index, row in enumerate(comments[:15], start=1):
            kind = "reply" if row.get("parent_comment_id") else "comment"
            sample = row.get("text", "").replace("\n", " | ")[:220]
            print(f"{index}. {kind} {row['comment_id']} @{row['username']}: {sample}")

        (DEBUG_DIR / f"{POST_CODE}_rows.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (DEBUG_DIR / f"{POST_CODE}.html").write_text(page.content(), encoding="utf-8")
        (DEBUG_DIR / f"{POST_CODE}_body.txt").write_text(
            page.locator("body").inner_text(), encoding="utf-8"
        )
        page.screenshot(path=str(DEBUG_DIR / f"{POST_CODE}.png"), full_page=True)

        print(f"Saved debug output to {DEBUG_DIR}.")
        context.close()


if __name__ == "__main__":
    main()
