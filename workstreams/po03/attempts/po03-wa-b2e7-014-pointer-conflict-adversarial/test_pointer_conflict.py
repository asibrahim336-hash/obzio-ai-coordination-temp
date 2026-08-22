#!/usr/bin/env python3
"""Adversarial tests for pointer-conflict/dangling detection (task po03-wa-b2e7-014).

Run with: python3 -I test_pointer_conflict.py
Standard library only. All conflicting/dangling fixtures used here are
synthetic files inside this unit's own subtree
(workstreams/po03/attempts/po03-wa-b2e7-014-pointer-conflict-adversarial/fixtures/);
none of them mutate a real repository pointer file.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pointer_conflict import (  # noqa: E402
    PointerConflictError,
    compare_fields,
    load_candidates,
    naive_current_candidates,
    resolve_authoritative,
    resolve_target_exists,
)

UNIT_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = UNIT_DIR / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[4]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_fixtures_are_synthetic_and_isolated() -> None:
    """Guard against accidentally pointing at real repository state: every
    fixture must live inside this unit's own subtree and must carry the
    `_fixture_note` marker."""
    fixture_files = sorted(FIXTURES_DIR.glob("*.json"))
    all_marked = all("_fixture_note" in json.loads(p.read_text(encoding="utf-8")) for p in fixture_files)
    check(
        "test_fixtures_are_synthetic_and_isolated",
        len(fixture_files) == 5 and all_marked,
        detail=str(fixture_files),
    )


def test_conflicting_fixtures_are_refused() -> None:
    candidates = load_candidates([FIXTURES_DIR / "conflict_a.json", FIXTURES_DIR / "conflict_b.json"])
    raised = False
    try:
        resolve_authoritative(candidates, "alias_id", "FIXTURE-CONFLICTING-CURRENT")
    except PointerConflictError as exc:
        raised = "conflict" in str(exc)
    check("test_conflicting_fixtures_are_refused", raised)


def test_dangling_fixture_is_refused() -> None:
    candidates = load_candidates([FIXTURES_DIR / "dangling.json"])
    winner = resolve_authoritative(candidates, "alias_id", "FIXTURE-DANGLING-CURRENT")
    raised = False
    try:
        resolve_target_exists(REPO_ROOT, winner, "selected_pointer.path")
    except PointerConflictError as exc:
        raised = "does not exist on disk" in str(exc)
    check("test_dangling_fixture_is_refused", raised)


def test_valid_fixture_resolves_successfully() -> None:
    candidates = load_candidates([FIXTURES_DIR / "valid_current.json"])
    winner = resolve_authoritative(candidates, "alias_id", "FIXTURE-VALID-CURRENT")
    target = resolve_target_exists(REPO_ROOT, winner, "selected_pointer.path")
    check(
        "test_valid_fixture_resolves_successfully",
        target == "workstreams/po03/attempts/po03-wa-b2e7-014-pointer-conflict-adversarial/fixtures/valid_target.json",
        detail=target,
    )


def test_absent_marker_is_refused_not_defaulted() -> None:
    candidates = load_candidates([FIXTURES_DIR / "valid_current.json"])
    raised = False
    try:
        resolve_authoritative(candidates, "alias_id", "SOME-MARKER-NOBODY-HAS")
    except PointerConflictError as exc:
        raised = "nothing to route to" in str(exc)
    check("test_absent_marker_is_refused_not_defaulted", raised)


def test_mixing_valid_and_conflicting_still_refuses_whole_pool() -> None:
    """A resolver that only checked one pairwise combination could miss a
    conflict hiding among a larger candidate pool; this proves the
    resolver scans the whole set."""
    candidates = load_candidates(
        [FIXTURES_DIR / "valid_current.json", FIXTURES_DIR / "conflict_a.json", FIXTURES_DIR / "conflict_b.json"]
    )
    raised = False
    try:
        resolve_authoritative(candidates, "alias_id", "FIXTURE-CONFLICTING-CURRENT")
    except PointerConflictError:
        raised = True
    check("test_mixing_valid_and_conflicting_still_refuses_whole_pool", raised)


def test_real_repository_naive_status_heuristic_finds_every_historical_version() -> None:
    """Genuine, real finding (not fabricated): every single
    state/ACTIVE_CONTROL_POINTER_*.json file, including six long-superseded
    historical versions, carries a `status` field containing the literal
    substring "CURRENT" (e.g. CURRENT_PACKAGE_READY_UNSENT,
    CURRENT_V009_SUCCESSOR_CONTROL_READBACK_VERIFIED_NOT_TRANSMITTED,
    CURRENT_ALIAS, ...). A naive resolver that trusted this field would
    treat all of them as simultaneously current -- exactly the failure
    mode this unit's hypothesis is about."""
    paths = sorted(REPO_ROOT.glob("state/ACTIVE_CONTROL_POINTER_*.json"))
    candidates = load_candidates(paths)
    naive_hits = naive_current_candidates(candidates, needle="CURRENT")
    check(
        "test_real_repository_naive_status_heuristic_finds_every_historical_version",
        len(naive_hits) == len(candidates) and len(candidates) >= 9,
        detail=f"{len(naive_hits)} of {len(candidates)} candidates: {[c['path'] for c in naive_hits]}",
    )
    print(f"    naive heuristic on real data: {len(naive_hits)}/{len(candidates)} files simultaneously claim 'CURRENT' in status")


