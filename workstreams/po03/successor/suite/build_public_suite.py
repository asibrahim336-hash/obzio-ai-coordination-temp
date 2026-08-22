#!/usr/bin/env python3
"""Build (or verify) the frozen public case set for the successor-generation test.

The public suite is data, not code, so that a controller written before the
suite existed can still be scored by it.  It is generated from this script
rather than hand-written because thirty cases share a lot of scaffolding and
hand-copied scaffolding is where suite bugs live.  Both the script and its
output are committed, and ``--check`` asserts the committed JSON still matches
the script, so "frozen" is an enforced property rather than a claim.

Case design rule: every case asserts an observable custody property drawn from
the commission's transactional-result custody section, and no case asserts an
implementation detail of any single generation.  Cases are written before the
generations are scored, and none is edited afterwards to change an outcome.

    python3 -I workstreams/po03/successor/suite/build_public_suite.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SUITE_ID = "po03-a8-public-custody-suite-v001"
OWNER = "po03-worker-a8"
OWNED = ["workstreams/po03/successor/", "workstreams/po03/control/units/a8/"]
ARTIFACT = "workstreams/po03/successor/scores/probe.json"
COMMIT = "1f0e4c2b9a7d5e3f8c1b6a4d2e9f7c5b3a1d8e6f"
BAD_SHA = "1" * 64
ZERO_SHA = "0" * 64


def spec(**overrides: Any) -> dict[str, Any]:
    base = {
        "owner": OWNER,
        "owned_prefixes": list(OWNED),
        "acceptance": {"assertion": "the unit leaves a durable, hash-verified result"},
        "pinned_inputs": {"workstreams/po03/COMMISSION.md": ZERO_SHA},
    }
    base.update(overrides)
    return base


def create(unit: str = "u1", **overrides: Any) -> dict[str, Any]:
    return {"label": "create", "op": "create", "args": {"unit_id": unit, "spec": spec(**overrides)}}


def lease(worker: str = "w1", ttl: int = 3600, label: str = "lease") -> dict[str, Any]:
    return {"label": label, "op": "lease", "args": {"unit_id": "u1", "worker": worker, "ttl": ttl}}


def write_artifact(path: str = ARTIFACT, label: str = "write") -> dict[str, Any]:
    return {
        "label": label,
        "op": "write_artifact",
        "args": {"path": path, "content": '{"probe":"durable result bytes"}'},
    }


def artifact(path: str = ARTIFACT, artifact_id: str = "art-01", **overrides: Any) -> dict[str, Any]:
    entry = {"artifact_id": artifact_id, "path": path, "sha256": "@auto", "bytes": "@auto"}
    entry.update(overrides)
    return entry


def submit(label: str = "submit", **overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "unit_id": "u1",
        "worker": "w1",
        "fence_token": 1,
        "provider_state": "COMPLETED",
        "claimed_state": "RESULT_COMMITTED",
        "artifacts": [artifact()],
        "result_commit_id": COMMIT,
        "readback_verified": True,
        "idempotency_key": "u1:key-001",
    }
    args.update(overrides)
    return {"label": label, "op": "submit", "args": args}


def ingest(label: str = "ingest", actor: str = "coordinator") -> dict[str, Any]:
    return {"label": label, "op": "ingest", "args": {"unit_id": "u1", "actor": actor}}


def complete(actor: str = "coordinator", label: str = "complete") -> dict[str, Any]:
    return {"label": label, "op": "complete", "args": {"unit_id": "u1", "actor": actor}}


def observe(label: str = "observe") -> dict[str, Any]:
    return {"label": label, "op": "state", "args": {"unit_id": "u1"}}


def verify(label: str = "verify") -> dict[str, Any]:
    return {"label": label, "op": "verify", "args": {}}


def recover(label: str = "recover") -> dict[str, Any]:
    return {"label": label, "op": "recover", "args": {}}


def reason(step: str, code: str) -> dict[str, Any]:
    return {"check": "reason_code", "step": step, "expect": code}


def reason_in(step: str, codes: list[str]) -> dict[str, Any]:
    return {"check": "reason_code", "step": step, "one_of": codes}


def admitted(step: str, expect: bool = True) -> dict[str, Any]:
    return {"check": "admitted", "step": step, "expect": expect}


def detail(step: str, path: str, **kind: Any) -> dict[str, Any]:
    entry = {"check": "detail", "step": step, "path": path}
    entry.update(kind)
    return entry


def case(
    case_id: str,
    family: str,
    intent: str,
    steps: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    *,
    critical: bool = False,
    safety_class: str | None = None,
    criteria: list[str] | None = None,
    commission_basis: str = "",
) -> dict[str, Any]:
    return {
        "id": case_id,
        "family": family,
        "intent": intent,
        "critical": critical,
        "safety_class": safety_class,
        "criteria": criteria or [],
        "commission_basis": commission_basis,
        "steps": steps,
        "assert": assertions,
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # -- F1 immutable dispatch input ---------------------------------------

    cases.append(
        case(
            "P01-dispatch-input-durably-recorded",
            "dispatch_durability",
            "Immutable task input is durably recorded before dispatch and is readable afterwards.",
            [create(), observe()],
            [
                admitted("create"),
                detail("create", "input_manifest_sha256", absent=False),
                admitted("observe"),
            ],
            criteria=["C3"],
            commission_basis="Before dispatch, durably write immutable task input, configuration, source hashes.",
        )
    )
    cases.append(
        case(
            "P02-acceptance-contract-hashed-at-dispatch",
            "dispatch_durability",
            "The frozen acceptance contract is hashed at dispatch so it cannot be renegotiated later.",
            [create()],
            [detail("create", "acceptance_contract_sha256", absent=False)],
            criteria=["C3"],
            commission_basis="durably write ... acceptance hashes ... before dispatch.",
        )
    )
    cases.append(
        case(
            "P03-idempotency-key-issued-at-dispatch",
            "dispatch_durability",
            "An idempotency key is issued at dispatch so retries can be deduplicated.",
            [create()],
            [detail("create", "idempotency_key", absent=False)],
            criteria=["C5", "C6"],
            commission_basis="durably write ... idempotency key, lease and fence token.",
        )
    )
    cases.append(
        case(
            "P04-acceptance-contract-tamper-detected",
            "dispatch_durability",
            "Editing the frozen acceptance contract after dispatch is detected rather than silently honoured.",
            [
                create(),
                {
                    "label": "tamper",
                    "op": "tamper",
                    "args": {
                        "target": "record",
                        "kind": "edit",
                        "unit_id": "u1",
                        "fields": {"acceptance": {"assertion": "anything the producer likes"}},
                    },
                },
                verify(),
            ],
            [detail("verify", "input_tampered", expect=["u1"])],
            critical=True,
            criteria=["C3"],
            commission_basis="immutable task input ... acceptance hashes written before dispatch.",
        )
    )
    cases.append(
        case(
            "P05-pinned-input-drift-detected",
            "dispatch_durability",
            "Drift in a pinned input hash is detected by re-hashing, not assumed away.",
            [
                create(),
                {
                    "label": "tamper",
                    "op": "tamper",
                    "args": {
                        "target": "record",
                        "kind": "edit",
                        "unit_id": "u1",
                        "fields": {"pinned_inputs": {"workstreams/po03/COMMISSION.md": BAD_SHA}},
                    },
                },
                verify(),
            ],
            [detail("verify", "input_drift", expect=["u1"])],
            criteria=["C3"],
            commission_basis="Every claimed input is pinned by repository and SHA.",
        )
    )

    # -- F2 completion truthfulness ---------------------------------------

    cases.append(
        case(
            "P06-provider-completion-is-not-obzio-completion",
            "false_completion",
            "A provider report of COMPLETED with no durable result commit never becomes Obzio COMPLETED.",
            [
                create(),
                submit(
                    claimed_state="COMPLETED",
                    result_commit_id=None,
                    artifacts=[],
                    readback_verified=False,
                ),
                observe(),
            ],
            [
                admitted("submit", False),
                reason("submit", "NO_RESULT_COMMIT"),
                detail("observe", "obzio_state", expect="PROVIDER_COMPLETED_UNCOMMITTED"),
            ],
            critical=True,
            safety_class="false_completion",
            criteria=["C1"],
            commission_basis="If no verified durable result commit exists, Obzio state is PROVIDER_COMPLETED_UNCOMMITTED, never COMPLETED.",
        )
    )
    cases.append(
        case(
            "P07-completion-requires-parent-ingestion",
            "false_completion",
            "Completion is refused before the parent has ingested and re-verified the result.",
            [create(), lease(), write_artifact(), submit(), complete(), observe()],
            [
                admitted("complete", False),
                reason("complete", "NOT_INGESTED"),
                detail("observe", "obzio_state", one_of=["RESULT_COMMITTED", "RESULT_VERIFIED"]),
            ],
            critical=True,
            safety_class="false_completion",
            criteria=["C2"],
            commission_basis="the parent records ingestion; only the coordinator sets COMPLETED.",
        )
    )
    cases.append(
        case(
            "P08-completion-authority-is-enforced-not-labelled",
            "authority",
            "A non-coordinator principal cannot reach COMPLETED even when every custody precondition holds.",
            [create(), lease(), write_artifact(), submit(), ingest(), complete(actor="w1"), observe()],
            [
                admitted("complete", False),
                reason("complete", "NOT_COORDINATOR"),
                detail("observe", "obzio_state", expect="PARENT_INGESTED"),
            ],
            critical=True,
            safety_class="false_completion",
            criteria=["C2", "C6"],
            commission_basis="only the coordinator sets COMPLETED.",
        )
    )
    cases.append(
        case(
            "P09-producer-cannot-accept-its-own-work",
            "authority",
            "The producing owner cannot record acceptance of its own result.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                ingest(),
                complete(),
                {
                    "label": "review",
                    "op": "review",
                    "args": {"unit_id": "u1", "reviewer": OWNER, "decision": "ACCEPTED"},
                },
            ],
            [admitted("review", False), reason("review", "SELF_ACCEPTANCE")],
            critical=True,
            criteria=["C2", "C6"],
            commission_basis="a different producer may then accept or reject it.",
        )
    )
    cases.append(
        case(
            "P10-acceptance-starts-untested",
            "authority",
            "A freshly dispatched unit is NOT_TESTED rather than presumed acceptable.",
            [create(), observe()],
            [detail("observe", "acceptance", expect="NOT_TESTED")],
            criteria=["C2"],
            commission_basis="Use only PASS, FAIL, NOT_YET, NOT_SUPPORTED or OWNER_BLOCKED.",
        )
    )

    # -- F3 leases and fencing --------------------------------------------

    cases.append(
        case(
            "P11-lease-grants-a-fence-token",
            "fencing",
            "Work is leased with a monotonic fence token rather than assigned informally.",
            [create(), lease()],
            [admitted("lease"), detail("lease", "fence_token", expect=1)],
            criteria=["C5"],
            commission_basis="Use ... leases, fencing, monotonic checkpoints.",
        )
    )
    cases.append(
        case(
            "P12-stale-worker-cannot-commit-after-transfer",
            "fencing",
            "After ownership transfers, the evicted worker's commit is refused.",
            [
                create(),
                lease(worker="w1"),
                lease(worker="w2", label="lease2"),
                write_artifact(),
                submit(worker="w1", fence_token=1),
            ],
            [admitted("submit", False), reason("submit", "STALE_FENCE")],
            critical=True,
            criteria=["C5"],
            commission_basis="An expired/stale worker must not commit after ownership transfers.",
        )
    )
    cases.append(
        case(
            "P13-forged-fence-token-refused",
            "fencing",
            "A fence token that was never granted to this worker is refused, not accepted for being large.",
            [create(), lease(worker="w1"), write_artifact(), submit(worker="w1", fence_token=99)],
            [admitted("submit", False), reason("submit", "FORGED_FENCE")],
            critical=True,
            criteria=["C5"],
            commission_basis="Use ... leases, fencing ... an expired/stale worker must not commit.",
        )
    )
    cases.append(
        case(
            "P14-expired-lease-cannot-commit",
            "fencing",
            "A worker whose lease deadline has passed cannot commit, even with the newest fence token.",
            [
                create(),
                lease(worker="w1", ttl=60),
                write_artifact(),
                {"label": "wait", "op": "advance_clock", "args": {"seconds": 600}},
                submit(worker="w1", fence_token=1),
            ],
            [admitted("submit", False), reason("submit", "EXPIRED_LEASE")],
            critical=True,
            criteria=["C5"],
            commission_basis="An expired/stale worker must not commit after ownership transfers.",
        )
    )
    cases.append(
        case(
            "P15-expired-lease-surfaces-in-recovery",
            "recovery",
            "An expired lease is reported by the recovery scanner so the unit can be re-dispatched.",
            [
                create(),
                lease(worker="w1", ttl=60),
                {"label": "wait", "op": "advance_clock", "args": {"seconds": 600}},
                recover(),
            ],
            [detail("recover", "expired_leases", expect=["u1"])],
            criteria=["C4", "C5"],
            commission_basis="Use ... a recovery scanner.",
        )
    )

    # -- F4 artifact integrity --------------------------------------------

    cases.append(
        case(
            "P16-missing-artifact-refused-on-readback",
            "artifact_integrity",
            "A result naming an artifact that does not exist is refused on read-back.",
            [
                create(),
                lease(),
                submit(artifacts=[artifact(sha256=ZERO_SHA, bytes=42)]),
            ],
            [admitted("submit", False), reason("submit", "ARTIFACT_MISSING")],
            critical=True,
            criteria=["C3"],
            commission_basis="another process reads every artifact back by immutable SHA.",
        )
    )
    cases.append(
        case(
            "P17-artifact-hash-mismatch-refused",
            "artifact_integrity",
            "A result whose claimed digest disagrees with the stored bytes is refused.",
            [create(), lease(), write_artifact(), submit(artifacts=[artifact(sha256=BAD_SHA)])],
            [admitted("submit", False), reason("submit", "ARTIFACT_HASH_MISMATCH")],
            critical=True,
            criteria=["C3"],
            commission_basis="hashes and byte counts are verified.",
        )
    )
    cases.append(
        case(
            "P18-byte-accounting-mismatch-refused",
            "artifact_integrity",
            "A result whose manifest accounting disagrees with its artifacts is refused.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(accounting={"artifact_count": 2, "total_bytes": 999999}),
            ],
            [admitted("submit", False), reason("submit", "ACCOUNTING_MISMATCH")],
            critical=True,
            criteria=["C3"],
            commission_basis="hashes and byte counts are verified.",
        )
    )
    cases.append(
        case(
            "P19-duplicate-artifact-identity-refused",
            "artifact_integrity",
            "Two artifacts cannot share one identity inside a single result manifest.",
            [
                create(),
                lease(),
                write_artifact(),
                write_artifact(path="workstreams/po03/successor/scores/probe2.json", label="write2"),
                submit(
                    artifacts=[
                        artifact(),
                        artifact(path="workstreams/po03/successor/scores/probe2.json"),
                    ]
                ),
            ],
            [admitted("submit", False), reason("submit", "DUPLICATE_ARTIFACT_ID")],
            criteria=["C3", "C6"],
            commission_basis="complete artifact manifest ... complete hash coverage.",
        )
    )
    cases.append(
        case(
            "P20-readback-evidence-required-for-terminal-state",
            "artifact_integrity",
            "A terminal committed state requires read-back evidence for every artifact.",
            [create(), lease(), write_artifact(), submit(readback_verified=False)],
            [admitted("submit", False), reason("submit", "READBACK_MISSING")],
            critical=True,
            criteria=["C3"],
            commission_basis="another process reads every artifact back by immutable SHA.",
        )
    )
    cases.append(
        case(
            "P21-drift-after-admission-is-detected",
            "artifact_integrity",
            "Artifact bytes that change after admission into custody are detected by re-verification.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                ingest(),
                {
                    "label": "tamper",
                    "op": "tamper",
                    "args": {"target": "artifact", "kind": "corrupt", "path": ARTIFACT},
                },
                verify(),
            ],
            [
                detail("verify", "drift_detected", expect=[ARTIFACT]),
                detail("verify", "artifacts_reverified", expect=1),
            ],
            critical=True,
            criteria=["C3", "C4"],
            commission_basis="complete hash coverage ... 100% recovery of committed results.",
        )
    )

    # -- F5 path scope and ownership --------------------------------------

    cases.append(
        case(
            "P22-out-of-allowlist-artifact-refused",
            "path_scope",
            "A result claiming an artifact outside the wave-one allowlist is refused at ingestion.",
            [
                create(),
                lease(),
                write_artifact(path="packs/injected.json", label="write"),
                submit(artifacts=[artifact(path="packs/injected.json")]),
            ],
            [admitted("submit", False), reason("submit", "OUT_OF_ALLOWLIST")],
            critical=True,
            criteria=["C6"],
            commission_basis="A path-scope guard must fail CI for writes outside the allowlist.",
        )
    )
    cases.append(
        case(
            "P23-cross-owner-artifact-refused",
            "path_scope",
            "A result claiming another cohort's owned path is refused even inside the allowlist.",
            [
                create(),
                lease(),
                write_artifact(path="workstreams/po03/metrics/generation-comparison.json", label="write"),
                submit(
                    artifacts=[artifact(path="workstreams/po03/metrics/generation-comparison.json")]
                ),
            ],
            [admitted("submit", False), reason("submit", "NOT_OWNED")],
            critical=True,
            criteria=["C6"],
            commission_basis="every subordinate writer receives a unique worktree/branch and owned subtree.",
        )
    )
    cases.append(
        case(
            "P24-path-traversal-refused",
            "path_scope",
            "A traversal escape from an owned subtree is refused.",
            [
                create(),
                lease(),
                write_artifact(path="workstreams/po03/successor/../../../etc/passwd", label="write"),
                submit(artifacts=[artifact(path="workstreams/po03/successor/../../../etc/passwd")]),
            ],
            [
                admitted("submit", False),
                reason_in("submit", ["OUT_OF_ALLOWLIST", "NOT_OWNED"]),
            ],
            critical=True,
            criteria=["C6"],
            commission_basis="Never write outside it, and within it never outside your owned prefixes.",
        )
    )

    # -- F6 replay and idempotency ----------------------------------------

    cases.append(
        case(
            "P25-identical-replay-is-harmless",
            "replay",
            "A byte-identical duplicate callback leaves exactly one durable result.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                ingest(),
                ingest(label="ingest2"),
                observe(),
            ],
            [
                reason("ingest2", "DUPLICATE_IGNORED"),
                detail("observe", "ingest_count", expect=1),
            ],
            critical=True,
            criteria=["C5", "C6"],
            commission_basis="Duplicate callbacks must be harmless.",
        )
    )
    cases.append(
        case(
            "P26-conflicting-replay-refused",
            "replay",
            "A replay under the same idempotency key carrying different content is refused, not ingested twice.",
            [
                create(),
                lease(),
                write_artifact(),
                write_artifact(path="workstreams/po03/successor/scores/probe2.json", label="write2"),
                submit(),
                ingest(),
                submit(
                    label="submit2",
                    artifacts=[artifact(path="workstreams/po03/successor/scores/probe2.json")],
                    result_commit_id="d3adb33fd3adb33fd3adb33fd3adb33fd3adb33f",
                ),
                ingest(label="ingest2"),
                observe(),
            ],
            [
                reason_in("ingest2", ["CONFLICTING_REPLAY", "DUPLICATE_IGNORED"]),
                admitted("ingest2", False),
                detail("observe", "ingest_count", expect=1),
            ],
            critical=True,
            criteria=["C5", "C6"],
            commission_basis="zero duplicate external effects.",
        )
    )

    # -- F7 log integrity and recovery ------------------------------------

    cases.append(
        case(
            "P27-in-place-log-edit-detected",
            "log_integrity",
            "An in-place edit of the append-only history is detected.",
            [
                create(),
                lease(),
                {"label": "tamper", "op": "tamper", "args": {"target": "ledger", "kind": "edit"}},
                verify(),
            ],
            [reason_in("verify", ["LEDGER_CORRUPT"]), detail("verify", "ledger_chain_valid", expect=False)],
            critical=True,
            criteria=["C4"],
            commission_basis="Use an append-only ledger.",
        )
    )
    cases.append(
        case(
            "P28-log-reordering-detected",
            "log_integrity",
            "Reordering the append-only history is detected.",
            [
                create(),
                lease(),
                {"label": "tamper", "op": "tamper", "args": {"target": "ledger", "kind": "reorder"}},
                verify(),
            ],
            [reason_in("verify", ["LEDGER_CORRUPT"]), detail("verify", "ledger_chain_valid", expect=False)],
            critical=True,
            criteria=["C4"],
            commission_basis="Use an append-only ledger ... monotonic checkpoints.",
        )
    )
    cases.append(
        case(
            "P29-log-tail-truncation-detected",
            "log_integrity",
            "Losing the most recent rows of the append-only history is detected, not silently accepted.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                {"label": "tamper", "op": "tamper", "args": {"target": "ledger", "kind": "truncate"}},
                verify(),
            ],
            [
                reason_in("verify", ["LEDGER_TRUNCATED", "LEDGER_CORRUPT"]),
                detail("verify", "ledger_truncated", expect=True),
            ],
            critical=True,
            criteria=["C4"],
            commission_basis="truncation, reordering and in-place edits are detectable.",
        )
    )
    cases.append(
        case(
            "P30-lost-callback-is-replayed-not-rerun",
            "recovery",
            "A committed result whose callback was lost is replayed into custody rather than re-run.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                {"label": "restart", "op": "restart", "args": {}},
                recover(),
                observe(),
            ],
            [
                detail("recover", "replayed_ingestions", expect=1),
                detail("recover", "rerun_required", expect=[]),
                detail("observe", "obzio_state", expect="PARENT_INGESTED"),
            ],
            critical=True,
            criteria=["C4", "C6"],
            commission_basis="Lost callbacks must replay ... transactional outbox ... 100% recovery of committed results.",
        )
    )

    cases.append(
        case(
            "P31-declared-locator-must-resolve-before-ingestion",
            "recovery",
            "A result is admitted only if its record is actually readable at the immutable locator it declares.",
            [
                create(),
                lease(),
                write_artifact(),
                submit(),
                {
                    "label": "tamper",
                    "op": "tamper",
                    "args": {"target": "locator", "kind": "delete", "unit_id": "u1"},
                },
                ingest(),
                observe(),
            ],
            [
                admitted("ingest", False),
                reason("ingest", "LOCATOR_UNRESOLVED"),
                detail("observe", "ingest_count", expect=0),
            ],
            critical=True,
            criteria=["C3", "C4"],
            commission_basis="another process reads every artifact back by immutable SHA; every counted unit has a terminal durable disposition and immutable locator.",
        )
    )

    return cases


def build_document() -> dict[str, Any]:
    cases = build_cases()
    return {
        "case_set_id": SUITE_ID,
        "authored_by": OWNER,
        "role": "public",
        "frozen": True,
        "generated_by": "workstreams/po03/successor/suite/build_public_suite.py",
        "case_count": len(cases),
        "criteria_source": {
            "owner": "po03-worker-a6",
            "path": "workstreams/po03/review/luna/criteria-a1.json",
            "criteria_id": "po03-a6-custody-engine-v002",
            "note": "criterion identifiers C1-C6 are a6's independently frozen custody criteria",
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify the committed suite matches this script")
    args = parser.parse_args()

    target = Path(__file__).resolve().parent / "public" / "cases.json"
    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not target.is_file():
            print(f"MISSING {target}")
            return 1
        current = target.read_text(encoding="utf-8")
        if current != text:
            print(f"DRIFTED {target}: committed suite does not match its generator")
            return 1
        print(f"FROZEN {target} sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()} cases={document['case_count']}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"WROTE {target} sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()} cases={document['case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
