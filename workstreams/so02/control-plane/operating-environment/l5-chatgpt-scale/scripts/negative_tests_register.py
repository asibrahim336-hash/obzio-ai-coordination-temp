#!/usr/bin/env python3
"""Adversarial tests for the register validator.

A validator that only ever passes proves nothing. Each test below mutates the
register into one of the failure modes the topology is supposed to make
impossible, then asserts that the checker rejects it. Test NT1 is the
overlapping-commission failure and NT2 is the whole-operation commission.

Usage:
    python3 negative_tests_register.py [path-to-register.json]

Exit code 0 means every failure mode was correctly rejected.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_function_register.py")
DEFAULT = os.path.join(os.path.dirname(HERE),
                       "FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json")


def run_checker(register: dict) -> tuple[int, list[str]]:
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(register, fh)
        proc = subprocess.run([sys.executable, CHECKER, tmp],
                              capture_output=True, text=True)
    finally:
        os.unlink(tmp)
    lines = [l.strip()[2:] for l in proc.stdout.splitlines() if l.startswith("  -")]
    return proc.returncode, lines


def dup_class(reg):
    m = copy.deepcopy(reg)
    for f in m["functions"]:
        if f["function_id"] == "F-RESEARCH":
            f["operating_record"]["decides"].append("DC-CAPABILITY-BACKLOG")
    return m


def claim_reserved(reg):
    m = copy.deepcopy(reg)
    for f in m["functions"]:
        if f["function_id"] == "F-RESEARCH":
            f["operating_record"]["decides"].append("DC-PROGRAMME-SHAPE")
    return m


def self_accept(reg):
    m = copy.deepcopy(reg)
    for f in m["functions"]:
        if f["function_id"] == "F-CAPDEV":
            f["operating_record"]["coordination_and_return"]["acceptance_owner"] = "F-CAPDEV"
    return m


def decorative(reg):
    m = copy.deepcopy(reg)
    for f in m["functions"]:
        if f["function_id"] == "F-ECOSYSTEM":
            f["operating_record"]["decides"] = []
    return m


def assurance_produces(reg):
    m = copy.deepcopy(reg)
    for s in m["project_slots"]:
        if s["slot_id"] == "P-ASSURE-ACCEPT":
            s["may_host_producing_functions"] = True
    return m


def no_falsifier(reg):
    m = copy.deepcopy(reg)
    for f in m["functions"]:
        if f["function_id"] == "F-KNOW":
            f["differentiation_warrant"]["pre_registered_falsifier"] = ""
    return m


TESTS = [
    ("NT1", "two functions claim the same decision class (the overlapping-commission failure)", dup_class, "I2"),
    ("NT2", "a function claims the reserved programme-shape class (the whole-operation commission)", claim_reserved, "I12"),
    ("NT3", "a producing function names itself as its own acceptance owner", self_accept, "I9"),
    ("NT4", "a decorative function with no decision class survives admission", decorative, "I4"),
    ("NT5", "an assurance container starts hosting producing functions", assurance_produces, "I8"),
    ("NT6", "a warrant is admitted with no pre-registered falsifier", no_falsifier, "I10"),
]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    with open(path, encoding="utf-8") as fh:
        reg = json.load(fh)

    baseline_code, baseline_bad = run_checker(reg)
    print(f"baseline register: exit={baseline_code} violations={len(baseline_bad)}")
    if baseline_code != 0:
        print("FAIL: the unmutated register must pass before negative tests mean anything")
        for b in baseline_bad:
            print("  -", b)
        return 1

    failures = 0
    for tid, description, mutate, expected in TESTS:
        code, bad = run_checker(mutate(reg))
        caught = code != 0 and any(v.startswith(expected) for v in bad)
        status = "REJECTED" if caught else "NOT CAUGHT"
        print(f"{tid} {status}: {description}")
        for v in bad[:3]:
            print("     ", v)
        if not caught:
            failures += 1

    print()
    if failures:
        print(f"FAIL: {failures} failure mode(s) were not caught")
        return 1
    print(f"PASS: all {len(TESTS)} failure modes rejected by the validator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
