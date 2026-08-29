#!/usr/bin/env python3
"""Collect Brad's public Instagram post captions and comment threads.

The script keeps two views of the same archive:

1. One readable Markdown file per post, with the caption and comments together.
2. Master CSV/JSONL datasets suitable for whole-corpus analysis.

It intentionally leaves Instaloader's core code untouched.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import instaloader

TARGET_USERNAME = "bradtroemel"
DEFAULT_OUTPUT = Path("brad_data")


@dataclass
class CommentRow:
    post_shortcode: str
    post_date_utc: str
    post_url: str
    comment_id: int
    parent_comment_id: Optional[int]
    username: str
    comment_date_utc: str
    text: str
    likes: int
    is_reply: bool


@dataclass
class PostRow:
    shortcode: str
    date_utc: str
    url: str
    caption: str
    typename: str
    is_video: bool
    likes: int
    comments_reported: int
    comments_collected: int


def iso_utc(value: datetime) -> str:
    """Return a stable UTC ISO-8601 timestamp."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def clean_markdown_text(text: str) -> str:
    """Preserve text while making Markdown headings/spacing predictable."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def comment_to_row(post, comment, parent_id: Optional[int] = None) -> CommentRow:
    owner = getattr(comment, "owner", None)
    username = getattr(owner, "username", "") if owner is not None else ""
    created = getattr(comment, "created_at_utc", None)
    if created is None:
        created = getattr(comment, "created_at", datetime.now(timezone.utc))

    return CommentRow(
        post_shortcode=post.shortcode,
        post_date_utc=iso_utc(post.date_utc),
        post_url=f"https://www.instagram.com/p/{post.shortcode}/",
        comment_id=int(comment.id),
        parent_comment_id=parent_id,
        username=username,
        comment_date_utc=iso_utc(created),
        text=comment.text or "",
        likes=int(getattr(comment, "likes_count", 0) or 0),
        is_reply=parent_id is not None,
    )


def flatten_comments(post, comments: Iterable) -> list[CommentRow]:
    rows: list[CommentRow] = []
    for comment in comments:
        rows.append(comment_to_row(post, comment))
        answers = getattr(comment, "answers", None) or []
        for answer in answers:
            rows.append(comment_to_row(post, answer, parent_id=int(comment.id)))
    return rows


def write_post_markdown(post, comments: list[CommentRow], output_dir: Path) -> None:
    post_dir = output_dir / "posts"
    post_dir.mkdir(parents=True, exist_ok=True)
    path = post_dir / f"{post.date_utc:%Y-%m-%d}_{post.shortcode}.md"

    top_level: dict[int, CommentRow] = {}
    replies: dict[int, list[CommentRow]] = {}
    for row in comments:
        if row.parent_comment_id is None:
            top_level[row.comment_id] = row
        else:
            replies.setdefault(row.parent_comment_id, []).append(row)

    lines = [
        f"# {post.date_utc:%Y-%m-%d} — {post.shortcode}",
        "",
        f"**URL:** https://www.instagram.com/p/{post.shortcode}/",
        f"**Posted (UTC):** {iso_utc(post.date_utc)}",
        f"**Type:** {post.typename}",
        f"**Likes at collection:** {post.likes}",
        f"**Comments reported by Instagram:** {post.comments}",
        f"**Comments/replies collected:** {len(comments)}",
        "",
        "## Caption",
        "",
        clean_markdown_text(post.caption or "*(No caption)*"),
        "",
        "## Comments",
        "",
    ]

    if not top_level:
        lines.append("*(No comments collected.)*")
    else:
        for row in top_level.values():
            lines.extend([
                f"### @{row.username} — {row.comment_date_utc}",
                "",
                clean_markdown_text(row.text),
                "",
                f"*Likes: {row.likes} · Comment ID: {row.comment_id}*",
                "",
            ])
            for reply in replies.get(row.comment_id, []):
                lines.extend([
                    f"> **↳ @{reply.username} — {reply.comment_date_utc}**",
                    ">",
                ])
                reply_lines = clean_markdown_text(reply.text).splitlines() or [""]
                lines.extend([f"> {line}" for line in reply_lines])
                lines.extend([
                    ">",
                    f"> *Likes: {reply.likes} · Comment ID: {reply.comment_id}*",
                    "",
                ])

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_master_files(posts: list[PostRow], comments: list[CommentRow], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    posts_csv = output_dir / "posts.csv"
    with posts_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(PostRow.__dataclass_fields__.keys()))
        writer.writeheader()
        writer.writerows(asdict(row) for row in posts)

    comments_csv = output_dir / "comments.csv"
    with comments_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CommentRow.__dataclass_fields__.keys()))
        writer.writeheader()
        writer.writerows(asdict(row) for row in comments)

    with (output_dir / "posts.jsonl").open("w", encoding="utf-8") as f:
        for row in posts:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    with (output_dir / "comments.jsonl").open("w", encoding="utf-8") as f:
        for row in comments:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def login(loader: instaloader.Instaloader, username: str) -> None:
    """Load a saved Instaloader session, or prompt for an Instagram login once."""
    try:
        loader.load_session_from_file(username)
        print(f"Loaded saved Instagram session for @{username}.")
        return
    except FileNotFoundError:
        pass

    print(f"No saved session found for @{username}.")
    print("Instagram currently requires login to retrieve comments.")
    loader.interactive_login(username)
    loader.save_session_to_file()
    print("Saved the session locally for future runs.")


def collect(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=False,
    )

    login(loader, args.login)
    profile = instaloader.Profile.from_username(loader.context, TARGET_USERNAME)

    all_posts: list[PostRow] = []
    all_comments: list[CommentRow] = []

    for index, post in enumerate(profile.get_posts(), start=1):
        if args.limit and index > args.limit:
            break

        print(f"[{index}] Collecting {post.shortcode} ({post.date_utc:%Y-%m-%d}) …")
        try:
            comments = flatten_comments(post, post.get_comments())
        except Exception as exc:  # preserve completed posts if Instagram changes mid-run
            print(f"WARNING: could not collect comments for {post.shortcode}: {exc}", file=sys.stderr)
            comments = []

        write_post_markdown(post, comments, output_dir)
        all_comments.extend(comments)
        all_posts.append(
            PostRow(
                shortcode=post.shortcode,
                date_utc=iso_utc(post.date_utc),
                url=f"https://www.instagram.com/p/{post.shortcode}/",
                caption=post.caption or "",
                typename=post.typename,
                is_video=bool(post.is_video),
                likes=int(post.likes or 0),
                comments_reported=int(post.comments or 0),
                comments_collected=len(comments),
            )
        )

        # Rewrite after every post so an interrupted run still leaves usable data.
        write_master_files(all_posts, all_comments, output_dir)

    print(
        f"Done. Collected {len(all_posts)} posts and {len(all_comments)} comments/replies "
        f"into {output_dir.resolve()}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive Brad's public Instagram captions and comment threads for research."
    )
    parser.add_argument(
        "--login",
        required=True,
        help="Your own Instagram username, used only to authenticate comment requests.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of newest posts to collect. Default is 1 for the first test; use 0 for all posts.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(collect(build_parser().parse_args()))
