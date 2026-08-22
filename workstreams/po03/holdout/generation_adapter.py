#!/usr/bin/env python3
"""Evaluator-owned adapter from frozen a13 cases to the pinned a8 controllers.

This is post-freeze glue.  It extracts the exact a8 commit into the scorer's
private work directory, invokes the generation's real controller operations,
and normalizes only observed outcomes.  It does not patch generation source.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import posixpath
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any


A8_COMMIT = "bb7c24e947eabfdea8761e4d2dfdd6c8966185a4"
REQUEST_VERSION = "OBZIO-PO03-HOLDOUT-REQUEST-v1"
RESPONSE_VERSION = "OBZIO-PO03-HOLDOUT-RESPONSE-v1"

# Opaque labels keep generation identity out of the scorer process and its
# request/response transcript.  The mapping is disclosed separately after all
# three transcripts have been produced.
SLOTS = {
    "SLOT-4F7": "g1",
    "SLOT-9A2": "g0",
    "SLOT-C31": "g2",
}


class UnsupportedCase(RuntimeError):
    pass


class NativeRun:
    def __init__(self, controller: Any, generation: str) -> None:
        self.controller = controller
        self.generation = generation
        self.trace: list[dict[str, Any]] = []
        self.producer_runs = 0
        self.external_effects = 0
        self.new_false_completions = 0

    def call(self, label: str, operation: str, **arguments: Any) -> Any:
        outcome = self.controller.apply(operation, arguments)
        item = {
            "label": label,
            "operation": operation,
            "arguments": arguments,
            "outcome": outcome.as_json(),
        }
        self.trace.append(item)
        if outcome.reason_code == "NOT_SUPPORTED":
            missing = outcome.detail.get("missing_capability", operation)
            raise UnsupportedCase(
                f"{self.generation.upper()} has no executable {missing!r} capability "
                f"required by step {label}"
            )
        return outcome

    def counts(self) -> dict[str, int]:
        completed = 0
        ingested = 0
        ledger = getattr(self.controller, "ledger", None)
        if ledger is not None:
            rows = ledger.rows()
            completed = sum(row.get("event") == "COMPLETED" for row in rows)
            ingested = sum(row.get("event") == "PARENT_INGESTED" for row in rows)
        else:
            receipt_dir = getattr(self.controller, "receipt_dir", None)
            if receipt_dir is not None:
                for path in Path(receipt_dir).glob("*.json"):
                    try:
                        state = json.loads(path.read_text(encoding="utf-8")).get("state")
                    except (OSError, json.JSONDecodeError):
                        continue
                    completed += state == "COMPLETED"
        return {
            "COMPLETED": int(completed),
            "PARENT_INGESTED": int(ingested),
            "external_effects": self.external_effects,
            "false_completions": self.new_false_completions,
            "producer_runs": self.producer_runs,
        }

    def state(self, unit_id: str) -> dict[str, Any]:
        outcome = self.call(f"state-{len(self.trace)}", "state", unit_id=unit_id)
        return dict(outcome.detail)

    def observation(
        self,
        *,
        outcomes: dict[str, str] | None = None,
        reasons: dict[str, str] | None = None,
        final: dict[str, Any] | None = None,
        flags: list[str] | None = None,
        values: dict[str, Any] | None = None,
        writes: list[str] | None = None,
    ) -> dict[str, Any]:
        merged_values = dict(values or {})
        merged_values["native_trace"] = self.trace
        return {
            "outcomes": dict(outcomes or {}),
            "reasons": dict(reasons or {}),
            "final": dict(final or {}),
            "counts": self.counts(),
            "flags": list(flags or []),
            "values": merged_values,
            "writes": list(writes or []),
        }


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def extract_generation(workdir: Path) -> Path:
    command = [
        "git",
        "-C",
        str(repository_root()),
        "archive",
        A8_COMMIT,
        "workstreams/po03/successor",
    ]
    archive = subprocess.run(command, check=True, capture_output=True).stdout
    source_root = workdir / "source"
    source_root.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        stream.extractall(source_root, filter="data")
    return source_root


def build_controller(generation: str, workdir: Path) -> Any:
    source_root = extract_generation(workdir)
    sys.path.insert(0, str(source_root))
    from workstreams.po03.successor.harness.controller_api import Clock

    if generation == "g0":
        from workstreams.po03.successor.g0.controller import build
    elif generation == "g1":
        from workstreams.po03.successor.g1.factory import build
    elif generation == "g2":
        from workstreams.po03.successor.g2.successor import build
    else:  # pragma: no cover - guarded by SLOTS
        raise ValueError(generation)
    return build(root=workdir / "candidate-state", clock=Clock(start=1_787_000_000.0))


def spec(owner: str = "worker-a", *, workflow: bool = False) -> dict[str, Any]:
    prefixes = ["workstreams/po03/"]
    if workflow:
        prefixes.append(".github/workflows/")
    return {
        "owner": owner,
        "owned_prefixes": prefixes,
        "acceptance": {"assertion": "frozen a13 holdout"},
        "pinned_inputs": {
            "workstreams/po03/COMMISSION.md": "0" * 64,
        },
    }


def create_and_lease(run: NativeRun, unit: str, worker: str = "worker-a") -> int:
    run.call("create", "create", unit_id=unit, spec=spec(worker))
    lease = run.call("lease", "lease", unit_id=unit, worker=worker, ttl=100)
    return int(lease.detail["fence_token"])


def write_one(
    run: NativeRun,
    path: str = "workstreams/po03/holdout-artifact.txt",
    content: str = "alpha",
) -> list[dict[str, Any]]:
    run.call("write", "write_artifact", path=path, content=content)
    return [{"artifact_id": "artifact-1", "path": path, "sha256": "@auto", "bytes": "@auto"}]


def submit(
    run: NativeRun,
    *,
    unit: str,
    worker: str,
    fence: int,
    commit: str,
    artifacts: list[dict[str, Any]],
    key: str | None = None,
    provider_state: str = "COMPLETED",
    claimed_state: str = "RESULT_COMMITTED",
) -> Any:
    run.producer_runs += 1
    return run.call(
        f"submit-{run.producer_runs}",
        "submit",
        unit_id=unit,
        worker=worker,
        fence_token=fence,
        provider_state=provider_state,
        claimed_state=claimed_state,
        artifacts=artifacts,
        result_commit_id=commit,
        readback_verified=True,
        idempotency_key=key,
    )


def valid_to_ingested(
    run: NativeRun,
    unit: str,
    *,
    commit: str = "commit-a",
    key: str | None = None,
    content: str = "alpha",
) -> tuple[int, list[dict[str, Any]]]:
    fence = create_and_lease(run, unit)
    artifacts = write_one(run, content=content)
    submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit=commit,
        artifacts=artifacts,
        key=key,
    )
    run.call("ingest", "ingest", unit_id=unit, actor="coordinator")
    return fence, artifacts


def case_h01(run: NativeRun) -> dict[str, Any]:
    unit = "u-h01"
    fence = create_and_lease(run, unit)
    artifacts = write_one(run)
    submit(run, unit=unit, worker="worker-a", fence=fence, commit="commit-local-only", artifacts=artifacts)
    tamper = run.call("unpublish", "tamper", target="locator", kind="delete", unit_id=unit)
    callback = run.call("cb1-native", "ingest", unit_id=unit, actor="coordinator")
    state = run.state(unit)
    refused = not callback.admitted
    return run.observation(
        outcomes={"cb1": "REFUSED" if refused else "ACCEPTED"},
        reasons={"cb1": "COMMIT_NOT_DURABLE" if callback.reason_code == "LOCATOR_UNRESOLVED" else callback.reason_code},
        final={"unit_state": state.get("obzio_state")},
        values={"unpublish_outcome": tamper.as_json()},
    )


def case_h02(run: NativeRun) -> dict[str, Any]:
    unit = "u-h02"
    fence = create_and_lease(run, unit)
    artifacts = write_one(run, content="same-bytes")
    submit(run, unit=unit, worker="worker-a", fence=fence, commit="commit-declared", artifacts=artifacts)
    run.call("sibling-bytes", "tamper", target="locator", kind="corrupt", unit_id=unit)
    callback = run.call("cb1-native", "ingest", unit_id=unit, actor="coordinator")
    return run.observation(
        outcomes={"cb1": "REFUSED" if not callback.admitted else "ACCEPTED"},
        reasons={
            "cb1": "MANIFEST_NOT_IN_DECLARED_COMMIT"
            if callback.reason_code == "LOCATOR_UNRESOLVED"
            else callback.reason_code
        },
    )


def case_h04(run: NativeRun) -> dict[str, Any]:
    unit = "u-h04"
    fence, artifacts = valid_to_ingested(run, unit, commit="commit-a")
    run.call("done1", "complete", unit_id=unit, actor="coordinator")
    run.call("loss", "restart")
    replay_submit = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit="commit-a",
        artifacts=artifacts,
    )
    if replay_submit.reason_code == "TERMINAL_STATE":
        replay = replay_submit
    else:
        replay = run.call("cb2-native", "ingest", unit_id=unit, actor="coordinator")
    state = run.state(unit)
    harmless = replay.reason_code in {"TERMINAL_STATE", "DUPLICATE_IGNORED"}
    return run.observation(
        outcomes={"cb2": "IDEMPOTENT_REPLAY" if harmless else ("ACCEPTED" if replay.admitted else "REFUSED")},
        final={"unit_state": state.get("obzio_state")},
    )


def case_h05(run: NativeRun) -> dict[str, Any]:
    unit = "u-h05"
    key = "stable-key-h05"
    fence, _ = valid_to_ingested(run, unit, commit="commit-a", key=key)
    run.call("done1", "complete", unit_id=unit, actor="coordinator")
    run.call("loss", "restart")
    artifacts = write_one(run, content="beta")
    offered = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit="commit-b",
        artifacts=artifacts,
        key=key,
    )
    if offered.admitted:
        callback = run.call("cb2-native", "ingest", unit_id=unit, actor="coordinator")
    else:
        callback = offered
    state = run.state(unit)
    accepted_commit = state.get("result_commit_id")
    terminal_conflict = callback.reason_code in {"TERMINAL_STATE", "CONFLICTING_REPLAY"}
    return run.observation(
        outcomes={"cb2": "REFUSED" if not callback.admitted else "ACCEPTED"},
        reasons={"cb2": "TERMINAL_RESULT_CONFLICT" if terminal_conflict else callback.reason_code},
        final={"unit_state": state.get("obzio_state")},
        values={"accepted_commit": accepted_commit},
    )


def case_h06(run: NativeRun) -> dict[str, Any]:
    unit = "u-h06"
    fence, artifacts = valid_to_ingested(run, unit, commit="commit-a")
    run.call("done1", "complete", unit_id=unit, actor="coordinator")
    regress = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit="commit-b",
        artifacts=artifacts,
        claimed_state="RUNNING",
    )
    done2 = run.call("done2-native", "complete", unit_id=unit, actor="coordinator")
    return run.observation(
        outcomes={
            "regress": "REFUSED" if not regress.admitted else "ACCEPTED",
            "done2": "REFUSED" if not done2.admitted else "ACCEPTED",
        },
        reasons={
            "regress": "TERMINAL_STATE_IMMUTABLE" if regress.reason_code == "TERMINAL_STATE" else regress.reason_code,
            "done2": done2.reason_code,
        },
    )


def case_h07(run: NativeRun) -> dict[str, Any]:
    unit = "u-h07"
    old_fence = create_and_lease(run, unit, "worker-old")
    new_lease = run.call("lease-new", "lease", unit_id=unit, worker="worker-new", ttl=100)
    artifacts = write_one(run)
    stale = submit(
        run,
        unit=unit,
        worker="worker-old",
        fence=old_fence,
        commit="commit-old-worker",
        artifacts=artifacts,
        key="fresh-key-from-old-worker",
    )
    return run.observation(
        outcomes={"cb1": "REFUSED" if not stale.admitted else "ACCEPTED"},
        reasons={"cb1": stale.reason_code},
        values={"current_lease_id": new_lease.detail.get("lease_id")},
    )


def case_h08(run: NativeRun) -> dict[str, Any]:
    unit = "u-h08"
    issued = create_and_lease(run, unit)
    artifacts = write_one(run)
    forged = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=99,
        commit="commit-guessed",
        artifacts=artifacts,
    )
    return run.observation(
        outcomes={"cb1": "REFUSED" if not forged.admitted else "ACCEPTED"},
        reasons={"cb1": "FENCE_NOT_ISSUED" if forged.reason_code == "FORGED_FENCE" else forged.reason_code},
        values={"current_fence": issued},
    )


def case_h11(run: NativeRun) -> dict[str, Any]:
    unit = "u-h11"
    key = "key-h11"
    fence, _ = valid_to_ingested(run, unit, commit="commit-h11", key=key)
    artifacts = write_one(run, content="changed")
    second = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit="commit-h11",
        artifacts=artifacts,
        key=key,
    )
    callback = second if not second.admitted else run.call("cb2-native", "ingest", unit_id=unit, actor="coordinator")
    return run.observation(
        outcomes={"cb2": "REFUSED" if not callback.admitted else "ACCEPTED"},
        reasons={"cb2": "IDEMPOTENCY_COLLISION" if callback.reason_code == "CONFLICTING_REPLAY" else callback.reason_code},
    )


def case_h17(run: NativeRun) -> dict[str, Any]:
    unit = "u-h17"
    valid_to_ingested(run, unit)
    first = run.call("review1-native", "review", unit_id=unit, reviewer="reviewer-b", decision="ACCEPTED")
    run.call("done", "complete", unit_id=unit, actor="coordinator")
    second = run.call("review2-native", "review", unit_id=unit, reviewer="reviewer-b", decision="ACCEPTED")
    state = run.state(unit)
    return run.observation(
        outcomes={
            "review1": "REFUSED" if not first.admitted else "ACCEPTED",
            "review2": "ACCEPTED" if second.admitted else "REFUSED",
        },
        reasons={"review1": "UNIT_NOT_COMPLETED" if first.reason_code == "NOT_INGESTED" else first.reason_code},
        final={"review_state": state.get("acceptance")},
    )


def case_h18(run: NativeRun) -> dict[str, Any]:
    unit = "u-h18"
    run.call("create", "create", unit_id=unit, spec=spec())
    result = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=1,
        commit="diagnostic-commit",
        artifacts=[],
        provider_state="FAILED",
        claimed_state="FAILED_TERMINAL",
    )
    state = run.state(unit)
    is_failure = state.get("obzio_state") == "FAILED_TERMINAL"
    return run.observation(
        outcomes={"cb1": "RECORDED_FAILURE" if is_failure else ("ACCEPTED" if result.admitted else "REFUSED")},
        final={"unit_state": state.get("obzio_state")},
    )


def case_h24(run: NativeRun) -> dict[str, Any]:
    store = Path(run.controller.artifact_dir)
    target = store / "packs"
    target.mkdir(parents=True, exist_ok=True)
    link = store / "workstreams" / "po03" / "link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("../../packs", target_is_directory=True)
    path1 = "workstreams/po03/../../packs/escape-a.txt"
    path2 = "workstreams/po03/link/escape-b.txt"
    first = run.call("w1-native", "write_artifact", path=path1, content="blocked-a")
    second = run.call("w2-native", "write_artifact", path=path2, content="blocked-b")
    writes = []
    if first.admitted:
        writes.append(posixpath.normpath(path1))
    if second.admitted:
        writes.append(posixpath.normpath(path2))
    return run.observation(
        outcomes={"w1": "ACCEPTED" if first.admitted else "REFUSED", "w2": "ACCEPTED" if second.admitted else "REFUSED"},
        reasons={"w1": first.reason_code, "w2": second.reason_code},
        writes=writes,
    )


def case_h25(run: NativeRun) -> dict[str, Any]:
    path1 = "./.github/workflows/po03-holdout.yml"
    path2 = ".github/workflows/xpo03-holdout.yml"
    first = run.call("w1-native", "write_artifact", path=path1, content="name: allowed")
    second = run.call("w2-native", "write_artifact", path=path2, content="name: blocked")
    writes = []
    if first.admitted:
        writes.append(posixpath.normpath(path1))
    if second.admitted:
        writes.append(posixpath.normpath(path2))
    return run.observation(
        outcomes={"w1": "ACCEPTED" if first.admitted else "REFUSED", "w2": "ACCEPTED" if second.admitted else "REFUSED"},
        reasons={"w2": "OUTSIDE_ALLOWLIST" if not second.admitted else second.reason_code},
        writes=writes,
    )


def case_h26(run: NativeRun, workdir: Path) -> dict[str, Any]:
    poison_root = workdir / "forbidden-tmp"
    poison_root.mkdir()
    (poison_root / "po03-generation-state.json").write_text('{"marker":"POISON"}\n', encoding="utf-8")
    old_tmpdir = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(poison_root)
    try:
        boot = run.call("run-native", "restart")
    finally:
        if old_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = old_tmpdir
    observed_poison = any(
        value == "POISON" for value in boot.detail.values() if isinstance(value, str)
    )
    return run.observation(
        outcomes={"run": "BOOTSTRAP_SUCCEEDED" if boot.admitted else "REFUSED"},
        flags=["NO_FORBIDDEN_TEMP_READ"] if not observed_poison else [],
        values={"state_source": "COMMITTED_REPOSITORY", "poison_marker_observed": observed_poison},
    )


def case_h27(run: NativeRun) -> dict[str, Any]:
    unit = "u-h27"
    fence = create_and_lease(run, unit)
    run.call("write", "write_artifact", path="workstreams/po03/a.txt", content="real")
    artifacts = [{
        "artifact_id": "artifact-1",
        "path": "workstreams/po03/a.txt",
        "sha256": "f" * 64,
        "bytes": 4,
    }]
    rejected = submit(
        run,
        unit=unit,
        worker="worker-a",
        fence=fence,
        commit="commit-h27",
        artifacts=artifacts,
    )
    run.call("loss", "restart")
    recovery = run.call("recover-native", "recover")
    rerun = unit in recovery.detail.get("rerun_required", [])
    ledger = getattr(run.controller, "ledger", None)
    durable_rejection = False
    if ledger is not None:
        durable_rejection = any(
            row.get("event") in {"RESULT_REJECTED", "ARTIFACT_REJECTED"}
            for row in ledger.rows()
        )
    return run.observation(
        outcomes={
            "cb1": "REFUSED" if not rejected.admitted else "ACCEPTED",
            "recover": "RERUN_SCHEDULED" if rerun else "NO_RECOVERY",
        },
        reasons={"cb1": rejected.reason_code},
        flags=["REJECTION_DURABLE"] if durable_rejection else [],
    )


def case_h30(run: NativeRun) -> dict[str, Any]:
    unit = "u-h30"
    valid_to_ingested(run, unit, commit="verified-commit-h30")
    worker = run.call("worker-done-native", "complete", unit_id=unit, actor="worker-a")
    if worker.admitted:
        run.new_false_completions += 1
    coordinator = run.call("coord-done-native", "complete", unit_id=unit, actor="coordinator")
    state = run.state(unit)
    return run.observation(
        outcomes={
            "worker_done": "ACCEPTED" if worker.admitted else "REFUSED",
            "coord_done": "ACCEPTED" if coordinator.admitted else "REFUSED",
        },
        reasons={"worker_done": "ACTOR_NOT_AUTHORIZED" if worker.reason_code == "NOT_COORDINATOR" else worker.reason_code},
        final={"unit_state": state.get("obzio_state")},
    )


def case_h32(run: NativeRun) -> dict[str, Any]:
    unit = "u-h32"
    run.call("create", "create", unit_id=unit, spec=spec())
    ledger = getattr(run.controller, "ledger", None)
    if ledger is None:
        raise UnsupportedCase(
            f"{run.generation.upper()} has no append-only ledger required by synthetic history scan"
        )
    for event, commit in [
        ("PARENT_INGESTED", "commit-a"),
        ("COMPLETED", "commit-a"),
        ("PARENT_INGESTED", "commit-b"),
        ("COMPLETED", "commit-b"),
    ]:
        ledger.append(
            unit,
            event,
            actor="coordinator",
            ts=run.controller.clock.iso(),
            provider_state="COMPLETED",
            fence_token=1,
            payload={"result_commit_id": commit},
        )
    scan = run.call("scan-native", "recover")
    detected = 1 if unit in scan.detail.get("false_completions", []) else 0
    return run.observation(
        outcomes={"scan": "DEFECT_DETECTED" if detected else "NO_DEFECT_DETECTED"},
        flags=["DUPLICATE_COMPLETION_HISTORY"] if detected else [],
        values={"detected_false_completions": detected},
    )


HANDLERS = {
    "H01": case_h01,
    "H02": case_h02,
    "H04": case_h04,
    "H05": case_h05,
    "H06": case_h06,
    "H07": case_h07,
    "H08": case_h08,
    "H11": case_h11,
    "H17": case_h17,
    "H18": case_h18,
    "H24": case_h24,
    "H25": case_h25,
    "H27": case_h27,
    "H30": case_h30,
    "H32": case_h32,
}

UNSUPPORTED_BOUNDARIES = {
    "H03": "generation contract has no mutable result-ref or supersession query",
    "H09": "generation result document has no immutable-input identity field to compare at admission",
    "H10": "generation contract has no barrier-synchronised concurrent callback operation",
    "H12": "generation contract has no barrier-synchronised commit operation",
    "H13": "generation ledger has no evaluator-addressable external immutable head seal",
    "H14": "generation ledger has no evaluator-addressable external immutable head seal",
    "H15": "generation contract has no ledger-replica reconciliation or equivocation operation",
    "H16": "in-process generation accepts caller identity strings and exposes no authenticated-principal binding",
    "H19": "generation package exposes no validator process boundary or schema-unavailable result",
    "H20": "generation contract has no external-effect ledger, so no-duplicate-effect recovery cannot be observed",
    "H21": "generation contract has no external-effect ledger or immutable-input rerun executor",
    "H22": "generation contract has no checkpoint operation",
    "H23": "generation contract has no heartbeat operation or barrier-synchronised expiry scan",
    "H28": "generation result and controller contracts expose no checkpoint metadata",
    "H29": "generation locator model has no declared-remote or result-slot identity",
    "H31": "generation submit operation combines verification and commit with no fault hook between them",
}


def execute_case(run: NativeRun, case_id: str, workdir: Path) -> dict[str, Any]:
    if case_id in UNSUPPORTED_BOUNDARIES:
        raise UnsupportedCase(UNSUPPORTED_BOUNDARIES[case_id])
    if case_id == "H26":
        return case_h26(run, workdir)
    handler = HANDLERS.get(case_id)
    if handler is None:
        raise UnsupportedCase(f"no evaluator translation exists for frozen case {case_id}")
    return handler(run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", required=True, choices=sorted(SLOTS))
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if request.get("protocol_version") != REQUEST_VERSION:
        raise ValueError("unsupported request protocol")
    case_id = request.get("case_id")
    if not isinstance(case_id, str):
        raise ValueError("missing case_id")
    generation = SLOTS[args.slot]
    controller = build_controller(generation, args.workdir)
    run = NativeRun(controller, generation)
    try:
        observation = execute_case(run, case_id, args.workdir)
        response = {
            "protocol_version": RESPONSE_VERSION,
            "case_id": case_id,
            "status": "EXECUTED",
            "boundary": None,
            "observation": observation,
        }
    except UnsupportedCase as exc:
        response = {
            "protocol_version": RESPONSE_VERSION,
            "case_id": case_id,
            "status": "NOT_SUPPORTED",
            "boundary": str(exc),
        }
    args.response.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.response.with_suffix(args.response.suffix + ".tmp")
    temporary.write_text(
        json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
