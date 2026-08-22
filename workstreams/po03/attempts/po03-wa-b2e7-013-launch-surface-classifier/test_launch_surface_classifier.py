#!/usr/bin/env python3
"""Tests for the launch-surface classifier (task po03-wa-b2e7-013).

Run with: python3 -I test_launch_surface_classifier.py
Standard library only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from launch_surface_classifier import (  # noqa: E402
    ClassificationError,
    classify,
    load_high_risk_markers,
    load_root_readme_linked_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _minimal_fixture(root: Path) -> None:
    (root / "operations").mkdir(parents=True)
    (root / "state" / "operator-system").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "AGENTS.md").write_text("agents\n", encoding="utf-8")
    (root / "README.md").write_text(
        "See [`operations/README.md`](operations/README.md).\n", encoding="utf-8"
    )
    (root / "operations" / "README.md").write_text("entrypoint\n", encoding="utf-8")
    (root / "operations" / "INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md").write_text(
        "| a | b |\n|---|---|\n| x | see `state/named_disposition.md` |\n", encoding="utf-8"
    )
    (root / "state" / "operator-system" / "ACTIVE_INSTRUCTION_STACK.json").write_text(
        json.dumps(
            {
                "resolve_in_order": ["operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md"],
                "immutable_execution_evidence": ["state/evidence_named_by_stack.md"],
            }
        ),
        encoding="utf-8",
    )
    (root / "scripts" / "check_operator_taxonomy.py").write_text(
        'high_risk_markers = {\n    "state/verified_marker.md": "SUPERSEDED FOR ACTIVE ROUTING",\n'
        '    "state/false_claim_marker.md": "SUPERSEDED FOR ACTIVE ROUTING",\n}\n',
        encoding="utf-8",
    )
    (root / "state" / "named_disposition.md").write_text("disposition table content\n", encoding="utf-8")
    (root / "state" / "evidence_named_by_stack.md").write_text("evidence content\n", encoding="utf-8")
    (root / "state" / "verified_marker.md").write_text("SUPERSEDED FOR ACTIVE ROUTING\n", encoding="utf-8")
    (root / "state" / "false_claim_marker.md").write_text("no marker text here at all\n", encoding="utf-8")
    (root / "state" / "truly_ambiguous.md").write_text("nobody has classified this yet\n", encoding="utf-8")


def test_fails_closed_when_stack_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "AGENTS.md").write_text("x", encoding="utf-8")
        raised = False
        try:
            classify(root)
        except ClassificationError as exc:
            raised = "instruction stack missing" in str(exc)
        check("test_fails_closed_when_stack_missing", raised)


def test_load_root_readme_linked_paths_parses_markdown_link() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        root.joinpath("operations").mkdir()
        (root / "operations" / "README.md").write_text("x", encoding="utf-8")
        (root / "README.md").write_text("[`operations/README.md`](operations/README.md)\n", encoding="utf-8")
        linked = load_root_readme_linked_paths(root)
        check("test_load_root_readme_linked_paths_parses_markdown_link", linked == {"operations/README.md"})


def test_load_high_risk_markers_parses_dict_literal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        root.joinpath("scripts").mkdir()
        (root / "scripts" / "check_operator_taxonomy.py").write_text(
            'high_risk_markers = {\n    "a.md": "MARKER ONE",\n    "b.md": "MARKER TWO",\n}\n',
            encoding="utf-8",
        )
        markers = load_high_risk_markers(root)
        check("test_load_high_risk_markers_parses_dict_literal", markers == {"a.md": "MARKER ONE", "b.md": "MARKER TWO"})


def test_minimal_fixture_classifies_each_bucket_correctly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _minimal_fixture(root)
        report = classify(root)
        launch = set(report["launch_surface"])
        evidence_paths = {e["path"] for e in report["evidence"]}
        ambiguous = set(report["ambiguous"])

        check(
            "test_minimal_fixture_launch_surface",
            launch
            == {
                "AGENTS.md",
                "README.md",
                "operations/README.md",
                "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md",
            },
            detail=str(launch),
        )
        check(
            "test_minimal_fixture_evidence",
            evidence_paths == {"state/evidence_named_by_stack.md", "state/named_disposition.md", "state/verified_marker.md"},
            detail=str(evidence_paths),
        )
        check(
            "test_minimal_fixture_false_claim_marker_is_ambiguous_not_evidence",
            "state/false_claim_marker.md" in ambiguous,
            detail=str(ambiguous),
        )
        check(
            "test_minimal_fixture_truly_ambiguous_file_is_ambiguous",
            "state/truly_ambiguous.md" in ambiguous,
        )
        check(
            "test_minimal_fixture_fails_closed_status",
            report["status"] == "FAILED_CLOSED_AMBIGUOUS_FILES_PRESENT" and report["all_classified"] is False,
        )


def test_minimal_fixture_with_no_ambiguous_files_reports_all_classified() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _minimal_fixture(root)
        (root / "state" / "truly_ambiguous.md").unlink()
        (root / "state" / "false_claim_marker.md").unlink()
        report = classify(root)
        check(
            "test_minimal_fixture_with_no_ambiguous_files_reports_all_classified",
            report["all_classified"] is True and report["status"] == "ALL_CLASSIFIED",
            detail=str(report["ambiguous"]),
        )


def test_launch_and_evidence_sets_never_overlap_on_synthetic_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _minimal_fixture(root)
        report = classify(root)
        overlap = set(report["launch_surface"]) & {e["path"] for e in report["evidence"]}
        check("test_launch_and_evidence_sets_never_overlap_on_synthetic_fixture", overlap == set())


def test_real_repository_produces_disjoint_launch_and_evidence_sets() -> None:
    """Falsifiable claim, on the real repository: no file that a structured
    source names as evidence-only is ever also classified as launch
    surface, and vice versa."""
    report = classify(REPO_ROOT)
    overlap = set(report["launch_surface"]) & {e["path"] for e in report["evidence"]}
    check(
        "test_real_repository_produces_disjoint_launch_and_evidence_sets",
        overlap == set(),
        detail=str(overlap),
    )
    print(
        f"    candidate_count={report['candidate_count']} launch_surface={len(report['launch_surface'])} "
        f"evidence={len(report['evidence'])} ambiguous={len(report['ambiguous'])} status={report['status']}"
    )


def test_real_repository_operations_readme_is_launch_surface_via_root_link() -> None:
    """Real finding: operations/README.md is not itself named inside
    ACTIVE_INSTRUCTION_STACK.json's resolve_in_order, so it only becomes
    mechanically classifiable as LAUNCH_SURFACE via the repository-root
    README.md's own markdown link to it -- not via any filename
    heuristic."""
    report = classify(REPO_ROOT)
    check(
        "test_real_repository_operations_readme_is_launch_surface_via_root_link",
        "operations/README.md" in report["launch_surface"],
        detail=str(report["launch_surface"]),
    )


def test_real_repository_verified_markers_are_confirmed_not_just_claimed() -> None:
    """Every file scripts/check_operator_taxonomy.py's high_risk_markers
    names must actually contain its claimed marker text to count as
    EVIDENCE here; this test confirms all five real entries pass that
    verification (i.e. the taxonomy script's own currentness claim about
    these files is independently corroborated by this classifier)."""
    report = classify(REPO_ROOT)
    verified = {e["path"] for e in report["evidence"] if e["reason"].startswith("verified_marker:")}
    expected = {
        "commissions/OPERATOR_D_CONTINUATION_DIRECTIVE_20260818.md",
        "dispatch/OPERATOR_D_REFERENCE_UPDATE_20260818.md",
        "state/DESK_OPERATOR_D_RECOVERY_AND_CONTINUATION_20260818.md",
        "templates/NEXT_OPERATOR_PREFLIGHT_20260818.md",
        "handover/PRINCIPAL_AI_OPERATOR_HANDOVER_20260819.md",
    }
    check(
        "test_real_repository_verified_markers_are_confirmed_not_just_claimed",
        verified == expected,
        detail=str(verified),
    )


def test_real_repository_has_a_large_uncovered_ambiguous_backlog() -> None:
    """Real finding, recorded honestly: the overwhelming majority of
    instruction-bearing markdown files in this repository have no
    structured disposition record at all (not named by the instruction
    stack, not covered by a verified high_risk_marker, not named in the
    disposition table), so the classifier correctly refuses to certify
    them either way instead of guessing."""
    report = classify(REPO_ROOT)
    check(
        "test_real_repository_has_a_large_uncovered_ambiguous_backlog",
        len(report["ambiguous"]) > len(report["launch_surface"]) + len(report["evidence"]),
        detail=f"ambiguous={len(report['ambiguous'])} launch={len(report['launch_surface'])} evidence={len(report['evidence'])}",
    )


def run_all() -> int:
    tests = [
        test_fails_closed_when_stack_missing,
        test_load_root_readme_linked_paths_parses_markdown_link,
        test_load_high_risk_markers_parses_dict_literal,
        test_minimal_fixture_classifies_each_bucket_correctly,
        test_minimal_fixture_with_no_ambiguous_files_reports_all_classified,
        test_launch_and_evidence_sets_never_overlap_on_synthetic_fixture,
        test_real_repository_produces_disjoint_launch_and_evidence_sets,
        test_real_repository_operations_readme_is_launch_surface_via_root_link,
        test_real_repository_verified_markers_are_confirmed_not_just_claimed,
        test_real_repository_has_a_large_uncovered_ambiguous_backlog,
    ]
    for test in tests:
        try:
            test()
        except Exception:  # noqa: BLE001
            FAILURES.append(test.__name__)
            print(f"[FAIL] {test.__name__} -- raised unexpected exception")
            traceback.print_exc()
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} failing: {FAILURES}")
        return 1
    print(f"RESULT: all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
