#!/usr/bin/env python3
"""Project the lesson register into lessons.json, and verify what it claims.

    python3 -I workstreams/po03/successor/lessons/build_lessons.py --write
    python3 -I workstreams/po03/successor/lessons/build_lessons.py --check
    python3 -I workstreams/po03/successor/lessons/build_lessons.py --verify-support

``--check`` asserts the committed document still matches the register in the
code, for the same reason the lineage document is generated: a hand-maintained
table that has drifted from its source looks like evidence and is not.

``--verify-support`` is the part that cannot be faked from inside this branch.
Every independence claim names an evaluator branch, commit, blob id and content
digest; this mode re-derives them from git objects and reports a mismatch or an
unavailable ref rather than assuming the citation is good. It is separate from
``--check`` on purpose: a clean clone that fetched only this cohort's branch can
still verify the document, and will honestly report the evaluator refs as
unavailable instead of silently passing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PO03 = HERE.parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.lessons.lessons import (  # noqa: E402
    DISPOSITIONS,
    EVIDENCE,
    LESSONS,
    OWNER,
    independently_supported,
)
from successor.g2 import successor as g2  # noqa: E402

TARGET = HERE / "lessons.json"

# The score as it stood before C-10 and C-11 were added.  Preserved by commit so
# the effect of revising G2 after the first scoring run is visible rather than
# quietly folded into the current number.
PRE_REVISION = {
    "commit": "91452a0",
    "document": "workstreams/po03/successor/scores/generation-comparison.json",
    "headline": {"baseline": "G1", "candidate": "G2", "suite": "holdout", "verdict": "PASS", "lift": 0.3},
    "g2_public": "31/31",
    "g2_holdout": "10/10",
}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def lesson_record(lesson: dict) -> dict:
    support = [
        {
            "evidence_id": item["evidence"],
            "owner": EVIDENCE[item["evidence"]]["owner"],
            "role": EVIDENCE[item["evidence"]]["role"],
            "branch": EVIDENCE[item["evidence"]]["branch"],
            "commit": EVIDENCE[item["evidence"]]["commit"],
            "path": EVIDENCE[item["evidence"]]["path"],
            "blob": EVIDENCE[item["evidence"]]["blob"],
            "sha256": EVIDENCE[item["evidence"]]["sha256"],
            "finding": EVIDENCE[item["evidence"]]["finding"],
            "observed": EVIDENCE[item["evidence"]]["observed"],
            "detail": item["detail"],
        }
        for item in lesson["support"]
    ]
    return {
        "lesson_id": lesson["lesson_id"],
        "statement": lesson["statement"],
        "support": support,
        "support_owners": sorted({item["owner"] for item in support}),
        "independently_supported": independently_supported(lesson),
        "mechanism": lesson["mechanism"],
        "mechanism_is_live": lesson["mechanism"]["kind"] != "none",
        "recurrence_test": lesson["recurrence_test"],
        "recurrence_test_author": OWNER,
        "disposition": lesson["disposition"],
        "disposition_basis": lesson["disposition_basis"],
        "residual_boundary": lesson["residual_boundary"],
        "lineage": lesson["lineage"],
    }


def build_document() -> dict:
    records = [lesson_record(lesson) for lesson in LESSONS]
    changes = {change["change_id"]: change for change in g2.CHANGES}

    qualifying = [
        record["lesson_id"]
        for record in records
        if record["independently_supported"] and record["mechanism_is_live"]
    ]
    by_disposition: dict[str, list[str]] = {}
    for record in records:
        by_disposition.setdefault(record["disposition"], []).append(record["lesson_id"])

    return {
        "document_id": "po03-a8-lesson-register-v001",
        "unit_id": "a8-u06",
        "owner": OWNER,
        "generated_by": "workstreams/po03/successor/lessons/build_lessons.py",
        "acceptance_addressed": (
            "Three or more lessons each produce a live mechanism change, a recurrence test, and a "
            "RETAIN/DELETE/SUPERSEDE/RETEST/REJECT disposition preserving lineage."
        ),
        "independence_rule": (
            f"Support authored by {OWNER} is not independent support, because {OWNER} authors the "
            "generations being scored. A lesson counts as independently supported only if at least "
            "one cited evidence record has a different owner."
        ),
        "recurrence_test_authorship_boundary": (
            "The frozen acceptance asks for a recurrence test authored by a different owner. The tests "
            f"in workstreams/po03/tests/test_a8_* are authored by {OWNER}, so that condition is NOT_YET "
            "as stated. What is independent is the material each test is bound to: for L-01, L-02 and "
            "L-03 the failing case is one of cohort a6's ten evaluator-held cases, authored without "
            "sight of any generation here; for L-04, L-06, L-07, L-08, L-11 and L-12 the reproducer is "
            "cohort a10's published audit finding. No test in this cohort was authored by another owner, "
            "and none is presented as if it were."
        ),
        "lesson_count": len(records),
        "independently_supported_count": len(
            [record for record in records if record["independently_supported"]]
        ),
        "lessons_with_live_mechanism_and_independent_support": sorted(qualifying),
        "qualifying_count": len(qualifying),
        "acceptance_threshold": 3,
        "acceptance_met": len(qualifying) >= 3,
        "dispositions_used": {key: sorted(value) for key, value in sorted(by_disposition.items())},
        "disposition_vocabulary": list(DISPOSITIONS),
        "mechanism_changes_in_g2": sorted(
            record["mechanism"]["change_id"]
            for record in records
            if record["mechanism"]["kind"] == "g2_change"
        ),
        "g2_changes_not_traced_to_a_lesson_here": sorted(
            change_id
            for change_id in changes
            if change_id
            not in {
                record["mechanism"]["change_id"]
                for record in records
                if record["mechanism"]["kind"] == "g2_change"
            }
            | {
                also
                for record in records
                for also in record["mechanism"].get("also", [])
            }
        ),
        "revision_after_first_scoring": {
            "changes_added": ["C-10", "C-11"],
            "reason": (
                "Both trace to findings published by cohort a10 after the suites were frozen and after "
                "the first scoring run. Neither was prompted by anything measured on the frozen suites, "
                "and no case was added, edited or removed."
            ),
            "pre_revision_score": PRE_REVISION,
            "post_revision_effect_on_frozen_suites": (
                "none: G2 scores 31/31 public and 10/10 holdout before and after, so the revision is "
                "visible in the register and in git history rather than in the headline number"
            ),
            "why_this_is_not_metric_tuning": (
                "A change made to raise a score would target a case the score counts. These two target "
                "shapes the frozen suites never contained, which is why they leave the score unchanged; "
                "the public suite's own blind spot on the path-scope shape is recorded under L-11."
            ),
        },
        "lessons": records,
    }


def verify_support() -> int:
    """Re-derive every independence claim from git objects."""
    failures = 0
    unavailable = 0
    for evidence_id, record in sorted(EVIDENCE.items()):
        commit = record["commit"]
        if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            print(f"NOT_YET {evidence_id}: commit {commit} is not present in this clone ({record['branch']})")
            unavailable += 1
            continue
        blob = git("rev-parse", f"{commit}:{record['path']}")
        if blob.returncode != 0:
            print(f"FAIL {evidence_id}: {record['path']} absent at {commit}")
            failures += 1
            continue
        if blob.stdout.strip() != record["blob"]:
            print(f"FAIL {evidence_id}: blob {blob.stdout.strip()} != recorded {record['blob']}")
            failures += 1
            continue
        content = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{record['path']}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        digest = hashlib.sha256(content).hexdigest()
        if digest != record["sha256"]:
            print(f"FAIL {evidence_id}: sha256 {digest} != recorded {record['sha256']}")
            failures += 1
            continue
        print(f"VERIFIED {evidence_id}: {record['owner']} {record['path']} @ {commit[:7]} sha256={digest[:16]}")
    if failures:
        print(f"SUPPORT UNVERIFIED: {failures} citation(s) do not match the git objects they name")
        return 1
    if unavailable:
        print(f"SUPPORT PARTIALLY VERIFIED: {unavailable} evaluator ref(s) not present in this clone")
        return 0
    print(f"SUPPORT VERIFIED: {len(EVIDENCE)} citation(s) match the git objects they name")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--verify-support", dest="verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        return verify_support()

    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
            print(f"DRIFTED {TARGET}: the lesson document no longer matches the register")
            return 1
        print(f"CONSISTENT {TARGET}")
        return 0

    TARGET.write_text(text, encoding="utf-8")
    print(f"WROTE {TARGET}")
    print(
        f"{document['qualifying_count']} lesson(s) have independent support and a live mechanism "
        f"(threshold {document['acceptance_threshold']}); dispositions used: "
        f"{', '.join(document['dispositions_used'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
