#!/usr/bin/env python3
"""Test comment retrieval for Brad's newest known post using instagrapi.

This reuses the already-working Instaloader login session instead of asking
Instagram to authenticate the account a second time through instagrapi.
"""

from __future__ import annotations

import instaloader
from instagrapi import Client

LOGIN_USERNAME = "weirdasshouses"
POST_CODE = "DcjFwHPxTaP"


def login() -> Client:
    loader = instaloader.Instaloader()
    loader.load_session_from_file(LOGIN_USERNAME)

    sessionid = loader.context._session.cookies.get("sessionid")
    if not sessionid:
        raise RuntimeError("Could not find sessionid in the saved Instaloader cookie jar.")

    client = Client()
    client.login_by_sessionid(sessionid)
    print(f"Reused existing Instagram session for @{LOGIN_USERNAME}.")
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
