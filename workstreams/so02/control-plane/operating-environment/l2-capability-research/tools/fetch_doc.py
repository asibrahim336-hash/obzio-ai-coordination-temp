#!/usr/bin/env python3
"""Fetch a URL with curl and record reproducible evidence.

Usage: fetch_doc.py <slug> <url> [--raw]

Writes `<slug>.meta.json` (status, effective URL, content type, sha256 of the body,
fetch timestamp, exact curl command) and `<slug>.txt` (tag-stripped text, or the raw
body when --raw) into the directory named by OE_EVIDENCE_DIR.

Keeping the command and the fetch date next to the extract is what lets a later
reader re-run the fetch and compare, so the claim stays DIRECTLY_REPRODUCED.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys

EVIDENCE_DIR = os.environ.get("OE_EVIDENCE_DIR", ".")

_DROP = re.compile(
    r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", re.I | re.S
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n{3,}")


def to_text(body: str) -> str:
    body = _DROP.sub(" ", body)
    body = re.sub(r"</(p|div|li|tr|h[1-6]|section|article)>", "\n", body, flags=re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = _TAG.sub(" ", body)
    body = html.unescape(body)
    body = _WS.sub(" ", body)
    body = "\n".join(line.strip() for line in body.split("\n"))
    return _BLANK.sub("\n\n", body).strip()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    slug, url = sys.argv[1], sys.argv[2]
    raw = "--raw" in sys.argv[3:]

    cmd = [
        "curl", "-sSL", "--max-time", "60", "--compressed",
        "-A", "Mozilla/5.0 (X11; Linux x86_64) obzio-capability-research",
        "-w", "\n__CURLMETA__%{http_code}\t%{url_effective}\t%{content_type}\n",
        url,
    ]
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")

    body, status, effective, ctype = proc.stdout, None, None, None
    marker = body.rfind("\n__CURLMETA__")
    if marker != -1:
        meta_line = body[marker:].strip().removeprefix("__CURLMETA__").split("\t")
        body = body[:marker]
        status = meta_line[0] if len(meta_line) > 0 else None
        effective = meta_line[1] if len(meta_line) > 1 else None
        ctype = meta_line[2] if len(meta_line) > 2 else None

    text = body if raw else to_text(body)
    max_chars = int(os.environ.get("OE_MAX_CHARS", "0") or 0)
    truncated = False
    if max_chars and len(text) > max_chars:
        text, truncated = text[:max_chars], True
    meta = {
        "extract_truncated": truncated,
        "slug": slug,
        "requested_url": url,
        "effective_url": effective,
        "http_status": status,
        "content_type": ctype,
        "fetched_at_utc": fetched_at,
        "curl_exit_code": proc.returncode,
        "curl_stderr": (proc.stderr or "").strip()[:300],
        "body_bytes": len(body.encode("utf-8", "replace")),
        "body_sha256": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
        "extract_chars": len(text),
        "command": "curl -sSL --max-time 60 --compressed " + url,
    }

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(os.path.join(EVIDENCE_DIR, f"{slug}.meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(EVIDENCE_DIR, f"{slug}.txt"), "w") as fh:
        fh.write(text)

    print(json.dumps({k: meta[k] for k in
                      ("slug", "http_status", "effective_url", "extract_chars")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
