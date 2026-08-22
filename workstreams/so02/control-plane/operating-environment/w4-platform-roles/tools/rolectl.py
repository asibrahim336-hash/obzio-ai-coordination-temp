#!/usr/bin/env python3
"""rolectl — check the platform role register's invariants.

The founder's condition on overlapping roles is that authority, provenance,
conflicts and acceptance remain visible. Visibility that is only asserted decays;
these fourteen invariants are what make it hold.

    python3 tools/rolectl.py check   [--register PATH]
    python3 tools/rolectl.py ledger  --ledger PATH [--register PATH]

`check` validates the register. `ledger` validates a contribution ledger against
it, which is the part that runs every wave once functions start collaborating.

Exit codes: 0 all invariants hold, 1 one or more violated, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

VALID_LABELS = {"DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS", "FOUNDER_SUPPLIED"}
FOUNDER_HOLDER = "FOUNDER"
ASSURANCE_FUNCTIONS = {"F-EVAL", "F-ACCEPT", "F-REDTEAM", "F-PROVAUDIT"}
CONFLICT_STATES = {"OPEN", "RESOLVED_BY_EVIDENCE", "RESOLVED_BY_FOUNDER", "STANDING_DISSENT"}
POSITIONS = {"agree", "dissent", "abstain"}

INVARIANTS = {
    "I1": "every function carries a complete authority envelope",
    "I2": "every function names an appointment that is not merely its runtime",
    "I3": "every function names a return and evaluation route",
    "I4": "every function carries an evidence label from the declared set",
    "I5": "a runtime binding never stands in for authority",
    "I6": "every decision class has exactly one holder",
    "I7": "founder-reserved classes are claimed by no function",
    "I8": "no function has an empty decides set",
    "I9": "informs and must_not_decide reference real classes and never a class the function holds",
    "I10": "no function may decide a class it also declares it must not decide",
    "I11": "no function is its own acceptance owner",
    "I12": "no assurance function accepts a class it decides, and assurance owners are reciprocal",
    "I13": "every function names a substitution route",
    "I14": "every platform-bound function binds to a declared platform",
}


def load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def check(reg: dict) -> list[str]:
    v: list[str] = []
    functions = reg.get("functions", [])
    classes = reg.get("decision_classes", [])
    platforms = {p["platform_id"] for p in reg.get("platforms", [])}

    class_ids = {c["class_id"] for c in classes}
    reserved = {c["class_id"] for c in classes if c.get("holder_function") == FOUNDER_HOLDER}
    fn_ids = {f["function_id"] for f in functions}

    # I6 / I7 — partition and reserved classes.
    holders: dict[str, list[str]] = {cid: [] for cid in class_ids}
    for f in functions:
        for cid in f.get("decides", []):
            if cid not in class_ids:
                v.append(f"I6 {f['function_id']} decides unknown class {cid}")
                continue
            holders[cid].append(f["function_id"])
    for cid, hs in holders.items():
        declared = next(c for c in classes if c["class_id"] == cid).get("holder_function")
        if cid in reserved:
            if hs:
                v.append(f"I7 founder-reserved class {cid} is claimed by {hs}")
            continue
        if len(hs) != 1:
            v.append(f"I6 {cid} has {len(hs)} holders: {hs}")
        elif hs[0] != declared:
            v.append(f"I6 {cid} declares holder {declared} but {hs[0]} decides it")

    for f in functions:
        fid = f["function_id"]
        env = f.get("authority_envelope") or {}

        # I1 / I2 / I3 / I5 — the envelope, and authority separated from runtime.
        for field in ("appointment", "authority", "runtime_binding", "return_and_evaluation_route"):
            if not (env.get(field) or "").strip():
                v.append(f"I1 {fid} authority envelope is missing {field}")
        appointment = (env.get("appointment") or "").strip()
        runtime = (env.get("runtime_binding") or "").strip()
        if appointment and runtime and appointment == runtime:
            v.append(f"I2 {fid} names its runtime as its appointment; a runtime never grants authority")
        authority = (env.get("authority") or "").strip()
        if authority and runtime and authority == runtime:
            v.append(f"I5 {fid} states its runtime binding as its authority")
        if not (env.get("return_and_evaluation_route") or "").strip():
            v.append(f"I3 {fid} names no return and evaluation route")

        # I4 — evidence label.
        if f.get("evidence_label") not in VALID_LABELS:
            v.append(f"I4 {fid} carries evidence label {f.get('evidence_label')!r}")

        # I8 — decorative functions.
        if not f.get("decides"):
            v.append(f"I8 {fid} has an empty decides set")

        # I9 / I10 — informs and must_not_decide.
        for cid in f.get("informs", []):
            if cid not in class_ids:
                v.append(f"I9 {fid} informs unknown class {cid}")
            elif cid in f.get("decides", []):
                v.append(f"I9 {fid} lists {cid} as both decides and informs")
        for cid in f.get("must_not_decide", []):
            if cid not in class_ids:
                v.append(f"I9 {fid} must_not_decide references unknown class {cid}")
            elif cid in f.get("decides", []):
                v.append(f"I10 {fid} both decides and must-not-decide {cid}")

        # I11 / I12 — acceptance independence.
        owner = (f.get("acceptance_owner") or "").strip()
        if not owner:
            v.append(f"I11 {fid} names no acceptance owner")
        elif owner.split()[0] == fid:
            v.append(f"I11 {fid} is its own acceptance owner")

        # I13 — substitution.
        if not (f.get("substitution_route") or "").strip():
            v.append(f"I13 {fid} names no substitution route, which is how exclusive dependency accumulates")

        # I14 — platform binding.
        if f.get("platform_binding") not in platforms:
            v.append(f"I14 {fid} binds to undeclared platform {f.get('platform_binding')!r}")

    # I12 — the acceptor's acceptor must be an adversary, not itself and not a producer it grades.
    by_id = {f["function_id"]: f for f in functions}
    for fid in ("F-ACCEPT", "F-REDTEAM"):
        f = by_id.get(fid)
        if not f:
            v.append(f"I12 {fid} is absent; acceptance has no reciprocal owner")
            continue
        owner = (f.get("acceptance_owner") or "").split()[0]
        if owner not in ASSURANCE_FUNCTIONS or owner == fid:
            v.append(f"I12 {fid} acceptance owner {owner!r} is not a distinct assurance function")
    if by_id.get("F-ACCEPT") and by_id.get("F-REDTEAM"):
        a = by_id["F-ACCEPT"]["acceptance_owner"].split()[0]
        r = by_id["F-REDTEAM"]["acceptance_owner"].split()[0]
        if not (a == "F-REDTEAM" and r == "F-ACCEPT"):
            v.append("I12 acceptance and red team are not reciprocal acceptance owners")

    # Cross-check: every non-founder class holder is a real function.
    for c in classes:
        h = c.get("holder_function")
        if h != FOUNDER_HOLDER and h not in fn_ids:
            v.append(f"I6 class {c['class_id']} names holder {h} which is not a declared function")

    return v


def check_ledger(reg: dict, ledger: dict) -> list[str]:
    v: list[str] = []
    class_ids = {c["class_id"] for c in reg.get("decision_classes", [])}
    holders = {c["class_id"]: c["holder_function"] for c in reg.get("decision_classes", [])}
    fn_ids = {f["function_id"] for f in reg.get("functions", [])}

    for i, row in enumerate(ledger.get("rows", [])):
        tag = row.get("row_id", f"row[{i}]")
        cid = row.get("decision_class")
        if cid not in class_ids:
            v.append(f"L1 {tag} references unknown decision class {cid!r}")
            continue
        if row.get("holder_function") != holders[cid]:
            v.append(f"L2 {tag} names holder {row.get('holder_function')!r} but {cid} is held by {holders[cid]}")
        contributor = row.get("contributing_function")
        if contributor not in fn_ids:
            v.append(f"L3 {tag} contributor {contributor!r} is not a declared function")
        if contributor == holders[cid]:
            v.append(f"L4 {tag} records the holder as its own contributor; a holder acting inside its own class is not a contribution")
        if row.get("position") not in POSITIONS:
            v.append(f"L5 {tag} position {row.get('position')!r} is not agree, dissent or abstain")
        if row.get("evidence_label") not in VALID_LABELS:
            v.append(f"L6 {tag} carries evidence label {row.get('evidence_label')!r}")

    conflicts = {c.get("conflict_id"): c for c in ledger.get("conflicts", [])}
    for cf_id, cf in conflicts.items():
        if cf.get("state") not in CONFLICT_STATES:
            v.append(f"L7 conflict {cf_id} state {cf.get('state')!r} is not a declared conflict state")
        # Evidence outranks ownership.
        if cf.get("state") == "RESOLVED_BY_EVIDENCE" and cf.get("closed_by") == cf.get("holder_function"):
            if cf.get("contributor_evidence_label") == "DIRECTLY_REPRODUCED" and \
               cf.get("holder_evidence_label") == "HYPOTHESIS":
                v.append(
                    f"L8 conflict {cf_id} was closed by the holder on HYPOTHESIS against a "
                    f"DIRECTLY_REPRODUCED contribution; evidence outranks ownership"
                )
        if cf.get("state") == "OPEN" and cf.get("blocks_work") is True:
            v.append(f"L9 conflict {cf_id} is recorded as blocking work; an unresolved conflict attaches to the work as a standing dissent and does not stop it")

    for i, row in enumerate(ledger.get("rows", [])):
        cf_id = row.get("conflict_id")
        if row.get("position") == "dissent" and not cf_id:
            v.append(f"L10 row[{i}] records a dissent with no conflict object")
        if cf_id and cf_id not in conflicts:
            v.append(f"L11 row[{i}] references conflict {cf_id!r} which is not declared")

    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "ledger"])
    ap.add_argument("--register", default=str(pathlib.Path(__file__).resolve().parents[1]
                                              / "PLATFORM-ROLE-REGISTER-20260822-v001.json"))
    ap.add_argument("--ledger")
    args = ap.parse_args()

    reg = load(pathlib.Path(args.register))

    if args.command == "check":
        violations = check(reg)
        for x in violations:
            print(f"VIOLATION: {x}")
        print(f"platforms {len(reg.get('platforms', []))}  "
              f"decision classes {len(reg.get('decision_classes', []))}  "
              f"functions {len(reg.get('functions', []))}")
        print(f"PASS: all {len(INVARIANTS)} invariants hold" if not violations
              else f"FAIL: {len(violations)} violation(s)")
        return 1 if violations else 0

    if not args.ledger:
        print("ERROR: ledger command requires --ledger", file=sys.stderr)
        return 2
    ledger = load(pathlib.Path(args.ledger))
    violations = check_ledger(reg, ledger)
    for x in violations:
        print(f"VIOLATION: {x}")
    print(f"ledger rows {len(ledger.get('rows', []))}  conflicts {len(ledger.get('conflicts', []))}")
    print("PASS: contribution ledger is consistent with the register" if not violations
          else f"FAIL: {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
