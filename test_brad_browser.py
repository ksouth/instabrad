#!/usr/bin/env python3
"""Browser-backed proof-of-concept for Brad comment collection.

Uses a dedicated persistent Playwright profile stored locally in
``brad_browser_profile``. On first run, log into Instagram manually in the
browser window that opens. The login state is then reused on future runs.

This test targets the high-comment Brad post chosen as the benchmark and tries
multiple DOM strategies so we are not dependent on one brittle Instagram CSS
layout.
"""

from __future__ import annotations

import json
import re
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
    """Scroll the page and any independently scrollable Instagram panels."""
    page.evaluate(
        """
        () => {
          window.scrollTo(0, document.body.scrollHeight);
          const els = [...document.querySelectorAll('div, section, main, article')];
          for (const el of els) {
            if (el.scrollHeight > el.clientHeight + 150 && el.clientHeight > 180) {
              el.scrollTop = el.scrollHeight;
            }
          }
        }
        """
    )


def load_more(page, rounds: int = 80) -> None:
    """Expand/scroll until the page stops visibly changing for several rounds."""
    stable = 0
    previous = ""

    for round_no in range(1, rounds + 1):
        clicked = click_expanders(page)
        scroll_comment_surfaces(page)
        page.wait_for_timeout(700)

        signature = page.evaluate(
            """
            () => {
              const article = document.querySelector('article') || document.body;
              return [
                article.innerText.length,
                article.querySelectorAll('time').length,
                article.querySelectorAll('a[href^="/"]').length
              ].join(':');
            }
            """
        )

        if signature == previous and clicked == 0:
            stable += 1
        else:
            stable = 0
        previous = signature

        print(f"Loading round {round_no}: page signature {signature}, expand clicks {clicked}")
        if stable >= 5:
            print("Page stopped changing; moving to extraction.")
            break


def extract_rows(page) -> list[dict]:
    """Extract comment-like records from the rendered post.

    Current Instagram markup varies between post types and experiments. We use
    timestamps as anchors when possible, then inspect nearby containers for a
    profile link and human-visible text. A fallback scans repeated profile-link
    containers when timestamps are absent.
    """
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

          function usefulText(el) {
            const clone = el.cloneNode(true);
            for (const bad of clone.querySelectorAll('svg, img, video')) bad.remove();
            return (clone.innerText || '').trim();
          }

          function add(el, source) {
            if (!el) return;
            const username = usernameFrom(el);
            const text = usefulText(el);
            if (!username || !text) return;
            if (text.length > 5000) return;
            const timeEl = el.querySelector('time');
            const timestamp = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText || '') : '';
            const key = username + '\n' + text + '\n' + timestamp;
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({username, text, timestamp, source});
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
                if (el.matches('li, [role="listitem"]')) break;
              }
            }
            add(best, 'time-anchor');
          }

          for (const el of root.querySelectorAll('li, [role="listitem"]')) {
            add(el, 'listitem');
          }

          for (const a of root.querySelectorAll('a[href^="/"]')) {
            let el = a.parentElement;
            for (let depth = 0; el && depth < 5; depth++, el = el.parentElement) {
              if (!root.contains(el)) break;
              const txt = usefulText(el);
              if (txt && txt.length < 1800 && (el.querySelector('time') || /reply|like/i.test(txt))) {
                add(el, 'profile-anchor');
                break;
              }
            }
          }

          return rows;
        }
        """
    )


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

        print("Automatically expanding and scrolling comments/replies now...")
        load_more(page)

        rows = extract_rows(page)
        print(f"Extracted {len(rows)} candidate comment/caption rows.")
        for index, row in enumerate(rows[:15], start=1):
            sample = row["text"].replace("\n", " | ")[:220]
            print(f"{index}. @{row['username']} [{row['source']}]: {sample}")

        (DEBUG_DIR / f"{POST_CODE}_rows.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (DEBUG_DIR / f"{POST_CODE}.html").write_text(page.content(), encoding="utf-8")
        (DEBUG_DIR / f"{POST_CODE}_body.txt").write_text(
            page.locator("body").inner_text(), encoding="utf-8"
        )
        page.screenshot(path=str(DEBUG_DIR / f"{POST_CODE}.png"), full_page=True)

        print(f"Saved debug output to {DEBUG_DIR}.")
        print("You can close the browser after this script finishes.")
        context.close()


if __name__ == "__main__":
    main()