def test_real_repository_authoritative_marker_narrows_to_exactly_one() -> None:
    """The safe resolution path (a specific alias_id value that only the
    live pointer alias file carries) correctly narrows the same real
    candidate pool down to exactly one winner, in contrast with the naive
    heuristic above."""
    paths = sorted(REPO_ROOT.glob("state/ACTIVE_CONTROL_POINTER_*.json"))
    candidates = load_candidates(paths)
    winner = resolve_authoritative(candidates, "alias_id", "OBZIO-ACTIVE-CONTROL-POINTER-CURRENT")
    check(
        "test_real_repository_authoritative_marker_narrows_to_exactly_one",
        winner["path"].endswith("state/ACTIVE_CONTROL_POINTER_CURRENT.json"),
        detail=winner["path"],
    )


def test_real_repository_operator_system_pointer_and_stack_do_not_conflict() -> None:
    """Real-data control check: the five identity keys the live operator
    system pointer and the active instruction stack both carry must
    agree, replicating scripts/check_operator_taxonomy.py's own
    pointer/stack mismatch check as an independent measurement."""
    pointer_doc = json.loads(
        (REPO_ROOT / "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json").read_text(encoding="utf-8")
    )
    stack_doc = json.loads((REPO_ROOT / "state/operator-system/ACTIVE_INSTRUCTION_STACK.json").read_text(encoding="utf-8"))
    fields = ["function_id", "appointment_id", "commission_id", "authority_envelope_id", "runtime_binding_id"]
    raised = False
    try:
        compare_fields(pointer_doc, stack_doc, fields, "ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", "ACTIVE_INSTRUCTION_STACK.json")
    except PointerConflictError:
        raised = True
    check(
        "test_real_repository_operator_system_pointer_and_stack_do_not_conflict",
        raised is False,
    )


def test_compare_fields_detects_synthetic_mismatch() -> None:
    """Proves compare_fields is not a stub that always passes."""
    doc_a = {"function_id": "a", "appointment_id": "x"}
    doc_b = {"function_id": "a", "appointment_id": "y"}
    raised = False
    try:
        compare_fields(doc_a, doc_b, ["function_id", "appointment_id"], "A", "B")
    except PointerConflictError as exc:
        raised = "appointment_id" in str(exc)
    check("test_compare_fields_detects_synthetic_mismatch", raised)


def run_all() -> int:
    tests = [
        test_fixtures_are_synthetic_and_isolated,
        test_conflicting_fixtures_are_refused,
        test_dangling_fixture_is_refused,
        test_valid_fixture_resolves_successfully,
        test_absent_marker_is_refused_not_defaulted,
        test_mixing_valid_and_conflicting_still_refuses_whole_pool,
        test_real_repository_naive_status_heuristic_finds_every_historical_version,
        test_real_repository_authoritative_marker_narrows_to_exactly_one,
        test_real_repository_operator_system_pointer_and_stack_do_not_conflict,
        test_compare_fields_detects_synthetic_mismatch,
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
