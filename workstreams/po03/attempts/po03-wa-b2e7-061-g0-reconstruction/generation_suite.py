#!/usr/bin/env python3
"""The frozen public custody suite and the generation runner.

One suite, one runner, three generations.  A generation is a factory source file
plus a name; the runner materialises a fresh sandbox repository per case, imports
the generation into it, and scores the case.

Scoring is deliberately unforgiving in the older generation's favour nowhere: a
capability the generation does not expose scores UNSUPPORTED, which counts as
not passed, exactly as the preregistration requires.

The public suite in this module is producer-visible.  The holdout cases it also
runs are loaded from the sealed evaluator-held file produced by unit 059, and the
seal digest is recorded with every run so two runs can be compared only when they
measured the same cases.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import itertools
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUITE_VERSION = "PO03-PUBLIC-CUSTODY-SUITE-v1"
RUNNER_VERSION = "PO03-GENERATION-RUNNER-v1"
HASH = "f" * 64

SKELETON_SOURCES = (
    "workstreams/po03/COMMISSION.md",
    "workstreams/po03/contracts/transactional-result.schema.json",
    "workstreams/po03/contracts/wave-compounding.schema.json",
    "workstreams/po03/tools/validate_contracts.py",
)

_COUNTER = itertools.count()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _passed(detail: str) -> dict[str, Any]:
    return {"outcome": "PASS", "detail": detail, "reports_success": False, "invariant_held": True}


def _failed(detail: str, *, reports_success: bool = True) -> dict[str, Any]:
    return {"outcome": "FAIL", "detail": detail, "reports_success": reports_success, "invariant_held": False}


def _unsupported(missing: list[str]) -> dict[str, Any]:
    return {
        "outcome": "UNSUPPORTED",
        "detail": f"generation does not expose {', '.join(missing)}",
        "reports_success": None,
        "invariant_held": None,
    }


def _missing(module, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not hasattr(module, name)]


class Instance:
    """A sandbox repository with one freshly imported generation module.

    The sandbox is cloned from a prepared template rather than initialised from
    scratch, so per-case setup is a file copy instead of repeated Git work.
    """

    def __init__(self, template: Path, module_relative: str, name: str):
        self.root = Path(tempfile.mkdtemp(prefix=f"po03-gen-{name.lower()}-"))
        self.root.rmdir()
        shutil.copytree(template, self.root, symlinks=False)
        self.module_path = self.root / module_relative
        self.module = self._import(name)

    def _import(self, name: str):
        unique = f"po03_generation_{name.lower()}_{next(_COUNTER)}"
        spec = importlib.util.spec_from_file_location(unique, self.module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments), cwd=self.root, check=True, capture_output=True, text=True
        )
        return completed.stdout

    def git(self, *arguments: str) -> str:
        return self._git(*arguments)

    def commit_bytes(self, relative: str, payload: bytes) -> str:
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        self._git("add", "--", relative)
        self._git("commit", "-q", "-m", f"add {relative}")
        return self._git("rev-parse", "HEAD").strip()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class Generation:
    """A named generation source that can be instantiated repeatedly."""

    def __init__(self, name: str, source: Path, repo: Path, description: str = ""):
        self.name = name
        self.source = Path(source)
        self.repo = Path(repo)
        self.description = description
        payload = self.source.read_bytes()
        self.source_sha256 = sha256_bytes(payload)
        self.source_bytes = len(payload)
        self.module_relative = f"workstreams/po03/tools/{self.source.name}"
        self.template = self._build_template()

    def _build_template(self) -> Path:
        template = Path(tempfile.mkdtemp(prefix=f"po03-template-{self.name.lower()}-"))
        (template / "workstreams/po03/tools").mkdir(parents=True)
        shutil.copy2(self.source, template / self.module_relative)
        for relative in SKELETON_SOURCES:
            destination = template / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.repo / relative, destination)
        for relative in ("workstreams/po03/control", "workstreams/po03/evidence", "workstreams/po03/metrics"):
            (template / relative).mkdir(parents=True, exist_ok=True)
        (template / ".gitignore").write_text("_child_*.py\n_barrier\n_tokens-*.json\n", encoding="utf-8")
        for arguments in (
            ("init", "-q", "-b", "main"),
            ("config", "user.email", "po03-generation-runner@obzio.internal"),
            ("config", "user.name", "PO03 Generation Runner"),
            ("config", "commit.gpgsign", "false"),
            ("config", "gc.auto", "0"),
            # The sandbox is disposable, so durability of its own Git objects
            # buys nothing and costs a synchronous flush per commit.
            ("config", "core.fsync", "none"),
        ):
            subprocess.run(("git", *arguments), cwd=template, check=True, capture_output=True)
        return template

    def instance(self) -> Instance:
        return Instance(self.template, self.module_relative, self.name)

    def close(self) -> None:
        shutil.rmtree(self.template, ignore_errors=True)


# --------------------------------------------------------------------------
# Shared fixtures for the public suite


def _acceptance() -> dict[str, Any]:
    return {"acceptance_version": "PO03-SUITE-ACCEPTANCE-v1", "criteria": ["suite"], "decision_changed": []}


def _make_capsule(module, task_id: str, *, fence_token: int = 1, result_slot: str | None = None) -> None:
    slot = result_slot or f"workstreams/po03/attempts/{task_id}"
    module.task_capsule(
        task_id=task_id,
        head_sha="0" * 40,
        run_id="suite-run",
        model="suite-model",
        reasoning="high",
        hypothesis="suite hypothesis",
        prompt="suite prompt",
        owned_paths=[f"{slot}/**"],
        result_slot=slot,
        acceptance=_acceptance(),
        lease_seconds=60,
        fence_token=fence_token,
    )


def _result_document(
    *, task_id: str, commit: str, path: str, sha256: str, size: int, state: str = "RESULT_COMMITTED"
) -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": task_id,
        "commission_id": "COM-PO03-SUITE",
        "immutable_input_manifest_sha256": HASH,
        "acceptance_contract_sha256": HASH,
        "provider_state": "RUNNING",
        "obzio_state": state,
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": f"COM-PO03-SUITE:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "fence_token": 1,
            "provider_run_id": "suite-provider-run",
            "worker_id": "suite-worker",
            "heartbeat_at": "2026-08-22T07:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"result-{task_id}-1",
            "state": "COMMITTED",
            "manifest_uri": f"git:{commit}:{path}",
            "manifest_sha256": HASH,
            "artifact_count": 1,
            "total_bytes": size,
            "committed_at": "2026-08-22T07:01:00Z",
            "verified_at": "2026-08-22T07:01:00Z",
            "parent_ingested_at": None,
            "result_commit_id": commit,
        },
        "artifacts": [
            {
                "artifact_id": f"{task_id}-artifact-001",
                "logical_name": Path(path).name,
                "content_uri": f"git:{commit}:{path}",
                "sha256": sha256,
                "bytes": size,
                "media_type": "text/plain",
                "readback_verified_at": "2026-08-22T07:01:00Z",
            }
        ],
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }


def _commit_artifact(instance: Instance, task_id: str) -> tuple[str, str, str, int]:
    relative = f"workstreams/po03/attempts/{task_id}/artifact.txt"
    payload = f"suite artifact for {task_id}\n".encode("utf-8")
    commit = instance.commit_bytes(relative, payload)
    return commit, relative, sha256_bytes(payload), len(payload)


# --------------------------------------------------------------------------
# The frozen public suite


def p01_capsule_creation_is_immutable(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule",))
        if missing:
            return _unsupported(missing)
        _make_capsule(module, "suite-capsule")
        directory = instance.root / "workstreams/po03/control/tasks/suite-capsule"
        events = sorted((instance.root / "workstreams/po03/control/events/suite-capsule").glob("*.json"))
        present = [name for name in ("input.json", "acceptance.json", "transaction-created.json")
                   if (directory / name).is_file()]
        if len(present) == 3 and len(events) == 1:
            return _passed("capsule wrote input, acceptance and transaction documents plus one CREATED event")
        return _failed(f"capsule wrote {present} and {len(events)} events")
    finally:
        instance.close()


def p02_write_once_rejects_divergent_rewrite(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("write_once",))
        if missing:
            return _unsupported(missing)
        target = instance.root / "workstreams/po03/control/immutable.json"
        module.write_once(target, b"first\n")
        try:
            module.write_once(target, b"second\n")
        except FileExistsError:
            if target.read_bytes() == b"first\n":
                return _passed("a divergent rewrite of an immutable file was refused and the bytes held")
            return _failed("the rewrite was refused but the bytes changed anyway")
        return _failed("an immutable file was silently rewritten with different bytes")
    finally:
        instance.close()


def p03_write_once_is_idempotent(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("write_once",))
        if missing:
            return _unsupported(missing)
        target = instance.root / "workstreams/po03/control/idempotent.json"
        module.write_once(target, b"same\n")
        try:
            module.write_once(target, b"same\n")
        except Exception as exc:  # noqa: BLE001
            return _failed(f"an identical replay raised {type(exc).__name__}", reports_success=False)
        if target.read_bytes() == b"same\n":
            return _passed("an identical replay was a no-op")
        return _failed("an identical replay changed the bytes")
    finally:
        instance.close()


def p04_allowlist_rejects_foreign_write(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("write_once",))
        if missing:
            return _unsupported(missing)
        try:
            module.write_once(instance.root / "packs/operator-packs-v1/forged.json", b"x\n")
        except ValueError as exc:
            return _passed(f"a write outside the PO-03 allowlist was refused: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _failed(f"the write failed for the wrong reason: {type(exc).__name__}: {exc}")
        return _failed("a write outside the PO-03 allowlist succeeded")
    finally:
        instance.close()


def p05_event_chain_links_previous_hash(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("hash_chain_event",))
        if missing:
            return _unsupported(missing)
        for state in ("LEASED", "RUNNING", "CHECKPOINTED"):
            module.hash_chain_event("suite-chain", state, actor="suite-controller")
        events = sorted((instance.root / "workstreams/po03/control/events/suite-chain").glob("*.json"))
        previous = None
        for path in events:
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("previous_event_sha256") != previous:
                return _failed(f"{path.name} does not link its predecessor")
            previous = sha256_bytes(path.read_bytes())
        if len(events) == 3:
            return _passed("three events form an unbroken hash chain")
        return _failed(f"expected three events, observed {len(events)}")
    finally:
        instance.close()


def p06_verify_chain_detects_tampering(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("hash_chain_event", "verify_chain"))
        if missing:
            return _unsupported(missing)
        for state in ("LEASED", "RUNNING"):
            module.hash_chain_event("suite-tamper", state, actor="suite-controller")
        events = sorted((instance.root / "workstreams/po03/control/events/suite-tamper").glob("*.json"))
        body = json.loads(events[0].read_text(encoding="utf-8"))
        body["details"] = {"tampered": True}
        events[0].write_bytes(canonical(body))
        errors = module.verify_chain("suite-tamper")
        if errors:
            return _passed(f"chain verification detected the tampered event body: {errors}")
        return _failed("a tampered event body verified clean")
    finally:
        instance.close()


def p07_fence_allocation_is_monotonic(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("allocate_fence",))
        if missing:
            return _unsupported(missing)
        tokens = [module.allocate_fence() for _ in range(5)]
        if tokens == sorted(set(tokens)) and len(set(tokens)) == 5:
            return _passed(f"sequential allocation produced strictly increasing tokens {tokens}")
        return _failed(f"sequential allocation produced {tokens}")
    finally:
        instance.close()


def p08_stale_fence_write_is_rejected(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("grant_lease", "assert_fence_current"))
        if missing:
            return _unsupported(missing)
        first = module.grant_lease("suite-fence", holder="worker-a", lease_seconds=60, attempt=1)
        module.grant_lease("suite-fence", holder="worker-b", lease_seconds=60, attempt=2)
        try:
            module.assert_fence_current("suite-fence", first["fence_token"])
        except Exception as exc:  # noqa: BLE001
            return _passed(f"a superseded fence was refused: {type(exc).__name__}")
        return _failed("a superseded worker's fence was accepted after ownership moved")
    finally:
        instance.close()


def p09_contract_rejects_worker_set_completion(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("load_result_validator",))
        if missing:
            return _unsupported(missing)
        validator = module.load_result_validator()
        commit, path, sha, size = _commit_artifact(instance, "suite-contract")
        document = _result_document(task_id="suite-contract", commit=commit, path=path, sha256=sha, size=size)
        document["obzio_state"] = "COMPLETED"
        document["completion_actor"] = "suite-worker"
        document["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:02:00Z"
        errors = validator.validate_result(document)
        if errors:
            return _passed(f"the contract refused a worker-set completion: {errors}")
        return _failed("the contract accepted a worker-set completion")
    finally:
        instance.close()


def p10_readback_is_by_immutable_object(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("read_object_bytes",))
        if missing:
            return _unsupported(missing)
        commit, path, sha, size = _commit_artifact(instance, "suite-readback")
        observed = module.read_object_bytes(f"git:{commit}:{path}")
        if sha256_bytes(observed) != sha or len(observed) != size:
            return _failed("reading a committed object by id returned different bytes")
        try:
            module.read_object_bytes("/var/tmp/not-a-git-locator")
        except Exception:
            return _passed("committed bytes read back by object id and a non-durable locator was refused")
        return _failed("a non-durable locator was accepted as an artifact source")
    finally:
        instance.close()


def p11_duplicate_callback_is_idempotent(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result"))
        if missing:
            return _unsupported(missing)
        task_id = "suite-duplicate"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(task_id=task_id, commit=commit, path=path, sha256=sha, size=size)
        first = module.ingest_result(task_id, document)
        second = module.ingest_result(task_id, copy.deepcopy(document))
        ingestions = sorted(
            (instance.root / "workstreams/po03/control/tasks" / task_id).glob("ingestion-*.json")
        )
        if first["errors"]:
            return _failed(f"a valid result was refused: {first['errors']}", reports_success=False)
        if len(ingestions) == 1 and second.get("duplicate_callback_suppressed"):
            return _passed("a replayed identical callback was suppressed rather than double counted")
        return _failed(f"{len(ingestions)} ingestion records exist after a replayed callback")
    finally:
        instance.close()


def p12_completion_requires_parent_ingestion(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "complete_unit"))
        if missing:
            return _unsupported(missing)
        task_id = "suite-completion-gate"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(task_id=task_id, commit=commit, path=path, sha256=sha, size=size)
        document["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:02:00Z"
        try:
            module.complete_unit(task_id, document)
        except Exception as exc:  # noqa: BLE001
            return _passed(f"completion before ingestion was refused: {type(exc).__name__}")
        return _failed("a unit reached COMPLETED without parent ingestion")
    finally:
        instance.close()


def p13_recovery_scan_flags_an_orphan(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("scan_recovery", "write_once"))
        if missing:
            return _unsupported(missing)
        orphan = instance.root / "workstreams/po03/control/tasks/suite-orphan/input.json"
        module.write_once(orphan, canonical({"task_id": "suite-orphan"}))
        state = module.scan_recovery("suite-run", "0" * 40)
        unit = state["units"].get("suite-orphan", {})
        if state.get("orphan_count", 0) >= 1 and unit.get("recovery_action") == "REDISPATCH_FROM_IMMUTABLE_INPUT":
            return _passed("the recovery scan flagged a unit with an immutable input and no events")
        return _failed(f"orphan_count={state.get('orphan_count')} action={unit.get('recovery_action')!r}")
    finally:
        instance.close()


def p14_path_collision_fails_closed(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("detect_path_collisions",))
        if missing:
            return _unsupported(missing)
        ownership = {
            "ownership_version": "PO03-PATH-OWNERSHIP-v1",
            "controller": {"run_id": "suite-run", "owned_paths": []},
            "subordinates": [
                {"task_id": "unit-a", "owned_paths": ["workstreams/po03/attempts/shared/**"], "fence_token": 1},
                {"task_id": "unit-b", "owned_paths": ["workstreams/po03/attempts/shared/deep/**"], "fence_token": 2},
            ],
            "collision_policy": "FAIL_CLOSED",
            "decision_changed": [],
        }
        (instance.root / "workstreams/po03/control").mkdir(parents=True, exist_ok=True)
        (instance.root / "workstreams/po03/control/path-ownership.json").write_bytes(canonical(ownership))
        collisions = module.detect_path_collisions()
        if collisions:
            return _passed(f"overlapping subtree claims were detected: {collisions}")
        return _failed("two subordinates claiming overlapping subtrees produced no collision")
    finally:
        instance.close()


def p15_registry_is_append_only(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("append_registry",))
        if missing:
            return _unsupported(missing)
        module.append_registry({"registry_event": "FIRST"})
        module.append_registry({"registry_event": "SECOND"})
        registry = instance.root / "workstreams/po03/control/work-unit-registry.jsonl"
        lines = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines() if line.strip()]
        if [line["registry_event"] for line in lines] == ["FIRST", "SECOND"]:
            return _passed("the second append preserved the first line in order")
        return _failed(f"registry contains {[line.get('registry_event') for line in lines]}")
    finally:
        instance.close()


def p16_ingestion_refuses_a_result_without_artifacts(generation: Generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result"))
        if missing:
            return _unsupported(missing)
        task_id = "suite-no-artifacts"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(
            task_id=task_id, commit=commit, path=path, sha256=sha, size=size, state="RESULT_STAGED"
        )
        document["artifacts"] = []
        document["result_transaction"]["artifact_count"] = 0
        document["result_transaction"]["total_bytes"] = 0
        ingestion = module.ingest_result(task_id, document)
        if ingestion["errors"]:
            return _passed(f"a result with nothing durable was refused: {ingestion['errors']}")
        return _failed("a result carrying no artifacts was ingested")
    finally:
        instance.close()


PUBLIC_SUITE: dict[str, dict[str, Any]] = {
    "P01-capsule-creation-is-immutable": {"case": p01_capsule_creation_is_immutable},
    "P02-write-once-rejects-divergent-rewrite": {"case": p02_write_once_rejects_divergent_rewrite},
    "P03-write-once-is-idempotent": {"case": p03_write_once_is_idempotent},
    "P04-allowlist-rejects-foreign-write": {"case": p04_allowlist_rejects_foreign_write},
    "P05-event-chain-links-previous-hash": {"case": p05_event_chain_links_previous_hash},
    "P06-verify-chain-detects-tampering": {"case": p06_verify_chain_detects_tampering},
    "P07-fence-allocation-is-monotonic": {"case": p07_fence_allocation_is_monotonic},
    "P08-stale-fence-write-is-rejected": {"case": p08_stale_fence_write_is_rejected},
    "P09-contract-rejects-worker-set-completion": {"case": p09_contract_rejects_worker_set_completion},
    "P10-readback-is-by-immutable-object": {"case": p10_readback_is_by_immutable_object},
    "P11-duplicate-callback-is-idempotent": {"case": p11_duplicate_callback_is_idempotent},
    "P12-completion-requires-parent-ingestion": {"case": p12_completion_requires_parent_ingestion},
    "P13-recovery-scan-flags-an-orphan": {"case": p13_recovery_scan_flags_an_orphan},
    "P14-path-collision-fails-closed": {"case": p14_path_collision_fails_closed},
    "P15-registry-is-append-only": {"case": p15_registry_is_append_only},
    "P16-ingestion-refuses-result-without-artifacts": {"case": p16_ingestion_refuses_a_result_without_artifacts},
}


# --------------------------------------------------------------------------
# Runner


def load_holdout(path: Path):
    spec = importlib.util.spec_from_file_location("po03_holdout_cases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def suite_freeze(holdout_path: Path, seal_path: Path | None) -> dict[str, Any]:
    this_file = Path(__file__).resolve()
    holdout_bytes = holdout_path.read_bytes()
    record = {
        "suite_version": SUITE_VERSION,
        "runner_version": RUNNER_VERSION,
        "public_suite_file": this_file.name,
        "public_suite_sha256": sha256_bytes(this_file.read_bytes()),
        "public_case_count": len(PUBLIC_SUITE),
        "holdout_file": holdout_path.as_posix(),
        "holdout_sha256": sha256_bytes(holdout_bytes),
    }
    if seal_path is not None and seal_path.is_file():
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        record["holdout_seal_combined_sha256"] = seal.get("combined_sha256")
        recorded = {entry["path"]: entry["sha256"] for entry in seal.get("files", [])}
        record["holdout_seal_matches_file"] = (
            recorded.get("hidden/holdout_custody_cases.py") == record["holdout_sha256"]
        )
    return record


def score(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record["outcome"] == "PASS")
    failed = sum(1 for record in records if record["outcome"] == "FAIL")
    unsupported = sum(1 for record in records if record["outcome"] == "UNSUPPORTED")
    reported_success = [record for record in records if record.get("reports_success")]
    false_green = [record for record in reported_success if record.get("invariant_held") is False]
    return {
        "case_count": total,
        "passed": passed,
        "failed": failed,
        "unsupported": unsupported,
        "pass_rate": passed / total if total else None,
        "reported_success_count": len(reported_success),
        "false_green_count": len(false_green),
        "false_green_rate": len(false_green) / len(reported_success) if reported_success else 0.0,
    }


def run_generation(generation: Generation, holdout_path: Path, seal_path: Path | None) -> dict[str, Any]:
    holdout = load_holdout(holdout_path)
    public_records = []
    for case_id, spec in PUBLIC_SUITE.items():
        record = spec["case"](generation)
        public_records.append({"case_id": case_id, "suite": "public", **record})
    holdout_records = []
    for case_id, spec in sorted(holdout.HOLDOUT_CASES.items()):
        record = spec["case"](generation)
        holdout_records.append(
            {
                "case_id": case_id,
                "suite": "holdout",
                "hazard": spec["hazard"],
                "public_suite_covers": spec["public_suite_covers"],
                **record,
            }
        )
    generation.close()
    combined = public_records + holdout_records
    return {
        "runner_version": RUNNER_VERSION,
        "measured_at": utc_now(),
        "generation": {
            "name": generation.name,
            "description": generation.description,
            "source": generation.source.as_posix(),
            "source_sha256": generation.source_sha256,
            "source_bytes": generation.source_bytes,
        },
        "suite_freeze": suite_freeze(holdout_path, seal_path),
        "public": score(public_records),
        "holdout": score(holdout_records),
        "combined": score(combined),
        "records": combined,
        "decision_changed": [],
    }
