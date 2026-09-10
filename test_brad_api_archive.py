#!/usr/bin/env python3
"""Direct Instagram comments-API benchmark for Instabrad.

The saved Brad post source declares the desktop comments transport as:
    GET /api/v1/media/{media_id}/comments/

This collector uses that first-party endpoint from inside the already-authenticated
Instagram page context. It avoids depending on virtualized DOM scrolling for
pagination. DOM/structured-page capture can still be used separately as a fallback.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

import test_brad_browser as base

POST_URL = base.POST_URL
POST_CODE = base.POST_CODE
PROFILE_DIR = base.PROFILE_DIR
DEBUG_DIR = base.DEBUG_DIR
OUT = DEBUG_DIR / f"{POST_CODE}_api_rows.json"
RAW_OUT = DEBUG_DIR / f"{POST_CODE}_api_pages.json"
INSTAGRAM_APP_ID = "936619743392459"
MEDIA_ID_RE = re.compile(r'"media_id"\s*:\s*"(\d+)"')


def normalize_timestamp(value) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            return ""
    return str(value or "")


def comment_rows_from_payload(payload: object) -> list[dict]:
    """Recursively extract Instagram comment objects from an API payload."""
    rows: dict[str, dict] = {}

    def visit(value: object, inherited_parent: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, inherited_parent)
            return
        if not isinstance(value, dict):
            return

        user = value.get("user")
        username = user.get("username") if isinstance(user, dict) else ""
        raw_id = value.get("pk") or value.get("id")
        text = value.get("text")
        looks_like_comment = bool(raw_id and isinstance(text, str) and username)

        parent = str(
            value.get("parent_comment_id")
            or value.get("parent_comment_pk")
            or inherited_parent
            or ""
        )

        current_id = ""
        if looks_like_comment:
            current_id = str(raw_id)
            rows[current_id] = {
                "comment_id": current_id,
                "parent_comment_id": parent,
                "username": str(username),
                "text": text,
                "timestamp": normalize_timestamp(
                    value.get("created_at_utc") or value.get("created_at")
                ),
                "likes": value.get("comment_like_count"),
                "child_comment_count": value.get("child_comment_count"),
                "is_reply": bool(parent),
                "is_edited": value.get("is_edited"),
                "source": "instagram-comments-api",
            }

        for key, child in value.items():
            child_parent = current_id if key in {
                "child_comments",
                "preview_child_comments",
                "threaded_comments",
                "replies",
            } else inherited_parent
            visit(child, child_parent)

    visit(payload)
    return list(rows.values())


def pagination_from_payload(payload: dict) -> tuple[str, str] | None:
    """Return (query_parameter, cursor) for the next comments page if exposed."""
    candidates = (
        ("min_id", payload.get("next_min_id")),
        ("max_id", payload.get("next_max_id")),
        ("cursor", payload.get("next_cursor")),
        ("min_id", payload.get("min_id")),
        ("max_id", payload.get("max_id")),
    )
    for parameter, value in candidates:
        if value not in (None, ""):
            return parameter, str(value)

    for key in ("page_info", "pagination", "paging"):
        nested = payload.get(key)
        if not isinstance(nested, dict):
            continue
        for parameter, field in (
            ("min_id", "next_min_id"),
            ("max_id", "next_max_id"),
            ("cursor", "next_cursor"),
            ("cursor", "end_cursor"),
        ):
            value = nested.get(field)
            if value not in (None, ""):
                return parameter, str(value)
    return None


def payload_has_more(payload: dict) -> bool:
    for key in (
        "has_more_comments",
        "has_more_headload_comments",
        "has_more_tailload_comments",
        "has_next_page",
    ):
        if payload.get(key) is True:
            return True
    nested = payload.get("page_info")
    return isinstance(nested, dict) and nested.get("has_next_page") is True


def discover_media_id(page) -> str:
    """Read the media ID from Instagram's own route/bootstrap source."""
    found = page.evaluate(
        r"""
        () => {
          const text = document.documentElement.innerHTML;
          const m = text.match(/"media_id"\s*:\s*"(\d+)"/);
          return m ? m[1] : '';
        }
        """
    )
    if found:
        return str(found)

    html = page.content()
    match = MEDIA_ID_RE.search(html)
    if match:
        return match.group(1)
    raise RuntimeError("Could not discover Instagram media_id from the post source.")


