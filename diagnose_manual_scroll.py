#!/usr/bin/env python3
"""Record what Instagram does when a human scrolls the comments panel.

This diagnostic intentionally asks for one short manual scroll. While the user
scrolls, it records comment IDs, scroll geometry, and relevant network responses
so we can compare successful human interaction with the automated collector.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import test_brad_browser as base

POST_URL = base.POST_URL
PROFILE_DIR = base.PROFILE_DIR
DEBUG_DIR = base.DEBUG_DIR
OUT = DEBUG_DIR / "manual_scroll_diagnostic.json"


def bell() -> None:
    print("\a", end="", flush=True)


def snapshot(page) -> dict:
    return page.evaluate(
        r"""
        () => {
          const panel = document.querySelector('[data-instabrad-scroller="1"]');
          const links = [...document.querySelectorAll('a[href*="/c/"]')];
          const ids = [];
          const seen = new Set();
          for (const a of links) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/\/c\/(\d+)\/?/);
            if (m && !seen.has(m[1])) {
              seen.add(m[1]);
              ids.push(m[1]);
            }
          }
          return {
            comment_ids: ids,
            comment_id_count: ids.length,
            time_count: document.querySelectorAll('time').length,
            panel_found: !!panel,
            scroll_top: panel ? panel.scrollTop : null,
            scroll_height: panel ? panel.scrollHeight : null,
            client_height: panel ? panel.clientHeight : null,
            view_reply_texts: panel
              ? [...panel.querySelectorAll('button, [role="button"], span, div')]
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t && t.length < 100 && /view .*repl|more .*repl|see .*repl/i.test(t))
                  .slice(0, 100)
              : []
          };
        }
        """
    )


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    network: list[dict] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response) -> None:
            try:
                req = response.request
                resource_type = req.resource_type
                url = response.url
                if resource_type not in {"xhr", "fetch"}:
                    return
                host = urlparse(url).netloc
                if "instagram" not in host and "facebook" not in host:
                    return
                network.append(
                    {
                        "status": response.status,
                        "method": req.method,
                        "resource_type": resource_type,
                        "url": url,
                        "post_data": (req.post_data or "")[:20000],
                    }
                )
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        selected = base.select_comment_scroller(page)
        if not selected.get("found"):
            raise RuntimeError("Could not find the Instagram comments panel.")

        print("\nManual-scroll diagnostic ready.")
        print("The comments panel has been selected. Do NOT click reply buttons.")
        print("\nWhen you hear the bell:")
        print("  1. Scroll ONLY inside the comments panel for about 10 seconds.")
        print("  2. Keep scrolling until you see new comments appear if possible.")
        print("  3. Return to Terminal and press ENTER.\n")

        before = snapshot(page)
        network.clear()
        bell()
        input("PRESS ENTER AFTER THE MANUAL SCROLL... ")
        page.wait_for_timeout(2000)
        after = snapshot(page)

        before_ids = set(before["comment_ids"])
        after_ids = set(after["comment_ids"])
        new_ids = sorted(after_ids - before_ids)

        interesting = []
        for item in network:
            u = item["url"].lower()
            body = item.get("post_data", "").lower()
            if any(k in u or k in body for k in ("graphql", "comment", "media", "query")):
                interesting.append(item)

        result = {
            "post_url": POST_URL,
            "before": before,
            "after": after,
            "new_comment_ids": new_ids,
            "new_comment_id_count": len(new_ids),
            "network_response_count": len(network),
            "interesting_network_responses": interesting,
            "all_network_responses": network,
        }
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        print("\nRESULT")
        print(f"  Comment IDs before : {before['comment_id_count']}")
        print(f"  Comment IDs after  : {after['comment_id_count']}")
        print(f"  New IDs from scroll: {len(new_ids)}")
        print(f"  XHR/fetch responses: {len(network)}")
        print(f"  Interesting requests: {len(interesting)}")
        print(f"\nSaved: {OUT}")

        if interesting:
            print("\nFirst relevant request URLs:")
            for item in interesting[:12]:
                print(f"  {item['status']} {item['method']} {item['url'][:220]}")

        bell()
        input("\nPress ENTER to close the browser... ")
        context.close()


if __name__ == "__main__":
    main()
