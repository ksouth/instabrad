#!/usr/bin/env python3
"""Browser-backed proof-of-concept for Brad comment collection.

Uses a dedicated persistent Playwright profile stored locally in
``brad_browser_profile``. On first run, log into Instagram manually in the
browser window that opens. The login state is then reused on future runs.

This test only targets one known Brad post and prints a small sample so we can
verify browser-based comment access before integrating it into collect_brad.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import sleep

from playwright.sync_api import sync_playwright

POST_URL = "https://www.instagram.com/p/DcjFwHPxTaP/"
PROFILE_DIR = Path("brad_browser_profile").resolve()
DEBUG_DIR = Path("brad_data/browser_debug")


def click_visible_text(page, patterns: list[str], max_rounds: int = 30) -> None:
    """Repeatedly click visible comment/reply expansion controls.

    Instagram changes its markup frequently, so this intentionally relies on
    visible button/link text instead of unstable CSS class names.
    """
    for _ in range(max_rounds):
        clicked = False
        for pattern in patterns:
            locator = page.get_by_text(pattern, exact=False)
            count = locator.count()
            for i in range(min(count, 10)):
                try:
                    item = locator.nth(i)
                    if item.is_visible():
                        item.click(timeout=1500)
                        sleep(0.4)
                        clicked = True
                except Exception:
                    pass
        if not clicked:
            break


def extract_comment_like_rows(page) -> list[dict[str, str]]:
    """Extract comment-like list items from the loaded post.

    We keep this deliberately permissive for the proof-of-concept. The final
    collector will normalize parent/reply relationships once we confirm the
    browser surface exposes the data reliably.
    """
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in page.locator("article li").all():
        try:
            text = item.inner_text(timeout=1000).strip()
        except Exception:
            continue
        if not text:
            continue

        username = ""
        try:
            links = item.locator('a[href^="/"]')
            for i in range(min(links.count(), 5)):
                candidate = links.nth(i).inner_text(timeout=500).strip()
                href = links.nth(i).get_attribute("href") or ""
                if candidate and href.count("/") >= 2:
                    username = candidate
                    break
        except Exception:
            pass

        key = (username, text)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"username": username, "text": text})

    return rows


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)

        print("Opened the Brad test post in the dedicated Instabrad browser profile.")
        print("If Instagram shows a login screen, log into @weirdasshouses in that browser window.")
        input("When the post and its comments are visible, press Return here in Terminal... ")

        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        click_visible_text(
            page,
            [
                "View all comments",
                "View more comments",
                "Load more comments",
                "more comments",
                "View replies",
                "more replies",
            ],
        )

        rows = extract_comment_like_rows(page)
        print(f"Extracted {len(rows)} comment-like rows from the loaded page.")

        for index, row in enumerate(rows[:10], start=1):
            user = f"@{row['username']}" if row["username"] else "(no username parsed)"
            sample = row["text"].replace("\n", " | ")[:180]
            print(f"{index}. {user}: {sample}")

        (DEBUG_DIR / "test_post_rows.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (DEBUG_DIR / "test_post.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / "test_post.png"), full_page=True)

        print(f"Saved debug output to {DEBUG_DIR}.")
        print("Close the Playwright browser window when you're finished inspecting it.")
        context.close()


if __name__ == "__main__":
    main()
