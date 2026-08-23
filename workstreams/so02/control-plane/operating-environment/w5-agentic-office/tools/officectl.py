#!/usr/bin/env python3
"""Validate the office seat register against the invariants that make the office safe.

These are the same class of invariants w4's rolectl.py enforces over functions,
lifted to seats. They exist because each corresponds to a failure this estate
actually produced: two holders for one decision, a mandate wide enough to swallow
the whole operation, a producer accepting its own work, a runtime binding
mistaken for authority, and a dependency with no named substitute.

    python3 tools/officectl.py check
    python3 tools/officectl.py check --register <path> --w4 <path>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_REGISTER = HERE.parent / "OFFICE-SEAT-REGISTER-20260822-v001.json"
DEFAULT_W4 = HERE.parent.parent / "w4-platform-roles/PLATFORM-ROLE-REGISTER-20260822-v001.json"

WHOLE_OPERATION_MARKERS = [
    "whole operation", "entire operation", "the operation", "cross-estate",
    "coordination kernel", "durable coordination kernel", "all workstreams",
    "the programme", "global",
]

REQUIRED_SEAT_FIELDS = [
    "seat_id", "name", "one_line", "w4_functions", "mandate", "decides",
    "can_change", "must_not_change", "return_route", "returns",
    "acceptance_method", "acceptance_owner_seat", "runtime_binding",
    "substitution_route", "fill_policy", "evidence_label",
]

EVIDENCE_LABELS = {"DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS", "FOUNDER_SUPPLIED"}


def violations(reg: dict, w4: dict) -> list[str]:
    v: list[str] = []
    seats = reg["seats"]
    seat_ids = {s["seat_id"] for s in seats}
    holder = {c["class_id"]: c["holder_function"] for c in w4["decision_classes"]}
    founder_reserved = {k for k, x in holder.items() if x == "FOUNDER"}
    non_founder = {k for k, x in holder.items() if x != "FOUNDER"}
    fn_decides = {f["function_id"]: set(f.get("decides") or []) for f in w4["functions"]}
    route_classes = {r["class"] for r in w4["return_route_classes"]}

    # I1 — every seat carries every required field, non-empty.
    for s in seats:
        for f in REQUIRED_SEAT_FIELDS:
            if not s.get(f):
                v.append(f"INCOMPLETE_SEAT: {s.get('seat_id', '?')} is missing or empty field '{f}'")

    # I2 — a decision class has exactly one holding seat.
    seen: dict[str, str] = {}
    for s in seats:
        for c in s.get("decides", []):
            if c in seen:
                v.append(f"DOUBLE_HOLDER: {c} is held by both {seen[c]} and {s['seat_id']}")
            seen[c] = s["seat_id"]

    # I3 — no seat claims a founder-reserved class.
    for s in seats:
        for c in s.get("decides", []):
            if c in founder_reserved:
                v.append(f"FOUNDER_RESERVED_CLAIMED: {s['seat_id']} claims {c}")

    # I4 — the seats partition the non-founder classes exactly.
    covered = set(seen)
    for c in sorted(non_founder - covered):
        v.append(f"UNHELD_CLASS: {c} is held by no seat")
    for c in sorted(covered - non_founder):
        v.append(f"UNKNOWN_CLASS: {c} is not a class in the w4 partition")

    # I5 — a seat's classes are exactly the union of its w4 functions' classes.
    for s in seats:
        expect: set[str] = set()
        for fid in s.get("w4_functions", []):
            if fid not in fn_decides:
                v.append(f"UNKNOWN_FUNCTION: {s['seat_id']} names {fid}, which is not a w4 function")
                continue
            expect |= fn_decides[fid]
        if expect != set(s.get("decides", [])):
            v.append(
                f"REFINEMENT_BREAK: {s['seat_id']} decides {sorted(set(s.get('decides', [])))} "
                f"but its w4 functions decide {sorted(expect)}"
            )

    # I6 — no seat is its own acceptance owner.
    for s in seats:
        if s.get("acceptance_owner_seat") == s["seat_id"]:
            v.append(f"SELF_ACCEPTANCE: {s['seat_id']} is its own acceptance owner")
        if s.get("acceptance_owner_seat") not in seat_ids:
            v.append(f"UNKNOWN_ACCEPTOR: {s['seat_id']} names acceptance owner {s.get('acceptance_owner_seat')}")

    # I7 — the acceptance holder's own acceptor is not one of its producers.
    acceptors = [s for s in seats if "DC-ACCEPTANCE" in s.get("decides", [])]
    for s in acceptors:
        adversary = s.get("acceptance_owner_seat")
        for other in seats:
            if other["seat_id"] == adversary and other.get("acceptance_owner_seat") != s["seat_id"]:
                v.append(
                    f"BROKEN_MUTUAL_CHECK: {s['seat_id']} is checked by {adversary}, "
                    f"but {adversary} is not checked back by {s['seat_id']}"
                )

    # I8 — no seat's mandate claims whole-operation scope.
    for s in seats:
        text = " ".join(str(s.get(k, "")) for k in ("one_line", "mandate")).lower()
        for m in WHOLE_OPERATION_MARKERS:
            if re.search(r"\b" + re.escape(m) + r"\b", text):
                v.append(f"UNDIFFERENTIATED_MANDATE: {s['seat_id']} mandate contains whole-operation marker '{m}'")

    # I9 — a runtime binding is never the seat's authority.
    for s in seats:
        mandate = str(s.get("mandate", "")).lower()
        binding = str(s.get("runtime_binding", "")).lower()
        if mandate and binding and mandate.strip() == binding.strip():
            v.append(f"RUNTIME_AS_AUTHORITY: {s['seat_id']} states its runtime binding as its mandate")
        if not s.get("can_change"):
            v.append(f"DECORATIVE_SEAT: {s['seat_id']} can change nothing and is decorative")

    # I10 — every seat names a substitution route and a known return route.
    for s in seats:
        if not str(s.get("substitution_route", "")).strip():
            v.append(f"NO_SUBSTITUTION_ROUTE: {s['seat_id']} names no substitute")
        routes = re.findall(r"R\d+-[a-z-]+", str(s.get("return_route", "")))
        if not routes:
            v.append(f"NO_RETURN_ROUTE: {s['seat_id']} names no return route class")
        for r in routes:
            if r not in route_classes:
                v.append(f"UNKNOWN_RETURN_ROUTE: {s['seat_id']} names {r}, not a w4 return route class")
            if r == "R0-founder-relay":
                v.append(f"FOUNDER_RELAY_ROUTE: {s['seat_id']} routes results through the founder, which is classified as a defect")

    # I11 — evidence labels are from the fixed vocabulary.
    for s in seats:
        if s.get("evidence_label") not in EVIDENCE_LABELS:
            v.append(f"BAD_EVIDENCE_LABEL: {s['seat_id']} carries '{s.get('evidence_label')}'")

    # I12 — the register does not silently become a commission.
    if reg.get("declares_commission"):
        v.append("REGISTER_DECLARES_COMMISSION: this register is a proposal and may not declare a commission")
    if reg.get("binds_company_strategy"):
        v.append("REGISTER_BINDS_STRATEGY: this register binds no company strategy")
    if reg.get("named_model_or_architecture_bound"):
        v.append("REGISTER_BINDS_TOOL: this register binds no named model, tool or architecture")

    # I13 — no fixed agent count may be imposed.
    if not reg.get("seat_is_not_an_agent", {}).get("no_fixed_agent_count"):
        v.append("FIXED_AGENT_COUNT: the register must state explicitly that seat count is not agent count")
    for s in seats:
        if re.search(r"\bexactly \d+ agents?\b", str(s.get("fill_policy", "")).lower()):
            if "one at a time" not in str(s.get("fill_policy", "")).lower():
                v.append(f"FIXED_AGENT_COUNT: {s['seat_id']} fill_policy imposes a fixed agent count")

    # I14 — the partition check recorded in the register agrees with recomputation.
    pc = reg.get("partition_check", {})
    if pc.get("complete") is not (covered == non_founder):
        v.append("STALE_PARTITION_CHECK: the recorded partition_check disagrees with recomputation")

    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--register", default=str(DEFAULT_REGISTER))
    ap.add_argument("--w4", default=str(DEFAULT_W4))
    a = ap.parse_args()

    reg = json.loads(pathlib.Path(a.register).read_text())
    w4 = json.loads(pathlib.Path(a.w4).read_text())
    v = violations(reg, w4)
    print(f"seats {len(reg['seats'])}  decision classes held {sum(len(s['decides']) for s in reg['seats'])}  founder-reserved {reg['founder_reserved_count']}")
    if v:
        for line in v:
            print(f"  {line}")
        print(f"FAIL: {len(v)} violation(s)")
        return 1
    print("PASS: all 14 invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
