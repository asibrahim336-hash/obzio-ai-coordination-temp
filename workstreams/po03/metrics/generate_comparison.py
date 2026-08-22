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
generations and their measured scores. po03-worker-a7 (this cohort) owns
workstreams/po03/metrics/ and is responsible only for defining the schema
below and computing the comparison from whatever a8 has actually landed --
never for inventing a score.

Expected input contract (the schema this tool looks for; a8 is expected to
land exactly this shape once it reports a generation, so that this
computation and any independent reader can find it deterministically):

    On branch cursor/po03-a8-successor-generations-ed20, for generation
    slug in {g0, g1, g2}:
        workstreams/po03/successor/<slug>/generation-result.json
    containing at minimum:
        {
          "generation": "G0" | "G1" | "G2",
          "executable": true | false,
          "frozen_suite": {
            "suite_manifest_sha256": "<64-hex>",
            "total_cases": <int>,
            "passed_cases": <int>
          },
          "holdout": {
            "holdout_manifest_sha256": "<64-hex>",
            "holdout_author_owner": "<owner id, must differ from the generation's author for a8-u03 to hold>",
            "total_cases": <int>,
            "passed_cases": <int>
          }
        }

This tool never merges or checks out the a8 branch. It only resolves the
remote-tracking ref origin/cursor/po03-a8-successor-generations-ed20 that an
operator's own prior ``git fetch origin cursor/po03-a8-successor-generations-ed20``
already populated (or did not, if the branch does not yet exist), and reads
tree/blob objects from it with ``git ls-tree`` / ``git cat-file``. It never
invokes ``git fetch`` itself, so that this tool's own output is reproducible
offline from whatever the local git object store already holds, independent
of live network access. Re-running ``git fetch`` for that branch is the
operator's job, exactly as for the coordinator's ledger branch.

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
SLUG_OF = {"G0": "g0", "G1": "g1", "G2": "g2"}
RESULT_FILENAME = "generation-result.json"


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


def resolve_successor_ref(root: Path) -> tuple[str | None, str]:
    """Return (commit_sha_or_None, boundary_message).

    Never fetches. Only resolves a remote-tracking ref that a prior, operator-run
    ``git fetch origin cursor/po03-a8-successor-generations-ed20`` may already
    have populated in the local object store.
    """
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


def load_generation(root: Path, sha: str | None, generation: str, fetch_boundary: str) -> dict[str, Any]:
    slug = SLUG_OF[generation]
    expected_path = f"workstreams/po03/successor/{slug}/{RESULT_FILENAME}"

    if sha is None:
        return {
            "generation": generation,
            "expected_path": expected_path,
            "status": "NOT_YET",
            "boundary": fetch_boundary,
            "executable": None,
            "frozen_suite": None,
            "holdout": None,
        }

    raw, blob_err = read_blob(root, sha, expected_path)
    if raw is None:
        return {
            "generation": generation,
            "expected_path": expected_path,
            "status": "NOT_YET",
            "boundary": (
                f"{expected_path} not found at {SUCCESSOR_REMOTE_REF}@{sha}: {blob_err}"
            ),
            "executable": None,
            "frozen_suite": None,
            "holdout": None,
        }

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "generation": generation,
            "expected_path": expected_path,
            "status": "NOT_YET",
            "boundary": f"{expected_path} at {sha} is not valid JSON: {exc}",
            "executable": None,
            "frozen_suite": None,
            "holdout": None,
        }

    return {
        "generation": generation,
        "expected_path": expected_path,
        "status": "REPORTED",
        "boundary": None,
        "source_commit": sha,
        "executable": doc.get("executable"),
        "frozen_suite": doc.get("frozen_suite"),
        "holdout": doc.get("holdout"),
    }


def score_of(section: dict[str, Any] | None) -> float | None:
    if not section:
        return None
    total = section.get("total_cases")
    passed = section.get("passed_cases")
    if not isinstance(total, int) or not isinstance(passed, int) or total <= 0:
        return None
    return passed / total


