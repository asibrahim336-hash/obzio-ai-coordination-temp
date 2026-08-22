#!/usr/bin/env python3
"""Run the lost-callback fault injection and record observed results.

Usage:
    python3 run_reproduction.py --out observed-results.json
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ATTEMPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ATTEMPT_ROOT / "tests"))

from sandbox import PINNED_COMMIT, build_sandbox  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=ATTEMPT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ATTEMPT_ROOT / "observed-results.json"))
    arguments = parser.parse_args()

    probe = build_sandbox("probe")
    started = time.time()
    results = []
    for scenario in SCENARIOS:
        scenario_started = time.time()
        observations = scenario()
        observations["wall_seconds"] = round(time.time() - scenario_started, 3)
        results.append(observations)

    document = {
        "result_version": "PO03-WAVE-A-033-OBSERVED-RESULTS-v1",
        "task_id": "wave-a-033-lost-callback-reproduction",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "recorded_at": utc_now(),
        "decision_changed": [],
        "mechanism_under_test": {
            "path": "workstreams/po03/tools/transactional_factory.py",
            "pinned_commit": PINNED_COMMIT,
            "blob_sha": probe.mechanism_blob_sha,
            "sha256": probe.mechanism_sha256,
            "modified_by_reproduction": False,
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "attempt_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "attempt_base_commit": PINNED_COMMIT,
        },
        "total_wall_seconds": round(time.time() - started, 3),
        "scenarios": results,
    }
    destination = Path(arguments.out)
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    for scenario in results:
        print(f"  {scenario['scenario_id']}: {scenario['title']} ({scenario['wall_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
