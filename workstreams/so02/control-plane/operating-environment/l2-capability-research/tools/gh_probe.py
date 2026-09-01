#!/usr/bin/env python3
"""Harvest live GitHub maintenance signals for candidate repositories.

Reads newline-separated `owner/repo` slugs on stdin (blank lines and `#` comments
ignored) and writes one JSON object per slug to stdout as JSONL.

Every field is taken verbatim from the GitHub REST API so the output is
DIRECTLY_REPRODUCED evidence rather than model recall. A slug that cannot be
resolved is emitted with `"resolved": false` and the API error, never guessed.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import subprocess
import sys

FETCHED_AT = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh(path: str) -> tuple[bool, object]:
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip()[:400]
    try:
        return True, json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return False, f"json decode error: {exc}"


def probe(slug: str) -> dict:
    out: dict = {
        "slug": slug,
        "fetched_at_utc": FETCHED_AT,
        "instrument": f"gh api /repos/{slug}",
        "resolved": False,
    }
    ok, repo = gh(f"/repos/{slug}")
    if not ok:
        out["error"] = repo
        return out

    out.update(
        {
            "resolved": True,
            "full_name": repo.get("full_name"),
            "html_url": repo.get("html_url"),
            "description": (repo.get("description") or "")[:300],
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
            "open_issues": repo.get("open_issues_count"),
            "archived": repo.get("archived"),
            "disabled": repo.get("disabled"),
            "fork": repo.get("fork"),
            "is_template": repo.get("is_template"),
            "license": (repo.get("license") or {}).get("spdx_id"),
            "license_name": (repo.get("license") or {}).get("name"),
            "default_branch": repo.get("default_branch"),
            "created_at": repo.get("created_at"),
            "pushed_at": repo.get("pushed_at"),
            "updated_at": repo.get("updated_at"),
            "homepage": repo.get("homepage"),
            "topics": repo.get("topics") or [],
            "owner_type": (repo.get("owner") or {}).get("type"),
        }
    )

    ok, rel = gh(f"/repos/{slug}/releases/latest")
    if ok and isinstance(rel, dict):
        out["latest_release_tag"] = rel.get("tag_name")
        out["latest_release_published_at"] = rel.get("published_at")
        out["latest_release_prerelease"] = rel.get("prerelease")
    else:
        out["latest_release_tag"] = None
        out["latest_release_note"] = "no published release via /releases/latest"

    ok, commits = gh(f"/repos/{slug}/commits?per_page=1")
    if ok and isinstance(commits, list) and commits:
        c = commits[0]
        out["last_commit_sha"] = c.get("sha")
        out["last_commit_date"] = (
            ((c.get("commit") or {}).get("committer") or {}).get("date")
        )
        out["last_commit_message"] = (
            ((c.get("commit") or {}).get("message") or "").splitlines() or [""]
        )[0][:160]
    return out


def main() -> int:
    slugs = []
    for line in sys.stdin:
        line = line.split("#", 1)[0].strip()
        if line:
            slugs.append(line)

    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(probe, slugs):
            results[res["slug"]] = res

    for slug in slugs:
        print(json.dumps(results[slug], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
