#!/usr/bin/env python3
"""Regenerate the WA-010 evidence artifacts from the engine and the fixtures.

Everything this script writes is derived: it runs the audit on the real seeded
registry, the audit on the deliberately overlapping fixture, the decision matrix
over every fixture change, and the sanitized pre-commit reproduction.  Nothing is
transcribed by hand, so a reviewer can re-run it from a clean clone and compare.

The only non-deterministic output is ``test-output.txt``, which carries unittest's
own wall-clock line; every JSON artifact is byte-stable.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RESULT_DIR = Path(__file__).resolve().parent
UNIT_DIR = RESULT_DIR.parent
ENGINE_DIR = UNIT_DIR / "engine"
FIXTURES_DIR = UNIT_DIR / "fixtures"
TESTS_DIR = UNIT_DIR / "tests"
REPO_ROOT = UNIT_DIR.parents[4]
REGISTRY_PATH = REPO_ROOT / "workstreams/po03/control/path-ownership.json"
TASK_INPUT_PATH = REPO_ROOT / "workstreams/po03/control/inputs/wave-a/wa-010-a02.json"
CONTROLLER_BASE = "f2bdb4908026f66e8450802bb15921be1f3c338d"

sys.path.insert(0, str(ENGINE_DIR))

from ownership import Change, OwnershipEngine, changes_from_document  # noqa: E402
from reproduce_overlap_prevention import run_reproduction  # noqa: E402

CHANGE_FIXTURES = (
    "changes-admitted.json",
    "changes-prohibited.json",
    "changes-rename-and-delete.json",
    "changes-adversarial.json",
)

STATUS_LETTERS = {"A": "ADD", "M": "MODIFY", "D": "DELETE", "R": "RENAME", "C": "COPY", "T": "TYPECHANGE"}


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path: Path, payload: Any) -> int:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def composed_engine() -> OwnershipEngine:
    return OwnershipEngine.from_registry_and_task_input(
        load(REGISTRY_PATH),
        load(TASK_INPUT_PATH),
        source_document="workstreams/po03/control/path-ownership.json"
        "+workstreams/po03/control/inputs/wave-a/wa-010-a02.json",
    )


def build_registry_audit() -> dict[str, Any]:
    engine = composed_engine()
    findings = engine.audit()
    return {
        "artifact": "registry-audit.json",
        "purpose": (
            "Audit of the real seeded PO-03 ownership registry composed with this attempt's "
            "immutable task input, run read-only."
        ),
        "registry_path": "workstreams/po03/control/path-ownership.json",
        "task_input_path": "workstreams/po03/control/inputs/wave-a/wa-010-a02.json",
        "owner_count": len(engine.owners),
        "subordinate_count": sum(1 for owner in engine.owners if owner.role == "subordinate"),
        "declared_deny_globs": [glob.pattern for glob in engine.declared_deny_globs],
        "implicit_deny_globs": [glob.pattern for glob in engine.implicit_deny_globs],
        "grant_overlap_count": len(engine.detect_grant_overlaps()),
        "grant_divergence_count": len(engine.detect_grant_divergence()),
        "blocking_finding_count": len(engine.blocking_findings()),
        "advisory_finding_count": sum(1 for f in findings if f.severity == "ADVISORY"),
        "outcome": "DISJOINT" if not engine.blocking_findings() else "OVERLAP_DETECTED",
        "findings": [finding.to_dict() for finding in findings],
        "note": (
            "The registry is read but never written. Advisory findings describe contradictory or "
            "fragile grants; only ERROR findings would block."
        ),
    }


def build_overlap_detection() -> dict[str, Any]:
    fixture = load(FIXTURES_DIR / "registry-overlapping.json")
    engine = OwnershipEngine.from_ownership_document(fixture)
    findings = engine.detect_grant_overlaps()
    observed_pairs = sorted(
        sorted((finding.left_owner or "", finding.right_owner or "")) for finding in findings
    )
    expected_pairs = sorted(sorted(pair) for pair in fixture["expected_overlap_pairs"])
    verified = []
    for finding in findings:
        left = next(
            glob
            for owner in engine.owners
            if owner.owner_id == finding.left_owner
            for glob in owner.owned_globs
            if glob.pattern == finding.left_glob
        )
        right = next(
            glob
            for owner in engine.owners
            if owner.owner_id == finding.right_owner
            for glob in owner.owned_globs
            if glob.pattern == finding.right_glob
        )
        verified.append(
            {
                "left_owner": finding.left_owner,
                "left_glob": finding.left_glob,
                "right_owner": finding.right_owner,
                "right_glob": finding.right_glob,
                "witness_path": finding.witness_path,
                "left_matches_witness": left.matches(finding.witness_path),
                "right_matches_witness": right.matches(finding.witness_path),
                "witness_exists_on_disk": (REPO_ROOT / finding.witness_path).exists(),
            }
        )
    return {
        "artifact": "overlap-detection.json",
        "purpose": (
            "Static detection of overlapping subordinate grants from the patterns alone, with a "
            "witness path that both grants provably admit."
        ),
        "fixture": "fixtures/registry-overlapping.json",
        "fixture_id": fixture["fixture_id"],
        "expected_outcome": fixture["expected_outcome"],
        "observed_outcome": "OVERLAP_DETECTED" if findings else "DISJOINT",
        "expected_owner_pairs": expected_pairs,
        "observed_owner_pairs": observed_pairs,
        "owner_pairs_match_preregistration": observed_pairs == expected_pairs,
        "glob_pair_finding_count": len(findings),
        "every_witness_verified": all(
            entry["left_matches_witness"] and entry["right_matches_witness"] for entry in verified
        ),
        "no_witness_exists_on_disk": not any(entry["witness_exists_on_disk"] for entry in verified),
        "verified_findings": verified,
    }


def _decide(engine: OwnershipEngine, fixture: dict[str, Any]) -> list[dict[str, Any]]:
    writer = fixture["writer"]
    fence = fixture["fence_token"]
    rows: list[dict[str, Any]] = []
    if "changes" in fixture:
        entries = [
            {"change": change, "expected": None}
            for change in changes_from_document(fixture)
        ]
    else:
        entries = []
        for expected in fixture["expected"]:
            status = STATUS_LETTERS.get(expected.get("status", "A"), "ADD")
            entries.append(
                {
                    "change": Change(
                        status=status,
                        path=expected.get("path"),
                        old_path=expected.get("old_path"),
                    ),
                    "expected": expected,
                }
            )
    for entry in entries:
        change = entry["change"]
        expected = entry["expected"]
        report = engine.check_changes(writer, [change], declared_fence=fence)
        row: dict[str, Any] = {
            "status": change.status,
            "path": change.path,
            "old_path": change.old_path,
            "outcome": report.outcome,
            "decisions": [
                {"side": d.side, "decision": d.decision, "reason": d.reason, "detail": d.detail}
                for d in report.decisions
            ],
        }
        if expected is not None:
            if "reason" in expected:
                row["expected_reason"] = expected["reason"]
                row["reason_matches_preregistration"] = (
                    report.decisions[0].reason == expected["reason"]
                )
            if "source_reason" in expected or "target_reason" in expected:
                by_side = {d.side: d.reason for d in report.decisions}
                row["case"] = expected.get("case")
                row["expected_source_reason"] = expected.get("source_reason")
                row["expected_target_reason"] = expected.get("target_reason")
                row["reason_matches_preregistration"] = (
                    by_side.get("source") == expected.get("source_reason")
                    and by_side.get("target") == expected.get("target_reason")
                )
            row["why"] = expected.get("why")
        rows.append(row)
    return rows


def build_denial_matrix() -> dict[str, Any]:
    engine = composed_engine()
    sections: dict[str, Any] = {}
    total = 0
    mismatches = 0
    for name in CHANGE_FIXTURES:
        fixture = load(FIXTURES_DIR / name)
        rows = _decide(engine, fixture)
        section_mismatches = [
            row for row in rows if row.get("reason_matches_preregistration") is False
        ]
        outcomes = {row["outcome"] for row in rows}
        sections[name] = {
            "fixture_id": fixture["fixture_id"],
            "purpose": fixture["purpose"],
            "expected_outcome": fixture["expected_outcome"],
            "row_count": len(rows),
            "observed_outcomes": sorted(outcomes),
            "preregistration_mismatch_count": len(section_mismatches),
            "rows": rows,
        }
        total += len(rows)
        mismatches += len(section_mismatches)
    return {
        "artifact": "denial-matrix.json",
        "purpose": (
            "Every fixture change decided by the composed registry plus task-input view, with the "
            "preregistered reason code compared against the observed one."
        ),
        "engine_source": engine.source_document,
        "writer": "lease-po03-wa-010-a02",
        "fence_token": 2,
        "total_rows": total,
        "preregistration_mismatch_count": mismatches,
        "outcome": "ALL_REASONS_AS_PREREGISTERED" if mismatches == 0 else "MISMATCH",
        "sections": sections,
    }


def build_reproduction() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        return run_reproduction(Path(tmp))


READ_SOURCES = (
    ("AGENTS.md", "Repository-wide operator instructions."),
    ("operations/README.md", "Current operator route and read order."),
    ("workstreams/po03/COMMISSION.md", "PO-03 commission, collision boundary and acceptance controls."),
    (
        "workstreams/po03/control/acceptance/wave-a-material-v1.json",
        "Frozen Wave A acceptance contract; producer-neutral criteria.",
    ),
    (
        "workstreams/po03/control/inputs/wave-a/wa-010-a02.json",
        "Immutable task input for this attempt, including the frozen hypothesis and grant.",
    ),
    (
        "workstreams/po03/control/path-ownership.json",
        "Real ownership registry used as the sanitized read-only audit workload.",
    ),
    ("workstreams/po03/control/wave-a-portfolio.json", "Wave A portfolio pinned by the task input."),
    ("workstreams/po03/contracts/transactional-result.schema.json", "Transactional result wire format."),
    ("workstreams/po03/contracts/wave-compounding.schema.json", "Wave compounding wire format."),
    ("workstreams/po03/tools/validate_contracts.py", "Seeded custody validator; strengthened, never bypassed."),
    ("workstreams/po03/tests/test_validate_contracts.py", "Seeded contract tests pinned by seed_tests_sha256."),
    ("workstreams/po03/tests/test_supersede_wave_a_inputs.py", "Seeded supersession tests."),
    (".github/workflows/po03-contracts.yml", "Clean-runtime contract workflow; dependency-free unittest discovery."),
    ("scripts/check_operator_taxonomy.py", "Operator taxonomy currentness check required before commit."),
    (
        "workstreams/po03/wave-a/units/wa-025/result/ready-to-commit.json",
        "Sibling unit return, read only to match the established producer-return conventions.",
    ),
)

PINNED_HASHES = {
    "workstreams/po03/control/inputs/wave-a/wa-010-a02.json": "096d8f69e099ee0abc87d65ed6012720ec16aa7b2bf685b4366d3735ec0fc809",
    "workstreams/po03/control/acceptance/wave-a-material-v1.json": "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
    "workstreams/po03/control/wave-a-portfolio.json": "515cf2325bda326471140aa1a294696f02c6c10effc3bae9022d55934c063ebd",
    "workstreams/po03/COMMISSION.md": "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
    "workstreams/po03/contracts/transactional-result.schema.json": "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
    "workstreams/po03/contracts/wave-compounding.schema.json": "5278cb6bc4e7f41a5d513d4a00427a1ed199a21459025c7fa96fb97d56439360",
    "workstreams/po03/tools/validate_contracts.py": "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
    "workstreams/po03/tests/test_validate_contracts.py": "401a684c0a2d3817d08a76044a331f0f241b16d687d2dd12d9ea0f31612dc112",
    ".github/workflows/po03-contracts.yml": "427949c07d93fe69bea6485a91ca58c4297be21759e6b0b00a0e5cc9f450c7cb",
}


def build_source_claims() -> dict[str, Any]:
    import hashlib

    head_commit = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    base_is_ancestor = (
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", CONTROLLER_BASE, "HEAD"],
            capture_output=True,
        ).returncode
        == 0
    )
    git_version = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()

    entries = []
    for relative, why in READ_SOURCES:
        data = (REPO_ROOT / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        entry: dict[str, Any] = {
            "path": relative,
            "sha256": digest,
            "bytes": len(data),
            "why_read": why,
            "access": "READ_ONLY",
        }
        pinned = PINNED_HASHES.get(relative)
        if pinned is not None:
            entry["pinned_sha256"] = pinned
            entry["pinned_sha256_matches"] = pinned == digest
        entries.append(entry)

    return {
        "artifact": "source-claims.json",
        "purpose": (
            "Exact repository sources read for this attempt, with observed SHA-256 and byte counts, "
            "kept separate from hypotheses, reproductions and mechanism changes."
        ),
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "immutable_controller_base_commit": CONTROLLER_BASE,
        "immutable_controller_base_is_ancestor_of_head": base_is_ancestor,
        "producer_head_commit_at_generation": head_commit,
        "repository_sources": entries,
        "all_pinned_hashes_match": all(
            entry.get("pinned_sha256_matches", True) for entry in entries
        ),
        "differential_oracle": {
            "claim": (
                "git's own ':(glob)' pathspec magic defines the dialect this engine must implement: "
                "wildcards do not cross '/', and '**' is meaningful only as a whole path component."
            ),
            "oracle": "the git binary present in this runtime, queried with 'git ls-files -- :(glob)PATTERN'",
            "observed_version": git_version,
            "how_used": (
                "tests/test_gitglob.py::GitDifferentialTest builds a throwaway repository and compares "
                "the engine's match set against git's for every pattern in its table."
            ),
            "why_an_oracle_rather_than_a_citation": (
                "A documentation quotation cannot be executed. Comparing against the shipped "
                "implementation converts the claim into a test that fails if the dialect drifts."
            ),
        },
        "external_source_retrieval": {
            "state": "NOT_ATTEMPTED",
            "reason": (
                "The immutable task input sets minimum_current_method_hypotheses and "
                "minimum_sanitized_reproductions to 0 and first_substantive_return_seed to false, so "
                "this engineering unit owes no external research quota. No network fetch was made and "
                "no external claim is asserted."
            ),
        },
        "excluded_sources": [
            {
                "scope": "every PO-01 branch, path, PR and artifact",
                "reason": "PO-01 non-interference is absolute; nothing was read, contacted or mutated.",
            },
            {
                "scope": "PR #8 and cursor/setup-dev-environment-b5ce",
                "reason": "Explicitly out of bounds for this commission.",
            },
            {
                "scope": "producer narratives from other units",
                "reason": "Narrative is not independent evidence; only wa-025's return shape was read for conventions.",
            },
        ],
    }


def build_test_output() -> tuple[str, dict[str, Any]]:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(TESTS_DIR),
            "-p",
            "test_*.py",
            "-v",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    text = completed.stdout + completed.stderr
    passed = text.rstrip().endswith("OK")
    ran = 0
    for line in text.splitlines():
        if line.startswith("Ran ") and " test" in line:
            ran = int(line.split()[1])
    return text, {"exit_code": completed.returncode, "tests_run": ran, "passed": passed}


def main() -> int:
    written: list[tuple[str, int]] = []

    text, summary = build_test_output()
    path = RESULT_DIR / "test-output.txt"
    path.write_text(text, encoding="utf-8")
    written.append((path.name, len(text.encode("utf-8"))))

    for name, payload in (
        ("registry-audit.json", build_registry_audit()),
        ("overlap-detection.json", build_overlap_detection()),
        ("denial-matrix.json", build_denial_matrix()),
        ("reproduction-result.json", build_reproduction()),
        ("source-claims.json", build_source_claims()),
    ):
        written.append((name, dump(RESULT_DIR / name, payload)))

    for name, size in written:
        print(f"{name} {size}")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
