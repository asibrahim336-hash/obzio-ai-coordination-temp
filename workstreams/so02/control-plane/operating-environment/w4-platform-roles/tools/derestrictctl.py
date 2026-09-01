#!/usr/bin/env python3
"""derestrictctl — keep removed restrictions removed, and keep earned ones earned.

Two subcommands.

    verify   Structural check of the de-restriction register itself. Every record
             must carry the fields its verdict requires, so a verdict can never be
             asserted without the thing that justifies it.

    scan     Search the estate for a removed restriction reappearing in a surface
             that routes work. This is the part that has to exist, because a
             restriction that was written down three times and superseded twice is
             re-readable out of any of the remaining copies.

The distinction that makes `scan` usable rather than noisy: a routing surface tells
an actor what to do next; an evidence surface records what was once believed.
A removed restriction matching inside an evidence surface is correct and expected,
because superseded files remain evidence rather than being deleted. The same string
inside a commission, a control-plane record or a launch packet is a re-inheritance
and fails closed.

Exit codes: 0 clean, 1 findings, 2 usage or integrity error.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import re
import sys

# Surfaces that route work. A removed restriction appearing here is a finding.
DEFAULT_ROUTING_SURFACES = [
    "workstreams/so02/control-plane/commissions/**",
    "workstreams/so02/control-plane/launch/**",
    "workstreams/so02/control-plane/state/control-plane.json",
    "workstreams/so02/control-plane/state/FOUNDER-OPERATING-DIRECTIVES-*.md",
    "workstreams/so02/control-plane/contracts/**",
    "state/operator-system/**",
    "operations/**",
    "AGENTS.md",
]

# Surfaces that record what was once believed. Matches here are expected.
DEFAULT_EVIDENCE_SURFACES = [
    "workstreams/so02/control-plane/operating-environment/**",
    "receipts/**",
    "dispatch/**",
    "workstreams/so02/control-plane/research/**",
    "workstreams/so02/control-plane/sources/**",
    "workstreams/so02/control-plane/errors/**",
]

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".py", ".yml", ".yaml", ".mdc", ".sh", ".tsv"}

# A routing surface may legitimately *name* a removed restriction in order to
# supersede it. The first version of this scanner did not know that and reported
# three supersession sentences as re-inheritances, including the founder's own
# "SO-02 does not impose an architectural one-agent ceiling". A detector that
# fires on the sentence removing a restriction is a detector that gets switched
# off, so the match is read in context before it is called a finding.
NEGATION_MARKERS = [
    r"supersede[sd]?", r"superseding", r"does\s+not\s+impose", r"do\s+not\s+impose",
    r"not\s+inherited", r"no\s+longer", r"rather\s+than\s+applying", r"rather\s+than\s+inherit",
    r"withdrawn", r"removed\s+as", r"is\s+removed", r"was\s+removed", r"remains?\s+historical",
    r"not\s+a\s+continuing\s+limit", r"completed_and_not_inherited", r"assistant_imposed",
    r"prohibited\s+as\s+wasteful", r"stop\s+claiming", r"closed\s+as", r"disposition",
]
NEGATION_RE = re.compile("|".join(NEGATION_MARKERS), re.IGNORECASE)
NEGATION_WINDOW = 260

REQUIRED_FIELDS = {
    "FOUNDER_BOUND": ["founder_source", "justification"],
    "EARNED_CONTROL": ["introduced_in", "defect_caught", "defect_evidence_path"],
    "ASSISTANT_IMPOSED": [
        "introduced_in",
        "why_not_founder_bound_and_no_defect_evidence",
        "removal_unlocks",
        "replacement_control_retained",
        "reinheritance_probe",
    ],
}

VALID_LABELS = {"DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS"}


def load_register(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: register not found at {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"ERROR: register is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)


def verify(register: dict) -> list[str]:
    findings: list[str] = []
    constraints = register.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        return ["REGISTER_EMPTY: no constraints"]

    seen: set[str] = set()
    counts = {k: 0 for k in REQUIRED_FIELDS}

    for c in constraints:
        cid = c.get("constraint_id", "<missing id>")
        verdict = c.get("verdict")

        if cid in seen:
            findings.append(f"DUPLICATE_ID: {cid}")
        seen.add(cid)

        if verdict not in REQUIRED_FIELDS:
            findings.append(f"UNKNOWN_VERDICT: {cid} has verdict {verdict!r}")
            continue
        counts[verdict] += 1

        for field in REQUIRED_FIELDS[verdict]:
            value = c.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                findings.append(
                    f"UNJUSTIFIED_VERDICT: {cid} is {verdict} but {field} is missing or empty"
                )

        label = c.get("evidence_label")
        if label not in VALID_LABELS:
            findings.append(f"MISSING_EVIDENCE_LABEL: {cid} carries {label!r}")

        if verdict == "EARNED_CONTROL" and label == "HYPOTHESIS":
            findings.append(
                f"UNEARNED_CONTROL: {cid} claims to have caught a real defect on HYPOTHESIS evidence"
            )

        if verdict == "ASSISTANT_IMPOSED":
            probes = c.get("reinheritance_probe") or []
            for pattern in probes:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    findings.append(f"BAD_PROBE: {cid} pattern {pattern!r} does not compile: {exc}")

    declared = register.get("counts") or {}
    for verdict, n in counts.items():
        if declared.get(verdict) != n:
            findings.append(
                f"COUNT_MISMATCH: {verdict} declared {declared.get(verdict)} but {n} records present"
            )
    if register.get("total_classified") != len(constraints):
        findings.append(
            f"COUNT_MISMATCH: total_classified {register.get('total_classified')} != {len(constraints)} records"
        )

    return findings


def _matches_any(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        # fnmatch does not treat ** as spanning separators; emulate a prefix match.
        if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-2])):
            return True
    return False


def _walk(root: pathlib.Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules"}]
        for name in filenames:
            p = pathlib.Path(dirpath) / name
            if p.suffix.lower() in TEXT_SUFFIXES:
                yield p


def scan(register: dict, root: pathlib.Path, routing: list[str], evidence: list[str],
         exclude: list[str]) -> tuple[list[str], list[dict]]:
    removed = [c for c in register["constraints"] if c["verdict"] == "ASSISTANT_IMPOSED"]
    compiled = {
        c["constraint_id"]: [re.compile(p, re.IGNORECASE) for p in c.get("reinheritance_probe", [])]
        for c in removed
    }

    routing_files: list[tuple[str, str]] = []
    supersession_files: list[tuple[str, str]] = []
    evidence_hits: dict[str, int] = {c["constraint_id"]: 0 for c in removed}

    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        if _matches_any(rel, exclude):
            continue
        in_routing = _matches_any(rel, routing)
        in_evidence = _matches_any(rel, evidence)
        if not in_routing and not in_evidence:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for cid, patterns in compiled.items():
            live = False
            superseded = False
            for pattern in patterns:
                for m in pattern.finditer(text):
                    window = text[max(0, m.start() - NEGATION_WINDOW): m.end() + NEGATION_WINDOW]
                    if NEGATION_RE.search(window):
                        superseded = True
                    else:
                        live = True
                        break
                if live:
                    break
            if not live and not superseded:
                continue
            if in_routing:
                (routing_files if live else supersession_files).append((cid, rel))
            else:
                evidence_hits[cid] += 1

    findings = [
        f"RE_INHERITED: {cid} routes work from {rel}"
        for cid, rel in sorted(set(routing_files))
    ]
    status = []
    for c in removed:
        cid = c["constraint_id"]
        hits = evidence_hits[cid]
        in_routing = any(x[0] == cid for x in routing_files)
        in_supersession = any(x[0] == cid for x in supersession_files)
        if in_routing:
            state = "RE_INHERITED"
        elif in_supersession:
            state = "SUPERSESSION_STATEMENT"
        elif hits:
            state = "EVIDENCE_ONLY"
        else:
            state = "RETIRED"
        status.append(
            {
                "constraint_id": cid,
                "state": state,
                "evidence_surface_hits": hits,
                "routing_surfaces": sorted({r for c2, r in routing_files if c2 == cid}),
                "supersession_surfaces": sorted({r for c2, r in supersession_files if c2 == cid}),
                "statement": c["statement"],
            }
        )
    return findings, status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["verify", "scan"])
    ap.add_argument("--register", default=str(pathlib.Path(__file__).resolve().parents[1]
                                              / "DE-RESTRICTION-REGISTER-20260822-v001.json"))
    ap.add_argument("--root", default=".")
    ap.add_argument("--routing-surface", action="append", default=None)
    ap.add_argument("--evidence-surface", action="append", default=None)
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = ap.parse_args()

    register = load_register(pathlib.Path(args.register))

    if args.command == "verify":
        findings = verify(register)
        if args.json:
            print(json.dumps({"command": "verify", "findings": findings}, indent=2))
        else:
            for f in findings:
                print(f"ERROR: {f}")
            c = register.get("counts", {})
            print(
                f"register {register.get('register_id')}: "
                f"{register.get('total_classified')} constraints "
                f"(FOUNDER_BOUND={c.get('FOUNDER_BOUND')} "
                f"EARNED_CONTROL={c.get('EARNED_CONTROL')} "
                f"ASSISTANT_IMPOSED={c.get('ASSISTANT_IMPOSED')})"
            )
            print("PASS: every verdict carries the evidence its class requires"
                  if not findings else f"FAIL: {len(findings)} integrity finding(s)")
        return 1 if findings else 0

    root = pathlib.Path(args.root).resolve()
    routing = args.routing_surface or DEFAULT_ROUTING_SURFACES
    evidence = args.evidence_surface or DEFAULT_EVIDENCE_SURFACES
    findings, status = scan(register, root, routing, evidence, args.exclude)

    if args.json:
        print(json.dumps({"command": "scan", "root": str(root), "findings": findings,
                          "status": status}, indent=2))
    else:
        for f in findings:
            print(f"ERROR: {f}")
        by_state: dict[str, int] = {}
        for s in status:
            by_state[s["state"]] = by_state.get(s["state"], 0) + 1
        print("removed-restriction states  " + "  ".join(
            f"{k}={v}" for k, v in sorted(by_state.items())))
        for s in status:
            if s["state"] != "RETIRED":
                print(f"  {s['state']:<14} {s['constraint_id']}  {s['statement'][:78]}")
        print("PASS: no removed restriction routes work" if not findings
              else f"FAIL: {len(findings)} re-inheritance finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
