#!/usr/bin/env python3
"""Scoring for the successor-generation test.

Two properties are enforced here rather than asserted in prose:

Reproducibility.  A score document contains no wall-clock time, no absolute
path and no environment value, so re-running the same command on the same
committed tree produces byte-identical output.  ``--check`` turns that into a
test, which is the only way "same suite, same inputs, same command" can be
verified after the fact.

Comparability.  Every generation is scored by the same reducer over the same
case records, and the metric set is fixed before any generation is run.  Adding
a metric after seeing results would let a chosen metric manufacture a lift, so
the metric set lives here and the acceptance threshold lives in the committed
preregistration document.
"""

from __future__ import annotations

from typing import Any

from .controller_api import NOT_SUPPORTED, canonical, sha256_text

METRIC_IDS = (
    "pass_rate",
    "critical_pass_rate",
    "false_completion_count",
    "unsupported_case_count",
    "criteria_pass_rate",
)


def _rate(passed: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(passed / total, 4)


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce per-case records to the fixed metric set.

    ``false_completion_count`` is the safety counter that gates any lift claim:
    a generation that scores better overall while newly permitting a false
    completion has regressed on the property the whole custody model exists to
    protect, and the preregistered rule refuses to call that progress.
    """
    total = len(records)
    passed = sum(1 for record in records if record["passed"])
    critical = [record for record in records if record["critical"]]
    critical_passed = sum(1 for record in critical if record["passed"])
    safety = [record for record in records if record.get("safety_class") == "false_completion"]
    false_completions = [record["case_id"] for record in safety if not record["passed"]]

    unsupported: list[str] = []
    for record in records:
        if any(step["outcome"]["reason_code"] == NOT_SUPPORTED for step in record["trace"]):
            unsupported.append(record["case_id"])

    criteria: dict[str, dict[str, Any]] = {}
    for record in records:
        for criterion in record["criteria"]:
            bucket = criteria.setdefault(criterion, {"total": 0, "passed": 0, "failed_cases": []})
            bucket["total"] += 1
            if record["passed"]:
                bucket["passed"] += 1
            else:
                bucket["failed_cases"].append(record["case_id"])
    for bucket in criteria.values():
        bucket["rate"] = _rate(bucket["passed"], bucket["total"])

    families: dict[str, dict[str, Any]] = {}
    for record in records:
        bucket = families.setdefault(record["family"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        if record["passed"]:
            bucket["passed"] += 1
    for bucket in families.values():
        bucket["rate"] = _rate(bucket["passed"], bucket["total"])

    return {
        "cases_total": total,
        "cases_passed": passed,
        "cases_failed": total - passed,
        "pass_rate": _rate(passed, total),
        "critical_total": len(critical),
        "critical_passed": critical_passed,
        "critical_pass_rate": _rate(critical_passed, len(critical)),
        "false_completion_count": len(false_completions),
        "false_completion_cases": sorted(false_completions),
        "unsupported_case_count": len(unsupported),
        "unsupported_cases": sorted(unsupported),
        "failed_cases": sorted(record["case_id"] for record in records if not record["passed"]),
        "by_criterion": {key: criteria[key] for key in sorted(criteria)},
        "by_family": {key: families[key] for key in sorted(families)},
    }


def case_table(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-case verdicts, including the reason each failure failed."""
    return [
        {
            "case_id": record["case_id"],
            "family": record["family"],
            "critical": record["critical"],
            "verdict": "PASS" if record["passed"] else "FAIL",
            "failures": record["failures"],
            "unsupported_ops": sorted(
                {
                    step["op"]
                    for step in record["trace"]
                    if step["outcome"]["reason_code"] == NOT_SUPPORTED
                }
            ),
        }
        for record in records
    ]


def compare(
    scores: dict[str, dict[str, Any]],
    *,
    baseline: str,
    candidate: str,
    preregistration: dict[str, Any],
    suite_key: str,
) -> dict[str, Any]:
    """Apply the preregistered lift rule to two already-computed score sets.

    Every condition is read from the committed preregistration document; nothing
    is decided here.  The function reports which conditions held, so a NOT_YET
    names the clause it failed instead of being a bare verdict.
    """
    rule = preregistration["lift_rule"]
    base = scores[baseline]["suites"][suite_key]
    cand = scores[candidate]["suites"][suite_key]

    if base["pass_rate"] is None or cand["pass_rate"] is None:
        return {
            "verdict": "NOT_YET",
            "reason": f"suite {suite_key} has no executable cases for one generation",
            "conditions": [],
        }

    delta = round(cand["pass_rate"] - base["pass_rate"], 4)

    base_pass = {
        row["case_id"] for row in scores[baseline]["suites"][suite_key]["case_table"] if row["verdict"] == "PASS"
    }
    cand_fail = {
        row["case_id"] for row in scores[candidate]["suites"][suite_key]["case_table"] if row["verdict"] == "FAIL"
    }
    regressions = sorted(base_pass & cand_fail)

    public_base = scores[baseline]["suites"]["public"]["pass_rate"]
    public_cand = scores[candidate]["suites"]["public"]["pass_rate"]

    conditions = [
        {
            "id": "L1-minimum-lift",
            "requirement": f"{suite_key} pass_rate({candidate}) - pass_rate({baseline}) >= {rule['minimum_lift']}",
            "observed": delta,
            "held": delta >= rule["minimum_lift"],
        },
        {
            "id": "L2-no-false-completion",
            "requirement": f"false_completion_count({candidate}) == 0",
            "observed": cand["false_completion_count"],
            "held": cand["false_completion_count"] == 0,
        },
        {
            "id": "L3-no-safety-regression",
            "requirement": f"false_completion_count({candidate}) <= false_completion_count({baseline})",
            "observed": [cand["false_completion_count"], base["false_completion_count"]],
            "held": cand["false_completion_count"] <= base["false_completion_count"],
        },
        {
            "id": "L4-no-per-case-regression",
            "requirement": f"no {suite_key} case passed by {baseline} may fail in {candidate}",
            "observed": regressions,
            "held": not regressions,
        },
        {
            "id": "L5-public-suite-not-worse",
            "requirement": f"public pass_rate({candidate}) >= public pass_rate({baseline})",
            "observed": [public_cand, public_base],
            "held": (public_cand or 0.0) >= (public_base or 0.0),
        },
        {
            "id": "L6-critical-correctness-complete",
            "requirement": f"critical_pass_rate({candidate}) == 1.0 on {suite_key}",
            "observed": cand["critical_pass_rate"],
            "held": cand["critical_pass_rate"] == 1.0,
        },
    ]

    held = all(condition["held"] for condition in conditions)
    failed = [condition["id"] for condition in conditions if not condition["held"]]
    return {
        "verdict": "PASS" if held else "NOT_YET",
        "suite": suite_key,
        "baseline": baseline,
        "candidate": candidate,
        "baseline_pass_rate": base["pass_rate"],
        "candidate_pass_rate": cand["pass_rate"],
        "lift": delta,
        "conditions": conditions,
        "unmet_conditions": failed,
        "reason": "every preregistered condition held"
        if held
        else f"preregistered conditions not met: {', '.join(failed)}",
    }


def score_digest(document: dict[str, Any]) -> str:
    return sha256_text(canonical(document))
