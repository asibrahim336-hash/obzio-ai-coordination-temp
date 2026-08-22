#!/usr/bin/env python3
"""Validate the OE-L5 ChatGPT function/topology register.

Checks the twelve invariants declared in the register itself. The point of this
script is that the anti-overlap claim is machine-checked rather than reviewed:
if two admitted functions ever claim the same decision class, or a function
claims the reserved programme-shape class, or an assurance container starts
hosting a producing function, the check fails and the register cannot be
promoted.

Usage:
    python3 check_function_register.py [path-to-register.json]

Exit code 0 means every invariant holds. Exit code 1 lists the violations.
"""
from __future__ import annotations

import json
import os
import sys

DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json",
)

RESERVED = "DC-PROGRAMME-SHAPE"
ADMITTED_STATES = {"DRAFTED", "ADMITTED", "BOUND", "OPERATING", "REGISTERED_DEFERRED"}


def check(reg: dict) -> list[str]:
    bad: list[str] = []
    funcs = reg["functions"]
    classes = {c["class_id"]: c for c in reg["decision_classes"]}
    external = {e["class_id"] for e in reg["external_decision_class_holders"]}
    slots = {s["slot_id"]: s for s in reg["project_slots"]}
    live = [f for f in funcs if f["lifecycle_state"] in ADMITTED_STATES]

    holders: dict[str, list[str]] = {}
    for f in live:
        for c in f["operating_record"]["decides"]:
            holders.setdefault(c, []).append(f["function_id"])

    # I1 exactly one holder per internal class
    for cid in classes:
        n = len(holders.get(cid, []))
        if n != 1:
            bad.append(f"I1 {cid} has {n} holders: {holders.get(cid, [])}")

    # I2 pairwise disjoint decides sets
    for cid, hs in holders.items():
        if len(hs) > 1:
            bad.append(f"I2 {cid} claimed by {hs}")

    for f in live:
        fid = f["function_id"]
        rec = f["operating_record"]
        decides = rec["decides"]
        must_not = rec["must_not_decide"]
        informs = rec["informs"]

        # I3 no external class claimed
        for c in decides:
            if c in external:
                bad.append(f"I3 {fid} claims external class {c}")

        # I4 non-empty decides
        if not decides:
            bad.append(f"I4 {fid} has an empty decides set")

        # I5 no class in both decides and must_not_decide
        for c in set(decides) & set(must_not):
            bad.append(f"I5 {fid} lists {c} in both decides and must_not_decide")

        # I6 every referenced class exists
        for c in informs + must_not:
            if c not in classes and c not in external:
                bad.append(f"I6 {fid} references unknown class {c}")

        # I7 slot exists
        slot_id = f["runtime_binding"]["project_slot"]
        if slot_id not in slots and slot_id != "UNBOUND_DEFERRED":
            bad.append(f"I7 {fid} bound to unknown slot {slot_id}")

        # I8 assurance containers host no producing function
        slot = slots.get(slot_id)
        if slot and slot["type"] == "ASSURANCE" and slot["may_host_producing_functions"]:
            bad.append(f"I8 assurance slot {slot_id} permits producing functions")

        # I9 no self-acceptance
        if rec["coordination_and_return"]["acceptance_owner"] == fid:
            bad.append(f"I9 {fid} is its own acceptance owner")

        # I10 warrant completeness
        w = f["differentiation_warrant"]
        if not w.get("pre_registered_falsifier"):
            bad.append(f"I10 {fid} has no pre-registered falsifier")
        if not w.get("exit_condition"):
            bad.append(f"I10 {fid} has no exit condition")

        # I12 reserved class never claimed or informed, only forbidden
        if RESERVED in decides or RESERVED in informs:
            bad.append(f"I12 {fid} claims or informs the reserved class {RESERVED}")

    # I11 slot hosts and function bindings agree
    for sid, slot in slots.items():
        declared = set(slot["hosts"])
        actual = {f["function_id"] for f in funcs
                  if f["runtime_binding"]["project_slot"] == sid}
        if declared != actual:
            bad.append(
                f"I11 slot {sid} hosts {sorted(declared)} but bindings say {sorted(actual)}"
            )

    return bad


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with open(path, encoding="utf-8") as fh:
        reg = json.load(fh)

    violations = check(reg)
    live = [f for f in reg["functions"] if f["lifecycle_state"] in ADMITTED_STATES]
    print(f"register: {reg['register_id']}")
    print(f"functions checked: {len(live)}")
    print(f"internal decision classes: {len(reg['decision_classes'])}")
    print(f"external decision classes: {len(reg['external_decision_class_holders'])}")
    print(f"project slots: {len(reg['project_slots'])}")

    if violations:
        print(f"\nFAIL: {len(violations)} violation(s)")
        for v in violations:
            print("  -", v)
        return 1

    print("\nPASS: all 12 invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
