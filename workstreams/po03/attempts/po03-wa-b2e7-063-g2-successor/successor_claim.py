#!/usr/bin/env python3
"""Decide whether the successor may claim improvement, and refuse when it may not.

The claim is evaluated against the preregistration committed before any
generation was measured, not against a rule chosen once the numbers were in.  The
tool reads the threshold and the decision rule out of that document rather than
restating them, so lowering the bar would require editing a file whose earlier
bytes are already in the history.

Every conjunct is reported with the numbers that decided it.  If any conjunct
fails, the claim is REFUSED and the honest outcome is NOT_YET.  A refusal is a
result, not an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLAIM_VERSION = "PO03-SUCCESSOR-CLAIM-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def outcomes_by_case(measurement: dict[str, Any]) -> dict[str, str]:
    return {record["case_id"]: record["outcome"] for record in measurement["records"]}


def comparable(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Two runs are only comparable when they measured the same suite bytes."""
    left, right = before["suite_freeze"], after["suite_freeze"]
    checks = {
        "public_suite_sha256_identical": left["public_suite_sha256"] == right["public_suite_sha256"],
        "holdout_sha256_identical": left["holdout_sha256"] == right["holdout_sha256"],
        "holdout_seal_identical": left.get("holdout_seal_combined_sha256")
        == right.get("holdout_seal_combined_sha256"),
        "case_count_identical": before["combined"]["case_count"] == after["combined"]["case_count"],
        "case_ids_identical": sorted(outcomes_by_case(before)) == sorted(outcomes_by_case(after)),
    }
    checks["comparable"] = all(checks.values())
    return checks


def evaluate(
    preregistration: dict[str, Any],
    g1: dict[str, Any],
    g2: dict[str, Any],
    regression: dict[str, Any] | None,
) -> dict[str, Any]:
    threshold = float(preregistration["lift_threshold"]["successor_lift_minimum"])
    before, after = outcomes_by_case(g1), outcomes_by_case(g2)
    regressed = sorted(
        case_id for case_id, outcome in before.items() if outcome == "PASS" and after.get(case_id) != "PASS"
    )
    repaired = sorted(
        case_id for case_id, outcome in before.items() if outcome != "PASS" and after.get(case_id) == "PASS"
    )
    lift = g2["combined"]["pass_rate"] - g1["combined"]["pass_rate"]

    conjuncts = [
        {
            "conjunct": "successor_lift >= lift_threshold",
            "observed": {"successor_lift": lift, "threshold": threshold,
                         "g1_combined_pass_rate": g1["combined"]["pass_rate"],
                         "g2_combined_pass_rate": g2["combined"]["pass_rate"]},
            "met": lift >= threshold,
        },
        {
            "conjunct": "quality_regression_count == 0 on the frozen suites",
            "observed": {"regressed_cases": regressed, "quality_regression_count": len(regressed)},
            "met": not regressed,
        },
        {
            "conjunct": "false_green_rate(G2) <= false_green_rate(G1)",
            "observed": {
                "g1_false_green_rate": g1["combined"]["false_green_rate"],
                "g2_false_green_rate": g2["combined"]["false_green_rate"],
                "g1_reported_success_count": g1["combined"]["reported_success_count"],
                "g2_reported_success_count": g2["combined"]["reported_success_count"],
            },
            "met": g2["combined"]["false_green_rate"] <= g1["combined"]["false_green_rate"],
        },
        {
            "conjunct": "public_suite_pass_rate(G2) >= public_suite_pass_rate(G1)",
            "observed": {"g1": g1["public"]["pass_rate"], "g2": g2["public"]["pass_rate"]},
            "met": g2["public"]["pass_rate"] >= g1["public"]["pass_rate"],
        },
        {
            "conjunct": "holdout_pass_rate(G2) >= holdout_pass_rate(G1)",
            "observed": {"g1": g1["holdout"]["pass_rate"], "g2": g2["holdout"]["pass_rate"]},
            "met": g2["holdout"]["pass_rate"] >= g1["holdout"]["pass_rate"],
        },
    ]

    if regression is not None:
        comparison = regression["comparison"]
        conjuncts.append(
            {
                "conjunct": "no regression in the independent baseline suite this cohort did not author",
                "observed": {
                    "suite": regression["suite"]["origin"],
                    "g1_ok": regression["g1"]["totals"]["ok"],
                    "g2_ok": regression["g2"]["totals"]["ok"],
                    "regressed_tests": comparison["regressed_tests"],
                    "disappeared_tests": comparison["disappeared_tests"],
                },
                "met": bool(comparison["no_quality_regression"]),
            }
        )

    comparability = comparable(g1, g2)
    unmet = [entry["conjunct"] for entry in conjuncts if not entry["met"]]
    claim = "SUPPORTED" if comparability["comparable"] and not unmet else "REFUSED"
    return {
        "claim_version": CLAIM_VERSION,
        "evaluated_at": utc_now(),
        "hypothesis": "A successor compiled from G1 failures and accepted lessons outperforms G1 on "
                      "preregistered metrics with no quality regression.",
        "preregistration": {
            "version": preregistration["preregistration_version"],
            "lift_threshold": threshold,
            "decision_rule": preregistration["decision_rule"]["PASS"],
        },
        "comparability": comparability,
        "conjuncts": conjuncts,
        "unmet_conjuncts": unmet,
        "repaired_cases": repaired,
        "regressed_cases": regressed,
        "successor_lift": lift,
        "claim": claim,
        "verdict": "PASS" if claim == "SUPPORTED" else "NOT_YET",
        "statement": (
            f"G2 raised combined_pass_rate from {g1['combined']['pass_rate']} to "
            f"{g2['combined']['pass_rate']} (lift {lift:.4f} against a preregistered minimum of "
            f"{threshold}) and repaired {len(repaired)} previously failing cases with "
            f"{len(regressed)} regressions."
            if claim == "SUPPORTED"
            else "The successor may not claim improvement: " + "; ".join(unmet or ["the runs are not comparable"])
        ),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preregistration", required=True)
    parser.add_argument("--g1-measurement", required=True)
    parser.add_argument("--g2-measurement", required=True)
    parser.add_argument("--regression-check", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    record = evaluate(
        load(Path(args.preregistration)),
        load(Path(args.g1_measurement)),
        load(Path(args.g2_measurement)),
        load(Path(args.regression_check)) if args.regression_check else None,
    )
    record["inputs"] = {
        name: {
            "path": Path(value).as_posix(),
            "sha256": sha256_bytes(Path(value).read_bytes()),
        }
        for name, value in (
            ("preregistration", args.preregistration),
            ("g1_measurement", args.g1_measurement),
            ("g2_measurement", args.g2_measurement),
        )
        + ((("regression_check", args.regression_check),) if args.regression_check else ())
    }
    Path(args.out).write_bytes(canonical(record))
    print(json.dumps(record, indent=2, sort_keys=True))
    if record["claim"] == "REFUSED":
        print("IMPROVEMENT CLAIM REFUSED: " + record["statement"], file=sys.stderr)
        # A refusal is the correct recorded outcome, so this is not a failure exit.
        return 0
    print("IMPROVEMENT CLAIM SUPPORTED: " + record["statement"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
