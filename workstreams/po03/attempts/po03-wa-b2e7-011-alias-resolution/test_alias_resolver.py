#!/usr/bin/env python3
"""Tests for the alias resolver (task po03-wa-b2e7-011).

Run with: python3 -I test_alias_resolver.py
Standard library only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alias_resolver import (  # noqa: E402
    AliasRegisterError,
    build_report,
    is_allowed_field,
    load_alias_register,
    resolve_alias,
    scan_repository,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS_MD_ALIASES = [
    "Operator D",
    "Claude extension",
    "Claude browser operator",
    "principal AI operator",
]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_is_allowed_field_accepts_alias_runtime_provenance() -> None:
    check(
        "test_is_allowed_field_accepts_alias_runtime_provenance",
        is_allowed_field("alias") and is_allowed_field("runtime_binding_id") and is_allowed_field("execution_record.recorded_by"),
    )


def test_is_allowed_field_rejects_routing_field_names() -> None:
    check(
        "test_is_allowed_field_rejects_routing_field_names",
        not is_allowed_field("owner") and not is_allowed_field("route_owner") and not is_allowed_field("destination"),
    )


def test_load_real_alias_register_contains_agents_md_aliases() -> None:
    register = load_alias_register(REPO_ROOT)
    aliases_seen = {row.get("alias") for row in register}
    missing = [a for a in AGENTS_MD_ALIASES if a not in aliases_seen]
    check(
        "test_load_real_alias_register_contains_agents_md_aliases",
        missing == [],
        detail=f"missing from register: {missing}",
    )


def test_resolve_alias_returns_none_for_unknown_alias() -> None:
    register = load_alias_register(REPO_ROOT)
    result = resolve_alias(register, "Totally Fictitious Operator Name XYZ")
    check("test_resolve_alias_returns_none_for_unknown_alias", result is None)


def test_resolve_alias_finds_known_alias_case_insensitively() -> None:
    register = load_alias_register(REPO_ROOT)
    result = resolve_alias(register, "operator d")
    check(
        "test_resolve_alias_finds_known_alias_case_insensitively",
        result is not None and result.get("target_type") == "appointment",
        detail=str(result),
    )


def test_fails_closed_when_register_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raised = False
        try:
            load_alias_register(Path(tmp))
        except AliasRegisterError as exc:
            raised = "missing" in str(exc)
        check("test_fails_closed_when_register_missing", raised)


def test_scan_repository_flags_occurrence_outside_allowed_field() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sample.json").write_text(
            json.dumps({"owner": "Operator D", "alias_note": "Operator D is historical"}),
            encoding="utf-8",
        )
        occurrences = scan_repository(root, ["Operator D"])
        flagged = [o for o in occurrences if not o["field_allowed"]]
        allowed = [o for o in occurrences if o["field_allowed"]]
        check(
            "test_scan_repository_flags_occurrence_outside_allowed_field",
            len(flagged) == 1 and flagged[0]["field_path"] == "owner" and len(allowed) == 1,
            detail=str(occurrences),
        )


def test_build_report_reports_unresolved_alias_as_evidence_not_invention() -> None:
    """This is the core falsification test: an alias with no register entry
    must be reported as unresolved, never silently mapped to a guessed
    function/appointment id."""
    report = build_report(REPO_ROOT, AGENTS_MD_ALIASES + ["Totally Fictitious Operator Name XYZ"])
    check(
        "test_build_report_reports_unresolved_alias_as_evidence_not_invention",
        report["unresolved"] == ["Totally Fictitious Operator Name XYZ"],
        detail=str(report["unresolved"]),
    )


def test_build_report_never_mutates_scanned_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "state" / "operator-system").mkdir(parents=True)
        register_path = root / "state" / "operator-system" / "OPERATOR_ALIAS_REGISTER.jsonl"
        register_path.write_text(json.dumps({"alias": "Operator D", "target_type": "appointment", "target_id": "x"}) + "\n", encoding="utf-8")
        sample = root / "sample.json"
        original_bytes = json.dumps({"owner": "Operator D"}).encode("utf-8")
        sample.write_bytes(original_bytes)
        before_mtime = sample.stat().st_mtime_ns
        build_report(root, ["Operator D"])
        check(
            "test_build_report_never_mutates_scanned_files",
            sample.read_bytes() == original_bytes and sample.stat().st_mtime_ns == before_mtime,
        )


def test_real_repository_agents_md_aliases_all_resolve() -> None:
    """Real-repo evidence: every alias AGENTS.md names by example resolves
    to a durable target via the committed register -- none are unresolved."""
    report = build_report(REPO_ROOT, AGENTS_MD_ALIASES)
    check(
        "test_real_repository_agents_md_aliases_all_resolve",
        report["unresolved"] == [],
        detail=str(report["unresolved"]),
    )
    for alias in AGENTS_MD_ALIASES:
        print(f"    {alias!r} -> {report['resolved'][alias]}")


def test_real_repository_finds_flagged_occurrences_outside_allowed_fields() -> None:
    """Real-repo finding, not fabricated: most literal occurrences of these
    four aliases in committed JSON/JSONL data sit in routing-shaped field
    names (owner, route_owner, destination, function, ...), not in
    alias/runtime/provenance fields. The resolver reports this without
    rewriting a single byte of the underlying evidence files."""
    report = build_report(REPO_ROOT, AGENTS_MD_ALIASES)
    check(
        "test_real_repository_finds_flagged_occurrences_outside_allowed_fields",
        len(report["flagged_field_occurrences"]) > 0 and report["mutated_files"] == [],
        detail=f"flagged={len(report['flagged_field_occurrences'])}",
    )
    print(
        f"    occurrence_count={report['occurrence_count']} "
        f"allowed={len(report['allowed_field_occurrences'])} "
        f"flagged={len(report['flagged_field_occurrences'])}"
    )


def run_all() -> int:
    tests = [
        test_is_allowed_field_accepts_alias_runtime_provenance,
        test_is_allowed_field_rejects_routing_field_names,
        test_load_real_alias_register_contains_agents_md_aliases,
        test_resolve_alias_returns_none_for_unknown_alias,
        test_resolve_alias_finds_known_alias_case_insensitively,
        test_fails_closed_when_register_missing,
        test_scan_repository_flags_occurrence_outside_allowed_field,
        test_build_report_reports_unresolved_alias_as_evidence_not_invention,
        test_build_report_never_mutates_scanned_files,
        test_real_repository_agents_md_aliases_all_resolve,
        test_real_repository_finds_flagged_occurrences_outside_allowed_fields,
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
