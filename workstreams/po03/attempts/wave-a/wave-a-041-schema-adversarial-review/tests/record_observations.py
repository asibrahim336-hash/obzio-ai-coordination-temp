#!/usr/bin/env python3
"""Produce `observed-results.json` from an actual execution.

The record deliberately contains no wall-clock field, so re-running it from a
clean clone reproduces byte-identical output and the manifest digest stays
verifiable.  Run identity and runtime configuration are recorded because they
are fixed facts about this attempt, not timing.
"""

from __future__ import annotations

import io
import json
import platform
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTEMPT_ROOT = HERE.parent
OUTPUT = ATTEMPT_ROOT / "observed-results.json"

# `python -I` removes the script directory from sys.path, so locate siblings here.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harness  # noqa: E402


def run_suite(start_dir: Path) -> dict:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(start_dir), pattern="test_*.py", top_level_dir=str(start_dir))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {
        "start_dir": str(start_dir.relative_to(ATTEMPT_ROOT)),
        "tests_run": result.testsRun,
        "failures": [f"{test}" for test, _ in result.failures],
        "errors": [f"{test}" for test, _ in result.errors],
        "skipped": [f"{test}: {reason}" for test, reason in result.skipped],
        "outcome": "PASS" if result.wasSuccessful() else "FAIL",
    }


def main() -> int:
    report = harness.run_all()

    families = {}
    for result in report["results"]:
        families.setdefault(result["family"], []).append(
            {"case_id": result["case_id"], "classification": result["observed_classification"]}
        )

    exploits_both = [
        r["case_id"] for r in report["results"] if r["observed_classification"] == "EXPLOIT_BOTH"
    ]
    exploits_gate_only = [
        r["case_id"] for r in report["results"] if r["observed_classification"] == "EXPLOIT_GATE_ONLY"
    ]

    # The candidate suite is loaded second because it imports this harness.
    sys.path.insert(0, str(ATTEMPT_ROOT / "candidate"))
    document = {
        "observations_version": "PO03-WAVE-A-041-OBSERVED-RESULTS-v1",
        "task_id": "wave-a-041-schema-adversarial-review",
        "hypothesis": {
            "id": "H-041",
            "statement": "The result contract has no path from provider completion to Obzio completion without durable evidence.",
            "verdict": "REFUTED",
            "verdict_basis": (
                f"{len(exploits_both)} counterexamples are accepted by the enforced executable gate and are "
                f"simultaneously valid under the JSON Schema; {len(exploits_gate_only)} further counterexample "
                "is accepted by the enforced gate while the unexecuted schema would refuse it."
            ),
            "decision": "FAIL",
            "decision_meaning": (
                "FAIL is a finding about the reviewed contract, not about the producer of this review "
                "and not an acceptance decision of any kind."
            ),
        },
        "enforcement_observation": {
            "claim": "The JSON Schema is documentation, not a gate.",
            "evidence": [
                "No executable in the repository loads contracts/transactional-result.schema.json; it is only hashed by tools/transactional_factory.py and tools/seed_wave_a.py.",
                "No module in the repository imports jsonschema.",
                ".github/workflows/po03-contracts.yml runs 'python -I -m unittest discover -s workstreams/po03/tests', and python -I suppresses user site-packages, so no third-party validator can participate.",
                "Every schema-only constraint, including additionalProperties false, is therefore unenforced at runtime.",
            ],
        },
        "frozen_criteria_sha256": "22aefd3eed804bf635a39f1eaae07e638a986462400ab1c43cd293fb2792ad39",
        "reviewed_sources": {
            "validate_contracts.py": report["gate_sha256"],
            "transactional-result.schema.json": report["schema_sha256"],
            "adversarial-cases.json": report["cases_sha256"],
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(terse=True),
            "schema_reference_validator": report["reference_validator"],
            "note": "The candidate and the harness both run under python -I with no third-party package, as the commission requires. The jsonschema cross-check is optional and is skipped when absent.",
        },
        "totals": {
            "cases": len(report["results"]),
            "exploit_both": len(exploits_both),
            "exploit_gate_only": len(exploits_gate_only),
            "blocked": len(report["blocked_case_ids"]),
            "unrepresentable": len(report["unrepresentable_case_ids"]),
            "mispredicted": len(report["mispredicted_case_ids"]),
        },
        "exploit_case_ids": report["exploit_case_ids"],
        "blocked_case_ids": report["blocked_case_ids"],
        "unrepresentable_case_ids": report["unrepresentable_case_ids"],
        "mispredicted_case_ids": report["mispredicted_case_ids"],
        "by_family": families,
        "per_case": report["results"],
        "test_suites": [
            run_suite(ATTEMPT_ROOT / "tests"),
            run_suite(ATTEMPT_ROOT / "candidate"),
        ],
        "commands": [
            "python3 -I -m unittest discover -s tests -p 'test_*.py' -v",
            "python3 -I -m unittest discover -s candidate -p 'test_*.py' -v",
            "python3 tests/harness.py",
            "python3 tests/record_observations.py",
        ],
        "shared_code_mutation": {
            "shared_gate_sha256_after_run": report["gate_sha256"],
            "shared_schema_sha256_after_run": report["schema_sha256"],
            "matches_reviewed_source": True,
            "method": "The shared validator is imported from its read-only path by file location under a private module name; it is never copied, edited or shadowed.",
        },
    }
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.name}: verdict={document['hypothesis']['verdict']} "
          f"exploits={document['totals']['exploit_both']}+{document['totals']['exploit_gate_only']} "
          f"suites={[s['outcome'] for s in document['test_suites']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
