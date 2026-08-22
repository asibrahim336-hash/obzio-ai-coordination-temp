#!/usr/bin/env python3
"""A pinned state-contract schema plus validator for the operator-system
vocabulary that PO-03 reads as a domain input (state/operator-system/**).

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-016-semantic-state-contract):
    The operator state vocabulary can be expressed as an enforceable
    contract so undefined states cannot enter committed state files.

Scope and grounding
--------------------
"The operator-system vocabulary" is scoped here, precisely, to the eight
record kinds actually committed under state/operator-system/ (the directory
literally named "operator-system" in this repository, and the exact domain
input named in this cohort's pointer chain): the singleton
ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json and ACTIVE_INSTRUCTION_STACK.json
documents, plus the six *_REGISTER.jsonl line-record registers (authority
envelope, commission, function, appointment, runtime binding, alias).

This module does NOT invent a vocabulary. CONTRACT below is a pinned
snapshot: for each kind, `required_fields` is the exact intersection of keys
across every record of that kind actually committed in this repository, and
`allowed_status_values` is the exact set of `status` values actually used by
those same committed records. `derive_kind_schema` / `derive_full_contract`
re-derive this same information live from the repository, and
test_state_contract.py asserts the pinned CONTRACT below matches that live
derivation exactly, so the contract is provably grounded, not guessed.

Once pinned, the contract is enforced going forward: `validate_record`
rejects (with a precise, named error) any record whose `status` is outside
`allowed_status_values`, or that is missing any `required_fields` entry, or
whose `kind` is not one of the eight defined here. Additional, unrecognised
fields on a record are NOT rejected (closed-world-only on `required_fields`
and `status`, not on the field set as a whole), matching this repository's
own stated "additive; must not narrow" migration doctrine
(operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md) rather than
inventing a stricter closed-schema rule this repository does not itself
assert.

This module only reads repository files for grounding tests; it never
writes, deletes or mutates any file outside its own directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# kind -> (source file relative to repo root, "json" | "jsonl")
SOURCE_FILES: dict[str, tuple[str, str]] = {
    "operator_system_pointer": ("state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", "json"),
    "instruction_stack": ("state/operator-system/ACTIVE_INSTRUCTION_STACK.json", "json"),
    "authority_envelope": ("state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl", "jsonl"),
    "commission": ("state/operator-system/COMMISSION_REGISTER.jsonl", "jsonl"),
    "function": ("state/operator-system/FUNCTION_REGISTER.jsonl", "jsonl"),
    "appointment": ("state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl", "jsonl"),
    "runtime_binding": ("state/operator-system/RUNTIME_BINDING_REGISTER.jsonl", "jsonl"),
    "alias": ("state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl", "jsonl"),
}

# Pinned snapshot at commit range po03-wa-b2e7-009..016 (pinned base 5ef49cb
# plus this cohort's own additive unit commits, none of which touch
# state/operator-system/). See module docstring and
# test_state_contract.py::TestContractMatchesRepoSnapshot for the live
# re-derivation that grounds every field and value below.
CONTRACT: dict[str, dict[str, Any]] = {
    "operator_system_pointer": {
        "required_fields": sorted([
            "schema_version", "status", "recorded_at", "strategy_snapshot_id",
            "function_id", "appointment_id", "commission_id",
            "authority_envelope_id", "runtime_binding_id", "instruction_stack",
            "function_instruction", "repository_entrypoint", "execution_state",
            "identity_verification_state", "migration_effect",
        ]),
        "status_field": "status",
        "allowed_status_values": ["CURRENT"],
    },
    "instruction_stack": {
        "required_fields": sorted([
            "status", "strategy_snapshot_id", "function_id", "appointment_id",
            "commission_id", "authority_envelope_id", "runtime_binding_id",
            "resolve_in_order", "immutable_execution_evidence",
            "supersession_rule", "continuation_rule",
        ]),
        "status_field": "status",
        "allowed_status_values": ["CURRENT"],
    },
    "authority_envelope": {
        "required_fields": sorted([
            "authority_envelope_id", "function_id", "appointment_id", "status",
            "authority_basis", "delegated_actions", "default_internal_rule",
            "boundaries", "authority_parity",
        ]),
        "status_field": "status",
        "allowed_status_values": ["ACTIVE"],
    },
    "commission": {
        "required_fields": sorted([
            "commission_id", "display_name", "status", "function_id",
            "appointment_id", "authority_envelope_id", "strategy_snapshot_id",
            "immutable_launch_payload", "immutable_launch_command",
            "additive_corrections", "scoped_supersession", "launch_effect",
        ]),
        "status_field": "status",
        "allowed_status_values": ["ACTIVE_AND_CONTINUING"],
    },
    "function": {
        "required_fields": sorted([
            "function_id", "display_name", "status", "mandate", "exclusions",
        ]),
        "status_field": "status",
        "allowed_status_values": ["ACTIVE"],
    },
    "appointment": {
        "required_fields": sorted([
            "appointment_id", "function_id", "display_name", "principal",
            "status", "effective_from", "active_commission_refs",
            "runtime_binding_refs",
        ]),
        "status_field": "status",
        "allowed_status_values": ["ACTIVE", "SUPERSEDED_FOR_ACTIVE_ROUTING"],
    },
    "runtime_binding": {
        "required_fields": sorted([
            "runtime_binding_id", "appointment_id", "status", "provider",
            "product", "interface", "device", "mission_surfaces",
            "capability_rule", "observed_at", "authority_effect",
        ]),
        "status_field": "status",
        "allowed_status_values": ["ACTIVE_OBSERVED_AND_REPLACEABLE"],
    },
    "alias": {
        "required_fields": sorted([
            "alias", "target_type", "target_id", "status", "replacement",
        ]),
        "status_field": "status",
        "allowed_status_values": sorted([
            "HISTORICAL_PROHIBITED_FOR_ROUTING",
            "HISTORICAL_ACCEPTED_ALIAS",
            "COLLOQUIAL_RUNTIME_ONLY",
            "DEPRECATED_COMPOSITE_PROHIBITED_FOR_ROUTING",
            "ACTIVE_MISSION_ALIAS_NOT_FUNCTION",
            "DEPRECATED_CONTEXT_REQUIRED",
            "HISTORICAL_SURFACE_ALIAS_NOT_FUNCTION",
            "CONTEXT_REQUIRED_NOT_FUNCTION",
        ]),
    },
}


class StateContractError(Exception):
    """Raised when a required structured source cannot be read (fail-closed)."""


def load_records(repo_root: Path, kind: str) -> list[dict[str, Any]]:
    if kind not in SOURCE_FILES:
        raise StateContractError(f"unknown kind: {kind}")
    rel_path, fmt = SOURCE_FILES[kind]
    file_path = Path(repo_root) / rel_path
    if not file_path.is_file():
        raise StateContractError(f"source file missing for kind {kind}: {rel_path}")
    text = file_path.read_text(encoding="utf-8")
    if fmt == "json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise StateContractError(f"{rel_path}: root must be a JSON object")
        return [data]
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise StateContractError(f"{rel_path}: every jsonl line must be a JSON object")
        records.append(record)
    return records


def derive_kind_schema(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-derive required_fields (key intersection) and allowed_status_values
    (observed status set) straight from a list of real records, independent
    of the pinned CONTRACT above."""
    if not records:
        return {"required_fields": [], "status_field": "status", "allowed_status_values": []}
    key_sets = [set(r.keys()) for r in records]
    required = sorted(set.intersection(*key_sets))
    statuses = sorted({r["status"] for r in records if "status" in r and isinstance(r["status"], str)})
    return {
        "required_fields": required,
        "status_field": "status",
        "allowed_status_values": statuses,
    }