def fetch_comments_page(page, media_id: str, cursor: tuple[str, str] | None = None) -> dict:
    """Call Instagram's own declared comments endpoint inside page context."""
    return page.evaluate(
        r"""
        async ({mediaId, cursor, appId}) => {
          const url = new URL(`/api/v1/media/${mediaId}/comments/`, location.origin);
          url.searchParams.set('can_support_threading', 'true');
          url.searchParams.set('permalink_enabled', 'false');
          if (cursor && cursor.length === 2) url.searchParams.set(cursor[0], cursor[1]);

          const response = await fetch(url.toString(), {
            method: 'GET',
            credentials: 'include',
            headers: {
              'Accept': '*/*',
              'X-IG-App-ID': appId,
              'X-Requested-With': 'XMLHttpRequest'
            }
          });
          const text = await response.text();
          let data = null;
          try { data = JSON.parse(text); } catch (_) {}
          return {
            ok: response.ok,
            status: response.status,
            url: response.url,
            data,
            body_preview: text.slice(0, 2000)
          };
        }
        """,
        {"mediaId": media_id, "cursor": list(cursor) if cursor else None, "appId": INSTAGRAM_APP_ID},
    )


def collect_api(page, media_id: str, max_pages: int = 200) -> tuple[list[dict], list[dict]]:
    archive: dict[str, dict] = {}
    page_log: list[dict] = []
    cursor: tuple[str, str] | None = None
    seen_cursors: set[tuple[str, str]] = set()

    for page_no in range(1, max_pages + 1):
        result = fetch_comments_page(page, media_id, cursor)
        if not result.get("ok"):
            raise RuntimeError(
                f"Instagram comments API returned HTTP {result.get('status')}: "
                f"{result.get('body_preview', '')[:500]}"
            )

        payload = result.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError("Instagram comments API returned a non-JSON response.")

        rows = comment_rows_from_payload(payload)
        new_count = 0
        for row in rows:
            cid = row["comment_id"]
            if cid not in archive:
                archive[cid] = row
                new_count += 1
            else:
                for key, value in row.items():
                    if value not in (None, ""):
                        archive[cid][key] = value

        next_cursor = pagination_from_payload(payload)
        page_log.append(
            {
                "page": page_no,
                "status": result.get("status"),
                "rows_seen": len(rows),
                "new_ids": new_count,
                "archive_size": len(archive),
                "cursor_used": cursor,
                "next_cursor": next_cursor,
                "has_more": payload_has_more(payload),
                "top_level_keys": sorted(payload.keys()),
            }
        )
        print(
            f"API page {page_no:03d}: rows {len(rows):3d} | new +{new_count:3d} | "
            f"archive {len(archive):3d} | next={next_cursor}"
        )

        if not next_cursor:
            if payload_has_more(payload):
                raise RuntimeError(
                    "Instagram says more comments exist but exposed no recognized cursor. "
                    f"Top-level keys: {sorted(payload.keys())}"
                )
            break
        if next_cursor in seen_cursors:
            raise RuntimeError(f"Instagram repeated pagination cursor {next_cursor}; stopping to avoid a loop.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

        if new_count == 0 and page_no > 1 and not payload_has_more(payload):
            break

    rows = sorted(
        archive.values(),
        key=lambda r: (r.get("timestamp") or "", r.get("comment_id") or ""),
    )
    return rows, page_log


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

        print(f"Opened Brad benchmark post {POST_CODE}.")
        print("If Instagram asks you to log in, log in in this browser.")
        input("Press ENTER when Instagram is visible... ")

        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        media_id = discover_media_id(page)
        print(f"Discovered media_id {media_id}; collecting directly from Instagram comments API.")

        rows, pages = collect_api(page, media_id)
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        RAW_OUT.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")

        replies = sum(1 for row in rows if row.get("parent_comment_id"))
        print(f"Archived {len(rows)} unique comment IDs ({replies} recognized replies).")
        print(f"Saved: {OUT}")
        print(f"Page log: {RAW_OUT}")
        input("Press ENTER to close the browser... ")
        context.close()


if __name__ == "__main__":
    main()
