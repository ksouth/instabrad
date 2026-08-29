#!/usr/bin/env python3
"""Test comment retrieval for Brad's newest known post using instagrapi.

This is deliberately separate from collect_brad.py so we can prove that
instagrapi can retrieve comments before changing the main archive pipeline.
"""

from __future__ import annotations

from getpass import getpass
from pathlib import Path

from instagrapi import Client

LOGIN_USERNAME = "weirdasshouses"
POST_CODE = "DcjFwHPxTaP"
SESSION_FILE = Path("brad_session.json")


def login() -> Client:
    client = Client()

    if SESSION_FILE.exists():
        try:
            client.load_settings(SESSION_FILE)
            print(f"Loaded saved instagrapi session from {SESSION_FILE}.")
        except Exception as exc:
            print(f"Could not load saved session ({exc}); doing a fresh login.")

    password = getpass(f"Instagram password for @{LOGIN_USERNAME}: ")
    client.login(LOGIN_USERNAME, password)
    client.dump_settings(SESSION_FILE)
    print(f"Logged in as @{LOGIN_USERNAME}; saved session locally to {SESSION_FILE}.")
    return client


def main() -> None:
    client = login()
    media_pk = client.media_pk_from_code(POST_CODE)
    media_id = client.media_id(media_pk)

    print(f"Testing Brad post {POST_CODE} (media {media_id}).")
    comments = client.media_comments(media_id, amount=0)
    print(f"Retrieved {len(comments)} top-level comments.")

    reply_total = 0
    for index, comment in enumerate(comments[:5], start=1):
        username = getattr(getattr(comment, "user", None), "username", "")
        text = getattr(comment, "text", "")
        comment_pk = str(getattr(comment, "pk", ""))
        print(f"{index}. @{username}: {text[:120]}")

        replies_count = int(getattr(comment, "replies_count", 0) or 0)
        if replies_count and comment_pk:
            replies = client.media_comment_replies(media_id, comment_pk, amount=0)
            reply_total += len(replies)
            print(f"   ↳ retrieved {len(replies)} replies")

    print(f"Sampled reply total from first five comments: {reply_total}")


if __name__ == "__main__":
    main()
