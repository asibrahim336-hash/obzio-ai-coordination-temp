#!/usr/bin/env python3
"""Compare G0, G1 and G2 on the frozen suites and decide compounding.

The three generations are re-measured here in one process on one set of suite
bytes, and the fresh outcomes are compared case by case against the measurements
each unit committed earlier.  Re-running is the point: a comparison assembled by
copying three numbers out of three documents cannot detect that they were
produced against different suites, and a disagreement between the fresh run and
the committed run is itself a finding rather than something to smooth over.

The verdict is computed from the preregistration committed before any generation
was measured.  The decision rule and the threshold are read out of that document.
If any conjunct is unmet the verdict is NOT_YET, which is a successful outcome of
this unit and is reported with the numbers that produced it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COMPARISON_VERSION = "PO03-GENERATION-COMPARISON-v1"
RECEIPT_VERSION = "OBZIO-WAVE-COMPOUNDING-v1"
WAVE_ID = "PO03-WAVE-A-b2e7"

UNIT_059 = "workstreams/po03/attempts/po03-wa-b2e7-059-adversarial-hidden-cases"
UNIT_060 = "workstreams/po03/attempts/po03-wa-b2e7-060-blind-review-harness"
UNIT_061 = "workstreams/po03/attempts/po03-wa-b2e7-061-g0-reconstruction"
UNIT_062 = "workstreams/po03/attempts/po03-wa-b2e7-062-g1-packaging"
UNIT_063 = "workstreams/po03/attempts/po03-wa-b2e7-063-g2-successor"
UNIT_064 = "workstreams/po03/attempts/po03-wa-b2e7-064-generation-comparison"

GENERATIONS = (
    {
        "name": "G0",
        "source": f"{UNIT_061}/g0/transactional_factory_g0.py",
        "committed_measurement": f"{UNIT_061}/g0-measurement.json",
        "description": "pre-amendment controller reconstructed byte-exactly from blob "
                       "2d34ae8c7f63e1c25d12f16096eec52effdeb73f at commit 2b48869",
    },
    {
        "name": "G1",
        "source": f"{UNIT_062}/g1/transactional_factory.py",
        "committed_measurement": f"{UNIT_062}/g1-measurement.json",
        "description": "the transactional factory at the cohort checkout, packaged from its committed blob",
    },
    {
        "name": "G2",
        "source": f"{UNIT_063}/g2/transactional_factory_g2.py",
        "committed_measurement": f"{UNIT_063}/g2-measurement.json",
        "description": "successor compiled only from measured G1 failures, one patch per failure",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_text(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def locator(repo: Path, relative: str) -> str:
    """An immutable git: locator for a committed file, never a mutable reference."""
    commit = git_text(repo, "rev-list", "-1", "HEAD", "--", relative)
    if not commit:
        raise ValueError(f"{relative} is not committed; a receipt may not point at uncommitted bytes")
    return f"git:{commit}:{relative}"


def outcomes_by_case(measurement: dict[str, Any]) -> dict[str, str]:
    return {record["case_id"]: record["outcome"] for record in measurement["records"]}


def measure_all(repo: Path) -> dict[str, dict[str, Any]]:
    suite = load_module(repo / UNIT_061 / "generation_suite.py", "po03_suite_for_comparison")
    holdout = repo / UNIT_059 / "hidden/holdout_custody_cases.py"
    seal = repo / UNIT_059 / "holdout-seal.json"
    measured: dict[str, dict[str, Any]] = {}
    for entry in GENERATIONS:
        generation = suite.Generation(
            entry["name"], repo / entry["source"], repo, description=entry["description"]
        )
        measured[entry["name"]] = suite.run_generation(generation, holdout, seal)
    return measured


def agreement(fresh: dict[str, Any], committed: dict[str, Any]) -> dict[str, Any]:
    left, right = outcomes_by_case(fresh), outcomes_by_case(committed)
    disagreements = sorted(
        {"case_id": case_id, "fresh": outcome, "committed": right.get(case_id)}.__repr__()
        for case_id, outcome in left.items()
        if right.get(case_id) != outcome
    )
    return {
        "suite_bytes_identical": fresh["suite_freeze"]["public_suite_sha256"]
        == committed["suite_freeze"]["public_suite_sha256"]
        and fresh["suite_freeze"]["holdout_sha256"] == committed["suite_freeze"]["holdout_sha256"],
        "source_identical": fresh["generation"]["source_sha256"] == committed["generation"]["source_sha256"],
        "case_ids_identical": sorted(left) == sorted(right),
        "outcome_disagreements": disagreements,
        "reproduces_the_committed_measurement": not disagreements
        and fresh["combined"]["pass_rate"] == committed["combined"]["pass_rate"],
    }


def one_suite_for_all(measured: dict[str, dict[str, Any]]) -> dict[str, Any]:
    freezes = {name: run["suite_freeze"] for name, run in measured.items()}
    public = {freeze["public_suite_sha256"] for freeze in freezes.values()}
    hold = {freeze["holdout_sha256"] for freeze in freezes.values()}
    seals = {freeze.get("holdout_seal_combined_sha256") for freeze in freezes.values()}
    case_sets = {name: sorted(outcomes_by_case(run)) for name, run in measured.items()}
    return {
        "public_suite_sha256": sorted(public),
        "holdout_sha256": sorted(hold),
        "holdout_seal_combined_sha256": sorted(str(value) for value in seals),
        "holdout_seal_matches_file": all(
            freeze.get("holdout_seal_matches_file") for freeze in freezes.values()
        ),
        "identical_case_sets": len({tuple(cases) for cases in case_sets.values()}) == 1,
        "all_generations_measured_on_one_suite": len(public) == 1 and len(hold) == 1 and len(seals) == 1,
    }


def metric_table(measured: dict[str, dict[str, Any]]) -> dict[str, Any]:
    table: dict[str, Any] = {}
    for name, run in measured.items():
        table[name] = {
            "public_suite_pass_rate": run["public"]["pass_rate"],
            "holdout_pass_rate": run["holdout"]["pass_rate"],
            "combined_pass_rate": run["combined"]["pass_rate"],
            "false_green_rate": run["combined"]["false_green_rate"],
            "passed": run["combined"]["passed"],
            "failed": run["combined"]["failed"],
            "unsupported": run["combined"]["unsupported"],
            "case_count": run["combined"]["case_count"],
            "reported_success_count": run["combined"]["reported_success_count"],
            "false_green_count": run["combined"]["false_green_count"],
        }
    return table


def transition(measured: dict[str, dict[str, Any]], before: str, after: str) -> dict[str, Any]:
    left, right = outcomes_by_case(measured[before]), outcomes_by_case(measured[after])
    regressed = sorted(case for case, outcome in left.items() if outcome == "PASS" and right.get(case) != "PASS")
    repaired = sorted(case for case, outcome in left.items() if outcome != "PASS" and right.get(case) == "PASS")
    return {
        "from": before,
        "to": after,
        "combined_pass_rate_before": measured[before]["combined"]["pass_rate"],
        "combined_pass_rate_after": measured[after]["combined"]["pass_rate"],
        "lift": measured[after]["combined"]["pass_rate"] - measured[before]["combined"]["pass_rate"],
        "repaired_cases": repaired,
        "repaired_count": len(repaired),
        "regressed_cases": regressed,
        "quality_regression_count": len(regressed),
    }


def decide(preregistration: dict[str, Any], measured: dict[str, dict[str, Any]],
           regression: dict[str, Any], suite_identity: dict[str, Any]) -> dict[str, Any]:
    threshold = float(preregistration["lift_threshold"]["successor_lift_minimum"])
    g1, g2 = measured["G1"], measured["G2"]
    step = transition(measured, "G1", "G2")

    conjuncts = [
        {
            "conjunct": "successor_lift >= 0.05 in combined_pass_rate",
            "observed": {"successor_lift": step["lift"], "threshold": threshold},
            "met": step["lift"] >= threshold,
        },
        {
            "conjunct": "quality_regression_count == 0",
            "observed": {"regressed_cases": step["regressed_cases"]},
            "met": step["quality_regression_count"] == 0,
        },
        {
            "conjunct": "false_green_rate(G2) <= false_green_rate(G1)",
            "observed": {
                "G1": g1["combined"]["false_green_rate"],
                "G2": g2["combined"]["false_green_rate"],
                "G2_reported_success_count": g2["combined"]["reported_success_count"],
            },
            "met": g2["combined"]["false_green_rate"] <= g1["combined"]["false_green_rate"],
        },
        {
            "conjunct": "public_suite_pass_rate(G2) >= public_suite_pass_rate(G1)",
            "observed": {"G1": g1["public"]["pass_rate"], "G2": g2["public"]["pass_rate"]},
            "met": g2["public"]["pass_rate"] >= g1["public"]["pass_rate"],
        },
        {
            "conjunct": "holdout_pass_rate(G2) >= holdout_pass_rate(G1)",
            "observed": {"G1": g1["holdout"]["pass_rate"], "G2": g2["holdout"]["pass_rate"]},
            "met": g2["holdout"]["pass_rate"] >= g1["holdout"]["pass_rate"],
        },
        {
            "conjunct": "all generations measured on one frozen suite",
            "observed": suite_identity,
            "met": bool(suite_identity["all_generations_measured_on_one_suite"])
            and bool(suite_identity["identical_case_sets"])
            and bool(suite_identity["holdout_seal_matches_file"]),
        },
        {
            "conjunct": "no regression in the independently authored baseline suite",
            "observed": {
                "suite": regression["suite"]["origin"],
                "G1_ok": regression["g1"]["totals"]["ok"],
                "G2_ok": regression["g2"]["totals"]["ok"],
                "regressed_tests": regression["comparison"]["regressed_tests"],
            },
            "met": bool(regression["comparison"]["no_quality_regression"]),
        },
    ]
    unmet = [entry["conjunct"] for entry in conjuncts if not entry["met"]]
    verdict = "PASS" if not unmet else "NOT_YET"
    return {
        "decision_rule": preregistration["decision_rule"]["PASS"],
        "lift_threshold": threshold,
        "conjuncts": conjuncts,
        "unmet_conjuncts": unmet,
        "compounding_verdict": verdict,
        "statement": (
            f"Compounding is demonstrated: G2 raised combined_pass_rate from "
            f"{step['combined_pass_rate_before']} to {step['combined_pass_rate_after']}, a lift of "
            f"{step['lift']:.4f} against the preregistered minimum of {threshold}, repairing "
            f"{step['repaired_count']} measured failures with {step['quality_regression_count']} regressions "
            f"on the frozen suites and none in the independently authored baseline suite."
            if verdict == "PASS"
            else "Compounding is NOT_YET: " + "; ".join(unmet)
        ),
    }


def dispositions(repo: Path, lineage: dict[str, Any], measured: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One disposition per changed or considered route, with its evidence locator.

    A route G2 changed is SUPERSEDE.  A route it left alone because the suite
    shows it already holds is RETAIN.  A repair that was considered and not made
    because no measured failure motivates it is REJECT, which is what the
    preregistration requires of a change without lineage.  RETEST marks a
    measurement whose value is real but whose instrument is known to be limited.
    """
    lineage_uri = locator(repo, f"{UNIT_063}/g2/lineage.json")
    g2_uri = locator(repo, f"{UNIT_063}/g2-measurement.json")
    g1_uri = locator(repo, f"{UNIT_062}/g1-measurement.json")
    g0_uri = locator(repo, f"{UNIT_061}/g0-measurement.json")
    regression_uri = locator(repo, f"{UNIT_063}/regression-check.json")

    records: list[dict[str, Any]] = []
    for change in lineage["changes"]:
        failure = change["motivating_failure"]
        records.append(
            {
                "subject": f"{change['route']} ({change['change_id']}, motivated by {failure['case_id']})",
                "decision": change["disposition"],
                "evidence_uri": lineage_uri,
                "lineage": {
                    "measured_failure": failure["case_id"],
                    "g1_observed": failure["g1_observed_detail"],
                    "g1_reported_success_while_broken": failure["g1_reported_success"],
                    "g2_outcome": outcomes_by_case(measured["G2"]).get(failure["case_id"]),
                    "g2_evidence_uri": g2_uri,
                    "g1_evidence_uri": g1_uri,
                },
            }
        )

    changed_cases = {change["motivating_failure"]["case_id"] for change in lineage["changes"]}
    retained = sorted(
        case_id
        for case_id, outcome in outcomes_by_case(measured["G1"]).items()
        if outcome == "PASS" and case_id not in changed_cases
    )
    records.append(
        {
            "subject": f"the {len(retained)} custody routes G1 already held and G2 did not change: "
                       + ", ".join(retained),
            "decision": "RETAIN",
            "evidence_uri": g2_uri,
            "lineage": {
                "reason": "each of these cases passes under both G1 and G2 on identical suite bytes, so the "
                          "route is preserved unchanged",
                "g1_evidence_uri": g1_uri,
            },
        }
    )
    records.append(
        {
            "subject": "scan_recovery duplicate_callback_count: candidate repair of a second asserted zero",
            "decision": "REJECT",
            "evidence_uri": lineage_uri,
            "lineage": {
                "reason": "the field is asserted rather than computed, the same defect class as H04, but no "
                          "case in either frozen suite measures it. The preregistration requires a change "
                          "without lineage to a measured failure to be rejected rather than shipped, so it "
                          "was left unrepaired and recorded here.",
                "observed_in": "G1 and G2 alike",
            },
        }
    )
    records.append(
        {
            "subject": "assert_fence_current holder identity: candidate repair of fence equality without a holder check",
            "decision": "REJECT",
            "evidence_uri": lineage_uri,
            "lineage": {
                "reason": "fence equality is compared without checking which worker holds the lease. No "
                          "measured failure covers it because grant_lease always advances the counter, so "
                          "the equal-fence-different-holder state could not be reached to fail a case. "
                          "Shipped nothing; recorded as rejected for want of measured lineage.",
                "observed_in": "G1 and G2 alike",
            },
        }
    )
    records.append(
        {
            "subject": "the G0 baseline measurement: 18 of 26 cases score UNSUPPORTED",
            "decision": "RETEST",
            "evidence_uri": g0_uri,
            "lineage": {
                "reason": "G0 lacks whole functions, so its combined_pass_rate measures capability absence "
                          "rather than behaviour under equal footing. The number is real and is reported "
                          "unchanged, but a behavioural comparison of G0 against later generations needs an "
                          "instrument that does not score a missing function the same way as a wrong answer.",
            },
        }
    )
    records.append(
        {
            "subject": "false_green_rate as an instrument at the G2 ceiling",
            "decision": "RETEST",
            "evidence_uri": regression_uri,
            "lineage": {
                "reason": "G2 has no case that reports success while broken, so the metric's denominator is "
                          "empty and it reads 0.0 by convention rather than by observation. The definition is "
                          "retained unchanged per the preregistration; it needs cases that report success "
                          "correctly before the rate can discriminate.",
            },
        }
    )
    return records


