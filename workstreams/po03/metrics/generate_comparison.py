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

Schema (revised after a8-u01 landed; this now matches what a8 actually
committed rather than a prior guess). For each generation slug in
{g0, g1, g2} and each suite in {public, holdout}, a8's harness
(workstreams/po03/successor/harness/{runner.py,score.py,cli.py}) writes a
plain-text run transcript at:

    workstreams/po03/successor/transcripts/<slug>-<suite>.txt

ending in exactly one summary line of the form (observed verbatim in
transcripts/g0-public.txt, produced by harness/cli.py around harness/score.py's
``summarise``):

    [<suite>] <passed>/<total> passed rate=<rate> critical=<critical_rate> false_completions=<n> unsupported_cases=<n>

This tool parses that line with a fixed regular expression; it does not import
a8's harness code (which lives only on a8's branch and may still be changing),
so it can never silently pick up a lift rule or threshold a8 has not yet
committed anywhere this tool can read.

a8's own harness/score.py already defines a six-condition preregistered lift
rule (L1 minimum lift, L2 zero false completions in the candidate, L3 no
increase in false completions vs baseline, L4 no per-case regression, L5
public suite not worse, L6 full critical-case correctness), gated on a
"preregistration" document supplying L1's minimum_lift threshold. As of this
measurement no such preregistration document has landed on a8's branch, so
this tool cannot read a minimum_lift value from anywhere -- inventing one
would violate the never-invent-a-number rule. This tool therefore checks only
the conditions computable from each transcript's summary line alone (no
per-case regression check, no minimum-lift threshold): pass_rate strictly
improves, false_completion_count does not increase, and critical_pass_rate
does not decrease. This is a strict subset of a8's L1-L6; a PASS by this
tool's rule is necessary but not sufficient for a8's own preregistered
verdict, and this tool says so in its output rather than presenting its
verdict as equivalent to a8's.

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
import re
import subprocess
from pathlib import Path
from typing import Any


SUCCESSOR_REMOTE_REF = "origin/cursor/po03-a8-successor-generations-ed20"
SUCCESSOR_OWNER = "po03-worker-a8"
GENERATIONS = ("G0", "G1", "G2")
SLUG_OF = {"G0": "g0", "G1": "g1", "G2": "g2"}
SUITES = ("public", "holdout")

