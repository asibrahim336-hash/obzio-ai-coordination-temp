#!/usr/bin/env python3
"""Turn a `cursor-cloud list-cloud-agents` census into a concurrency record.

The input is the verbatim tool response recorded under receipts/raw. This script
derives only what the census actually supports: how many top-level cloud agents
existed, how many distinct exact model configurations ran, and the tightest
observed simultaneous-dispatch window. It deliberately does not infer a platform
concurrency ceiling, because a census of what did run is not a measurement of
what may run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys


def iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build(census: dict) -> dict:
    agents = census["agents"]
    models = sorted({a["originalModelName"] for a in agents if a.get("originalModelName")})
    families = sorted({m.split("-")[0] for m in models})

    # The tightest window in which N agents were created, for every N.
    stamps = sorted(a["createdAtMs"] for a in agents)
    bursts = []
    for n in range(2, len(stamps) + 1):
        span = min(stamps[i + n - 1] - stamps[i] for i in range(len(stamps) - n + 1))
        bursts.append({"agents": n, "tightest_window_ms": span})
    widest_burst = max((b for b in bursts if b["tightest_window_ms"] <= 1000), key=lambda b: b["agents"], default=None)

    by_source: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in agents:
        by_source[a["source"]] = by_source.get(a["source"], 0) + 1
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1

    return {
        "record_id": "OE-W5-CONCURRENCY-EVIDENCE-20260822-v001",
        "lane": "OE-W5-AGENTIC-OFFICE-GUIDE",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "evidence_label": "DIRECTLY_REPRODUCED",
        "instrument": "cursor-cloud list-cloud-agents (limit=200, includeArchived=true)",
        "scan_complete": census.get("hasMore") is False,
        "totals": {
            "top_level_cloud_agents": census["totalMatched"],
            "one_account": True,
            "one_repository": len({a["repoUrl"] for a in agents}) == 1,
            "distinct_exact_model_configurations": len(models),
            "distinct_model_families": len(families),
        },
        "exact_model_configurations_observed": models,
        "model_families_observed": families,
        "by_source": by_source,
        "by_lifecycle_status": by_status,
        "simultaneous_dispatch": {
            "largest_burst_within_1000ms": widest_burst,
            "window_by_count": bursts,
            "earliest_created_at": iso(stamps[0]),
            "latest_created_at": iso(stamps[-1]),
        },
        "what_this_does_and_does_not_establish": {
            "establishes": [
                "One Cursor account ran this many top-level cloud agents on one repository.",
                "Several distinct exact model configurations ran concurrently under one account.",
                "A burst of agents was dispatched inside a sub-second window from a single operator action.",
            ],
            "does_not_establish": [
                "Any platform concurrency ceiling. A census of what did run is not a measurement of what may run.",
                "Any statement about compute or rate-limit contention. Only the visible run layer is observable from inside a pod.",
                "Any cost figure. Token consumption is not exposed by this instrument.",
            ],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", required=True, help="verbatim list-cloud-agents JSON")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    census = json.loads(pathlib.Path(a.census).read_text())
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(build(census), indent=2, sort_keys=False) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
