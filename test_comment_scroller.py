#!/usr/bin/env python3
"""Diagnose the actual Instagram comments scroll container.

Opens the Instabrad benchmark post in the existing persistent browser profile,
finds scrollable elements that contain comment-like content, outlines the best
candidate in red, and scrolls only that element. It never scrolls window.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

POST_URL = "https://www.instagram.com/p/Dclt_nKkUVg/"
PROFILE_DIR = Path("brad_browser_profile").resolve()


def find_comment_scroller(page) -> dict:
    return page.evaluate(
        r"""
        () => {
          // Remove an old diagnostic outline if this script was rerun.
          for (const el of document.querySelectorAll('[data-instabrad-scroller]')) {
            el.style.outline = '';
            el.removeAttribute('data-instabrad-scroller');
          }

          const candidates = [];
          const all = [...document.querySelectorAll('div, section, main, article, ul')];

          for (const el of all) {
            const style = getComputedStyle(el);
            const overflowY = style.overflowY;
            const genuinelyScrollable =
              el.scrollHeight > el.clientHeight + 100 &&
              el.clientHeight >= 180 &&
              ['auto', 'scroll', 'overlay'].includes(overflowY);

            if (!genuinelyScrollable) continue;

            const commentLinks = el.querySelectorAll('a[href*="/c/"]').length;
            const times = el.querySelectorAll('time').length;
            const text = (el.innerText || '').slice(0, 20000);
            const replyMentions = (text.match(/\bReply\b/gi) || []).length;
            const viewReplyMentions = (text.match(/View .*repl(?:y|ies)/gi) || []).length;
            const hasPost = !!el.closest('article') || !!el.querySelector('article');

            // Strongly prefer a scrollable surface containing actual comment IDs.
            // Timestamps and Reply UI are useful fallbacks for Instagram builds
            // where comment permalink anchors are sparse.
            const score =
              commentLinks * 1000 +
              times * 20 +
              replyMentions * 8 +
              viewReplyMentions * 30 +
              (hasPost ? 50 : 0);

            candidates.push({
              el,
              score,
              commentLinks,
              times,
              replyMentions,
              viewReplyMentions,
              scrollTop: el.scrollTop,
              scrollHeight: el.scrollHeight,
              clientHeight: el.clientHeight,
              overflowY,
              tag: el.tagName,
              className: typeof el.className === 'string' ? el.className : ''
            });
          }

          candidates.sort((a, b) => b.score - a.score);
          const best = candidates[0];
          if (!best) {
            return {found: false, candidates: []};
          }

          best.el.dataset.instabradScroller = '1';
          best.el.style.outline = '6px solid red';
          best.el.style.outlineOffset = '-6px';

          return {
            found: true,
            best: {
              score: best.score,
              commentLinks: best.commentLinks,
              times: best.times,
              replyMentions: best.replyMentions,
              viewReplyMentions: best.viewReplyMentions,
              scrollTop: best.scrollTop,
              scrollHeight: best.scrollHeight,
              clientHeight: best.clientHeight,
              overflowY: best.overflowY,
              tag: best.tag,
              className: best.className
            },
            candidates: candidates.slice(0, 8).map((c, i) => ({
              rank: i + 1,
              score: c.score,
              commentLinks: c.commentLinks,
              times: c.times,
              replyMentions: c.replyMentions,
              scrollTop: c.scrollTop,
              scrollHeight: c.scrollHeight,
              clientHeight: c.clientHeight,
              overflowY: c.overflowY,
              tag: c.tag
            }))
          };
        }
        """
    )


def scroll_selected(page) -> dict:
    return page.evaluate(
        r"""
        () => {
          const el = document.querySelector('[data-instabrad-scroller="1"]');
          if (!el) return {ok: false};
          const before = el.scrollTop;
          const step = Math.max(300, el.clientHeight * 0.7);
          el.scrollTop = Math.min(el.scrollTop + step, el.scrollHeight - el.clientHeight);
          el.dispatchEvent(new Event('scroll', {bubbles: true}));
          return {
            ok: true,
            before,
            after: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight
          };
        }
        """
    )


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        print("Opened the Instabrad benchmark post.")
        print("IMPORTANT: do not scroll the page manually for this test.")
        input("When the post/comments are visible, press Return... ")

        result = find_comment_scroller(page)
        if not result.get("found"):
            print("No independently scrollable comment candidate was found.")
            input("Press Return to close the browser... ")
            context.close()
            return

        best = result["best"]
        print("\nBest candidate (outlined RED in the browser):")
        print(
            f"  comment links={best['commentLinks']}  times={best['times']}  "
            f"reply labels={best['replyMentions']}"
        )
        print(
            f"  scrollTop={best['scrollTop']}  scrollHeight={best['scrollHeight']}  "
            f"clientHeight={best['clientHeight']}  overflowY={best['overflowY']}"
        )
        print("\nTop scrollable candidates:")
        for c in result["candidates"]:
            print(
                f"  #{c['rank']} score={c['score']} comments={c['commentLinks']} "
                f"times={c['times']} replies={c['replyMentions']} "
                f"scroll={c['scrollTop']}/{c['scrollHeight']} height={c['clientHeight']}"
            )

        input("\nLOOK AT THE BROWSER. Is the RED outlined area the comments panel? Then press Return... ")

        print("\nScrolling ONLY the red element. The webpage itself will not be scrolled.")
        for i in range(1, 9):
            info = scroll_selected(page)
            page.wait_for_timeout(1000)
            if not info.get("ok"):
                print("Lost selected element.")
                break
            print(
                f"  step {i}: {info['before']:.0f} -> {info['after']:.0f} "
                f"of {info['scrollHeight']} (viewport {info['clientHeight']})"
            )

        input("\nDid ONLY the comments move? Press Return to close... ")
        context.close()


if __name__ == "__main__":
    main()
