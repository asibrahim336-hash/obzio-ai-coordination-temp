#!/usr/bin/env python3
"""Adversarial tests for rolectl and derestrictctl.

A validator that has only ever seen valid input is a validator nobody has tested.
Each case below mutates a committed register into a specific failure and asserts
that the checker refuses it. The failures are not invented for the test: every one
of them is either a failure this estate has actually produced or the exact failure
the corresponding control exists to prevent.

    python3 tools/negative_tests.py

Exit codes: 0 every failure mode was rejected, 1 one leaked through.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import derestrictctl  # noqa: E402
import rolectl  # noqa: E402

ROLE_REGISTER = HERE.parent / "PLATFORM-ROLE-REGISTER-20260822-v001.json"
DERESTRICT_REGISTER = HERE.parent / "DE-RESTRICTION-REGISTER-20260822-v001.json"


def _fn(reg, fid):
    return next(f for f in reg["functions"] if f["function_id"] == fid)


# ---------------------------------------------------------------------------
# rolectl failure modes
# ---------------------------------------------------------------------------

def nt_role_1(reg):
    """Two functions claim the same decision class.

    The estate's live instance: seven undifferentiated commission overlaps, two of
    which assert whole-operation authority over the same paths with no supersession
    edge.
    """
    _fn(reg, "F-RESEARCH")["decides"].append("DC-CAPABILITY-DEVELOPMENT")
    return "two functions claim DC-CAPABILITY-DEVELOPMENT", ["I6"]


def nt_role_2(reg):
    """A function claims a founder-reserved class.

    This is what a whole-operation commission looks like structurally: it claims
    programme shape. Reserving the class makes it rejectable at admission.
    """
    _fn(reg, "F-OPENV")["decides"].append("DC-PROGRAMME-SHAPE")
    return "a function claims the reserved DC-PROGRAMME-SHAPE", ["I7"]


def nt_role_3(reg):
    """A function names itself its own acceptance owner.

    The live instance is AC-12: the producer authored the assertions that graded it.
    """
    _fn(reg, "F-CAPDEV")["acceptance_owner"] = "F-CAPDEV"
    return "a producing function is its own acceptance owner", ["I11"]


def nt_role_4(reg):
    """A decorative function with no decision class survives admission."""
    _fn(reg, "F-QUESTIONS")["decides"] = []
    return "a function is admitted with an empty decides set", ["I6", "I8"]


def nt_role_5(reg):
    """Authority is asserted from the runtime.

    AGENTS.md rule 6 states it directly: a runtime never grants authority. This is
    the failure that lets a rename or a provider migration look like a change in
    standing.
    """
    f = _fn(reg, "F-OPENV")
    f["authority_envelope"]["appointment"] = f["authority_envelope"]["runtime_binding"]
    return "a function names its runtime as its appointment", ["I2"]


def nt_role_6(reg):
    """Acceptance and red team stop being reciprocal.

    Without reciprocity the holder of DC-ACCEPTANCE is effectively self-certified,
    because nothing can force it to re-adjudicate.
    """
    _fn(reg, "F-ACCEPT")["acceptance_owner"] = "F-EVAL"
    return "acceptance and red team are no longer reciprocal owners", ["I12"]


def nt_role_7(reg):
    """A function is bound to a platform with no substitution route.

    This is how exclusive provider dependency accumulates: not by decision, but by
    nobody ever writing down what would happen if the provider went away.
    """
    _fn(reg, "F-ESTATE")["substitution_route"] = ""
    return "a function names no substitution route", ["I13"]


def nt_role_8(reg):
    """A function both decides and must-not-decide the same class.

    A contradiction inside one envelope, which reads as authority from whichever
    half a reader looks at first.
    """
    _fn(reg, "F-ACCEPT")["must_not_decide"].append("DC-ACCEPTANCE")
    return "a function both decides and must-not-decide one class", ["I10"]


def nt_role_9(reg):
    """A function binds to a platform that is not declared.

    The estate's version of this is an alias used as a locator, which currently
    occurs twice in the live control plane.
    """
    _fn(reg, "F-INTAKE")["platform_binding"] = "the current conversation"
    return "a function binds to an undeclared platform", ["I14"]


ROLE_CASES = [nt_role_1, nt_role_2, nt_role_3, nt_role_4, nt_role_5,
              nt_role_6, nt_role_7, nt_role_8, nt_role_9]


# ---------------------------------------------------------------------------
# Contribution ledger failure modes
# ---------------------------------------------------------------------------

CLEAN_LEDGER = {
    "wave": "W4-0",
    "rows": [
        {"row_id": "CL-1", "decision_class": "DC-RESEARCH-FRONTIER", "holder_function": "F-RESEARCH",
         "contributing_function": "F-ESTATE", "wave": "W4-0", "evidence_label": "FOUNDER_SUPPLIED",
         "position": "agree", "disposition": "accepted into the candidate register", "conflict_id": None},
        {"row_id": "CL-2", "decision_class": "DC-ROUTE-QUALIFICATION", "holder_function": "F-ROUTE",
         "contributing_function": "F-ALIGN", "wave": "W4-0", "evidence_label": "DOCUMENTED",
         "position": "dissent", "disposition": "overruled, retained in the ledger", "conflict_id": "CF-1"},
    ],
    "conflicts": [
        {"conflict_id": "CF-1", "decision_class": "DC-ROUTE-QUALIFICATION",
         "holder_function": "F-ROUTE", "contributing_function": "F-ALIGN",
         "state": "STANDING_DISSENT", "closed_by": None, "blocks_work": False,
         "holder_evidence_label": "DIRECTLY_REPRODUCED", "contributor_evidence_label": "DOCUMENTED"},
    ],
}


def nt_ledger_1(ledger):
    """A holder closes a conflict on HYPOTHESIS against reproduced evidence."""
    cf = ledger["conflicts"][0]
    cf.update({"state": "RESOLVED_BY_EVIDENCE", "closed_by": "F-ROUTE",
               "holder_evidence_label": "HYPOTHESIS",
               "contributor_evidence_label": "DIRECTLY_REPRODUCED"})
    return "a holder closes a conflict on hypothesis against reproduced evidence", ["L8"]


def nt_ledger_2(ledger):
    """An unresolved conflict is recorded as blocking work.

    No lane may idle pending a resolution: a standing dissent attaches to the work
    rather than stopping it.
    """
    ledger["conflicts"][0].update({"state": "OPEN", "blocks_work": True})
    return "an open conflict is recorded as blocking work", ["L9"]


def nt_ledger_3(ledger):
    """A dissent is filed with no conflict object, so it evaporates."""
    ledger["rows"][1]["conflict_id"] = None
    return "a dissent is recorded with no conflict object", ["L10"]


def nt_ledger_4(ledger):
    """A contribution row names the wrong holder, quietly re-assigning the class."""
    ledger["rows"][0]["holder_function"] = "F-CAPDEV"
    return "a contribution row names a holder that does not hold the class", ["L2"]


def nt_ledger_5(ledger):
    """A holder files itself as its own contributor, which makes overlap look like collaboration."""
    ledger["rows"][0]["contributing_function"] = "F-RESEARCH"
    return "a holder files itself as its own contributor", ["L4"]


LEDGER_CASES = [nt_ledger_1, nt_ledger_2, nt_ledger_3, nt_ledger_4, nt_ledger_5]


# ---------------------------------------------------------------------------
# derestrictctl failure modes
# ---------------------------------------------------------------------------

def nt_dr_1(reg):
    """A removed constraint loses the record of what its removal unlocks.

    Without it the removal is an assertion, and the next reader has no way to tell
    a considered de-restriction from a deleted control.
    """
    for c in reg["constraints"]:
        if c["verdict"] == "ASSISTANT_IMPOSED":
            c["removal_unlocks"] = ""
            break
    return "a removed constraint records no unlock", ["UNJUSTIFIED_VERDICT"]


def nt_dr_2(reg):
    """An earned control loses the defect it caught.

    This is the dangerous direction: a retained control with no cited defect is
    indistinguishable from an invented limit that survived the sweep.
    """
    for c in reg["constraints"]:
        if c["verdict"] == "EARNED_CONTROL":
            c["defect_caught"] = ""
            break
    return "an earned control cites no defect", ["UNJUSTIFIED_VERDICT"]


def nt_dr_3(reg):
    """A control is called earned on hypothesis evidence."""
    for c in reg["constraints"]:
        if c["verdict"] == "EARNED_CONTROL":
            c["evidence_label"] = "HYPOTHESIS"
            break
    return "a control claims to have caught a defect on hypothesis evidence", ["UNEARNED_CONTROL"]


def nt_dr_4(reg):
    """A founder-bound constraint loses its founder source, so it is unfalsifiable."""
    for c in reg["constraints"]:
        if c["verdict"] == "FOUNDER_BOUND":
            c["founder_source"] = ""
            break
    return "a founder-bound constraint cites no founder source", ["UNJUSTIFIED_VERDICT"]


def nt_dr_5(reg):
    """A constraint is quietly dropped without the counts moving.

    The estate's version of this is a wave that reports only its admissions and
    never its denominator.
    """
    reg["constraints"] = reg["constraints"][:-1]
    return "a constraint is dropped without the declared count moving", ["COUNT_MISMATCH"]


def nt_dr_6(reg):
    """A removed constraint keeps no re-inheritance probe, so it can silently return."""
    for c in reg["constraints"]:
        if c["verdict"] == "ASSISTANT_IMPOSED":
            c["reinheritance_probe"] = []
            break
    return "a removed constraint carries no re-inheritance probe", ["UNJUSTIFIED_VERDICT"]


DR_CASES = [nt_dr_1, nt_dr_2, nt_dr_3, nt_dr_4, nt_dr_5, nt_dr_6]


def run() -> int:
    role_reg = json.loads(ROLE_REGISTER.read_text(encoding="utf-8"))
    dr_reg = json.loads(DERESTRICT_REGISTER.read_text(encoding="utf-8"))

    failures = 0
    total = 0

    baseline = rolectl.check(copy.deepcopy(role_reg))
    if baseline:
        print("FAIL: the committed role register does not pass its own invariants")
        for x in baseline:
            print(f"   {x}")
        return 1
    baseline = derestrictctl.verify(copy.deepcopy(dr_reg))
    if baseline:
        print("FAIL: the committed de-restriction register does not pass its own integrity check")
        for x in baseline:
            print(f"   {x}")
        return 1
    baseline = rolectl.check_ledger(role_reg, copy.deepcopy(CLEAN_LEDGER))
    if baseline:
        print("FAIL: the clean contribution ledger does not validate")
        for x in baseline:
            print(f"   {x}")
        return 1
    print("baseline: committed registers and the clean ledger all validate\n")

    for i, case in enumerate(ROLE_CASES, start=1):
        total += 1
        mutated = copy.deepcopy(role_reg)
        desc, expect = case(mutated)
        found = rolectl.check(mutated)
        fired = {x.split()[0] for x in found}
        ok = all(any(e == f for f in fired) for e in expect)
        print(f"NR{i} {'REJECTED' if ok else 'LEAKED  '}: {desc}")
        for x in found[:3]:
            print(f"      {x}")
        if not ok:
            failures += 1
            print(f"      expected invariants {expect}, fired {sorted(fired)}")

    for i, case in enumerate(LEDGER_CASES, start=1):
        total += 1
        mutated = copy.deepcopy(CLEAN_LEDGER)
        desc, expect = case(mutated)
        found = rolectl.check_ledger(role_reg, mutated)
        fired = {x.split()[0] for x in found}
        ok = all(e in fired for e in expect)
        print(f"NL{i} {'REJECTED' if ok else 'LEAKED  '}: {desc}")
        for x in found[:3]:
            print(f"      {x}")
        if not ok:
            failures += 1
            print(f"      expected {expect}, fired {sorted(fired)}")

    for i, case in enumerate(DR_CASES, start=1):
        total += 1
        mutated = copy.deepcopy(dr_reg)
        desc, expect = case(mutated)
        found = derestrictctl.verify(mutated)
        fired = {x.split(":")[0] for x in found}
        ok = all(e in fired for e in expect)
        print(f"ND{i} {'REJECTED' if ok else 'LEAKED  '}: {desc}")
        for x in found[:3]:
            print(f"      {x}")
        if not ok:
            failures += 1
            print(f"      expected {expect}, fired {sorted(fired)}")

    print()
    if failures:
        print(f"FAIL: {failures} of {total} failure modes leaked through")
        return 1
    print(f"PASS: all {total} failure modes rejected by the validators")
    return 0


if __name__ == "__main__":
    sys.exit(run())
