#!/usr/bin/env python3
"""Emit the successor receipt from committed evidence.

    python3 -I workstreams/po03/successor/write_receipt.py --write
    python3 -I workstreams/po03/successor/write_receipt.py --check

The receipt is generated, not written by hand, for the same reason the score and
the lineage are: every hash in it is a claim about a file, and a hand-copied hash
is a claim that stops being true the moment the file changes.  Here the hashes
are read from the files themselves, so ``--check`` fails if the receipt has
drifted from the tree it describes.

The receipt records states this cohort is permitted to emit.  ``RESULT_COMMITTED``
is the strongest, acceptance is ``NOT_TESTED``, and nothing here accepts this
cohort's own work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

TARGET = REPO_ROOT / "receipts" / "po03" / "2026-08-22" / "successor-generation.json"
BRANCH = "cursor/po03-a8-successor-generations-ed20"

ARTIFACTS = (
    "workstreams/po03/successor/g0/controller.py",
    "workstreams/po03/successor/g0/provenance.json",
    "workstreams/po03/successor/g1/factory.py",
    "workstreams/po03/successor/g1/packaging.json",
    "workstreams/po03/successor/g2/successor.py",
    "workstreams/po03/successor/g2/lineage.json",
    "workstreams/po03/successor/suite/public/cases.json",
    "workstreams/po03/successor/suite/holdout/cases.json",
    "workstreams/po03/successor/suite/holdout/a6-source-cases.json",
    "workstreams/po03/successor/suite/holdout/provenance.json",
    "workstreams/po03/successor/suite/lift-preregistration.json",
    "workstreams/po03/successor/suite/suite-manifest.json",
    "workstreams/po03/successor/scores/generation-comparison.json",
    "workstreams/po03/successor/lessons/lessons.json",
)

UNITS = (
    ("a8-u01", "G0 reconstructed as executable code from immutable pre-amendment source"),
    ("a8-u02", "G1 packaged as a generation runnable from its own entry point"),
    ("a8-u03", "public suite frozen, a6 holdout bound, lift metric preregistered"),
    ("a8-u04", "G2 compiled from G1 failures and accepted lessons with explicit lineage"),
    ("a8-u05", "all three generations scored on identical frozen inputs"),
    ("a8-u06", "lesson register with mechanism, recurrence test and disposition"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def build_document() -> dict:
    scores = json.loads((PO03 / "successor" / "scores" / "generation-comparison.json").read_text(encoding="utf-8"))
    lessons = json.loads((PO03 / "successor" / "lessons" / "lessons.json").read_text(encoding="utf-8"))

    generations = {
        key: {
            "label": value["label"],
            "entry_point": value["entry_point"],
            "source": value["source"],
            "source_sha256": value["source_sha256"],
            "public": f"{value['suites']['public']['cases_passed']}/{value['suites']['public']['cases_total']}",
            "holdout": f"{value['suites']['holdout']['cases_passed']}/{value['suites']['holdout']['cases_total']}",
            "false_completions_public": value["suites"]["public"]["false_completion_count"],
            "false_completions_holdout": value["suites"]["holdout"]["false_completion_count"],
        }
        for key, value in scores["generations"].items()
    }

    unit_records = []
    for unit_id, outcome in UNITS:
        record_path = PO03 / "control" / "units" / "a8" / f"{unit_id}.json"
        unit_records.append(
            {
                "unit_id": unit_id,
                "outcome": outcome,
                "state": "RESULT_COMMITTED" if record_path.is_file() else "READY_TO_COMMIT",
                "result_record": f"workstreams/po03/control/units/a8/{unit_id}.json",
                "result_record_present": record_path.is_file(),
            }
        )

    return {
        "receipt_id": "RCP-PO03-A8-SUCCESSOR-GENERATION-20260822-v001",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "commission_revision": "v002",
        "cohort_id": "a8",
        "owner": "po03-worker-a8",
        "function": "successor-generation test: three measured generations, each executable code with tests",
        "branch": BRANCH,
        "generated_by": "workstreams/po03/successor/write_receipt.py",
        "state": "RESULT_COMMITTED",
        "acceptance": "NOT_TESTED",
        "acceptance_note": (
            "This cohort cannot accept its own work and has not set COMPLETED. Acceptance is for the "
            "coordinator and the independent evaluator cohorts."
        ),
        "units": unit_records,
        "generations": generations,
        "measurement": {
            "preregistration": scores["preregistration"],
            "headline": scores["headline"],
            "comparisons": [
                {
                    "baseline": row["baseline"],
                    "candidate": row["candidate"],
                    "suite": row["suite"],
                    "lift": row.get("lift"),
                    "verdict": row["verdict"],
                    "unmet_conditions": row["unmet_conditions"],
                }
                for row in scores["comparisons"]
            ],
            "reproduction_command": "python3 -I workstreams/po03/successor/score_generations.py --check",
            "test_gate": "python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'",
        },
        "suites": scores["suites"],
        "lessons": {
            "register": "workstreams/po03/successor/lessons/lessons.json",
            "lesson_count": lessons["lesson_count"],
            "independently_supported_count": lessons["independently_supported_count"],
            "qualifying_count": lessons["qualifying_count"],
            "acceptance_threshold": lessons["acceptance_threshold"],
            "acceptance_met": lessons["acceptance_met"],
            "dispositions_used": lessons["dispositions_used"],
            "verification_command": "python3 -I workstreams/po03/successor/lessons/build_lessons.py --verify-support",
        },
        "consumers": {
            "workstreams/po03/metrics/generation-comparison.json": (
                "owned by po03-worker-a7, which consumes the scores under successor/scores/; this cohort "
                "did not write into workstreams/po03/metrics/"
            )
        },
        "artifacts": [
            {"path": path, "sha256": sha256(REPO_ROOT / path)} for path in ARTIFACTS
        ],
        "boundaries": [
            {
                "boundary": "recurrence tests are authored by this cohort",
                "status": "NOT_YET",
                "detail": (
                    "a8-u06's frozen acceptance asks for a recurrence test authored by a different owner. "
                    "Every test under workstreams/po03/tests/test_a8_ is authored by po03-worker-a8. The "
                    "material each test is bound to is independent - a6's evaluator-held cases and a10's "
                    "published audit findings - but the test code is not."
                ),
            },
            {
                "boundary": "no a8 unit has been independently accepted",
                "status": "NOT_YET",
                "detail": (
                    "At a6's scoring snapshot this branch was absent from a6's fetch, so a6 recorded all six "
                    "a8 units as unavailable evidence rather than as quality failures. Absence of an adverse "
                    "finding is not acceptance."
                ),
            },
            {
                "boundary": "the live control plane still carries the defects G2 fixes",
                "status": "NOT_SUPPORTED",
                "detail": (
                    "workstreams/po03/tools/control_plane.py is coordinator-owned and was not modified. G2 is "
                    "a successor generation and a proposal, not a deployment."
                ),
            },
            {
                "boundary": "derived bytecode remains tracked outside this cohort's ownership",
                "status": "NOT_YET",
                "detail": (
                    "Two tracked .pyc files remain under workstreams/po03/tests/ and workstreams/po03/tools/. "
                    "check_custody_hygiene.py reports them and refuses any under owned paths; lesson L-13 is "
                    "held at RETEST rather than closed."
                ),
            },
        ],
        "po01_non_interference": True,
        "merge_authority": False,
        "decision_changed": [],
        "read_back_verification": (
            f"git cat-file blob origin/{BRANCH}:<path> | sha256sum must match the artifact hashes above"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text = json.dumps(build_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
            print(f"DRIFTED {TARGET}: the receipt no longer matches the tree it describes")
            return 1
        print(f"CONSISTENT {TARGET}")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"WROTE {TARGET} at {head()[:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
