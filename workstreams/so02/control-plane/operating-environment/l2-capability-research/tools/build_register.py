#!/usr/bin/env python3
"""Join hand-authored candidate assessments with mechanically harvested signals.

The judgement layer (candidate-assessments.json) and the evidence layer
(receipts/.../raw/github-signals.jsonl) are kept in separate files on purpose:
the register is then a join, not a transcription, so a live signal can never be
mis-copied into a verdict. Anything asserted in the assessment file that has no
matching harvested signal is emitted with signals set to null rather than
quietly filled in from recall.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

STALE_BEFORE = "2026-05-01"

SIGNAL_FIELDS = (
    "full_name", "html_url", "stars", "forks", "open_issues", "archived",
    "license", "default_branch", "created_at", "pushed_at",
    "latest_release_tag", "latest_release_published_at",
    "last_commit_sha", "last_commit_date", "homepage", "fetched_at_utc",
    "instrument",
)


def load_signals(path: str) -> dict[str, dict]:
    """Index by requested slug and, as a fallback, by the name GitHub resolved to.

    Several projects have moved org, so an assessment may legitimately name the
    current location while the harvest recorded the older slug that redirected.
    """
    by_slug: dict[str, dict] = {}
    by_resolved: dict[str, dict] = {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        by_slug[rec["slug"].lower()] = rec
        if rec.get("full_name"):
            by_resolved.setdefault(rec["full_name"].lower(), rec)
    for name, rec in by_resolved.items():
        by_slug.setdefault(name, rec)
    return by_slug


def maintenance_flags(sig: dict) -> list[str]:
    flags = []
    if sig.get("archived"):
        flags.append("ARCHIVED")
    pushed = sig.get("pushed_at") or ""
    if pushed and pushed < STALE_BEFORE:
        flags.append(f"STALE_LAST_PUSH_{pushed[:10]}")
    if not sig.get("latest_release_tag"):
        flags.append("NO_PUBLISHED_RELEASE")
    if sig.get("license") in (None, "NOASSERTION"):
        flags.append("LICENSE_NOT_MACHINE_RESOLVED")
    slug = sig.get("slug", "")
    full = sig.get("full_name", "")
    if slug and full and slug.lower() != full.lower():
        flags.append(f"MOVED_FROM_{slug}")
    return flags


def main() -> int:
    assessments_path, signals_path = sys.argv[1], sys.argv[2]
    assessments = json.load(open(assessments_path))
    signals = load_signals(signals_path)

    entries = []
    for a in assessments["candidates"]:
        slug = a.get("github_slug")
        sig = signals.get(slug.lower()) if slug else None

        entry = dict(a)
        if slug and sig is None:
            entry["live_signals"] = None
            entry["signal_status"] = "NOT_HARVESTED"
        elif sig is not None and not sig.get("resolved"):
            entry["live_signals"] = {"error": sig.get("error")}
            entry["signal_status"] = "UNRESOLVED_ON_GITHUB"
        elif sig is not None:
            entry["live_signals"] = {k: sig.get(k) for k in SIGNAL_FIELDS}
            entry["signal_status"] = "HARVESTED"
            entry["maintenance_flags"] = maintenance_flags(sig)
        else:
            entry["live_signals"] = None
            entry["signal_status"] = "NO_GITHUB_HOME"
        entries.append(entry)

    verdicts: dict[str, int] = {}
    for e in entries:
        verdicts[e["verdict"]] = verdicts.get(e["verdict"], 0) + 1

    out = {
        "artifact_id": "OE-L2-CANDIDATE-REGISTER-20260822-v001",
        "lane": "OE-L2-CAPABILITY-RESEARCH",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "parent_fence_token": "d5e76252f0ea259d",
        "built_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "binding_status": "NON_BINDING_RESEARCH_NO_TOOL_MODEL_OR_ARCHITECTURE_SELECTED",
        "how_to_read": assessments["how_to_read"],
        "verdict_definitions": assessments["verdict_definitions"],
        "stale_threshold_last_push_before": STALE_BEFORE,
        "counts": {
            "candidates": len(entries),
            "with_harvested_github_signals": sum(
                1 for e in entries if e["signal_status"] == "HARVESTED"
            ),
            "by_verdict": dict(sorted(verdicts.items())),
        },
        "candidates": entries,
    }
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
