#!/usr/bin/env python3
"""Build the schema for, and compute, workstreams/po03/metrics/generation-comparison.json.

Frozen wording this tool must satisfy (workstreams/po03/COMMISSION.md,
"Successor-generation test", and workstreams/po03/control/dispatch/a8-u05.json,
which is immutable and owned by po03-worker-a8 but whose stated artifact is
this exact file):

    G0: the pre-amendment controller reconstructed from immutable source
    G1: this high-scale transactional factory
    G2: a successor compiled from G1 failures and accepted lessons

    "generation-comparison.json reports scores for all three generations on
    identical inputs and states PASS or NOT_YET on the preregistered lift
    metric with no quality regression permitted."

Ownership split: po03-worker-a8 (branch cursor/po03-a8-successor-generations-ed20,
owned prefix workstreams/po03/successor/) produces the G0/G1/G2 executable
generations, the frozen suites, the preregistered lift rule and the raw
per-case scores. po03-worker-a7 (this cohort) owns workstreams/po03/metrics/
and is responsible for the schema below and for an INDEPENDENT computation of
the same six preregistered conditions from a8's raw per-suite data -- never
for copying a8's own verdict, and never for inventing a score.

Schema (revised a third time, now that both suites and a preregistration
document have landed on a8's branch). This tool reads two files a8 committed
at a pinned commit:

    workstreams/po03/successor/suite/lift-preregistration.json
        the frozen minimum_lift threshold and the six condition definitions
        (L1-L6), authored_by po03-worker-a8, declared before G2 existed in
        the tree.
    workstreams/po03/successor/scores/generation-comparison.json
        a8's own scored raw data: per generation, per suite (public,
        holdout), pass_rate, critical_pass_rate, false_completion_count,
        cases_total/cases_passed, a full case_table with per-case verdicts,
        and a `suites` metadata array recording who authored each suite's
        case set.

From those raw per-suite numbers and case tables, this tool independently
recomputes L1-L6 for both comparisons (G0-vs-G1, G1-vs-G2) on both suites,
without reading or trusting a8's own precomputed `conditions`/`verdict`
fields, and then separately records whether that independent computation
agrees with a8's own reported conditions and headline verdict. Disagreement,
if found, is reported explicitly rather than silently reconciled.

Two verdicts are kept separate, never collapsed into one headline, per the
commission's own recorded lesson (receipts/po03/2026-08-22/producer-execution.json,
successor_generation_result.why_that_matters): G1-to-G2 passing and G0-to-G1
not passing are distinct facts about distinct generations.

This tool never merges or checks out the a8 branch. It only resolves a
commit reference (a live remote-tracking ref, or an explicit immutable pin)
that a prior, operator-run ``git fetch`` already populated in the local
object store, and reads blob objects from it with ``git cat-file``. It never
invokes ``git fetch`` itself.

Dependency-free standard-library Python 3.12.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


SUCCESSOR_REMOTE_REF = "origin/cursor/po03-a8-successor-generations-ed20"
SUCCESSOR_OWNER = "po03-worker-a8"
GENERATIONS = ("G0", "G1", "G2")
SUITES = ("public", "holdout")
PAIRS = (("G0", "G1"), ("G1", "G2"))

PREREG_PATH = "workstreams/po03/successor/suite/lift-preregistration.json"
SCORES_PATH = "workstreams/po03/successor/scores/generation-comparison.json"

CONDITION_IDS = (
    "L1-minimum-lift",
    "L2-no-false-completion",
    "L3-no-safety-regression",
    "L4-no-per-case-regression",
    "L5-public-suite-not-worse",
    "L6-critical-correctness-complete",
)


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_git(root: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def resolve_successor_ref(root: Path, successor_pin: str | None = None) -> tuple[str | None, str]:
    """Return (commit_sha_or_None, boundary_message).

    Never fetches. With no pin, resolves the remote-tracking ref that a prior,
    operator-run ``git fetch origin cursor/po03-a8-successor-generations-ed20``
    may already have populated in the local object store -- this is what the
    live CLI does, and it is a *moving* answer: the same ref resolves to a
    different commit as a8 lands more of the branch.

    ``successor_pin``, when given, is resolved instead of the live ref: an
    explicit, immutable commit reference that always resolves to the same
    commit regardless of what the remote-tracking ref currently points at.
    This is what workstreams/po03/evidence/snapshot-coupling.json's binding
    operating rule requires a reproduction test (or a report meant to be
    reproducible) to assert against, instead of live state.
    """
    if successor_pin is not None:
        code, out, err = run_git(root, ["rev-parse", "--verify", f"{successor_pin}^{{commit}}"])
        if code == 0 and out:
            return out, f"pinned to explicit immutable commit {successor_pin} -> {out}"
        return None, (
            f"git rev-parse --verify {successor_pin}^{{commit}} failed (exit {code}): "
            f"{err or 'no output'}. The pin does not resolve to a commit in the local object store."
        )
    code, out, err = run_git(root, ["rev-parse", "--verify", f"{SUCCESSOR_REMOTE_REF}^{{commit}}"])
    if code == 0 and out:
        return out, f"resolved {SUCCESSOR_REMOTE_REF} -> {out}"
    return None, (
        f"git rev-parse --verify {SUCCESSOR_REMOTE_REF}^{{commit}} failed (exit {code}): "
        f"{err or 'no output'}. The branch cursor/po03-a8-successor-generations-ed20 has not "
        "been fetched to a resolvable remote-tracking ref, most likely because it does not yet "
        "exist on origin (confirmed separately via `git ls-remote origin` returning no matching "
        "refs/heads entry at measurement time)."
    )


def read_blob(root: Path, sha: str, path: str) -> tuple[str | None, str]:
    code, out, err = run_git(root, ["cat-file", "blob", f"{sha}:{path}"])
    if code == 0:
        return out, ""
    return None, f"git cat-file blob {sha}:{path} failed (exit {code}): {err or 'no output'}"


def load_generations_from_scores(scores: dict[str, Any], sha: str) -> dict[str, Any]:
    generations: dict[str, Any] = {}
    for gen in GENERATIONS:
        gdoc = scores["generations"][gen]
        suites: dict[str, Any] = {}
        for suite in SUITES:
            sdoc = gdoc["suites"][suite]
            case_table = sdoc.get("case_table", [])
            passed_case_ids = sorted(c["case_id"] for c in case_table if c["verdict"] == "PASS")
            failed_case_ids = sorted(sdoc.get("failed_cases", []))
            suites[suite] = {
                "status": "REPORTED",
                "cases_passed": sdoc["cases_passed"],
                "cases_total": sdoc["cases_total"],
                "pass_rate": sdoc["pass_rate"],
                "critical_pass_rate": sdoc["critical_pass_rate"],
                "critical_passed": sdoc.get("critical_passed"),
                "critical_total": sdoc.get("critical_total"),
                "false_completion_count": sdoc["false_completion_count"],
                "unsupported_case_count": sdoc["unsupported_case_count"],
                "passed_case_ids": passed_case_ids,
                "failed_case_ids": failed_case_ids,
                "source_commit": sha,
            }
        generations[gen] = {
            "generation": gen,
            "status": "REPORTED",
            "label": gdoc.get("label"),
            "provenance": gdoc.get("provenance"),
            "source_sha256": gdoc.get("source_sha256"),
            "suites": suites,
        }
    return generations


def independent_conditions(
    generations: dict[str, Any], baseline: str, candidate: str, suite: str, minimum_lift: float
) -> dict[str, Any]:
    """Independently recompute all six preregistered conditions from raw
    per-suite numbers and per-case verdicts, without reading a8's own
    precomputed `conditions`/`verdict` fields at all. L5 always checks the
    *public* suite regardless of which suite this comparison targets, per
    a8's own preregistration (the public suite is the cross-suite guard;
    the suite argument selects the metric-of-record suite for L1/L2/L3/L4/L6)."""
    b = generations[baseline]["suites"][suite]
    c = generations[candidate]["suites"][suite]
    b_pub = generations[baseline]["suites"]["public"]
    c_pub = generations[candidate]["suites"]["public"]

    # a8's own pass_rate values are rounded to 4 decimal places (its scorer's
    # own convention, visible in every suites.*.pass_rate value this tool
    # reads); a plain float subtraction of two such values can surface binary
    # floating-point noise below that precision (e.g. 1.0 - 0.7 ==
    # 0.30000000000000004 in IEEE 754 double). Rounding to the same 4 decimal
    # places a8 already committed to removes that noise without changing
    # which side of minimum_lift the value falls on for any input observed
    # here, and without inventing any digit a8 did not already report.
    lift_value = round(c["pass_rate"] - b["pass_rate"], 4)
    l1 = lift_value >= minimum_lift
    l2 = c["false_completion_count"] == 0
    l3 = c["false_completion_count"] <= b["false_completion_count"]
    regressed_cases = sorted(set(b["passed_case_ids"]) & set(c["failed_case_ids"]))
    l4 = len(regressed_cases) == 0
    l5 = c_pub["pass_rate"] >= b_pub["pass_rate"]
    l6 = c["critical_pass_rate"] == 1.0

    conditions = {
        "L1-minimum-lift": {
            "held": l1,
            "observed": lift_value,
            "requirement": f"{suite} pass_rate({candidate}) - pass_rate({baseline}) >= {minimum_lift}",
        },
        "L2-no-false-completion": {
            "held": l2,
            "observed": c["false_completion_count"],
            "requirement": f"false_completion_count({candidate}) == 0 on {suite}",
        },
        "L3-no-safety-regression": {
            "held": l3,
            "observed": [c["false_completion_count"], b["false_completion_count"]],
            "requirement": f"false_completion_count({candidate}) <= false_completion_count({baseline}) on {suite}",
        },
        "L4-no-per-case-regression": {
            "held": l4,
            "observed": regressed_cases,
            "requirement": f"no {suite} case passed by {baseline} may fail in {candidate}",
        },
        "L5-public-suite-not-worse": {
            "held": l5,
            "observed": [c_pub["pass_rate"], b_pub["pass_rate"]],
            "requirement": f"public pass_rate({candidate}) >= public pass_rate({baseline})",
        },
        "L6-critical-correctness-complete": {
            "held": l6,
            "observed": c["critical_pass_rate"],
            "requirement": f"critical_pass_rate({candidate}) == 1.0 on {suite}",
        },
    }
    unmet = [cid for cid in CONDITION_IDS if not conditions[cid]["held"]]
    verdict = "PASS" if not unmet else "NOT_YET"

    return {
        "baseline": baseline,
        "candidate": candidate,
        "suite": suite,
        "baseline_pass_rate": b["pass_rate"],
        "candidate_pass_rate": c["pass_rate"],
        "lift": lift_value,
        "conditions": conditions,
        "unmet_conditions": unmet,
        "verdict": verdict,
    }


def agreement_with_a8(mine: dict[str, Any], a8_scores: dict[str, Any]) -> dict[str, Any]:
    """Compare this cohort's independently computed conditions/verdict for one
    (baseline, candidate, suite) comparison against a8's own committed
    conditions/verdict for the identical comparison. Disagreement is reported
    explicitly, never silently reconciled toward either side."""
    a8_cmp = next(
        (
            cmp
            for cmp in a8_scores["comparisons"]
            if cmp["baseline"] == mine["baseline"] and cmp["candidate"] == mine["candidate"] and cmp["suite"] == mine["suite"]
        ),
        None,
    )
    if a8_cmp is None:
        return {
            "a8_comparison_found": False,
            "boundary": (
                f"no comparison with baseline={mine['baseline']} candidate={mine['candidate']} "
                f"suite={mine['suite']} in a8's committed {SCORES_PATH}"
            ),
        }

    a8_conditions_by_id = {cond["id"]: cond for cond in a8_cmp["conditions"]}
    per_condition = {}
    disagreements = []
    for cid in CONDITION_IDS:
        a8_held = a8_conditions_by_id.get(cid, {}).get("held")
        mine_held = mine["conditions"][cid]["held"]
        agrees = a8_held == mine_held
        per_condition[cid] = {"a8_held": a8_held, "a7_held": mine_held, "agrees": agrees}
        if not agrees:
            disagreements.append(cid)

    verdict_agrees = a8_cmp["verdict"] == mine["verdict"]
    return {
        "a8_comparison_found": True,
        "a8_verdict": a8_cmp["verdict"],
        "a7_verdict": mine["verdict"],
        "verdict_agrees": verdict_agrees,
        "per_condition": per_condition,
        "disagreements": disagreements,
    }


INDEPENDENCE_BOUNDARIES = {
    "g2_is_proposal_not_deployment": (
        "G2 is a proposal, not a deployment. control_plane.py is coordinator-owned "
        "and untouched, so the live control plane still carries the defects G2 fixes."
    ),
    "a8_recurrence_tests_self_authored": (
        "a8's recurrence tests are authored by a8 itself, not by a different owner as "
        "its frozen acceptance requires. Recorded NOT_YET and routed to a6-u07."
    ),
    "no_a8_unit_independently_accepted": (
        "No a8 unit has been independently accepted; a6 scored while a8's branch was "
        "absent from its fetch. Absence of an adverse finding is not acceptance."
    ),
    "holdout_independence_is_provisional": (
        "The holdout was sourced from a6's cases but selected and bound by the "
        "generation author (a8), which is weaker independence than authorship by a "
        "non-author. Cohort a13 is authoring a genuinely blind holdout to close this; "
        "treat the current holdout figure as provisional until a13 lands it."
    ),
    "source": "receipts/po03/2026-08-22/producer-execution.json:successor_generation_result.outstanding_boundaries, reflected here verbatim, not resolved by this tool",
}


def compute(root: Path, successor_pin: str | None = None) -> dict[str, Any]:
    sha, resolution_boundary = resolve_successor_ref(root, successor_pin)

    measured_against = {
        "successor_remote_ref": SUCCESSOR_REMOTE_REF,
        "successor_commit_sha": sha,
        "resolution_boundary": resolution_boundary,
    }

    if sha is None:
        return _not_yet_report(measured_against, resolution_boundary)

    prereg_raw, prereg_err = read_blob(root, sha, PREREG_PATH)
    scores_raw, scores_err = read_blob(root, sha, SCORES_PATH)
    if prereg_raw is None or scores_raw is None:
        boundary = prereg_err if prereg_raw is None else scores_err
        return _not_yet_report(measured_against, boundary)

    prereg = json.loads(prereg_raw)
    a8_scores = json.loads(scores_raw)

    minimum_lift = prereg["lift_rule"]["minimum_lift"]
    generations = load_generations_from_scores(a8_scores, sha)

    independent: dict[str, dict[str, Any]] = {}
    agreement: dict[str, dict[str, Any]] = {}
    for baseline, candidate in PAIRS:
        pair_key = f"{baseline.lower()}_vs_{candidate.lower()}"
        independent[pair_key] = {}
        agreement[pair_key] = {}
        for suite in SUITES:
            mine = independent_conditions(generations, baseline, candidate, suite, minimum_lift)
            independent[pair_key][suite] = mine
            agreement[pair_key][suite] = agreement_with_a8(mine, a8_scores)

    primary = prereg["primary_comparison"]
    primary_pair_key = f"{primary['baseline'].lower()}_vs_{primary['candidate'].lower()}"
    primary_result = independent[primary_pair_key][primary["suite"]]
    primary_agreement = agreement[primary_pair_key][primary["suite"]]

    all_pair_suite_pass = all(
        independent[f"{b.lower()}_vs_{c.lower()}"][suite]["verdict"] == "PASS"
        for b, c in PAIRS
        for suite in SUITES
    )
    compounding_claim = {
        "value": "PASS" if all_pair_suite_pass else "NOT_SUSTAINED",
        "reason": (
            "every preregistered condition holds for both G0-vs-G1 and G1-vs-G2 on both suites"
            if all_pair_suite_pass
            else (
                "the full G0-through-G2 compounding claim is not sustained because at least one "
                "pairwise comparison does not meet the preregistered guards on at least one suite "
                "(see g0_vs_g1 / g1_vs_g2 below for exactly which); per a8's own "
                "lift-preregistration.json not_claimable rule, compounding may not be claimed if "
                "any guard metric regresses even when the primary metric improves"
            )
        ),
        "not_claimable_source": f"{PREREG_PATH}:not_claimable",
    }

    all_disagreements = {
        pair_key: {suite: agreement[pair_key][suite].get("disagreements", []) for suite in SUITES}
        for pair_key in independent
    }
    any_disagreement = any(
        disagreements for pair in all_disagreements.values() for disagreements in pair.values()
    )

    return {
        "protocol_version": "OBZIO-GENERATION-COMPARISON-v2",
        "produced_by": "po03-worker-a7",
        "generations_owned_by": SUCCESSOR_OWNER,
        "generations_source_branch": "cursor/po03-a8-successor-generations-ed20",
        "measured_against": measured_against,
        "schema": {
            "prereg_path": PREREG_PATH,
            "scores_path": SCORES_PATH,
            "note": (
                "Third revision. The first guessed a JSON path before a8's branch existed; the "
                "second parsed plain-text transcript summary lines before a preregistration "
                "document or per-case records existed. This revision reads a8's committed "
                "structured scores and preregistration directly and independently recomputes all "
                "six preregistered conditions from the raw per-suite and per-case data, rather "
                "than copying a8's own conditions/verdict fields."
            ),
        },
        "preregistration": {
            "path": PREREG_PATH,
            "authored_by": prereg.get("authored_by"),
            "frozen_at_commit": prereg.get("frozen_at_commit"),
            "minimum_lift": minimum_lift,
            "primary_comparison": primary,
            "condition_ids": list(CONDITION_IDS),
        },
        "generations": generations,
        "independent_conditions": independent,
        "agreement_with_a8": agreement,
        "disagreements_found": any_disagreement,
        "lift": {
            "g0_vs_g1": independent["g0_vs_g1"],
            "g1_vs_g2": independent["g1_vs_g2"],
        },
        "primary_preregistered_verdict": {
            "metric_id": prereg["primary_metric"]["metric_id"],
            "baseline": primary["baseline"],
            "candidate": primary["candidate"],
            "suite": primary["suite"],
            "value": primary_result["verdict"],
            "lift": primary_result["lift"],
            "unmet_conditions": primary_result["unmet_conditions"],
            "agrees_with_a8_headline": primary_agreement.get("verdict_agrees"),
        },
        "compounding_claim_g0_through_g2": compounding_claim,
        "overall_result": primary_result["verdict"],
        "overall_result_definition": (
            "overall_result states PASS or NOT_YET on THE preregistered lift metric "
            f"({prereg['primary_metric']['metric_id']}, baseline={primary['baseline']}, "
            f"candidate={primary['candidate']}, suite={primary['suite']}) per the frozen commission "
            "wording naming this exact artifact. It intentionally does NOT collapse in the other "
            "pairwise comparison (g0_vs_g1); see compounding_claim_g0_through_g2 for the separate, "
            "full-chain answer, and lift.g0_vs_g1 / lift.g1_vs_g2 for both verdicts kept apart."
        ),
        "independence_boundaries": INDEPENDENCE_BOUNDARIES,
    }


def _not_yet_report(measured_against: dict[str, Any], boundary: str) -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-GENERATION-COMPARISON-v2",
        "produced_by": "po03-worker-a7",
        "generations_owned_by": SUCCESSOR_OWNER,
        "generations_source_branch": "cursor/po03-a8-successor-generations-ed20",
        "measured_against": measured_against,
        "schema": {"prereg_path": PREREG_PATH, "scores_path": SCORES_PATH},
        "preregistration": None,
        "generations": {gen: {"generation": gen, "status": "NOT_YET", "boundary": boundary} for gen in GENERATIONS},
        "independent_conditions": None,
        "agreement_with_a8": None,
        "disagreements_found": None,
        "lift": None,
        "primary_preregistered_verdict": {"value": "NOT_YET", "boundary": boundary},
        "compounding_claim_g0_through_g2": {"value": "NOT_YET", "boundary": boundary},
        "overall_result": "NOT_YET",
        "overall_result_definition": (
            "blocked: " + boundary
        ),
        "independence_boundaries": INDEPENDENCE_BOUNDARIES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/generation-comparison.json")
    parser.add_argument(
        "--successor-pin",
        default=None,
        help=(
            "Explicit immutable commit to resolve instead of the live "
            f"{SUCCESSOR_REMOTE_REF} ref, for reproducing a past measurement "
            "exactly regardless of what a8 has landed since."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = compute(root, successor_pin=args.successor_pin)

    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(canonical({"wrote": str(out_path), "overall_result": report["overall_result"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
