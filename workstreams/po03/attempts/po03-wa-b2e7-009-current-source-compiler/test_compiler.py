#!/usr/bin/env python3
"""Tests for the current-source compiler (task po03-wa-b2e7-009).

Run with: python3 -I test_compiler.py
Standard library only; no third-party test runner is used so this is
runnable in a clean python -I environment without pytest installed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compiler import (  # noqa: E402
    CurrentSourceCompilationError,
    compile_current_source,
    extract_readme_order,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_extract_readme_order_parses_numbered_backtick_list() -> None:
    sample = (
        "# Title\n\n"
        "## Read in this order\n\n"
        "1. `a/b.json` — desc\n"
        "2. `c/d.md` — desc\n\n"
        "## Another section\n\n"
        "1. `should/not/appear.md`\n"
    )
    order = extract_readme_order(sample)
    check(
        "test_extract_readme_order_parses_numbered_backtick_list",
        order == ["a/b.json", "c/d.md"],
        detail=f"got {order!r}",
    )


def test_extract_readme_order_empty_when_section_absent() -> None:
    sample = "# Title\n\n## Some other section\n\n1. `x.md`\n"
    order = extract_readme_order(sample)
    check(
        "test_extract_readme_order_empty_when_section_absent",
        order == [],
        detail=f"got {order!r}",
    )


def test_compiles_real_repository_pointer_chain() -> None:
    """Against the actual repository head, both named sources must exist,
    be parsable, and every path either names must resolve on disk. This
    proves the mechanism runs against real, not fabricated, pointers."""
    try:
        report = compile_current_source(REPO_ROOT)
    except CurrentSourceCompilationError as exc:
        check("test_compiles_real_repository_pointer_chain", False, detail=f"unexpected fail-closed: {exc}")
        return
    check(
        "test_compiles_real_repository_pointer_chain",
        report["all_named_paths_resolved"] is True and len(report["current_source_set"]) >= len(report["readme_order"]),
        detail=json.dumps(report, indent=2),
    )
    print("    real repo compiler report:")
    print("    " + json.dumps(report, sort_keys=True))


def test_real_repository_readme_and_stack_currently_disagree() -> None:
    """This is a recorded, falsifiable finding about the actual repository
    state at HEAD, not an invented value: operations/README.md's 'Read in
    this order' list and ACTIVE_INSTRUCTION_STACK.json's resolve_in_order
    list do not currently have identical membership or order. If a future
    repair reconciles them, this test will start failing and must be
    revisited rather than silently loosened."""
    report = compile_current_source(REPO_ROOT)
    disagreement_detected = (not report["order_agrees"]) or (not report["membership_agrees"])
    check(
        "test_real_repository_readme_and_stack_currently_disagree",
        disagreement_detected,
        detail=(
            f"order_agrees={report['order_agrees']} membership_agrees={report['membership_agrees']} "
            f"only_in_readme={report['only_in_readme']} only_in_stack={report['only_in_stack']}"
        ),
    )
    print("    only_in_readme:", report["only_in_readme"])
    print("    only_in_stack:", report["only_in_stack"])


def test_fails_closed_when_readme_names_missing_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "operations").mkdir(parents=True)
        (root / "state" / "operator-system").mkdir(parents=True)
        (root / "operations" / "README.md").write_text(
            "## Read in this order\n\n1. `state/does/not/exist.json`\n",
            encoding="utf-8",
        )
        (root / "state" / "operator-system" / "ACTIVE_INSTRUCTION_STACK.json").write_text(
            json.dumps({"resolve_in_order": ["state/does/not/exist.json"]}),
            encoding="utf-8",
        )
        raised = False
        try:
            compile_current_source(root)
        except CurrentSourceCompilationError as exc:
            raised = "missing or unreadable" in str(exc)
        check("test_fails_closed_when_readme_names_missing_path", raised)


def test_fails_closed_when_stack_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "operations").mkdir(parents=True)
        (root / "operations" / "README.md").write_text(
            "## Read in this order\n\n1. `operations/README.md`\n",
            encoding="utf-8",
        )
        raised = False
        try:
            compile_current_source(root)
        except CurrentSourceCompilationError as exc:
            raised = "instruction stack missing" in str(exc)
        check("test_fails_closed_when_stack_missing", raised)


def test_fails_closed_when_stack_json_invalid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "operations").mkdir(parents=True)
        (root / "state" / "operator-system").mkdir(parents=True)
        (root / "operations" / "README.md").write_text(
            "## Read in this order\n\n1. `operations/README.md`\n",
            encoding="utf-8",
        )
        (root / "state" / "operator-system" / "ACTIVE_INSTRUCTION_STACK.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        raised = False
        try:
            compile_current_source(root)
        except CurrentSourceCompilationError as exc:
            raised = "unreadable/invalid" in str(exc)
        check("test_fails_closed_when_stack_json_invalid", raised)


def test_succeeds_on_minimal_agreeing_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "operations").mkdir(parents=True)
        (root / "state" / "operator-system").mkdir(parents=True)
        (root / "operations" / "README.md").write_text(
            "## Read in this order\n\n1. `operations/README.md`\n2. `state/operator-system/ACTIVE_INSTRUCTION_STACK.json`\n",
            encoding="utf-8",
        )
        (root / "state" / "operator-system" / "ACTIVE_INSTRUCTION_STACK.json").write_text(
            json.dumps(
                {
                    "resolve_in_order": [
                        "operations/README.md",
                        "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
                    ]
                }
            ),
            encoding="utf-8",
        )
        report = compile_current_source(root)
        check(
            "test_succeeds_on_minimal_agreeing_fixture",
            report["order_agrees"] is True and report["membership_agrees"] is True,
            detail=json.dumps(report),
        )


def run_all() -> int:
    tests = [
        test_extract_readme_order_parses_numbered_backtick_list,
        test_extract_readme_order_empty_when_section_absent,
        test_compiles_real_repository_pointer_chain,
        test_real_repository_readme_and_stack_currently_disagree,
        test_fails_closed_when_readme_names_missing_path,
        test_fails_closed_when_stack_missing,
        test_fails_closed_when_stack_json_invalid,
        test_succeeds_on_minimal_agreeing_fixture,
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