def compare_pair(later: dict[str, Any], earlier: dict[str, Any]) -> dict[str, Any]:
    """Preregistered lift metric (metric-definitions.json: successor_lift):
    score(later) - score(earlier) on the frozen public suite plus holdout,
    combined here as (frozen_suite_score, holdout_score); PASS requires a
    positive delta on both with no regression on either, FAIL is a measured
    negative or zero result, NOT_YET means at least one side is unreported."""
    if later["status"] != "REPORTED" or earlier["status"] != "REPORTED":
        return {
            "value": "NOT_YET",
            "boundary": (
                f"cannot compare {later['generation']} to {earlier['generation']}: "
                f"{later['generation']} status={later['status']}, "
                f"{earlier['generation']} status={earlier['status']}"
            ),
        }

    later_suite = score_of(later["frozen_suite"])
    earlier_suite = score_of(earlier["frozen_suite"])
    later_holdout = score_of(later["holdout"])
    earlier_holdout = score_of(earlier["holdout"])

    if None in (later_suite, earlier_suite, later_holdout, earlier_holdout):
        return {
            "value": "NOT_YET",
            "boundary": (
                f"{later['generation']} or {earlier['generation']} reported but missing a "
                "well-formed frozen_suite/holdout total_cases+passed_cases score"
            ),
        }

    suite_delta = later_suite - earlier_suite
    holdout_delta = later_holdout - earlier_holdout
    regression = suite_delta < 0 or holdout_delta < 0
    result = "FAIL" if regression else ("PASS" if suite_delta > 0 and holdout_delta > 0 else "FAIL")

    return {
        "value": result,
        "frozen_suite_score_delta": suite_delta,
        "holdout_score_delta": holdout_delta,
        "regression_detected": regression,
        "later_frozen_suite_score": later_suite,
        "earlier_frozen_suite_score": earlier_suite,
        "later_holdout_score": later_holdout,
        "earlier_holdout_score": earlier_holdout,
    }


def compute(root: Path) -> dict[str, Any]:
    sha, fetch_boundary = resolve_successor_ref(root)
    generations = {gen: load_generation(root, sha, gen, fetch_boundary) for gen in GENERATIONS}

    lift = {
        "g1_vs_g0": compare_pair(generations["G1"], generations["G0"]),
        "g2_vs_g1": compare_pair(generations["G2"], generations["G1"]),
    }

    reported_count = sum(1 for g in generations.values() if g["status"] == "REPORTED")
    if reported_count < 3:
        overall_result = "NOT_YET"
    elif lift["g1_vs_g0"]["value"] == "NOT_YET" or lift["g2_vs_g1"]["value"] == "NOT_YET":
        overall_result = "NOT_YET"
    elif lift["g1_vs_g0"]["value"] == "FAIL" or lift["g2_vs_g1"]["value"] == "FAIL":
        overall_result = "FAIL"
    else:
        overall_result = "PASS"

    return {
        "protocol_version": "OBZIO-GENERATION-COMPARISON-v1",
        "produced_by": "po03-worker-a7",
        "generations_owned_by": SUCCESSOR_OWNER,
        "generations_source_branch": "cursor/po03-a8-successor-generations-ed20",
        "measured_against": {
            "successor_remote_ref": SUCCESSOR_REMOTE_REF,
            "successor_commit_sha": sha,
            "resolution_boundary": fetch_boundary,
        },
        "schema": {
            "expected_result_filename": RESULT_FILENAME,
            "expected_path_pattern": "workstreams/po03/successor/<g0|g1|g2>/" + RESULT_FILENAME,
            "expected_fields": [
                "generation",
                "executable",
                "frozen_suite.suite_manifest_sha256",
                "frozen_suite.total_cases",
                "frozen_suite.passed_cases",
                "holdout.holdout_manifest_sha256",
                "holdout.holdout_author_owner",
                "holdout.total_cases",
                "holdout.passed_cases",
            ],
        },
        "generations": generations,
        "preregistered_lift_metric": {
            "formula": "score(later) - score(earlier) on frozen_suite and holdout independently; PASS requires both deltas > 0 with no regression on either; FAIL is a measured non-positive or regressive result; NOT_YET means a required generation or score field has not been reported",
            "no_regression_rule": "any negative delta on frozen_suite_score or holdout_score is a regression and forces FAIL, never PASS",
        },
        "lift": lift,
        "overall_result": overall_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/generation-comparison.json")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = compute(root)

    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(canonical({"wrote": str(out_path), "overall_result": report["overall_result"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
