#!/usr/bin/env python3
"""Record what Instagram does when a human scrolls the comments panel.

This diagnostic intentionally asks for one short manual scroll. While the user
scrolls, it records comment IDs, scroll geometry, and relevant network responses
so we can compare successful human interaction with the automated collector.

For GraphQL POSTs it keeps only safe request fields (query name/doc_id/variables)
and captures a capped response body locally for structural analysis. It does not
persist cookies, headers, CSRF values, or other authentication fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

import test_brad_browser as base

POST_URL = base.POST_URL
PROFILE_DIR = base.PROFILE_DIR
DEBUG_DIR = base.DEBUG_DIR
OUT = DEBUG_DIR / "manual_scroll_diagnostic.json"
MAX_RESPONSE_CHARS = 400_000


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


def safe_graphql_request(post_data: str | None) -> dict:
    """Return useful GraphQL request fields without auth/session values."""
    if not post_data:
        return {}
    try:
        values = parse_qs(post_data, keep_blank_values=True)
        out: dict[str, object] = {}
        for key in ("doc_id", "fb_api_req_friendly_name", "fb_api_caller_class"):
            if key in values and values[key]:
                out[key] = values[key][0]
        raw_variables = values.get("variables", [""])[0]
        if raw_variables:
            try:
                out["variables"] = json.loads(raw_variables)
            except Exception:
                out["variables_raw"] = raw_variables[:20_000]
        return out
    except Exception:
        return {}


def analyze_graphql_body(body: str) -> dict:
    """Find comment-like objects and pagination hints in a GraphQL response."""
    result = {
        "json": False,
        "comment_like_count": 0,
        "comment_ids": [],
        "usernames": [],
        "pagination": [],
    }
    if not body:
        return result

    try:
        data = json.loads(body)
    except Exception:
        return result

    result["json"] = True
    comment_ids: set[str] = set()
    usernames: set[str] = set()
    pagination: list[dict] = []
    seen_pagination: set[str] = set()

    def visit(value, path: str = "$") -> None:
        if isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, f"{path}[{i}]")
            return
        if not isinstance(value, dict):
            return

        user = value.get("user")
        username = user.get("username") if isinstance(user, dict) else None
        text = value.get("text")
        raw_id = value.get("pk") or value.get("id")
        typename = value.get("__typename")
        looks_like_comment = (
            typename == "XDTCommentDict"
            or (raw_id and isinstance(text, str) and username)
        )
        if looks_like_comment:
            comment_ids.add(str(raw_id))
            if username:
                usernames.add(str(username))

        # Instagram has used several pagination shapes. Record any small object
        # that contains a cursor and/or an explicit next-page flag.
        cursor = value.get("end_cursor") or value.get("next_cursor") or value.get("cursor")
        has_next = value.get("has_next_page")
        if cursor is not None or isinstance(has_next, bool):
            item = {
                "path": path,
                "end_cursor": value.get("end_cursor"),
                "next_cursor": value.get("next_cursor"),
                "cursor": value.get("cursor"),
                "has_next_page": has_next,
            }
            fingerprint = json.dumps(item, sort_keys=True, default=str)
            if fingerprint not in seen_pagination:
                seen_pagination.add(fingerprint)
                pagination.append(item)

        for key, child in value.items():
            visit(child, f"{path}.{key}")

    visit(data)
    result["comment_like_count"] = len(comment_ids)
    result["comment_ids"] = sorted(comment_ids)
    result["usernames"] = sorted(usernames)
    result["pagination"] = pagination[:100]
    return result


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

                item = {
                    "status": response.status,
                    "method": req.method,
                    "resource_type": resource_type,
                    "url": url,
                }

                if "graphql" in url.lower():
                    item["graphql_request"] = safe_graphql_request(req.post_data)
                    try:
                        body = response.text()[:MAX_RESPONSE_CHARS]
                    except Exception as exc:
                        body = ""
                        item["response_read_error"] = str(exc)
                    item["response_body"] = body
                    item["response_analysis"] = analyze_graphql_body(body)

                network.append(item)
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
        page.wait_for_timeout(2500)
        after = snapshot(page)

        before_ids = set(before["comment_ids"])
        after_ids = set(after["comment_ids"])
        new_ids = sorted(after_ids - before_ids)

        interesting = []
        for item in network:
            u = item["url"].lower()
            if "graphql" in u or "comment" in u:
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

        graphql_items = [item for item in interesting if "graphql" in item["url"].lower()]
        if graphql_items:
            print("\nGraphQL responses:")
            for i, item in enumerate(graphql_items[:12], start=1):
                req_info = item.get("graphql_request", {})
                analysis = item.get("response_analysis", {})
                name = req_info.get("fb_api_req_friendly_name") or "(unnamed query)"
                doc_id = req_info.get("doc_id") or "?"
                print(
                    f"  #{i} {item['status']} {name} doc_id={doc_id} | "
                    f"comment-like objects={analysis.get('comment_like_count', 0)} | "
                    f"pagination hints={len(analysis.get('pagination', []))}"
                )
                if analysis.get("pagination"):
                    for hint in analysis["pagination"][:3]:
                        print(
                            "       cursor="
                            f"{hint.get('end_cursor') or hint.get('next_cursor') or hint.get('cursor')} "
                            f"has_next={hint.get('has_next_page')}"
                        )

        bell()
        input("\nPress ENTER to close the browser... ")
        context.close()


if __name__ == "__main__":
    main()
