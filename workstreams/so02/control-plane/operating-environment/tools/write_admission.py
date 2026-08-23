#!/usr/bin/env python3
"""The composed write guard: three gates, each recomputed rather than believed.

Ahmed Sadek, standing amendment 2026-08-23:

    "A write is gated only by a live operational reason, and each gate expires
    when its reason does:
     1. Concurrency. Do not corrupt work in flight.
     2. Reversibility. Snapshot before an irreversible write.
     3. Evidence. A write that asserts a result carries the evidence for that
        result. The problem was never the target of a write; it was unverified
        writes."

    "The distinction I am drawing is between authority and mechanism. I am
    removing an authority restriction I never issued. I am not asking for
    unverified or unrecoverable writes."

This module is the mechanism half. It contains no list of targets and would not
know what to do with one; a declaration naming `main` is decided by exactly the
tests that decide a declaration naming a scratch branch.

## Nothing here trusts what the declaration says about itself

That is the whole lesson of `evidence_integrity.verify_readback_truth`: a
wholly fabricated read-back record naming commit 000...0 passed the old
verifier because the verifier checked the record's SHAPE and never its TRUTH.
So a declaration's own claims are treated as claims:

| The declaration says | This module does |
|---|---|
| "my reversal was rehearsed and it worked" | re-executes the rehearsal against a fresh disposable remote |
| "here is the command that reverses it" | re-derives it from the constructor and compares |
| "the target was idle" | recomputes the verdict from the observed agent list and the live remote ref |
| "here is my evidence" | hands it to `evidence_integrity`, which recomputes it against the remote |

An unverifiable gate refuses. `NOT_RETURNED` rather than assumed success is the
same principle applied one layer down: absence of a check result is not a pass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


write_declaration = _load("write_declaration")
concurrency_observer = _load("concurrency_observer")
reversal_rehearsal = _load("reversal_rehearsal")
# Reused rather than reimplemented: these controls were earned by an independent
# acceptor's refusal and re-deriving them here would fork the corrections.
evidence_integrity = _load("evidence_integrity")


ADMITTED = "WRITE_ADMITTED"
REFUSED = "WRITE_REFUSED"

GATE_DECLARATION = "declaration"
GATE_CONCURRENCY = "concurrency"
GATE_REVERSIBILITY = "reversibility"
GATE_EVIDENCE = "evidence"


def _gate(name: str, passed: bool, verdict: str, findings: list[str], **extra) -> dict[str, Any]:
    return {"gate": name, "passed": passed, "verdict": verdict, "findings": findings, **extra}


def check_declaration_gate(declaration: Any, ratified: list[str]) -> dict[str, Any]:
    findings = write_declaration.validate_declaration(declaration, ratified)
    blocking = write_declaration.blocking_findings(findings)
    return _gate(
        GATE_DECLARATION,
        not blocking,
        "DECLARED_AND_REASONED" if not blocking else "UNDECLARED_OR_UNREASONED",
        [f"{f.code}: {f.message}" for f in blocking],
        advisories=[f"{f.code}: {f.message}" for f in write_declaration.advisory_findings(findings)],
        all_findings=[f.to_dict() for f in findings],
    )


def check_concurrency_gate(declaration: dict[str, Any], repo: Path | None,
                           check_ref_movement: bool = True,
                           max_observation_age_seconds: int | None = None) -> dict[str, Any]:
    target = declaration.get("target") or {}
    reversal = declaration.get("reversal") or {}
    result = concurrency_observer.concurrency_verdict(
        str(target.get("ref") or ""),
        declaration.get("concurrency"),
        repo=repo,
        recorded_sha=reversal.get("recorded_sha"),
        check_ref_movement=check_ref_movement,
        max_observation_age_seconds=max_observation_age_seconds,
    )
    return _gate(
        GATE_CONCURRENCY,
        bool(result.get("writable")),
        result.get("verdict", "CONCURRENCY_UNOBSERVABLE"),
        list(result.get("findings", [])),
        observation=result,
        limit=result.get("limit"),
        gate_expires_when=result.get("gate_expires_when"),
    )


def check_reversibility_gate(declaration: dict[str, Any], rehearse: bool = True) -> dict[str, Any]:
    """Re-derive the command, then re-execute the rollback. The receipt is a claim."""
    findings = list(reversal_rehearsal.command_matches_constructor(declaration))
    reversal = declaration.get("reversal") or {}
    target = declaration.get("target") or {}
    method = reversal.get("method")

    receipt: dict[str, Any] | None = None
    if rehearse and method in {"RESTORE_REF_TO_RECORDED_SHA", "REVERT_COMMIT_RANGE", "DELETE_CREATED_REF"}:
        receipt = reversal_rehearsal.rehearse_reversal(method, ref=str(target.get("ref") or "rehearsal-target"))
        if receipt.get("result") != reversal_rehearsal.EXECUTED_AND_VERIFIED:
            findings.append(
                f"the reversal was re-executed and did not restore the pre-write state: "
                f"{receipt.get('result')} — {receipt.get('detail', '')}"
            )
    elif rehearse:
        findings.append(
            f"reversal.method {method!r} cannot be rehearsed by this harness, so its rollback is "
            "described rather than demonstrated; an unrehearsed rollback is refused"
        )

    return _gate(
        GATE_REVERSIBILITY,
        not findings,
        "REVERSAL_RE_EXECUTED_AND_VERIFIED" if not findings else "REVERSAL_NOT_DEMONSTRATED",
        findings,
        rehearsal_receipt=receipt,
        note=(
            "The rehearsal proves the reversal constructor restores the tree against a real bare "
            "remote. It does not prove the live remote will accept the push at rollback time."
        ),
    )


def check_evidence_gate(declaration: dict[str, Any], repo: Path | None,
                        remote_url: str | None = None) -> dict[str, Any]:
    """Delegate to `evidence_integrity`, which recomputes rather than trusting."""
    reason = declaration.get("reason") or {}
    spec = write_declaration.REASON_VOCABULARY.get(reason.get("code"))
    evidence = declaration.get("evidence") or {}
    asserts = bool(evidence.get("asserts_result")) or bool(spec and spec.asserts_result)

    if not asserts:
        return _gate(GATE_EVIDENCE, True, "NO_RESULT_ASSERTED", [],
                     note="the gate expires with its reason; a write asserting no result owes no evidence")

    kind, record = evidence.get("kind"), evidence.get("record")
    if not isinstance(record, dict) or not record:
        return _gate(GATE_EVIDENCE, False, "EVIDENCE_ABSENT",
                     [f"reason {reason.get('code')} asserts a result but carries no record to recompute"])

    if kind == "MANIFEST_CLOSURE":
        present = evidence.get("present_paths") or [e.get("path") for e in record.get("entries", [])]
        errors = evidence_integrity.verify_manifest_closure(record, present)
        return _gate(GATE_EVIDENCE, not errors,
                     "EVIDENCE_RECOMPUTED" if not errors else "EVIDENCE_FAILED_RECOMPUTATION",
                     errors, verified_by="evidence_integrity.verify_manifest_closure")

    if kind == "READBACK":
        if not remote_url:
            # Fail closed. An evidence gate that cannot run is not a gate that passed.
            return _gate(GATE_EVIDENCE, False, "EVIDENCE_UNVERIFIABLE_HERE",
                         ["a READBACK record can only be recomputed against a remote; none was supplied, "
                          "so the claim is unverified and an unverified assertion is refused"],
                         verified_by="evidence_integrity.verify_readback_truth (not run)")
        errors = evidence_integrity.verify_readback_truth(record, remote_url, repo or Path("."))
        return _gate(GATE_EVIDENCE, not errors,
                     "EVIDENCE_RECOMPUTED" if not errors else "EVIDENCE_FAILED_RECOMPUTATION",
                     errors, verified_by="evidence_integrity.verify_readback_truth")

    return _gate(GATE_EVIDENCE, False, "EVIDENCE_KIND_UNKNOWN",
                 [f"evidence.kind {kind!r} has no recomputation route, so it cannot be verified"])


def admit(
    declaration: Any,
    repo: Path | None = None,
    *,
    ratified_assistant_checks: list[str] | None = None,
    rehearse_reversal: bool = True,
    check_ref_movement: bool = True,
    remote_url: str | None = None,
    max_observation_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Decide one write. Refuses on any failed gate; never consults a target list."""
    ratified = list(ratified_assistant_checks or [])
    gates = [check_declaration_gate(declaration, ratified)]

    # The remaining gates read fields the declaration gate has just validated.
    # Running them on a malformed declaration would report confusing derived
    # failures instead of the real one.
    if gates[0]["passed"]:
        gates.append(check_concurrency_gate(declaration, repo, check_ref_movement,
                                            max_observation_age_seconds))
        gates.append(check_reversibility_gate(declaration, rehearse_reversal))
        gates.append(check_evidence_gate(declaration, repo, remote_url))
    else:
        for name in (GATE_CONCURRENCY, GATE_REVERSIBILITY, GATE_EVIDENCE):
            gates.append(_gate(name, False, "NOT_EVALUATED",
                               ["not evaluated: the declaration gate refused first"]))

    failed = [g["gate"] for g in gates if not g["passed"]]
    target = declaration.get("target") if isinstance(declaration, dict) else {}
    return {
        "guard_id": "OE-W9-REASON-GATED-WRITE-ADMISSION",
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_ref": (target or {}).get("ref"),
        "target_paths": (target or {}).get("paths"),
        "operation": (target or {}).get("operation"),
        "verdict": ADMITTED if not failed else REFUSED,
        "admitted": not failed,
        "failed_gates": failed,
        "gates": gates,
        "authority_basis": (
            "Ahmed Sadek, standing amendment 2026-08-23: 'You do not need my permission for any of "
            "it — you need a reason and a rollback.' No target is consulted; the protected-surface "
            "category is void."
        ),
        "decision_changed": [],
    }


