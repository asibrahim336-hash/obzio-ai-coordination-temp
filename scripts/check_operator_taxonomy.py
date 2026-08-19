#!/usr/bin/env python3
"""Fail if the current Obzio operator system drifts back to runtime-as-identity."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def load(path: str):
    target = ROOT / path
    if not target.exists():
        ERRORS.append(f"missing: {path}")
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        ERRORS.append(f"invalid json {path}: {exc}")
        return {}


def jsonl(path: str):
    target = ROOT / path
    if not target.exists():
        ERRORS.append(f"missing: {path}")
        return []
    rows = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            ERRORS.append(f"invalid jsonl {path}:{number}: {exc}")
    return rows


pointer = load("state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json")
stack = load("state/operator-system/ACTIVE_INSTRUCTION_STACK.json")
functions = {row.get("function_id"): row for row in jsonl("state/operator-system/FUNCTION_REGISTER.jsonl")}
appointments = {row.get("appointment_id"): row for row in jsonl("state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl")}
commissions = {row.get("commission_id"): row for row in jsonl("state/operator-system/COMMISSION_REGISTER.jsonl")}
envelopes = {row.get("authority_envelope_id"): row for row in jsonl("state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl")}
runtimes = {row.get("runtime_binding_id"): row for row in jsonl("state/operator-system/RUNTIME_BINDING_REGISTER.jsonl")}
aliases = jsonl("state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl")

for key, table in (
    (pointer.get("function_id"), functions),
    (pointer.get("appointment_id"), appointments),
    (pointer.get("commission_id"), commissions),
    (pointer.get("authority_envelope_id"), envelopes),
    (pointer.get("runtime_binding_id"), runtimes),
):
    if key not in table:
        ERRORS.append(f"pointer target unresolved: {key}")

for key in ("function_id", "appointment_id", "commission_id", "authority_envelope_id", "runtime_binding_id"):
    if pointer.get(key) != stack.get(key):
        ERRORS.append(f"pointer/stack mismatch: {key}")

for runtime_id, row in runtimes.items():
    if row.get("authority_effect") != "NONE":
        ERRORS.append(f"runtime grants authority: {runtime_id}")

provider_terms = re.compile(r"claude|chatgpt|cursor|metamate|browser|extension|anthropic|openai", re.I)
for function_id, row in functions.items():
    if provider_terms.search(function_id or "") or provider_terms.search(row.get("display_name", "")):
        ERRORS.append(f"runtime/provider embedded in function identity: {function_id}")

required_aliases = {"Operator D", "SC-CIEG", "Claude extension", "Claude browser operator", "CHATGPT ACCOUNT OPERATIONS AND COMMISSIONING DIRECTOR", "principal AI operator", "SW/Metamate", "Cursor operator"}
seen_aliases = {row.get("alias") for row in aliases}
for alias in sorted(required_aliases - seen_aliases):
    ERRORS.append(f"unclassified legacy alias: {alias}")

for path in stack.get("resolve_in_order", []) + stack.get("immutable_execution_evidence", []):
    if not (ROOT / path).exists():
        ERRORS.append(f"instruction stack path missing: {path}")

high_risk_markers = {
    "commissions/OPERATOR_D_CONTINUATION_DIRECTIVE_20260818.md": "SUPERSEDED FOR ACTIVE ROUTING",
    "dispatch/OPERATOR_D_REFERENCE_UPDATE_20260818.md": "SUPERSEDED FOR ACTIVE ROUTING",
    "state/DESK_OPERATOR_D_RECOVERY_AND_CONTINUATION_20260818.md": "SUPERSEDED FOR ACTIVE ROUTING",
    "templates/NEXT_OPERATOR_PREFLIGHT_20260818.md": "SUPERSEDED FOR ACTIVE ROUTING",
    "handover/PRINCIPAL_AI_OPERATOR_HANDOVER_20260819.md": "QUARANTINED OPERATOR REPORT",
}
for path, marker in high_risk_markers.items():
    target = ROOT / path
    if not target.exists() or marker not in target.read_text(encoding="utf-8", errors="replace")[:1200]:
        ERRORS.append(f"legacy file lacks routing marker: {path}")

if ERRORS:
    print("OPERATOR TAXONOMY CHECK: FAIL")
    for error in ERRORS:
        print(f"- {error}")
    sys.exit(1)

print("OPERATOR TAXONOMY CHECK: PASS")
print(f"active function: {pointer['function_id']}")
print(f"active appointment: {pointer['appointment_id']}")
print(f"classified aliases: {len(aliases)}")