def receipt(repo: Path, comparison: dict[str, Any], lineage: dict[str, Any],
            measured: dict[str, dict[str, Any]], regression: dict[str, Any]) -> dict[str, Any]:
    g1_relative = f"{UNIT_062}/g1-measurement.json"
    baseline_bytes = (repo / g1_relative).read_bytes()
    decision = comparison["decision"]
    step = comparison["transitions"]["G1_to_G2"]

    return {
        "protocol_version": RECEIPT_VERSION,
        "wave_id": WAVE_ID,
        "baseline": {
            "metrics_uri": locator(repo, g1_relative),
            "sha256": sha256_bytes(baseline_bytes),
        },
        "observations": [
            f"G0, reconstructed byte-exactly from blob 2d34ae8c7f63e1c25d12f16096eec52effdeb73f at commit "
            f"2b48869, scores {measured['G0']['combined']['passed']} of "
            f"{measured['G0']['combined']['case_count']} on the frozen suites "
            f"(combined_pass_rate {measured['G0']['combined']['pass_rate']:.4f}), with 18 cases UNSUPPORTED "
            f"because fencing, ingestion, completion gating and the recovery scanner do not exist in it.",
            f"G1 scores {measured['G1']['combined']['passed']} of {measured['G1']['combined']['case_count']} "
            f"(combined_pass_rate {measured['G1']['combined']['pass_rate']:.4f}): it passes all 16 "
            f"producer-visible public cases and fails 6 of the 10 evaluator-held holdout cases.",
            f"Every one of G1's six failures reported a successful custody outcome while the invariant was "
            f"violated, so its false_green_rate on cases that report success is "
            f"{measured['G1']['combined']['false_green_rate']}.",
            f"G2 scores {measured['G2']['combined']['passed']} of {measured['G2']['combined']['case_count']} "
            f"(combined_pass_rate {measured['G2']['combined']['pass_rate']:.4f}).",
            "The public suite alone could not have found any of the six defects: G1 passes it completely. "
            "The finding came from the evaluator-held holdout sealed before the successor existed.",
            "A frozen suite that a generation saturates stops being an instrument. G2 is at 26 of 26, so this "
            "suite can no longer measure a further successor and a later generation would show zero lift on it.",
        ],
        "challenges": [
            "Challenge: the suite was tuned to make G2 win. The suite and the holdout seal were committed "
            "before the G2 source existed, their sha256 values are recorded in every run, and the recorded "
            "runs for all three generations carry identical suite digests.",
            "Challenge: the six repairs were reverse-engineered from known fixes. The builder refuses any "
            "patch whose case_id is not present in the committed G1 measurement's failure list, so a change "
            "cannot be applied without a prior measured failure.",
            "Challenge: the producer graded their own successor. The decisive cases are evaluator-held and "
            "sealed, and the no-regression check runs the repository's own 58 tests, which this cohort did "
            "not author, against both generations unmodified.",
            "Challenge: the repairs pass the hazard case and break the legitimate path. Measured directly: "
            "the byte-identity form of the completion binding would have broken every legitimate completion, "
            "which the independent suite caught, and the shipped binding normalises only the fields the "
            "coordinator stamps.",
            "Challenge unanswered: one producer authored the public suite, the holdout and the successor. "
            "Independence rests on commit chronology, sha256 freezing and the independently authored baseline "
            "suite, not on a separate author. No claim of independent authorship is made.",
        ],
        "external_hypotheses": [
            "PRODUCER-STATED ENGINEERING CLAIM, NOT A CITATION: a fence token must be strictly monotonic and "
            "issued under mutual exclusion, because a lease that can hand the same token to two workers "
            "cannot order their writes. No external source was consulted; this environment has no research "
            "access and fabricating a citation would be worse than naming the claim as the producer's.",
            "PRODUCER-STATED ENGINEERING CLAIM, NOT A CITATION: seeding defects into a target and measuring "
            "which arm detects them is the way to tell a test suite that exercises code from one that "
            "constrains it. Applied in unit 059 as a mutation differential rather than asserted.",
            "PRODUCER-STATED ENGINEERING CLAIM, NOT A CITATION: an append-only hash chain detects alteration "
            "of what it retains but not removal of its own tip, so length and tip must be attested outside "
            "the sequence being verified. This is the reasoning behind the H05 repair.",
            "PRODUCER-STATED ENGINEERING CLAIM, NOT A CITATION: a receipt that names a mutable reference is "
            "not evidence, because the bytes it points at can change after verification. This is the "
            "reasoning behind the H06 repair.",
        ],
        "reproductions": [
            f"{change['motivating_failure']['case_id']} reproduced as an executable case: "
            f"{change['motivating_failure']['g1_observed_detail']}"
            for change in lineage["changes"]
        ]
        + [
            f"All six reproductions are re-runnable: {comparison['reproducibility']['command']}",
        ],
        "live_mechanism_changes": [
            f"{change['change_id']} {change['disposition']} {change['route']}: {change['rationale']} "
            f"(lineage: {change['motivating_failure']['case_id']})"
            for change in lineage["changes"]
        ]
        + [
            "No change was made to the live workstreams/po03/tools/transactional_factory.py. G2 is staged as "
            "a package in this cohort's unit subtree for the controller to ingest into successor/g2/; a "
            "subordinate producer does not write the controller's shared paths.",
        ],
        "independent_tests": [
            f"Evaluator-held holdout of 10 custody cases, sealed at combined sha256 "
            f"{measured['G2']['suite_freeze']['holdout_seal_combined_sha256']} before the successor existed "
            f"and unmodified across all three runs; it is the arm that found all six defects.",
            f"The repository's own baseline suite at workstreams/po03/tests, authored outside this cohort: "
            f"{regression['g1']['totals']['ok']} of {regression['g1']['totals']['ran']} pass under G1 and "
            f"{regression['g2']['totals']['ok']} of {regression['g2']['totals']['ran']} under G2, with "
            f"{regression['comparison']['regression_count']} regressions and "
            f"{len(regression['comparison']['disappeared_tests'])} disappeared tests.",
            "Seeded-defect mutation differential in unit 059, run against a validator this cohort did not "
            "author, measuring which defects the producer-visible suite misses and the hidden cases catch.",
            "Blind review harness in unit 060, applied to other cohorts' committed results rather than to "
            "this cohort's own conclusions, comparing a criteria-only reviewer against a narrative-anchored one.",
            "Cross-cohort application of evaluator-held invariants in unit 059 to results committed on other "
            "cohorts' branches.",
        ],
        "dispositions": comparison["dispositions"],
        "successor_manifest_uri": locator(repo, f"{UNIT_063}/g2/lineage.json"),
        "decision_changed": [],
        "compounding_verdict": decision["compounding_verdict"],
        "verdict_statement": decision["statement"],
        "successor_lift": step["lift"],
        "lift_threshold": decision["lift_threshold"],
        "subordinate_claim": "READY_TO_COMMIT. This receipt is produced by a subordinate producer. It does "
                             "not set Obzio COMPLETED, does not accept this cohort's own work and does not "
                             "declare the wave accepted.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    preregistration = load_json(repo / UNIT_064 / "preregistration.json")
    regression = load_json(repo / UNIT_063 / "regression-check.json")
    lineage = load_json(repo / UNIT_063 / "g2/lineage.json")

    measured = measure_all(repo)
    suite_identity = one_suite_for_all(measured)
    agreements = {
        entry["name"]: agreement(measured[entry["name"]], load_json(repo / entry["committed_measurement"]))
        for entry in GENERATIONS
    }
    decision = decide(preregistration, measured, regression, suite_identity)
    records = dispositions(repo, lineage, measured)

    comparison = {
        "comparison_version": COMPARISON_VERSION,
        "wave_id": WAVE_ID,
        "cohort": "c8",
        "compared_at": utc_now(),
        "preregistration": {
            "path": f"{UNIT_064}/preregistration.json",
            "sha256": sha256_bytes((repo / UNIT_064 / "preregistration.json").read_bytes()),
            "locator": locator(repo, f"{UNIT_064}/preregistration.json"),
            "registered_before": preregistration["registered_before"],
        },
        "suite_identity": suite_identity,
        "generations": {
            entry["name"]: {
                "description": entry["description"],
                "source": entry["source"],
                "source_sha256": measured[entry["name"]]["generation"]["source_sha256"],
                "source_bytes": measured[entry["name"]]["generation"]["source_bytes"],
                "locator": locator(repo, entry["source"]),
            }
            for entry in GENERATIONS
        },
        "metrics": metric_table(measured),
        "transitions": {
            "G0_to_G1": transition(measured, "G0", "G1"),
            "G1_to_G2": transition(measured, "G1", "G2"),
            "G0_to_G2": transition(measured, "G0", "G2"),
        },
        "reproducibility": {
            "command": preregistration["verdict_command"],
            "fresh_run_agreement": agreements,
            "all_generations_reproduced_their_committed_measurement": all(
                record["reproduces_the_committed_measurement"] for record in agreements.values()
            ),
        },
        "independent_regression_check": {
            "suite": regression["suite"]["origin"],
            "authored_by": regression["suite"]["authored_by"],
            "g1_ok": regression["g1"]["totals"]["ok"],
            "g2_ok": regression["g2"]["totals"]["ok"],
            "regression_count": regression["comparison"]["regression_count"],
            "no_quality_regression": regression["comparison"]["no_quality_regression"],
        },
        "decision": decision,
        "dispositions": records,
        "per_case": {
            name: outcomes_by_case(run) for name, run in measured.items()
        },
        "decision_changed": [],
    }

    comparison_path = out / "generation-comparison.json"
    comparison_path.write_bytes(canonical(comparison))
    receipt_path = out / "compounding-results.json"
    receipt_path.write_bytes(canonical(receipt(repo, comparison, lineage, measured, regression)))

    print(json.dumps(
        {
            "metrics": comparison["metrics"],
            "transitions": comparison["transitions"],
            "suite_identity": suite_identity,
            "reproducibility": comparison["reproducibility"]["all_generations_reproduced_their_committed_measurement"],
            "unmet_conjuncts": decision["unmet_conjuncts"],
            "compounding_verdict": decision["compounding_verdict"],
        },
        indent=2,
        sort_keys=True,
    ))
    print(decision["statement"])
    if not comparison["reproducibility"]["all_generations_reproduced_their_committed_measurement"]:
        print("A fresh run disagreed with a committed measurement; the comparison is not sound", file=sys.stderr)
        return 1
    print(f"COMPOUNDING VERDICT: {decision['compounding_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