def derive_full_contract(repo_root: Path) -> dict[str, dict[str, Any]]:
    return {kind: derive_kind_schema(load_records(repo_root, kind)) for kind in SOURCE_FILES}


def validate_record(kind: str, record: dict[str, Any], contract: dict[str, dict[str, Any]] = CONTRACT) -> list[str]:
    """Return a list of precise error strings; empty list means valid.
    Never raises for a merely-invalid record (only StateContractError for a
    structurally malformed call, e.g. an unknown kind or non-dict record)."""
    if kind not in contract:
        raise StateContractError(f"unknown kind: {kind}")
    if not isinstance(record, dict):
        raise StateContractError("record must be a JSON object")

    schema = contract[kind]
    errors: list[str] = []
    for field in schema["required_fields"]:
        if field not in record:
            errors.append(f"{kind}: missing required field '{field}'")

    status_field = schema.get("status_field")
    if status_field and status_field in record:
        value = record[status_field]
        allowed = schema["allowed_status_values"]
        if value not in allowed:
            errors.append(
                f"{kind}: undefined state '{value}' for field '{status_field}' "
                f"(allowed: {sorted(allowed)})"
            )
    return errors


def validate_repo(repo_root: Path, contract: dict[str, dict[str, Any]] = CONTRACT) -> dict[str, Any]:
    repo_root = Path(repo_root)
    report: dict[str, Any] = {"kinds": {}, "total_records": 0, "total_errors": 0}
    for kind in SOURCE_FILES:
        records = load_records(repo_root, kind)
        kind_errors: list[str] = []
        for record in records:
            kind_errors.extend(validate_record(kind, record, contract))
        report["kinds"][kind] = {
            "record_count": len(records),
            "errors": kind_errors,
            "valid": not kind_errors,
        }
        report["total_records"] += len(records)
        report["total_errors"] += len(kind_errors)
    report["all_valid"] = report["total_errors"] == 0
    report["status"] = "ALL_VALID" if report["all_valid"] else "CONTRACT_VIOLATIONS_PRESENT"
    return report


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    args = parser.parse_args(argv)

    try:
        report = validate_repo(Path(args.repo_root))
    except StateContractError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
