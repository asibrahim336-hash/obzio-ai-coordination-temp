#!/usr/bin/env python3
"""Complement the operator taxonomy gate with transitive and state-contract checks."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT_PATH = "operations/README.md"
CONTROL_POINTER_PATH = "state/ACTIVE_CONTROL_POINTER_CURRENT.json"
OPERATOR_POINTER_PATH = "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json"
STACK_PATH = "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"
FUNCTIONS_PATH = "state/operator-system/FUNCTION_REGISTER.jsonl"
APPOINTMENTS_PATH = "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl"
COMMISSIONS_PATH = "state/operator-system/COMMISSION_REGISTER.jsonl"
ENVELOPES_PATH = "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl"
RUNTIMES_PATH = "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl"
ALIASES_PATH = "state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl"
PO03_COMMISSION_PATH = "workstreams/po03/COMMISSION.md"
LEDGER_PATH = "workstreams/po03/control/events/ledger.jsonl"
RESULT_SCHEMA_PATH = "workstreams/po03/contracts/transactional-result.schema.json"
RESULT_VALIDATOR_PATH = "workstreams/po03/tools/validate_contracts.py"
BASE_RESULT_PATH = "workstreams/po03/control/units/a9/a9-u01.json"
TAXONOMY_CHECK_PATH = "scripts/check_operator_taxonomy.py"


class DuplicateKeyError(ValueError):
    """Raised when JSON would otherwise silently take the last duplicate key."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_json_text(text: str, source: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateKeyError(f"{source}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def load_json(root: Path, relative: str) -> dict[str, Any]:
    value = parse_json_text((root / relative).read_text(encoding="utf-8"), relative)
    if not isinstance(value, dict):
        raise ValueError(f"{relative}: root must be an object")
    return value


