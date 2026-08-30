#!/usr/bin/env python3
"""Benchmark Instabrad with synchronized, one-at-a-time expansion.

Reuses test_brad_browser.py but replaces its batch expander with a slower
version that clicks one visible expansion control inside the selected comments
panel, then waits for Instagram to react before clicking another.

This benchmark also replaces direct ``scrollTop`` mutation with real Playwright
mouse-wheel input over the comments panel. Manual scrolling proved that Instagram
loads additional comments in response to a genuine scroll gesture.
"""

from __future__ import annotations

import test_brad_browser as base


def comment_id_count(page) -> int:
    return page.locator('a[href*="/c/"]').count()


def click_expanders_slow(page, max_clicks: int = 80) -> int:
    """Click one expander at a time and wait for Instagram after each click."""
    clicked = 0

    for _ in range(max_clicks):
        panel = page.locator('[data-instabrad-scroller="1"]')
        if panel.count() == 0:
            selected = base.select_comment_scroller(page)
            if not selected.get("found"):
                break
            panel = page.locator('[data-instabrad-scroller="1"]')

        candidates = panel.locator("button, [role='button'], span, div")
        chosen = None
        chosen_text = ""

        count = min(candidates.count(), 2500)
        for i in range(count):
            item = candidates.nth(i)
            try:
                if not item.is_visible():
                    continue
                text = (item.inner_text(timeout=120) or "").strip()
                if not text or len(text) > 90:
                    continue
                if not base.EXPAND_TEXT.search(text):
                    continue
                chosen = item
                chosen_text = text
                break
            except Exception:
                continue

        if chosen is None:
            break

        before_ids = comment_id_count(page)
        try:
            chosen.scroll_into_view_if_needed(timeout=1000)
            chosen.click(timeout=1200)
            clicked += 1
        except Exception:
            break

        # Instagram often inserts replies asynchronously. Give it up to four
        # seconds to add comment permalink IDs or remove/replace the expander.
        reacted = False
        for _wait in range(20):
            page.wait_for_timeout(200)
            after_ids = comment_id_count(page)
            if after_ids > before_ids:
                reacted = True
                break
            try:
                if not chosen.is_visible():
                    reacted = True
                    break
                new_text = (chosen.inner_text(timeout=100) or "").strip()
                if new_text != chosen_text:
                    reacted = True
                    break
            except Exception:
                reacted = True
                break

        # Even when no visible reaction is detected, pause briefly rather than
        # hammering Instagram with another immediate click.
        if not reacted:
            page.wait_for_timeout(600)

    return clicked


def scroll_comments_with_wheel(page) -> dict:
    """Send a genuine mouse-wheel gesture over the selected comments panel."""
    panel = page.locator('[data-instabrad-scroller="1"]')
    if panel.count() == 0:
        selected = base.select_comment_scroller(page)
        if not selected.get("found"):
            return {"ok": False}
        panel = page.locator('[data-instabrad-scroller="1"]')

    try:
        box = panel.bounding_box()
    except Exception:
        box = None

    if not box:
        return {"ok": False}

    before = panel.evaluate(
        "el => ({scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})"
    )

    # Put the pointer squarely inside the comment surface, then perform the same
    # kind of wheel gesture a person makes with a mouse/trackpad.
    x = box["x"] + box["width"] * 0.5
    y = box["y"] + box["height"] * 0.65
    page.mouse.move(x, y)
    page.mouse.wheel(0, max(500, int(box["height"] * 0.8)))
    page.wait_for_timeout(500)

    after = panel.evaluate(
        "el => ({scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})"
    )

    max_top = max(0, after["scrollHeight"] - after["clientHeight"])
    return {
        "ok": True,
        "before": before["scrollTop"],
        "after": after["scrollTop"],
        "scrollHeight": after["scrollHeight"],
        "clientHeight": after["clientHeight"],
        "atBottom": after["scrollTop"] >= max_top - 2,
    }


if __name__ == "__main__":
    base.click_expanders = click_expanders_slow
    base.scroll_comments = scroll_comments_with_wheel
    base.main()
