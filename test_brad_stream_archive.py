#!/usr/bin/env python3
"""Streaming Instabrad benchmark collector.

This test follows the source-first architecture discovered from the saved
Instagram HTML:

- rendered comments have stable permalinks of the form /p/<shortcode>/c/<id>/;
- reply expanders are real role=button controls containing "View all N replies";
- the DOM is treated as a stream, never as the complete archive;
- every newly observed comment ID is archived immediately before scrolling;
- structured XDTCommentDict data enriches matching IDs when Instagram exposes it.

The archive is append-only for the duration of a run, so Instagram may recycle
or remove rendered nodes without losing comments we have already seen.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

import test_brad_browser as base

POST_URL = base.POST_URL
POST_CODE = base.POST_CODE
PROFILE_DIR = base.PROFILE_DIR
DEBUG_DIR = base.DEBUG_DIR
OUT = DEBUG_DIR / f"{POST_CODE}_stream_rows.json"

COMMENT_HREF_RE = re.compile(rf"^/p/{re.escape(POST_CODE)}/c/(\d+)/?$")
REPLY_TEXT_RE = re.compile(r"^View all\s+(\d+)\s+repl(?:y|ies)$", re.I)


def bell() -> None:
    print("\a", end="", flush=True)


def normalize(text: str) -> str:
    return " ".join((text or "").split())


def extract_visible_permalink_rows(page) -> list[dict]:
    """Extract only currently rendered comments identified by permalink anchors."""
    return page.evaluate(
        r"""
        (postCode) => {
          const panel = document.querySelector('[data-instabrad-scroller="1"]');
          const root = panel || document.querySelector('article') || document.body;
          const rows = [];
          const seen = new Set();
          const hrefRe = new RegExp('^/p/' + postCode.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '/c/(\\d+)/?$');

          function profileUsername(el) {
            for (const a of el.querySelectorAll('a[href^="/"]')) {
              const href = a.getAttribute('href') || '';
              const m = href.match(/^\/([^/?#]+)\/?$/);
              if (!m) continue;
              const u = m[1];
              if (!['p','reel','reels','explore','accounts'].includes(u)) return u;
            }
            return '';
          }

          function textOf(el) {
            const clone = el.cloneNode(true);
            for (const bad of clone.querySelectorAll('svg,img,video')) bad.remove();
            return (clone.innerText || '').trim();
          }

          function candidateContainer(anchor) {
            let el = anchor;
            let best = null;
            for (let depth = 0; el && depth < 10; depth++, el = el.parentElement) {
              if (!root.contains(el)) break;
              const user = profileUsername(el);
              const time = el.querySelector('time');
              const txt = textOf(el);
              if (user && time && txt && txt.length < 5000) {
                best = el;
                // Prefer the smallest container that has exactly one comment permalink.
                if (el.querySelectorAll('a[href*="/c/"]').length === 1) break;
              }
            }
            return best;
          }

          for (const anchor of root.querySelectorAll('a[href*="/c/"]')) {
            const href = anchor.getAttribute('href') || '';
            const m = href.match(hrefRe);
            if (!m) continue;
            const commentId = m[1];
            if (seen.has(commentId)) continue;
            const container = candidateContainer(anchor);
            if (!container) continue;

            const username = profileUsername(container);
            const timeEl = container.querySelector('time');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText || '') : '';
            const rawText = textOf(container);

            rows.push({
              comment_id: commentId,
              parent_comment_id: '',
              username,
              text: rawText,
              timestamp,
              likes: null,
              child_comment_count: null,
              is_reply: null,
              source: 'dom-permalink'
            });
            seen.add(commentId);
          }
          return rows;
        }
        """,
        POST_CODE,
    )


def structured_rows(page) -> list[dict]:
    return base.extract_structured_comments(page)


def merge(archive: dict[str, dict], rows: list[dict]) -> int:
    added = 0
    for row in rows:
        cid = str(row.get("comment_id") or "")
        if not cid:
            continue
        if cid not in archive:
            archive[cid] = dict(row)
            added += 1
            continue

        existing = archive[cid]
        # Structured data is authoritative for explicit metadata; DOM remains
        # useful for whatever is currently visible.
        if row.get("source") == "instagram-structured-json":
            for key, value in row.items():
                if value not in (None, ""):
                    existing[key] = value
    return added


def capture(page, archive: dict[str, dict]) -> tuple[int, int, int]:
    dom = extract_visible_permalink_rows(page)
    structured = structured_rows(page)
    added = merge(archive, dom)
    added += merge(archive, structured)
    return len(dom), len(structured), added


def reply_buttons(page):
    """Return visible, exact reply expanders inside the selected comment panel."""
    panel = page.locator('[data-instabrad-scroller="1"]')
    if panel.count() == 0:
        return []

    candidates = panel.locator('[role="button"]')
    found = []
    for i in range(min(candidates.count(), 2500)):
        item = candidates.nth(i)
        try:
            if not item.is_visible():
                continue
            text = normalize(item.inner_text(timeout=120))
            if REPLY_TEXT_RE.match(text):
                found.append((item, text))
        except Exception:
            continue
    return found


def expand_visible_replies(page, archive: dict[str, dict], max_clicks: int = 30) -> tuple[int, int]:
    """Expand precise reply controls one at a time, capturing after every click."""
    clicks = 0
    newly_archived = 0

    for _ in range(max_clicks):
        buttons = reply_buttons(page)
        if not buttons:
            break

        item, label = buttons[0]
        try:
            item.scroll_into_view_if_needed(timeout=1000)
            page.wait_for_timeout(150)
            item.click(timeout=1200)
            clicks += 1
        except Exception:
            break

        # Archive repeatedly while Instagram inserts replies asynchronously.
        quiet_ticks = 0
        for _tick in range(20):
            page.wait_for_timeout(200)
            _dom, _structured, added = capture(page, archive)
            newly_archived += added
            if added:
                quiet_ticks = 0
            else:
                quiet_ticks += 1
            if quiet_ticks >= 4:
                break

    return clicks, newly_archived


def wheel_comments(page, amount: int = 650) -> dict:
    """Send a real wheel gesture over the selected comments panel."""
    panel = page.locator('[data-instabrad-scroller="1"]')
    if panel.count() == 0:
        selected = base.select_comment_scroller(page)
        if not selected.get("found"):
            return {"ok": False}
        panel = page.locator('[data-instabrad-scroller="1"]')

    try:
        before = panel.evaluate("el => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
        box = panel.bounding_box()
        if not box:
            return {"ok": False}
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.72)
        page.mouse.wheel(0, amount)
        page.wait_for_timeout(700)
        after = panel.evaluate("el => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
        return {
            "ok": True,
            "before": before["top"],
            "after": after["top"],
            "scrollHeight": after["height"],
            "clientHeight": after["client"],
        }
    except Exception:
        return {"ok": False}


def save_archive(archive: dict[str, dict]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(archive.values())
    rows.sort(key=lambda r: (r.get("timestamp") or "", r.get("comment_id") or ""))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    archive: dict[str, dict] = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)

        print(f"Opened Brad benchmark post {POST_CODE}.")
        print("If Instagram asks you to log in, log in in this browser.")
        bell()
        input("Press ENTER when the post/comments are visible... ")

        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        selected = base.select_comment_scroller(page)
        if not selected.get("found"):
            raise RuntimeError("Could not find Instagram comments panel.")

        print("\nStreaming archive test: permalink IDs + immediate capture + precise reply expansion.")
        dom_n, structured_n, added = capture(page, archive)
        save_archive(archive)
        print(f"Initial: visible permalink comments {dom_n}, structured {structured_n}, new +{added}, archive {len(archive)}")

        quiet_passes = 0
        max_passes = 160

        for pass_no in range(1, max_passes + 1):
            # Capture BEFORE touching the page.
            dom_before, structured_before, added_before = capture(page, archive)

            # Expand what is visible, and capture DURING expansion.
            reply_controls_before = len(reply_buttons(page))
            clicks, added_expand = expand_visible_replies(page, archive)

            # Capture again before scrolling away from anything newly exposed.
            dom_after_expand, structured_after_expand, added_after_expand = capture(page, archive)

            # Then move a small amount and capture the new viewport.
            scroll = wheel_comments(page)
            if not scroll.get("ok"):
                raise RuntimeError("Lost Instagram comments panel during wheel scroll.")

            page.wait_for_timeout(500)
            dom_after_scroll, structured_after_scroll, added_scroll = capture(page, archive)

            new_total = added_before + added_expand + added_after_expand + added_scroll
            save_archive(archive)

            replies = sum(1 for row in archive.values() if row.get("parent_comment_id"))
            with_children = sum(1 for row in archive.values() if (row.get("child_comment_count") or 0) > 0)

            print(
                f"Pass {pass_no:03d}: visible {dom_after_scroll:3d} | new +{new_total:3d} | "
                f"archive {len(archive):3d} | reply-buttons {reply_controls_before:2d} | "
                f"clicked {clicks:2d} | structured-replies {replies:3d} | parents-with-replies {with_children:3d} | "
                f"scroll {scroll['before']:.0f}->{scroll['after']:.0f}/{scroll['scrollHeight']}"
            )

            moved = abs(float(scroll["after"]) - float(scroll["before"])) > 1
            if new_total == 0 and clicks == 0 and not moved:
                quiet_passes += 1
            else:
                quiet_passes = 0

            if quiet_passes >= 6:
                print("No new IDs, reply expansions, or scroll movement for 6 passes; stopping.")
                break

        save_archive(archive)
        print(f"\nArchive complete: {len(archive)} unique Instagram comment IDs.")
        print(f"Saved continuously to: {OUT}")
        bell()
        input("Press ENTER to close the browser... ")
        context.close()


if __name__ == "__main__":
    main()