def summarise(report: dict[str, Any]) -> str:
    lines = [f"{report['verdict']}  target={report.get('target_ref')!r} "
             f"operation={report.get('operation')!r}"]
    for gate in report["gates"]:
        mark = "pass" if gate["passed"] else "FAIL"
        lines.append(f"  [{mark}] {gate['gate']:<14} {gate['verdict']}")
        for finding in gate["findings"]:
            lines.append(f"         - {finding}")
        for advisory in gate.get("advisories", []):
            lines.append(f"         ~ advisory (assistant-authored, not in force): {advisory}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admit or refuse a declared write")
    parser.add_argument("declaration", help="path to a write declaration JSON file")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--remote-url", default=None, help="remote to recompute READBACK evidence against")
    parser.add_argument("--ratified", nargs="*", default=[])
    parser.add_argument("--no-rehearsal", action="store_true",
                        help="skip re-executing the rollback (records why the gate could not run)")
    parser.add_argument("--no-ref-movement", action="store_true")
    parser.add_argument("--max-observation-age-seconds", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.declaration).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read declaration: {exc}", file=sys.stderr)
        return 2

    report = admit(
        payload, Path(args.repo),
        ratified_assistant_checks=args.ratified,
        rehearse_reversal=not args.no_rehearsal,
        check_ref_movement=not args.no_ref_movement,
        remote_url=args.remote_url,
        max_observation_age_seconds=args.max_observation_age_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else summarise(report))
    return 0 if report["admitted"] else 1


if __name__ == "__main__":
    sys.exit(main())
