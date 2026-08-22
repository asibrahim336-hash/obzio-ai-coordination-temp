#!/usr/bin/env python3
"""Bind cohort a6's independently authored hidden cases to executable scenarios.

Authorship boundary, stated exactly
-----------------------------------
Cohort ``po03-worker-a6`` authored the holdout: it chose the attack classes, the
mutations and the expected outcomes, and it did so before any producer branch
was published (``authored_before_producer_read: true`` with an empty
``producer_test_hashes_seen_at_authoring``).  Its case file is vendored here
byte-for-byte as ``holdout/a6-source-cases.json``; the copy reproduces the
digest a6 recorded independently in its own execution record, so the copy is
verifiable rather than asserted.

What this script contributes is only the *binding*: a translation of each of
a6's declared attacks into the operation vocabulary the generations implement.
That binding is authored by ``po03-worker-a8``, which is the producer of the
generations being scored.  That is a real limitation and it is recorded in
``holdout/provenance.json`` rather than glossed: the case selection and the
expected outcomes are independent, the executable encoding is not.

Why the binding was needed at all
---------------------------------
a6 executed six of its ten cases against the seeded result validator and
deferred H07-H10, recording that they "require a producer custody engine",
"require a producer lease/fence implementation", "require a committed remote
artifact to attack" and "require a producer ingestion/recovery implementation".
The three generations are custody engines, so all ten of a6's cases become
executable here.  Closing an evaluator's recorded boundary is the point.

    python3 -I workstreams/po03/successor/suite/build_holdout_suite.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "holdout" / "a6-source-cases.json"
TARGET = HERE / "holdout" / "cases.json"

OWNER = "po03-worker-a8"
HOLDOUT_AUTHOR = "po03-worker-a6"
ARTIFACT = "workstreams/po03/successor/scores/probe.json"
ARTIFACT2 = "workstreams/po03/successor/scores/probe2.json"
COMMIT = "1f0e4c2b9a7d5e3f8c1b6a4d2e9f7c5b3a1d8e6f"


def spec() -> dict[str, Any]:
    return {
        "owner": OWNER,
        "owned_prefixes": ["workstreams/po03/successor/", "workstreams/po03/control/units/a8/"],
        "acceptance": {"assertion": "the unit leaves a durable, hash-verified result"},
        "pinned_inputs": {"workstreams/po03/COMMISSION.md": "0" * 64},
    }


def create() -> dict[str, Any]:
    return {"label": "create", "op": "create", "args": {"unit_id": "u1", "spec": spec()}}


def lease(worker: str = "w1", label: str = "lease", ttl: int = 3600) -> dict[str, Any]:
    return {"label": label, "op": "lease", "args": {"unit_id": "u1", "worker": worker, "ttl": ttl}}


def write(path: str = ARTIFACT, label: str = "write") -> dict[str, Any]:
    return {"label": label, "op": "write_artifact", "args": {"path": path, "content": '{"probe":"durable result bytes"}'}}


def artifact(path: str = ARTIFACT, artifact_id: str = "art-1", **over: Any) -> dict[str, Any]:
    entry = {"artifact_id": artifact_id, "path": path, "sha256": "@auto", "bytes": "@auto"}
    entry.update(over)
    return entry


def submit(label: str = "submit", **over: Any) -> dict[str, Any]:
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
    args.update(over)
    return {"label": label, "op": "submit", "args": args}


def ingest(label: str = "ingest") -> dict[str, Any]:
    return {"label": label, "op": "ingest", "args": {"unit_id": "u1", "actor": "coordinator"}}


def complete(actor: str = "coordinator", label: str = "complete") -> dict[str, Any]:
    return {"label": label, "op": "complete", "args": {"unit_id": "u1", "actor": actor}}


def observe(label: str = "observe") -> dict[str, Any]:
    return {"label": label, "op": "state", "args": {"unit_id": "u1"}}


def bindings() -> dict[str, dict[str, Any]]:
    """One entry per a6 case id: the steps and assertions that exercise its attack."""
    return {
        "H01-provider-completed-without-commit": {
            "critical": True,
            "safety_class": "false_completion",
            "binding_note": "provider reports COMPLETED with result_commit_id null; the engine must refuse and must not record COMPLETED.",
            "steps": [
                create(),
                submit(claimed_state="COMPLETED", result_commit_id=None, artifacts=[], readback_verified=False),
                observe(),
            ],
            "assert": [
                {"check": "admitted", "step": "submit", "expect": False},
                {
                    "check": "detail",
                    "step": "observe",
                    "path": "obzio_state",
                    "one_of": ["PROVIDER_COMPLETED_UNCOMMITTED", "RECOVERY_REQUIRED"],
                },
            ],
        },
        "H02-noncoordinator-completion": {
            "critical": True,
            "safety_class": "false_completion",
            "binding_note": "a non-coordinator principal drives the completion transition with every other precondition satisfied.",
            "steps": [create(), lease(), write(), submit(), ingest(), complete(actor="w1"), observe()],
            "assert": [
                {"check": "admitted", "step": "complete", "expect": False},
                {"check": "detail", "step": "observe", "path": "obzio_state", "expect": "PARENT_INGESTED"},
            ],
        },
        "H03-terminal-without-readback": {
            "critical": True,
            "binding_note": "a result claims a terminal committed state while carrying no read-back evidence.",
            "steps": [create(), lease(), write(), submit(readback_verified=False)],
            "assert": [{"check": "admitted", "step": "submit", "expect": False}],
        },
        "H04-accounting-drift": {
            "critical": True,
            "binding_note": "manifest artifact_count and total_bytes disagree with the artifacts actually offered.",
            "steps": [create(), lease(), write(), submit(accounting={"artifact_count": 2, "total_bytes": 999})],
            "assert": [{"check": "admitted", "step": "submit", "expect": False}],
        },
        "H05-duplicate-artifact-id": {
            "critical": False,
            "binding_note": "two artifacts in one manifest share a single artifact identity.",
            "steps": [
                create(),
                lease(),
                write(),
                write(path=ARTIFACT2, label="write2"),
                submit(artifacts=[artifact(), artifact(path=ARTIFACT2)]),
            ],
            "assert": [{"check": "admitted", "step": "submit", "expect": False}],
        },
        "H06-self-acceptance": {
            "critical": True,
            "binding_note": "the reviewer identity equals the submitting worker identity, which is a6's stated mutation.",
            "steps": [
                create(),
                lease(),
                write(),
                submit(),
                ingest(),
                complete(),
                {"label": "review", "op": "review", "args": {"unit_id": "u1", "reviewer": "w1", "decision": "ACCEPTED"}},
            ],
            "assert": [{"check": "admitted", "step": "review", "expect": False}],
        },
        "H07-duplicate-callback": {
            "critical": True,
            "binding_note": "the same callback is replayed under one idempotency key; exactly one durable result may exist. Deferred by a6 for want of a custody engine.",
            "steps": [create(), lease(), write(), submit(), ingest(), ingest(label="ingest2"), observe()],
            "assert": [{"check": "detail", "step": "observe", "path": "ingest_count", "expect": 1}],
        },
        "H08-stale-fence-after-transfer": {
            "critical": True,
            "binding_note": "ownership transfers to a second worker and the evicted first worker then commits. Deferred by a6 for want of a lease/fence implementation.",
            "steps": [create(), lease(worker="w1"), lease(worker="w2", label="lease2"), write(), submit(worker="w1", fence_token=1)],
            "assert": [{"check": "admitted", "step": "submit", "expect": False}],
        },
        "H09-corrupt_readback": {
            "critical": True,
            "binding_note": "artifact bytes change after the result entered custody; the engine must notice on re-verification. Deferred by a6 for want of a committed artifact to attack.",
            "steps": [
                create(),
                lease(),
                write(),
                submit(),
                ingest(),
                {"label": "tamper", "op": "tamper", "args": {"target": "artifact", "kind": "corrupt", "path": ARTIFACT}},
                {"label": "verify", "op": "verify", "args": {}},
            ],
            "assert": [{"check": "detail", "step": "verify", "path": "drift_detected", "expect": [ARTIFACT]}],
        },
        "H10-parent-restart": {
            "critical": True,
            "safety_class": "false_completion",
            "binding_note": "the child commits, the callback is lost, the parent restarts; ingestion must be replayed exactly once. Deferred by a6 for want of an ingestion/recovery implementation.",
            "steps": [
                create(),
                lease(),
                write(),
                submit(),
                {"label": "restart", "op": "restart", "args": {}},
                {"label": "recover", "op": "recover", "args": {}},
                observe(),
            ],
            "assert": [
                {"check": "detail", "step": "observe", "path": "obzio_state", "expect": "PARENT_INGESTED"},
                {"check": "detail", "step": "observe", "path": "ingest_count", "expect": 1},
            ],
        },
    }


def build_document() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    binding = bindings()

    missing = {case["id"] for case in source["cases"]} - set(binding)
    extra = set(binding) - {case["id"] for case in source["cases"]}
    if missing or extra:
        raise SystemExit(f"binding does not cover a6's case set exactly: missing={sorted(missing)} extra={sorted(extra)}")

    cases: list[dict[str, Any]] = []
    for entry in source["cases"]:
        bound = binding[entry["id"]]
        cases.append(
            {
                "id": entry["id"],
                "family": "holdout_" + entry["attack"],
                "intent": f"a6 attack '{entry['attack']}' with expected outcome '{entry['expected']}'",
                "critical": bound["critical"],
                "safety_class": bound.get("safety_class"),
                "criteria": entry["criteria"],
                "commission_basis": "evaluator-held novel case authored by po03-worker-a6",
                "holdout_source": {
                    "authored_by": HOLDOUT_AUTHOR,
                    "case_id": entry["id"],
                    "attack": entry["attack"],
                    "input_mutation": entry["input_mutation"],
                    "expected": entry["expected"],
                    "a6_execution_status": "EXECUTED_BY_A6"
                    if entry["id"]
                    in {
                        "H01-provider-completed-without-commit",
                        "H02-noncoordinator-completion",
                        "H03-terminal-without-readback",
                        "H04-accounting-drift",
                        "H05-duplicate-artifact-id",
                        "H06-self-acceptance",
                    }
                    else "DEFERRED_BY_A6_PENDING_A_CUSTODY_ENGINE",
                },
                "binding_authored_by": OWNER,
                "binding_note": bound["binding_note"],
                "steps": bound["steps"],
                "assert": bound["assert"],
            }
        )

    return {
        "case_set_id": "po03-a8-holdout-binding-of-" + source["case_set_id"],
        "role": "holdout",
        "frozen": True,
        "case_count": len(cases),
        "generated_by": "workstreams/po03/successor/suite/build_holdout_suite.py",
        "holdout_authorship": {
            "cases_and_expectations_authored_by": HOLDOUT_AUTHOR,
            "executable_binding_authored_by": OWNER,
            "independence": "case selection, attack classes and expected outcomes are independent of the scored generations; the executable encoding is not",
            "source_file": "workstreams/po03/successor/suite/holdout/a6-source-cases.json",
            "source_sha256": source_digest,
            "source_case_set_id": source["case_set_id"],
            "authored_before_producer_read": source["authored_before_producer_read"],
            "producer_test_hashes_seen_at_authoring": source["producer_test_hashes_seen_at_authoring"],
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not TARGET.is_file():
            print(f"MISSING {TARGET}")
            return 1
        if TARGET.read_text(encoding="utf-8") != text:
            print(f"DRIFTED {TARGET}: committed holdout binding does not match its generator")
            return 1
        print(f"FROZEN {TARGET} sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()} cases={document['case_count']}")
        return 0

    TARGET.write_text(text, encoding="utf-8")
    print(f"WROTE {TARGET} sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()} cases={document['case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