def load_jsonl(root: Path, relative: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate((root / relative).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = parse_json_text(line, f"{relative}:{number}")
        if not isinstance(value, dict):
            raise ValueError(f"{relative}:{number}: row must be an object")
        rows.append(value)
    return rows


def index_unique(
    rows: list[dict[str, Any]], key: str, source: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    table: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for number, row in enumerate(rows, 1):
        identity = row.get(key)
        if not isinstance(identity, str) or not identity:
            errors.append(f"{source}:{number}: missing {key}")
            continue
        if identity in table:
            errors.append(f"{source}:{number}: duplicate {key} {identity}")
            continue
        table[identity] = row
    return table, errors


def parse_entrypoint_order(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        if re.match(r"^\d+\.\s+", line):
            match = re.search(r"`([^`]+)`", line)
            if match:
                paths.append(match.group(1))
    return paths


def parse_po03_header(text: str) -> dict[str, Any]:
    match = re.search(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError(f"{PO03_COMMISSION_PATH}: missing opening YAML block")
    values: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        field = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not field:
            continue
        key, raw = field.groups()
        raw = raw.strip()
        if raw == "[]":
            value: Any = []
        elif raw.lower() in {"true", "false"}:
            value = raw.lower() == "true"
        elif raw.startswith('"') and raw.endswith('"'):
            value = json.loads(raw)
        else:
            value = raw
        values[key] = value
    return values


def extract_literal_assignment(source: str, name: str) -> Any:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise ValueError(f"Python assignment {name} not found")


def proposal(
    proposal_id: str,
    text: str,
    *,
    founder_interlock: str = "NOT_INVOKED",
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "proposal": text,
        "binding_state": "PROPOSAL_ONLY",
        "applied": False,
        "founder_interlock": founder_interlock,
        "decision_changed": [],
    }


def finding(
    finding_id: str,
    category: str,
    statement: str,
    evidence: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "severity": "AMBIGUITY",
        "category": category,
        "statement": statement,
        "evidence": evidence,
        "resolution": resolution,
        "decision_changed": [],
    }


def run_taxonomy_check(root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, TAXONOMY_CHECK_PATH],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return {
        "command": f"{sys.executable} {TAXONOMY_CHECK_PATH}",
        "exit_code": completed.returncode,
        "stdout": completed.stdout.rstrip(),
        "stderr": completed.stderr.rstrip(),
    }


def run_validator_probe(
    root: Path,
    name: str,
    base: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    probe = json.loads(json.dumps(base))
    mutate(probe)
    relative = f"workstreams/po03/strategy/.semantic-probe-{name}.json"
    target = root / relative
    target.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                RESULT_VALIDATOR_PATH,
                "result",
                relative,
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
    finally:
        target.unlink(missing_ok=True)
    return {
        "probe_id": name,
        "validator_exit_code": completed.returncode,
        "validator_output": (completed.stdout + completed.stderr).strip(),
        "accepted": completed.returncode == 0,
    }


def _chain_checks(
    pointer: dict[str, Any],
    stack: dict[str, Any],
    functions: dict[str, dict[str, Any]],
    appointments: dict[str, dict[str, Any]],
    commissions: dict[str, dict[str, Any]],
    envelopes: dict[str, dict[str, Any]],
    runtimes: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    identity_fields = (
        "function_id",
        "appointment_id",
        "commission_id",
        "authority_envelope_id",
        "runtime_binding_id",
    )
    for field in identity_fields:
        if pointer.get(field) != stack.get(field):
            errors.append(f"pointer and stack disagree on {field}")
    function_id = pointer.get("function_id")
    appointment_id = pointer.get("appointment_id")
    commission_id = pointer.get("commission_id")
    envelope_id = pointer.get("authority_envelope_id")
    runtime_id = pointer.get("runtime_binding_id")
    function = functions.get(function_id, {})
    appointment = appointments.get(appointment_id, {})
    commission = commissions.get(commission_id, {})
    envelope = envelopes.get(envelope_id, {})
    runtime = runtimes.get(runtime_id, {})
    if not function:
        errors.append(f"function target does not resolve: {function_id}")
    if not appointment:
        errors.append(f"appointment target does not resolve: {appointment_id}")
    if not commission:
        errors.append(f"commission target does not resolve: {commission_id}")
    if not envelope:
        errors.append(f"authority envelope target does not resolve: {envelope_id}")
    if not runtime:
        errors.append(f"runtime target does not resolve: {runtime_id}")
    if appointment:
        if appointment.get("function_id") != function_id:
            errors.append("appointment does not belong to pointer function")
        if appointment.get("authority_envelope_ref") != envelope_id:
            errors.append("appointment authority reference differs from pointer")
        if commission_id not in appointment.get("active_commission_refs", []):
            errors.append("pointer commission absent from appointment active commissions")
        if runtime_id not in appointment.get("runtime_binding_refs", []):
            errors.append("pointer runtime absent from appointment runtime bindings")
    if commission:
        for field, expected in (
            ("function_id", function_id),
            ("appointment_id", appointment_id),
            ("authority_envelope_id", envelope_id),
        ):
            if commission.get(field) != expected:
                errors.append(f"commission {field} differs from pointer")
    if envelope:
        if envelope.get("function_id") != function_id:
            errors.append("authority envelope does not belong to pointer function")
        if envelope.get("appointment_id") != appointment_id:
            errors.append("authority envelope does not belong to pointer appointment")
    if runtime:
        if runtime.get("appointment_id") != appointment_id:
            errors.append("runtime does not belong to pointer appointment")
        if runtime.get("authority_effect") != "NONE":
            errors.append("runtime binding has a non-NONE authority effect")
    return errors


def build_report(root: Path = REPO_ROOT) -> dict[str, Any]:
    pointer = load_json(root, OPERATOR_POINTER_PATH)
    control_pointer = load_json(root, CONTROL_POINTER_PATH)
    stack = load_json(root, STACK_PATH)
    function_rows = load_jsonl(root, FUNCTIONS_PATH)
    appointment_rows = load_jsonl(root, APPOINTMENTS_PATH)
    commission_rows = load_jsonl(root, COMMISSIONS_PATH)
    envelope_rows = load_jsonl(root, ENVELOPES_PATH)
    runtime_rows = load_jsonl(root, RUNTIMES_PATH)
    alias_rows = load_jsonl(root, ALIASES_PATH)
    ledger_rows = load_jsonl(root, LEDGER_PATH)
    functions, function_index_errors = index_unique(
        function_rows, "function_id", FUNCTIONS_PATH
    )
    appointments, appointment_index_errors = index_unique(
        appointment_rows, "appointment_id", APPOINTMENTS_PATH
    )
    commissions, commission_index_errors = index_unique(
        commission_rows, "commission_id", COMMISSIONS_PATH
    )
    envelopes, envelope_index_errors = index_unique(
        envelope_rows, "authority_envelope_id", ENVELOPES_PATH
    )
    runtimes, runtime_index_errors = index_unique(
        runtime_rows, "runtime_binding_id", RUNTIMES_PATH
    )
    index_errors = (
        function_index_errors
        + appointment_index_errors
        + commission_index_errors
        + envelope_index_errors
        + runtime_index_errors
    )
    chain_errors = index_errors + _chain_checks(
        pointer,
        stack,
        functions,
        appointments,
        commissions,
        envelopes,
        runtimes,
    )

    findings: list[dict[str, Any]] = []
    if chain_errors:
        findings.append(
            finding(
                "CURRENT-CHAIN-TRANSITIVE-MISMATCH",
                "operator-taxonomy",
                "The selected current pointer does not resolve one internally consistent transitive actor chain.",
                {"errors": chain_errors},
                proposal(
                    "P-SEMANTIC-CHAIN-01",
                    "Repair the inconsistent register relationship without changing the selected authority or execution.",
                    founder_interlock="REQUIRED_IF_AUTHORITY_OR_STRATEGY_WOULD_CHANGE",
                ),
            )
        )

    po03 = parse_po03_header((root / PO03_COMMISSION_PATH).read_text(encoding="utf-8"))
    po03_function = po03.get("institutional_function")
    po03_appointment = po03.get("appointment")
    po03_commission = po03.get("commission_id")
    missing_route_components = []
    if po03_function not in functions:
        missing_route_components.append(f"function:{po03_function}")
    if po03_appointment not in appointments:
        missing_route_components.append(f"appointment:{po03_appointment}")
    if po03_commission not in commissions:
        missing_route_components.append(f"commission:{po03_commission}")
    if not po03.get("authority_envelope_id"):
        missing_route_components.append("authority_envelope_id:ABSENT")
    if not po03.get("runtime_binding_id"):
        missing_route_components.append("runtime_binding_id:ABSENT")
    if stack.get("commission_id") != po03_commission:
        missing_route_components.append(
            f"active_stack_parent_link:{stack.get('commission_id')}->PO03:ABSENT"
        )
    if missing_route_components:
        findings.append(
            finding(
                "PO03-ACTIVE-COMMISSION-ROUTE-INCOMPLETE",
                "operator-taxonomy",
                "The executing PO-03 commission cannot machine-resolve its function, appointment, authority envelope, runtime binding and parent/return route through the current instruction stack.",
                {
                    "po03_commission_path": PO03_COMMISSION_PATH,
                    "missing_or_unlinked": missing_route_components,
                    "current_stack_commission_id": stack.get("commission_id"),
                },
                proposal(
                    "P-SEMANTIC-PO03-ROUTE-01",
                    "Add an explicit subordinate-commission relationship and registered bindings that preserve the current envelope; do not infer new authority from Cursor or this report.",
                    founder_interlock="REQUIRED_IF_RESOLUTION_CHANGES_AUTHORITY_OR_STRATEGY",
                ),
            )
        )

    active_events = [
        row for row in ledger_rows if row.get("event") in {"LEASED", "RUNNING", "CHECKPOINTED"}
    ]
    if active_events and po03.get("lifecycle") == "COMMISSIONED_NOT_YET_EXECUTING":
        findings.append(
            finding(
                "PO03-LIFECYCLE-CONTRADICTS-LEDGER",
                "state-contract",
                "The commission header says NOT_YET_EXECUTING while the committed control ledger records execution leases.",
                {
                    "commission_lifecycle": po03.get("lifecycle"),
                    "active_ledger_event_count": len(active_events),
                    "first_active_event": {
                        key: active_events[0].get(key)
                        for key in ("seq", "unit_id", "event", "ts")
                    },
                },
                proposal(
                    "P-SEMANTIC-LIFECYCLE-01",
                    "Make one append-only execution projection authoritative and mark the commission header as a stale snapshot without rewriting historical evidence.",
                ),
            )
        )

    if not stack.get("return_route") or not stack.get("evaluation_route"):
        findings.append(
            finding(
                "ACTIVE-STACK-RETURN-EVALUATION-ROUTE-IMPLICIT",
                "operator-taxonomy",
                "The active instruction stack selects identity and source paths but has no explicit machine-readable return_route or evaluation_route fields.",
                {
                    "stack_path": STACK_PATH,
                    "return_route": stack.get("return_route"),
                    "evaluation_route": stack.get("evaluation_route"),
                    "resolve_in_order_count": len(stack.get("resolve_in_order", [])),
                },
                proposal(
                    "P-SEMANTIC-RETURN-ROUTE-01",
                    "Add explicit return and independent-evaluation locators to the stack while preserving current separation of duties.",
                ),
            )
        )

    alias_tables = {
        "function": functions,
        "appointment": appointments,
        "commission_title": commissions,
        "runtime_class": runtimes,
        "composite": appointments,
    }
    unresolved_aliases = []
    for row in alias_rows:
        table = alias_tables.get(row.get("target_type"))
        if table is None:
            unresolved_aliases.append(
                {
                    "alias": row.get("alias"),
                    "target_type": row.get("target_type"),
                    "target_id": row.get("target_id"),
                    "reason": "no canonical target registry is named",
                }
            )
        elif row.get("target_id") not in table:
            unresolved_aliases.append(
                {
                    "alias": row.get("alias"),
                    "target_type": row.get("target_type"),
                    "target_id": row.get("target_id"),
                    "reason": "target absent from the mapped canonical register",
                }
            )
    if unresolved_aliases:
        findings.append(
            finding(
                "ALIAS-TARGET-NAMESPACE-NOT-MACHINE-RESOLVABLE",
                "operator-taxonomy",
                "Some classified aliases name target namespaces that the current operator system does not register, so a machine cannot validate their target identity.",
                {"aliases": unresolved_aliases},
                proposal(
                    "P-SEMANTIC-ALIAS-NAMESPACE-01",
                    "Register the external surface/environment namespaces or mark target_id as intentionally non-resolvable evidence-only.",
                ),
            )
        )

    schema = load_json(root, RESULT_SCHEMA_PATH)
    validator_source = (root / RESULT_VALIDATOR_PATH).read_text(encoding="utf-8")
    schema_states = set(schema["properties"]["obzio_state"]["enum"])
    validator_states = set(extract_literal_assignment(validator_source, "RESULT_STATES"))
    if schema_states != validator_states:
        findings.append(
            finding(
                "RESULT-STATE-ENUMS-DIVERGE",
                "state-contract",
                "The documented JSON Schema and dependency-free validator accept different Obzio states.",
                {
                    "schema_only": sorted(schema_states - validator_states),
                    "validator_only": sorted(validator_states - schema_states),
                },
                proposal(
                    "P-SEMANTIC-STATE-ENUM-01",
                    "Align the executable and documented state sets without admitting any stronger producer state.",
                ),
            )
        )

    base_result = load_json(root, BASE_RESULT_PATH)
    probes = [
        run_validator_probe(
            root,
            "top-level-extension",
            base_result,
            lambda doc: doc.__setitem__("unexpected_semantic_field", True),
        ),
        run_validator_probe(
            root,
            "provider-state",
            base_result,
            lambda doc: doc.__setitem__("provider_state", "SEMANTICALLY_UNKNOWN"),
        ),
        run_validator_probe(
            root,
            "transaction-state",
            base_result,
            lambda doc: doc["result_transaction"].__setitem__(
                "state", "SEMANTICALLY_UNKNOWN"
            ),
        ),
    ]
    probe_findings = {
        "top-level-extension": (
            "RESULT-VALIDATOR-ACCEPTS-UNDECLARED-FIELD",
            "The executable validator accepts an undeclared top-level field even though the JSON Schema sets additionalProperties=false.",
            "Reject fields not declared by the result contract at every closed object boundary.",
        ),
        "provider-state": (
            "RESULT-VALIDATOR-ACCEPTS-UNKNOWN-PROVIDER-STATE",
            "The executable validator accepts a provider_state outside the schema enum.",
            "Enforce the documented provider-state enum in the dependency-free validator.",
        ),
        "transaction-state": (
            "RESULT-VALIDATOR-ACCEPTS-UNKNOWN-TRANSACTION-STATE",
            "The executable validator accepts a result_transaction.state outside the schema enum.",
            "Enforce the documented transaction-state enum in the dependency-free validator.",
        ),
    }
    for probe in probes:
        if not probe["accepted"]:
            continue
        finding_id, statement, resolution_text = probe_findings[probe["probe_id"]]
        findings.append(
            finding(
                finding_id,
                "state-contract",
                statement,
                probe,
                proposal(
                    f"P-{finding_id}",
                    resolution_text,
                ),
            )
        )

    taxonomy = run_taxonomy_check(root)
    if taxonomy["exit_code"] != 0:
        findings.append(
            finding(
                "EXISTING-TAXONOMY-GATE-FAILED",
                "operator-taxonomy",
                "The existing taxonomy gate failed; the semantic check cannot substitute for it.",
                taxonomy,
                proposal(
                    "P-SEMANTIC-EXISTING-GATE-01",
                    "Repair the existing gate failure before promotion; do not waive or weaken it.",
                ),
            )
        )

    entrypoint_text = (root / ENTRYPOINT_PATH).read_text(encoding="utf-8")
    control_operator = control_pointer.get("institutional_operator", {})
    control_pointer_mismatches = [
        field
        for field in (
            "function_id",
            "appointment_id",
            "commission_id",
            "authority_envelope_id",
            "runtime_binding_id",
        )
        if control_operator.get(field) != pointer.get(field)
    ]
    if control_pointer_mismatches:
        findings.append(
            finding(
                "CONTROL-POINTER-INSTITUTIONAL-ROUTE-DIVERGES",
                "operator-taxonomy",
                "The programme control pointer projects a different institutional operator than the current operator-system pointer.",
                {"mismatched_fields": control_pointer_mismatches},
                proposal(
                    "P-SEMANTIC-CONTROL-POINTER-01",
                    "Reconcile the projection to the current pointer without changing immutable v010 launch evidence.",
                    founder_interlock="REQUIRED_IF_RESOLUTION_CHANGES_AUTHORITY_OR_STRATEGY",
                ),
            )
        )

    evidence_paths = (
        ENTRYPOINT_PATH,
        CONTROL_POINTER_PATH,
        OPERATOR_POINTER_PATH,
        STACK_PATH,
        FUNCTIONS_PATH,
        APPOINTMENTS_PATH,
        COMMISSIONS_PATH,
        ENVELOPES_PATH,
        RUNTIMES_PATH,
        ALIASES_PATH,
        PO03_COMMISSION_PATH,
        LEDGER_PATH,
        RESULT_SCHEMA_PATH,
        RESULT_VALIDATOR_PATH,
        BASE_RESULT_PATH,
        TAXONOMY_CHECK_PATH,
    )
    return {
        "artifact_id": "PO03-A9-SEMANTIC-CHECK-v001",
        "unit_id": "a9-u04",
        "scope": "Read-only semantic analysis of the current operator pointer chain plus executable result-contract probes. This complements and does not replace scripts/check_operator_taxonomy.py.",
        "current_chain": {
            "repository_entrypoint": ENTRYPOINT_PATH,
            "entrypoint_order": parse_entrypoint_order(entrypoint_text),
            "operator_pointer_path": OPERATOR_POINTER_PATH,
            "instruction_stack_path": STACK_PATH,
            "function_id": pointer.get("function_id"),
            "appointment_id": pointer.get("appointment_id"),
            "commission_id": pointer.get("commission_id"),
            "authority_envelope_id": pointer.get("authority_envelope_id"),
            "runtime_binding_id": pointer.get("runtime_binding_id"),
            "strategy_snapshot_id": pointer.get("strategy_snapshot_id"),
            "transitive_error_count": len(chain_errors),
            "transitive_errors": chain_errors,
            "control_pointer_projection_mismatches": control_pointer_mismatches,
        },
        "state_contract": {
            "schema_path": RESULT_SCHEMA_PATH,
            "validator_path": RESULT_VALIDATOR_PATH,
            "schema_validator_state_enums_equal": schema_states == validator_states,
            "validator_probes": probes,
        },
        "existing_taxonomy_gate": taxonomy,
        "findings": findings,
        "summary": {
            "finding_count": len(findings),
            "operator_taxonomy_findings": sum(
                item["category"] == "operator-taxonomy" for item in findings
            ),
            "state_contract_findings": sum(
                item["category"] == "state-contract" for item in findings
            ),
            "current_chain_transitive_errors": len(chain_errors),
            "existing_taxonomy_gate_passed": taxonomy["exit_code"] == 0,
            "status": "AMBIGUITIES_REPORTED" if findings else "NO_AMBIGUITIES_FOUND",
        },
        "evidence": [
            {
                "path": relative,
                "sha256": sha256_file(root / relative),
                "bytes": (root / relative).stat().st_size,
            }
            for relative in evidence_paths
        ],
        "write_scope": {
            "implementation": "workstreams/po03/strategy/semantic_check.py",
            "output": "workstreams/po03/strategy/semantic-check-results.json",
            "outside_allowlist_write_required": False,
        },
        "strategy_restarted": False,
        "decision_changed": [],
    }


def strict_exit_code(report: dict[str, Any]) -> int:
    return 0 if not report["findings"] else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workstreams/po03/strategy/semantic-check-results.json"),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    report = build_report(root)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"WROTE {output.relative_to(root)} findings={report['summary']['finding_count']} "
        f"chain_errors={report['summary']['current_chain_transitive_errors']} "
        f"taxonomy_exit={report['existing_taxonomy_gate']['exit_code']} decision_changed=[]"
    )
    return strict_exit_code(report) if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