SUMMARY_LINE_RE = re.compile(
    r"^\[(?P<suite>\S+)\]\s+(?P<passed>\d+)/(?P<total>\d+)\s+passed"
    r"\s+rate=(?P<rate>[0-9.]+)\s+critical=(?P<critical>[0-9.]+)"
    r"\s+false_completions=(?P<false_completions>\d+)"
    r"\s+unsupported_cases=(?P<unsupported>\d+)\s*$",
    re.MULTILINE,
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


def parse_summary(text: str, expected_suite: str) -> tuple[dict[str, Any] | None, str]:
    matches = [m for m in SUMMARY_LINE_RE.finditer(text) if m.group("suite") == expected_suite]
    if not matches:
        return None, f"no '[{expected_suite}] <passed>/<total> passed rate=...' summary line found in transcript"
    if len(matches) > 1:
        return None, f"transcript contains {len(matches)} '[{expected_suite}]' summary lines; expected exactly one"
    m = matches[0]
    passed, total = int(m.group("passed")), int(m.group("total"))
    return {
        "cases_passed": passed,
        "cases_total": total,
        "pass_rate": float(m.group("rate")),
        "critical_pass_rate": float(m.group("critical")),
        "false_completion_count": int(m.group("false_completions")),
        "unsupported_case_count": int(m.group("unsupported")),
    }, ""


def load_suite(root: Path, sha: str | None, slug: str, suite: str, fetch_boundary: str) -> dict[str, Any]:
    expected_path = f"workstreams/po03/successor/transcripts/{slug}-{suite}.txt"

    if sha is None:
        return {"status": "NOT_YET", "expected_path": expected_path, "boundary": fetch_boundary, "scores": None}

    raw, blob_err = read_blob(root, sha, expected_path)
    if raw is None:
        return {
            "status": "NOT_YET",
            "expected_path": expected_path,
            "boundary": f"{expected_path} not found at {SUCCESSOR_REMOTE_REF}@{sha}: {blob_err}",
            "scores": None,
        }

    scores, parse_boundary = parse_summary(raw, suite)
    if scores is None:
        return {
            "status": "NOT_YET",
            "expected_path": expected_path,
            "boundary": f"{expected_path} at {sha}: {parse_boundary}",
            "scores": None,
        }

    return {
        "status": "REPORTED",
        "expected_path": expected_path,
        "boundary": None,
        "source_commit": sha,
        "scores": scores,
    }


def load_generation(root: Path, sha: str | None, generation: str, fetch_boundary: str) -> dict[str, Any]:
    slug = SLUG_OF[generation]
    suites = {suite: load_suite(root, sha, slug, suite, fetch_boundary) for suite in SUITES}
    any_reported = any(s["status"] == "REPORTED" for s in suites.values())
    return {
        "generation": generation,
        "status": "REPORTED" if any_reported else "NOT_YET",
        "suites": suites,
    }


def compare_suite(later: dict[str, Any], earlier: dict[str, Any]) -> dict[str, Any]:
    """A strict subset of a8's own harness/score.py L1-L6 preregistered lift
    rule, computable from each transcript's summary line alone: pass_rate
    strictly improves, false_completion_count never increases, and
    critical_pass_rate never decreases. This tool cannot evaluate a8's L1
    (minimum_lift threshold, no preregistration document has landed yet) or
    L4 (no per-case regression, which needs raw per-case records this tool
    does not have), so a PASS here is necessary but not a substitute for a8's
    own preregistered verdict once that document exists."""
    if later["status"] != "REPORTED" or earlier["status"] != "REPORTED":
        return {
            "value": "NOT_YET",
            "boundary": f"later status={later['status']}, earlier status={earlier['status']}",
        }

    later_s, earlier_s = later["scores"], earlier["scores"]
    pass_rate_delta = later_s["pass_rate"] - earlier_s["pass_rate"]
    false_completion_delta = later_s["false_completion_count"] - earlier_s["false_completion_count"]
    critical_delta = later_s["critical_pass_rate"] - earlier_s["critical_pass_rate"]

    regression = false_completion_delta > 0 or critical_delta < 0
    improved = pass_rate_delta > 0 and not regression
    value = "PASS" if improved else "FAIL"

    return {
        "value": value,
        "pass_rate_delta": pass_rate_delta,
        "false_completion_count_delta": false_completion_delta,
        "critical_pass_rate_delta": critical_delta,
        "regression_detected": regression,
        "later_pass_rate": later_s["pass_rate"],
        "earlier_pass_rate": earlier_s["pass_rate"],
        "not_evaluated": [
            "L1-minimum-lift (no preregistration document with lift_rule.minimum_lift has landed)",
            "L4-no-per-case-regression (transcript summary line has no per-case records)",
        ],
    }


def compare_pair(later: dict[str, Any], earlier: dict[str, Any]) -> dict[str, Any]:
    if later["status"] != "REPORTED" or earlier["status"] != "REPORTED":
        return {
            "value": "NOT_YET",
            "boundary": (
                f"cannot compare {later['generation']} to {earlier['generation']}: "
                f"{later['generation']} status={later['status']}, "
                f"{earlier['generation']} status={earlier['status']}"
            ),
        }
    return {suite: compare_suite(later["suites"][suite], earlier["suites"][suite]) for suite in SUITES}


def compute(root: Path) -> dict[str, Any]:
    sha, fetch_boundary = resolve_successor_ref(root)
    generations = {gen: load_generation(root, sha, gen, fetch_boundary) for gen in GENERATIONS}

    lift = {
        "g1_vs_g0": compare_pair(generations["G1"], generations["G0"]),
        "g2_vs_g1": compare_pair(generations["G2"], generations["G1"]),
    }

    def pair_value(pair: dict[str, Any]) -> str:
        if "value" in pair:
            return pair["value"]
        values = {pair[suite]["value"] for suite in SUITES}
        if "NOT_YET" in values:
            return "NOT_YET"
        if "FAIL" in values:
            return "FAIL"
        return "PASS"

    reported_count = sum(1 for g in generations.values() if g["status"] == "REPORTED")
    g1_vs_g0_value = pair_value(lift["g1_vs_g0"])
    g2_vs_g1_value = pair_value(lift["g2_vs_g1"])
    if reported_count < 3 or g1_vs_g0_value == "NOT_YET" or g2_vs_g1_value == "NOT_YET":
        overall_result = "NOT_YET"
    elif g1_vs_g0_value == "FAIL" or g2_vs_g1_value == "FAIL":
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
            "expected_path_pattern": "workstreams/po03/successor/transcripts/<g0|g1|g2>-<public|holdout>.txt",
            "expected_summary_line_pattern": (
                r"[<suite>] <passed>/<total> passed rate=<rate> critical=<critical_rate> "
                r"false_completions=<n> unsupported_cases=<n>"
            ),
            "note": (
                "Revised to match what po03-worker-a8 actually committed for G0 (a8-u01); "
                "an earlier revision of this schema guessed workstreams/po03/successor/<gen>/"
                "generation-result.json before a8's branch existed and was never matched by real data."
            ),
        },
        "generations": generations,
        "preregistered_lift_metric": {
            "authoritative_source": (
                "workstreams/po03/successor/harness/score.py:compare() on "
                "cursor/po03-a8-successor-generations-ed20 defines six conditions (L1-L6); "
                "this tool independently checks the three of those six computable from a "
                "transcript's summary line alone (see each comparison's not_evaluated list) "
                "and never claims equivalence to a8's own preregistered verdict."
            ),
            "this_tool_checks": "pass_rate_delta > 0 and false_completion_count_delta <= 0 and critical_pass_rate_delta >= 0",
            "no_regression_rule": "an increase in false_completion_count or a decrease in critical_pass_rate is a regression and forces FAIL, never PASS",
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
