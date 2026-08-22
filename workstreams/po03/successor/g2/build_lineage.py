#!/usr/bin/env python3
"""Project G2's change table into lineage.json, with measured evidence per change.

The lineage document is generated rather than written by hand for one reason: a
hand-maintained lineage table drifts from the code it describes, and a drifted
lineage table is worse than none because it looks like evidence.  Here the
causes come from ``CHANGES`` in the code itself, and the evidence for each cause
is produced by actually running that change's named cases against G1 and G2.

    python3 -I workstreams/po03/successor/g2/build_lineage.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[2]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g1 import factory as g1  # noqa: E402
from successor.g2 import successor as g2  # noqa: E402
from successor.harness.runner import load_cases, run_suite  # noqa: E402

TARGET = PO03 / "successor" / "g2" / "lineage.json"
SUITES = (
    PO03 / "successor" / "suite" / "public" / "cases.json",
    PO03 / "successor" / "suite" / "holdout" / "cases.json",
)


def load_all_cases() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for path in SUITES:
        _, entries = load_cases(path)
        for case in entries:
            cases[case["id"]] = case
    return cases


def verdicts(case_ids: list[str], catalogue: dict[str, dict]) -> list[dict]:
    """Run exactly the named cases against G1 and G2 and report both outcomes."""
    selected = [catalogue[case_id] for case_id in case_ids if case_id in catalogue]
    if not selected:
        return []
    before = {record["case_id"]: record["passed"] for record in run_suite(g1.build, selected)}
    after = {record["case_id"]: record["passed"] for record in run_suite(g2.build, selected)}
    return [
        {
            "case_id": case_id,
            "case_present_in_frozen_suite": case_id in catalogue,
            "g1_verdict": "PASS" if before.get(case_id) else "FAIL",
            "g2_verdict": "PASS" if after.get(case_id) else "FAIL",
            "closed_by_this_change": bool(after.get(case_id)) and not before.get(case_id),
        }
        for case_id in case_ids
    ]


def build_document() -> dict:
    catalogue = load_all_cases()
    changes = []
    for change in g2.CHANGES:
        declared = list(change["caused_by_failures"])
        missing = [case_id for case_id in declared if case_id not in catalogue]
        evidence = verdicts(declared, catalogue)
        changes.append(
            {
                "change_id": change["change_id"],
                "name": change["name"],
                "caused_by_failures": declared,
                "caused_by_lessons": list(change["caused_by_lessons"]),
                "g1_behaviour": change["g1_behaviour"],
                "change": change["change"],
                "recurrence_test": change["recurrence_test"],
                "evidence": evidence,
                "unknown_case_ids": missing,
                # A change may be caused by a frozen suite case or by an
                # independently supported lesson.  The suites were frozen before
                # the evaluator cohorts published, so a later finding cannot have
                # a case: its recurrence test carries the evidence instead.
                "evidence_basis": "frozen_suite_case" if declared else "independently_supported_lesson",
                "all_named_failures_closed": (
                    all(row["closed_by_this_change"] for row in evidence) if declared else "NOT_APPLICABLE"
                ),
            }
        )
    return {
        "document_id": "po03-a8-g2-lineage-v001",
        "unit_id": "a8-u04",
        "generation_id": "G2",
        "owner": "po03-worker-a8",
        "generated_by": "workstreams/po03/successor/g2/build_lineage.py",
        "compilation_rule": "Every change traces to a specific case G1 was measured to fail, or to a lesson independently supported by an evaluator cohort of a different owner, or to both. A change with no such trace falsifies a8-u04 regardless of its effect on the score.",
        "verification": "workstreams/po03/tests/test_a8_g2_lineage.py asserts this document matches the change table in the code, that every named case exists in a frozen suite, that G1 fails it and G2 passes it, that a change with no named case names an independently supported lesson instead, and that every change names a recurrence test that exists.",
        "change_count": len(changes),
        "changes": changes,
        "inherited_from_g1_unchanged": [
            "the hash-chained append-only ledger and its row schema",
            "the state projection that rebuilds the fleet from the ledger alone",
            "the allowlist and ownership prefix rules",
            "artifact digest and byte-count verification at admission",
            "the refusal to treat provider completion as Obzio completion",
            "the requirement that completion follow parent ingestion",
            "the self-acceptance refusal on the dispatched owner"
        ],
        "not_changed_and_why": [
            {
                "candidate": "independent rejection of path traversal inside the ownership check",
                "reason": "the allowlist already refuses traversal before ownership is consulted, so no case measured a failure and no lesson supported it. Adding it would have been an untraceable change, which the compilation rule forbids even when the change is harmless.",
                "disposition": "SUPERSEDED_BY_C-10",
                "disposition_basis": "Cohort a10's audit finding D1 (INV-6) showed the premise was false: the allowlist check normalised the declared path with a character-class lstrip that does not match the join used for I/O, so traversal was not refused before ownership was consulted. The entry is retained rather than deleted because it records what was believed, and on what basis, at the time G2 was first compiled.",
                "superseded_by": "C-10",
                "superseding_lesson": "L-11"
            }
        ],
        "revision_note": "C-10 and C-11 were added after the first scoring run, in response to findings published by an independent evaluator cohort rather than to anything measured on the frozen suites. The suites were not modified. The pre-revision score is preserved in git at commit 91452a0 and the score was re-derived afterwards; see workstreams/po03/successor/lessons/lessons.json for the comparison."
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text = json.dumps(build_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
            print(f"DRIFTED {TARGET}: the lineage document no longer matches the change table")
            return 1
        print(f"CONSISTENT {TARGET}")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"WROTE {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
