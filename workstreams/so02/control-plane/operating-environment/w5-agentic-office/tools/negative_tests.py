#!/usr/bin/env python3
"""Prove the office invariants actually reject, by mutating the register to break each one.

An invariant that has never rejected anything is a claim, not a control. Each case
below mutates a valid register into a specific failure and asserts that officectl
refuses it with the expected code. A case that fails to be rejected is a hole in
the office's constitution and this script exits non-zero.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import officectl  # noqa: E402

REG = json.loads((HERE.parent / "OFFICE-SEAT-REGISTER-20260822-v001.json").read_text())
W4 = json.loads((HERE.parent.parent / "w4-platform-roles/PLATFORM-ROLE-REGISTER-20260822-v001.json").read_text())


def seat(reg: dict, sid: str) -> dict:
    return next(s for s in reg["seats"] if s["seat_id"] == sid)


def m_double_holder(r):
    """two seats hold one decision class"""
    seat(r, "S-SCOUT")["decides"].append("DC-CUSTODY")
    seat(r, "S-SCOUT")["w4_functions"].append("F-CUSTODY")


def m_founder_reserved(r):
    """a seat claims a founder-reserved class"""
    seat(r, "S-CHIEF")["decides"].append("DC-COMPANY-STRATEGY")


def m_unheld_class(r):
    """a decision class ends up held by nobody"""
    s = seat(r, "S-SCOUT")
    s["decides"] = []
    s["w4_functions"] = []


def m_self_acceptance(r):
    """a seat accepts its own work"""
    seat(r, "S-BUILD")["acceptance_owner_seat"] = "S-BUILD"


def m_broken_mutual_check(r):
    """the acceptor's checker is not checked back by the acceptor"""
    seat(r, "S-ADVERSARY")["acceptance_owner_seat"] = "S-CHIEF"


def m_whole_operation(r):
    """a seat claims a whole-operation mandate"""
    seat(r, "S-CHIEF")["mandate"] = "Hold the whole operation and decide everything in it."


def m_runtime_as_authority(r):
    """a seat's only stated mandate is where it runs"""
    s = seat(r, "S-BUILD")
    s["mandate"] = "A Cursor cloud agent run."
    s["runtime_binding"] = "A Cursor cloud agent run."


def m_decorative_seat(r):
    """a seat can change nothing"""
    seat(r, "S-SCOUT")["can_change"] = []


def m_no_substitution(r):
    """a seat names no substitute and accrues silent exclusive dependency"""
    seat(r, "S-RUNTIME")["substitution_route"] = ""


def m_founder_relay_route(r):
    """a seat returns results by making the founder carry them"""
    seat(r, "S-SCOUT")["return_route"] = "R0-founder-relay"


def m_unknown_return_route(r):
    """a seat names a return route class that does not exist"""
    seat(r, "S-SCOUT")["return_route"] = "R9-invented-route"


def m_refinement_break(r):
    """a seat's classes stop matching the w4 functions it claims to group"""
    seat(r, "S-REGISTRAR")["decides"].remove("DC-ADMISSION")


def m_bad_evidence_label(r):
    """a seat carries a label outside the fixed vocabulary"""
    seat(r, "S-BUILD")["evidence_label"] = "PROBABLY_FINE"


def m_incomplete_seat(r):
    """a seat omits a required field"""
    seat(r, "S-RUNTIME")["acceptance_method"] = ""


def m_register_declares_commission(r):
    """the register quietly promotes itself to a commission"""
    r["declares_commission"] = True


def m_register_binds_tool(r):
    """the register binds a named model or architecture"""
    r["named_model_or_architecture_bound"] = True


def m_fixed_agent_count(r):
    """the register imposes a fixed number of agents"""
    r["seat_is_not_an_agent"]["no_fixed_agent_count"] = False


def m_fixed_fill_policy(r):
    """a seat's fill policy imposes a fixed agent count"""
    seat(r, "S-BUILD")["fill_policy"] = "Exactly 3 agents fill this seat."


def m_stale_partition_check(r):
    """the recorded partition check disagrees with recomputation"""
    s = seat(r, "S-SCOUT")
    s["decides"] = []
    s["w4_functions"] = []
    r["partition_check"]["complete"] = True


def m_unknown_class(r):
    """a seat claims a class that is not in the partition at all"""
    seat(r, "S-SCOUT")["decides"].append("DC-INVENTED-BY-AN-ASSISTANT")


CASES = [
    ("NO1", m_double_holder, "DOUBLE_HOLDER"),
    ("NO2", m_founder_reserved, "FOUNDER_RESERVED_CLAIMED"),
    ("NO3", m_unheld_class, "UNHELD_CLASS"),
    ("NO4", m_self_acceptance, "SELF_ACCEPTANCE"),
    ("NO5", m_broken_mutual_check, "BROKEN_MUTUAL_CHECK"),
    ("NO6", m_whole_operation, "UNDIFFERENTIATED_MANDATE"),
    ("NO7", m_runtime_as_authority, "RUNTIME_AS_AUTHORITY"),
    ("NO8", m_decorative_seat, "DECORATIVE_SEAT"),
    ("NO9", m_no_substitution, "NO_SUBSTITUTION_ROUTE"),
    ("NO10", m_founder_relay_route, "FOUNDER_RELAY_ROUTE"),
    ("NO11", m_unknown_return_route, "UNKNOWN_RETURN_ROUTE"),
    ("NO12", m_refinement_break, "REFINEMENT_BREAK"),
    ("NO13", m_bad_evidence_label, "BAD_EVIDENCE_LABEL"),
    ("NO14", m_incomplete_seat, "INCOMPLETE_SEAT"),
    ("NO15", m_register_declares_commission, "REGISTER_DECLARES_COMMISSION"),
    ("NO16", m_register_binds_tool, "REGISTER_BINDS_TOOL"),
    ("NO17", m_fixed_agent_count, "FIXED_AGENT_COUNT"),
    ("NO18", m_fixed_fill_policy, "FIXED_AGENT_COUNT"),
    ("NO19", m_stale_partition_check, "STALE_PARTITION_CHECK"),
    ("NO20", m_unknown_class, "UNKNOWN_CLASS"),
]


def main() -> int:
    baseline = officectl.violations(copy.deepcopy(REG), W4)
    if baseline:
        print("FAIL: the unmutated register does not pass its own invariants:")
        for line in baseline:
            print(f"  {line}")
        return 1
    print("baseline: unmutated register PASSES all invariants")

    failures = 0
    for cid, mutate, expect in CASES:
        r = copy.deepcopy(REG)
        mutate(r)
        v = officectl.violations(r, W4)
        hit = [x for x in v if x.startswith(expect)]
        if hit:
            print(f"{cid} REJECTED: {mutate.__doc__}")
            print(f"      {hit[0]}")
        else:
            failures += 1
            print(f"{cid} NOT REJECTED (expected {expect}): {mutate.__doc__}")
            for line in v:
                print(f"      saw: {line}")

    print()
    if failures:
        print(f"FAIL: {failures} of {len(CASES)} failure modes were not rejected")
        return 1
    print(f"PASS: all {len(CASES)} failure modes rejected by the validators")
    return 0


if __name__ == "__main__":
    sys.exit(main())
