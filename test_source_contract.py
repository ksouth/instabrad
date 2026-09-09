#!/usr/bin/env python3
"""Source-derived contract test for Brad Instagram comment extraction.

These cases come directly from the saved Dclt_nKkUVg Instagram HTML fixture.
They protect the source-first assumptions used by test_brad_stream_archive.py:
- comment permalinks carry stable comment IDs;
- one username may own many distinct comments;
- reply controls use "View all N replies";
- structured rows enrich an existing comment ID rather than duplicating it.
"""

import re

POST_CODE = "Dclt_nKkUVg"
COMMENT_HREF_RE = re.compile(rf"^/p/{re.escape(POST_CODE)}/c/(\d+)/?$")
REPLY_TEXT_RE = re.compile(r"^View all\s+(\d+)\s+repl(?:y|ies)$", re.I)

# Distinct comment permalinks observed for @snoredan in the saved Brad HTML.
SNOREDAN_HREFS = [
    "/p/Dclt_nKkUVg/c/17982474650886584/",
    "/p/Dclt_nKkUVg/c/18147489409554118/",
    "/p/Dclt_nKkUVg/c/17864997819660711/",
    "/p/Dclt_nKkUVg/c/18559999156073192/",
    "/p/Dclt_nKkUVg/c/18265754098307104/",
    "/p/Dclt_nKkUVg/c/17944114479296200/",
]


def merge(archive: dict[str, dict], rows: list[dict]) -> int:
    added = 0
    for row in rows:
        cid = str(row.get("comment_id") or "")
        if not cid:
            continue
        if cid not in archive:
            archive[cid] = dict(row)
            added += 1
            continue
        existing = archive[cid]
        if row.get("source") == "instagram-structured-json":
            for key, value in row.items():
                if value not in (None, ""):
                    existing[key] = value
    return added


def test_permalink_contract() -> None:
    ids = []
    for href in SNOREDAN_HREFS:
        match = COMMENT_HREF_RE.match(href)
        assert match, href
        ids.append(match.group(1))
    assert len(set(ids)) == 6


def test_reply_button_contract() -> None:
    assert REPLY_TEXT_RE.match("View all 1 replies")
    assert REPLY_TEXT_RE.match("View all 2 replies")


def test_same_username_keeps_distinct_ids() -> None:
    ids = [COMMENT_HREF_RE.match(href).group(1) for href in SNOREDAN_HREFS]
    archive: dict[str, dict] = {}
    rows = [
        {"comment_id": cid, "username": "snoredan", "source": "dom-permalink"}
        for cid in ids
    ]
    assert merge(archive, rows) == 6
    assert len(archive) == 6

    # Structured enrichment of a known ID must not create a seventh record.
    assert merge(
        archive,
        [
            {
                "comment_id": ids[0],
                "username": "snoredan",
                "text": "enriched",
                "source": "instagram-structured-json",
            }
        ],
    ) == 0
    assert len(archive) == 6
    assert archive[ids[0]]["text"] == "enriched"


if __name__ == "__main__":
    test_permalink_contract()
    test_reply_button_contract()
    test_same_username_keeps_distinct_ids()
    print("PASS source-derived comment extraction contract")
