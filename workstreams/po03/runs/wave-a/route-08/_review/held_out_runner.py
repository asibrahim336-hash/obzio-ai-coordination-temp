#!/usr/bin/env python3
"""Execute the frozen route-08 challenger cases against immutable target code."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]


def load(task: str, relative: str) -> Any:
    path = REPO / "workstreams/po03/runs/wave-a" / task / relative
    name = "route08_held_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def expect_raises(exc: type[BaseException], call: Callable[[], Any]) -> BaseException:
    try:
        call()
    except exc as caught:
        return caught
    raise AssertionError(f"expected {exc.__name__}")


def h001() -> dict[str, Any]:
    m = load("route-01/PO03-WA-001", "custody_fsm.py")
    rejected = []
    for source, target in (
        ("CREATED", "RESULT_STAGED"),
        ("RESULT_STAGED", "RUNNING"),
        ("COMPLETED", "RESULT_COMMITTED"),
    ):
        record = m.CustodyRecord("held", state=source)
        before = (record.state, list(record.history))
        verdict = record.try_transition(target)
        assert not verdict["accepted"]
        assert (record.state, record.history) == before
        rejected.append(verdict["reason"])
    return {"rejected": rejected}


def h002() -> dict[str, Any]:
    m = load("route-01/PO03-WA-002", "fenced_sink.py")
    with tempfile.TemporaryDirectory() as tmp:
        sink = m.FencedResultSink(Path(tmp) / "sink.json")
        sink.acquire(2, "live")
        expect_raises(m.InvalidFenceError, lambda: sink.stage(0, "invalid", b"x"))
        expect_raises(m.StaleFenceError, lambda: sink.stage(1, "stale", b"x"))
        sink.stage(2, "live", b"current")
        other = m.FencedResultSink(Path(tmp) / "other.json")
        other.acquire(2, "live")
        try:
            other.stage(3, "unleased", b"future")
        except m.FenceError:
            future_rejected = True
        else:
            future_rejected = False
        assert future_rejected, "current+1 staged without an externally validated live lease"
    return {"invalid_rejected": True, "stale_rejected": True, "future_rejected": future_rejected}


def h003() -> dict[str, Any]:
    m = load("route-01/PO03-WA-003", "idempotent_callback.py")
    with tempfile.TemporaryDirectory() as tmp:
        receiver = m.IdempotentCallbackReceiver(Path(tmp))
        first = receiver.receive("key", {"result": "A"})
        replay = receiver.receive("key", {"result": "A"})
        expect_raises(m.IdempotencyConflict, lambda: receiver.receive("key", {"result": "B"}))
        assert first["result_txn_id"] == replay["result_txn_id"]
        assert len(receiver.transactions()) == 1 and receiver.created_count() == 1
    return {"transactions": 1, "created_events": 1}


def h004() -> dict[str, Any]:
    m = load("route-01/PO03-WA-004", "outbox_relay.py")
    with tempfile.TemporaryDirectory() as tmp:
        store = m.WorkerStore(Path(tmp) / "worker.json")
        store.commit_and_enqueue("held", {"value": 1})
        row = store.pending()[0]
        parent = m.ParentCoordinator()
        message = {
            "idempotency_key": row["idempotency_key"],
            "task_id": row["task_id"],
            "payload": row["payload"],
        }
        parent.callback(message)  # effect happened; acknowledgement was lost
        relay = m.OutboxRelay(store, m.UnreliableChannel([]), parent)
        first, second = relay.scan_once(), relay.scan_once()
        assert len(parent.ingested) == 1
        assert first["still_pending"] == 0 and not second["outcomes"]
    return {"effects": len(parent.ingested), "second_recovery_outcomes": second["outcomes"]}


def h005() -> dict[str, Any]:
    m = load("route-01/PO03-WA-005", "staging_gate.py")

    class SameSizeCorruptor(m.CrashInjector):
        def intercept(self, index: int, payload: bytes) -> bytes:
            if index == 0:
                return bytes([payload[0] ^ 1]) + payload[1:]
            return payload

    with tempfile.TemporaryDirectory() as tmp:
        gate = m.StagingGate(Path(tmp) / "slot")
        declared = [m.DeclaredArtifact("artifact.bin", b"same-size")]
        refusal = expect_raises(m.StagingRefused, lambda: gate.stage(declared, SameSizeCorruptor()))
        assert refusal.reason == "ARTIFACT_VERIFICATION_FAILED"
        assert gate.state == "RESULT_STAGING" and not gate.slot.exists()
    return {"reason": refusal.reason, "state": gate.state}


def h006() -> dict[str, Any]:
    m = load("route-01/PO03-WA-006", "effect_journal.py")
    with tempfile.TemporaryDirectory() as tmp:
        external = m.ExternalSystem()
        workflow = m.CommitWorkflow(Path(tmp), external)
        expect_raises(
            m.ProcessLost,
            lambda: workflow.run("held", {"value": 1}, crash_at="after_applied"),
        )
        first = m.CommitWorkflow(Path(tmp), external).recover("held")
        second = m.CommitWorkflow(Path(tmp), external).recover("held")
        assert external.total_executions() == 1
        assert not first["effect_reapplied"] and not second["effect_reapplied"]
    return {"external_executions": 1, "recoveries": [first["action"], second["action"]]}


def h007() -> dict[str, Any]:
    m = load("route-01/PO03-WA-007", "reclassifier.py")
    result = m.Reclassifier(m.CommitResolver()).classify(
        m.Observation("held", "COMPLETED", result_commit_id=None)
    )
    assert result.obzio_state == "PROVIDER_COMPLETED_UNCOMMITTED"
    return result.as_dict()


def h008() -> dict[str, Any]:
    m = load("route-01/PO03-WA-008", "recovery_scan.py")
    roster = ["b", "a", "a", "c"]
    events = [
        {"task_id": "b", "event_seq": 1, "state": "RUNNING", "fence_token": 1},
        {"task_id": "a", "event_seq": 1, "state": "LEASED", "fence_token": 1},
    ]
    one = m.scan(roster, events + [events[0]])
    two = m.scan(reversed(roster), list(reversed(events)) + [events[0]])
    assert one == two and [row["task_id"] for row in one["resume"]] == ["a", "b", "c"]
    return {"plan_sha256": one["plan_sha256"], "resume": ["a", "b", "c"]}


def h033() -> dict[str, Any]:
    m = load("route-05/PO03-WA-033", "src/changed_path_guard.py")
    guard = m.ChangedPathGuard(("owned/",))
    report = m.build_report(guard, ["owned/add.json", "foreign/deleted.json"])
    assert not report["admissible"] and report["rejected"] == 1
    assert report["decisions"][1]["raw_path"] == "foreign/deleted.json"
    return report


def h034() -> dict[str, Any]:
    m = load("route-05/PO03-WA-034", "src/symlink_resolution_guard.py")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        owned, outside = base / "owned", base / "outside"
        owned.mkdir()
        outside.mkdir()
        (owned / "nested").mkdir()
        (owned / "nested/link").symlink_to(Path("../../outside"), target_is_directory=True)
        verdict = m.SymlinkResolutionGuard(str(owned)).evaluate("nested/link/result.json")
        assert not verdict.allowed() and "SYMLINK_ESCAPE" in verdict.verdict
    return {"verdict": verdict.verdict, "resolved_path": verdict.resolved_path}


def h035() -> dict[str, Any]:
    m = load("route-05/PO03-WA-035", "src/rename_guard.py")
    guard = m.RenameGuard(m.subtree_ownership(("owned/",)))
    out = guard.evaluate(m.RenameRecord("owned/a", "foreign/a"))
    into = guard.evaluate(m.RenameRecord("foreign/b", "owned/b"))
    assert not out.allowed() and not into.allowed()
    return {"out": out.verdict, "into": into.verdict}


def h036() -> dict[str, Any]:
    m = load("route-05/PO03-WA-036", "src/manifest_reconciler.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "unicode.txt"
        original = "é漢".encode()
        path.write_bytes(original)
        entry = {
            "artifact_id": "u",
            "content_uri": "unicode.txt",
            "sha256": hashlib.sha256(original).hexdigest(),
            "bytes": len(original),
        }
        clean = m.reconcile_artifacts(root, [entry])[0]
        path.write_bytes("ê漢".encode())
        corrupt = m.reconcile_artifacts(root, [entry])[0]
        assert clean.finding == m.MATCH and clean.observed_bytes == len(original)
        assert corrupt.finding == m.SHA_MISMATCH
    return {"bytes": len(original), "characters": 2, "corrupt_finding": corrupt.finding}


def h037() -> dict[str, Any]:
    m = load("route-05/PO03-WA-037", "src/transport_debris_disposition.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "deep/__pycache__").mkdir(parents=True)
        debris = root / "deep/__pycache__/x.pyc"
        legitimate = root / "cache-evidence.pyc.txt"
        debris.write_bytes(b"cache")
        legitimate.write_text("legitimate evidence")
        before = m.census(root)
        findings = m.scan(root)
        after = m.census(root)
        paths = {row.path for row in findings}
        assert "deep/__pycache__/x.pyc" in paths
        assert "cache-evidence.pyc.txt" not in paths
        assert not m.verify_census_unchanged(before, after)
    return {"findings": sorted(paths), "legitimate_preserved": legitimate.exists()}


def h038() -> dict[str, Any]:
    m = load("route-05/PO03-WA-038", "src/lineage_recorder.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "source").write_text("source")
        (root / "tool").write_text("tool")
        (root / "output").write_text("output")
        record = m.record_generation(
            root, "child", "output", ["source"], "tool", "1", "tool", {"seed": 1}
        )
        document = record.to_dict()
        document.pop("parents")
        restored = m.LineageLedger.from_dict({"records": [document]})
        findings = m.verify(restored, root)
        assert findings, "omitting the parent lineage field was silently treated as no parents"
    return {"findings": [row.finding for row in findings]}


def h039() -> dict[str, Any]:
    m = load("route-05/PO03-WA-039", "src/disjoint_writer_arbiter.py")
    lookalike = m.detect_claim_overlaps([m.Claim("a", "a/b"), m.Claim("b", "a/bc")])
    nested = m.detect_claim_overlaps([m.Claim("a", "a/b"), m.Claim("b", "a/b/c")])
    disjoint = m.detect_claim_overlaps([m.Claim("a", "x/one"), m.Claim("b", "x/two")])
    assert not lookalike and len(nested) == 1 and not disjoint
    return {"lookalike_overlaps": 0, "nested_overlaps": 1, "disjoint_overlaps": 0}


def h040() -> dict[str, Any]:
    m = load("route-05/PO03-WA-040", "src/shared_path_controller_gate.py")
    policy = m.OwnershipPolicy(
        ("workstreams/po03/",),
        ("workstreams/po03/control/**",),
        m.Identity("controller", 7),
    )
    with tempfile.TemporaryDirectory() as tmp:
        gate = m.SharedPathControllerGate(
            Path(tmp), policy, m.Identity("worker", 7), "workstreams/po03/runs/wave-a/route-05"
        )
        path = "workstreams/po03/control/forged.json"
        gate.stage(path, b'{"actor_id":"controller","fence_token":7}')
        decision = gate.precommit_check()
        expect_raises(m.GateViolationError, gate.commit)
        assert not decision.admissible and not (Path(tmp) / path).exists()
    return {"verdict": decision.violations[0].verdict, "written": False}


def h041() -> dict[str, Any]:
    m = load("route-06/PO03-WA-041", "mechanism.py")
    with tempfile.TemporaryDirectory() as tmp:
        store = m.CapsuleStore(tmp)
        first = store.put({"b": 2, "a": 1})
        reordered = store.put({"a": 1, "b": 2})
        changed = store.put({"a": 1, "b": 3})
        assert first == reordered and first != changed
    return {"canonical": first == reordered, "changed_address": first != changed}


def h042() -> dict[str, Any]:
    m = load("route-06/PO03-WA-042", "mechanism.py")
    with tempfile.TemporaryDirectory() as tmp:
        db = m.open_db(Path(tmp) / "db.sqlite")
        event = m.stage_result(db, "held", {"value": 1})
        first = m.deliver(db, event, crash_after_receiver=True)
        replay_one = m.replay(db)
        replay_two = m.replay(db)
        effects = db.execute("SELECT count(*) FROM callbacks").fetchone()[0]
        delivered = db.execute("SELECT delivered FROM outbox").fetchone()[0]
        db.close()
        assert first == "CRASHED_AFTER_IDEMPOTENT_EFFECT"
        assert effects == 1 and delivered == 1 and replay_two == []
    return {"effects": effects, "replays": [replay_one, replay_two]}


def h043() -> dict[str, Any]:
    m = load("route-06/PO03-WA-043", "mechanism.py")
    db = m.new_store()
    old = m.acquire(db, "same-worker")
    live = m.acquire(db, "same-worker")
    live_ok = m.fenced_write(db, live, "live")
    stale_ok = m.fenced_write(db, old, "stale")
    value = db.execute("SELECT value FROM custody").fetchone()[0]
    db.close()
    assert live_ok and not stale_ok and value == "live"
    return {"tokens": [old, live], "stale_accepted": stale_ok}


def h044() -> dict[str, Any]:
    m = load("route-06/PO03-WA-044", "mechanism.py")
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
        root = Path(tmp)
        (root / "inputs").mkdir()
        (root / "inputs/config.json").write_text('{"token":"declared"}')
        old_environment, old_cwd = dict(os.environ), Path.cwd()
        try:
            os.environ.clear()
            os.environ["HOME"] = home
            os.chdir(home)
            value = m.hermetic_load(root, "inputs/config.json")
        finally:
            os.chdir(old_cwd)
            os.environ.clear()
            os.environ.update(old_environment)
        assert value == "declared"
    return {"value": value, "ambient_state_used": False}


def h045() -> dict[str, Any]:
    m = load("route-06/PO03-WA-045", "mechanism.py")
    state = m.initial()
    unknown = m.guarded_step(state, "unknown-transition")
    after_terminal = m.guarded_step(
        {"state": "COMPLETED", "commit": True, "parent": True, "coordinator": True},
        "stage",
    )
    unknown_reported = unknown != state
    post_terminal_rejected = after_terminal["state"] == "COMPLETED"
    assert unknown_reported, "unknown transition was silently ignored"
    assert post_terminal_rejected, "post-terminal transition changed state"
    return {
        "unknown_reported": unknown_reported,
        "post_terminal_rejected": post_terminal_rejected,
    }


def h046() -> dict[str, Any]:
    m = load("route-06/PO03-WA-046", "mechanism.py")
    critical = lambda case: True
    equivalent = lambda case: m.valid_completion(case)
    original = m.MUTANTS
    try:
        m.MUTANTS = {"critical_false_completion": critical, "equivalent_syntax": equivalent}
        report = m.mutation_run(m.CASES)
    finally:
        m.MUTANTS = original
    assert "critical_false_completion" in report["killed"]
    assert "equivalent_syntax" not in report["survived"], (
        "behavior-equivalent mutant was reported as a surviving correctness escape"
    )
    return report


def h047() -> dict[str, Any]:
    m = load("route-06/PO03-WA-047", "mechanism.py")
    names = ["space name.json", "unicodé.json", ".leading-dot", "line\nbreak.json"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        observed = []
        for name in names:
            (root / name).write_text("same")
            row = m.portable_identity(root, name)
            assert row["relative_path"] == name
            observed.append(row["relative_path"])
    return {"round_tripped_paths": observed}


def h048() -> dict[str, Any]:
    m = load("route-06/PO03-WA-048", "mechanism.py")
    with tempfile.TemporaryDirectory() as tmp:
        warm = Path(tmp)
        (warm / "tracked").mkdir()
        (warm / "tracked/config.json").write_text('{"source":"tracked"}')
        (warm / "local-default.json").write_text('{"source":"untracked-helper"}')
        report = m.differential(warm)
        coupled = report["baseline_warm"] != report["baseline_clean"]
        assert coupled and report["portable_warm"] == report["portable_clean"]
    return {"environment_coupling_reported": coupled}


def h049() -> dict[str, Any]:
    m = load("route-07/PO03-WA-049", "completion_semantics.py")
    triple = m.CompletionTriple("COMPLETED", "RESULT_STAGED", "PENDING", None)
    report = m.independent_axes_report(triple)
    classification = m.classify(triple)
    assert report["provider"]["complete"]
    assert not report["obzio"]["complete"] and not report["acceptance"]["complete"]
    assert classification.effective_obzio_state == "PROVIDER_COMPLETED_UNCOMMITTED"
    return {"axes": report, "effective_obzio_state": classification.effective_obzio_state}


def h050() -> dict[str, Any]:
    m = load("route-07/PO03-WA-050", "acceptance_authority.py")
    producer = m.Principal(
        "obzio.function.producer",
        "obzio.appointment.producer.20260822.001",
        display_name="Alice Producer",
        aliases=("producer-alias",),
        model_family="gpt",
    )
    registry = m.IdentityRegistry([producer])
    claims = (" alice producer ", "ALICE PRODUCER", "producer-alias")
    for claim in claims:
        expect_raises(
            m.SelfAcceptanceBlocked,
            lambda claim=claim: m.authorize_acceptance(
                registry, "Alice Producer", claim, consequential=False
            ),
        )
    return {"blocked_claims": list(claims)}


def h051() -> dict[str, Any]:
    m = load("route-07/PO03-WA-051", "transition_oracle.py")
    cases = m.enumerate_cases()
    terminal_outgoing = [
        case for case in cases if case.source in m.TERMINAL_STATES and case.must_be_accepted
    ]
    skips = [case for case in cases if case.verdict is m.Verdict.SKIP]
    legal = m.legal_cases()
    assert len(cases) == len(m.ALL_STATES) ** 2
    assert legal and skips and not terminal_outgoing
    return {"total": len(cases), "legal": len(legal), "skips": len(skips)}


def h052() -> dict[str, Any]:
    m = load("route-07/PO03-WA-052", "ontology_guard.py")
    bad = m.ActorRecord(
        function="cursor",
        appointment="gpt-5.6-sol-xhigh",
        runtime_binding="cursor",
        provider_model="gpt-5.6-sol-xhigh",
    )
    expect_raises(m.OntologyViolation, lambda: m.resolve(bad))
    good = m.ActorRecord(
        function="obzio.function.review",
        appointment="obzio.appointment.review.20260822.001",
        runtime_binding="cursor",
        provider_model="gpt-5.6-sol-xhigh",
        authority_envelope="AE-1",
    )
    resolved = m.resolve(good)
    assert resolved.separated
    return {"invalid_rejected": True, "runtime_axis": resolved.axes["runtime"]}


def h053() -> dict[str, Any]:
    m = load("route-07/PO03-WA-053", "metric_aggregator.py")
    values = [0, None, m.NOT_SUPPORTED, 5]
    aggregate = m.aggregate_sum("mixed", values)
    assert aggregate.value == 5
    assert aggregate.known_count == 2 and aggregate.unknown_count == 2
    assert aggregate.coverage == 0.5
    return aggregate.as_row()


def h054() -> dict[str, Any]:
    m = load("route-07/PO03-WA-054", "review_order_gate.py")
    gate = m.ReviewOrderGate()
    expect_raises(
        m.ReviewOrderViolation,
        lambda: gate.open_source("workstreams/po03/runs/wave-a/route-x/FINDING.md"),
    )
    audit = gate.audit()
    assert not audit["blind_order_held"] and audit["violations"]
    return audit


def h055() -> dict[str, Any]:
    m = load("route-07/PO03-WA-055", "candidate_ranker.py")
    rubric = m.Rubric(
        "held",
        (
            m.Criterion("critical_correctness", 100),
            m.Criterion("optional", 1),
        ),
    )
    candidates = [
        m.Candidate("missing-critical", "p1", "gpt", {"optional": 1.0}),
        m.Candidate("complete-a", "p2", "claude", {"critical_correctness": 0.9, "optional": 0.0}),
        m.Candidate("complete-b", "p3", "gpt", {"critical_correctness": 0.8, "optional": 0.0}),
    ]
    result = m.rank(rubric, candidates, rubric.digest())
    assert result["winner"] != "missing-critical", (
        "candidate missing critical evidence won through optional-score averaging"
    )
    return result


def h056() -> dict[str, Any]:
    m = load("route-07/PO03-WA-056", "manifest_verifier.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_bytes(b"AAAA")
        manifest = m.build_manifest(root)
        duplicate = copy.deepcopy(manifest)
        duplicate["artifacts"].append(copy.deepcopy(duplicate["artifacts"][0]))
        duplicate["artifact_count"] += 1
        duplicate["total_bytes"] += duplicate["artifacts"][0]["bytes"]
        duplicate["artifacts"][1]["sha256"] = "f" * 64
        dup_verdict = m.verify(root, duplicate)
        corrupt = copy.deepcopy(manifest)
        corrupt["artifacts"][0]["sha256"] = hashlib.sha256(b"BBBB").hexdigest()
        corrupt_verdict = m.verify(root, corrupt)
        assert not dup_verdict.passed and "DUPLICATE_ENTRY" in dup_verdict.codes
        assert not corrupt_verdict.passed and "DIGEST_MISMATCH" in corrupt_verdict.codes
    return {"duplicate_codes": sorted(dup_verdict.codes), "corrupt_codes": sorted(corrupt_verdict.codes)}


CASES: dict[str, Callable[[], dict[str, Any]]] = {
    f"H{number}": globals()[f"h{number}"]
    for number in (
        "001", "002", "003", "004", "005", "006", "007", "008",
        "033", "034", "035", "036", "037", "038", "039", "040",
        "041", "042", "043", "044", "045", "046", "047", "048",
        "049", "050", "051", "052", "053", "054", "055", "056",
    )
}


def execute(selected: set[str] | None = None) -> dict[str, Any]:
    outcomes = []
    for case_id, function in CASES.items():
        task_id = f"PO03-WA-{case_id[1:]}"
        if selected and task_id not in selected and case_id not in selected:
            continue
        try:
            evidence = function()
        except Exception as exc:  # each case must produce an evidence row
            outcomes.append(
                {
                    "case_id": next(
                        row["case_id"]
                        for row in json.loads((HERE / "held-out-cases.json").read_text())["cases"]
                        if row["task_id"] == task_id
                    ),
                    "task_id": task_id,
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )
        else:
            outcomes.append(
                {
                    "case_id": next(
                        row["case_id"]
                        for row in json.loads((HERE / "held-out-cases.json").read_text())["cases"]
                        if row["task_id"] == task_id
                    ),
                    "task_id": task_id,
                    "status": "PASS",
                    "evidence": evidence,
                }
            )
    return {
        "suite_id": "PO03-WA-ROUTE-08-HELD-OUT-v1",
        "cases": outcomes,
        "passed": sum(row["status"] == "PASS" for row in outcomes),
        "failed": sum(row["status"] == "FAIL" for row in outcomes),
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = execute(set(args.task) or None)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
