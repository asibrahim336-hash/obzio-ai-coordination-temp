#!/usr/bin/env python3
"""Re-fetch the sources this lane's function adjudication depends on.

Standard library only. Sends no credential, follows redirects, records the
final URL, HTTP status, byte count and sha256 of every body, and writes the
bodies so a later reader can check that an excerpt was really cut out of the
document rather than recalled.

The lane's own claims are cut out of these bodies by
``build_claim_evidence.py``; if a locator stops matching, that build fails
rather than emitting a stale quotation.

    python3 tools/verify_function_claims.py --out DOCS --log LOG.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

# Only the sources on which an adjudication verdict, the admission rule or the
# triage plan actually rests. This is deliberately not a route census: the
# route evidence table is a sibling lane's deliverable and duplicating it here
# would produce two tables that can disagree.
SOURCES: dict[str, str] = {
    # A — function adjudication
    "chatgpt-voice": "https://learn.chatgpt.com/docs/features/voice.md",
    "chatgpt-projects": "https://learn.chatgpt.com/docs/projects.md",
    "chatgpt-memories": "https://learn.chatgpt.com/docs/customization/memories.md",
    "chatgpt-automations": "https://learn.chatgpt.com/docs/automations.md",
    "chatgpt-apps-connectors": "https://learn.chatgpt.com/docs/enterprise/apps-and-connectors.md",
    "chatgpt-plugins": "https://learn.chatgpt.com/docs/plugins.md",
    "chatgpt-import": "https://learn.chatgpt.com/docs/import.md",
    # B — provenance and admission
    "chatgpt-compliance-api": "https://learn.chatgpt.com/docs/enterprise/compliance-api.md",
    "chatgpt-governance": "https://learn.chatgpt.com/docs/enterprise/governance.md",
    # C — triage. help.openai.com answers 403 to an unauthenticated fetch, so the
    # consumer Settings -> Data Controls surface cannot be evidenced from here.
    # It is probed anyway, so the gap is recorded rather than assumed away.
    "openai-export-data": (
        "https://help.openai.com/en/articles/"
        "7260999-how-do-i-export-my-chatgpt-history-and-data"
    ),
    # index, so a broken path above is visible rather than guessed at
    "index-chatgpt": "https://learn.chatgpt.com/llms.txt",
}

UA = "obzio-oe-w8-constitution/1.0 (+unauthenticated documentation fetch)"


def fetch(url: str, timeout: float = 25.0) -> tuple[int, bytes, str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, body, resp.geturl(), 0
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a body worth hashing
        body = exc.read()
        return exc.code, body, exc.url or url, 0
    except Exception as exc:  # noqa: BLE001 - network shape is not knowable here
        return -1, str(exc).encode("utf-8"), url, 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory to write fetched bodies")
    ap.add_argument("--log", required=True, help="path for the JSON fetch log")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    entries: dict[str, dict] = {}
    ok_count = 0
    for name, url in sorted(SOURCES.items()):
        status, body, final, err = fetch(url)
        digest = hashlib.sha256(body).hexdigest()
        if status == 200:
            ok_count += 1
            (out / f"{name}.md").write_bytes(body)
        entries[name] = {
            "url_requested": url,
            "url_effective": final,
            "http_status": status,
            "bytes": len(body),
            "sha256": digest,
            "credential_sent": False,
            "ok": status == 200,
            "error": err,
            "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(f"{status:>4}  {name:<26} {len(body):>7}B  {url}", file=sys.stderr)

    log = {
        "artifact_id": "OE-W8-CLAIM-SOURCE-FETCH-LOG",
        "lane": "OE-W8-CHATGPT-CONSTITUTION",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "authenticated_requests": 0,
        "credential_used": None,
        "source_count": len(SOURCES),
        "http_200_count": ok_count,
        "non_200": {k: v["http_status"] for k, v in entries.items() if not v["ok"]},
        "sources": entries,
    }
    pathlib.Path(args.log).write_text(
        json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\n{ok_count}/{len(SOURCES)} at HTTP 200", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
