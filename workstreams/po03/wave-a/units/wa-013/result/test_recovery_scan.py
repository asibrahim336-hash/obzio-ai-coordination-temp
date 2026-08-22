#!/usr/bin/env python3
"""Focused and adversarial tests for the PO-03 append-only recovery scanner.

Run from a clean clone with:

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s <this directory> -p 'test_*.py' -v

The suite has four parts:

1. fixture integrity - the committed crash fixtures match their manifest and the
   generator reproduces them byte for byte;
2. fixture expectations - each injected fault produces the classification the
   commission requires, asserted independently of the generator;
3. adversarial cases - hostile and malformed ledgers that try to obtain a
   completion, a stale commit, a silent skip or a nondeterministic report;
4. live-ledger regression - the repository's own append-only ledger reconstructs
   cleanly and reproduces this unit's own attempt lineage.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import recovery_scan as rs  # noqa: E402
import make_fixtures  # noqa: E402

FIXTURES = HERE / "fixtures"
NOW = "2026-08-22T12:00:00Z"

COORD = "controller:fx-coordinator-0001"
VERIFIER = "controller-verifier:fx-assurance-0001"
PRODUCER = "producer:fx-worker-0001"


def repo_root() -> Path:
    for candidate in [HERE, *HERE.parents]:
        if (candidate / "workstreams" / "po03" / "control" / "events" / "ledger.jsonl").is_file():
            return candidate
    raise unittest.SkipTest("live PO-03 ledger not present in this checkout")


def line(**fields: object) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def ledger(*lines: str, trailing_newline: bool = True) -> bytes:
    body = "\n".join(lines)
    return (body + "\n" if trailing_newline else body).encode("utf-8")


def lifecycle_lines(
    task_id: str = "T-1",
    *,
    stop_after: str = "ACCEPTED",
    fence: int = 1,
    lease_expires_at: str = "2026-08-22T14:00:00Z",
    start_seq: int = 1,
) -> list[str]:
    """Build a minimal well-formed lifecycle for use inside adversarial cases."""
    steps: list[tuple[str, str | None, str, dict[str, object]]] = [
        ("CREATED", None, COORD, {"idempotency_key": f"po03:t:{task_id}:a01"}),
        (
            "LEASED",
            "CREATED",
            COORD,
            {"idempotency_key": f"po03:t:{task_id}:a01", "lease_id": f"lease-{task_id}", "lease_expires_at": lease_expires_at},
        ),
        ("RUNNING", "LEASED", PRODUCER, {"provider_run_id": f"run-{task_id}"}),
        ("CHECKPOINTED", "RUNNING", PRODUCER, {"checkpoint_seq": 1}),
        ("RESULT_STAGING", "CHECKPOINTED", PRODUCER, {}),
        ("RESULT_STAGED", "RESULT_STAGING", PRODUCER, {}),
        ("RESULT_VERIFIED", "RESULT_STAGED", PRODUCER, {}),
        (
            "RESULT_COMMITTED",
            "RESULT_VERIFIED",
            PRODUCER,
            {"result_commit_id": "c" * 40, "return_commit_id": "d" * 40, "manifest_sha256": "e" * 64},
        ),
        ("PARENT_INGESTED", "RESULT_COMMITTED", COORD, {}),
        ("COMPLETED", "PARENT_INGESTED", COORD, {}),
        ("ACCEPTED", "COMPLETED", VERIFIER, {}),
    ]
    out: list[str] = []
    for offset, (to_state, from_state, actor, extra) in enumerate(steps):
        out.append(
            line(
                actor=actor,
                at=f"2026-08-22T10:{offset:02d}:00Z",
                event_id=f"evt-{task_id}-{start_seq + offset:04d}",
                event_seq=start_seq + offset,
                fence_token=fence,
                from_state=from_state,
                task_id=task_id,
                to_state=to_state,
                **extra,
            )
        )
        if to_state == stop_after:
            break
    return out


def scan_bytes(raw: bytes, **kwargs: object) -> dict:
    kwargs.setdefault("now", NOW)
    return rs.scan(raw, **kwargs)  # type: ignore[arg-type]


def only_task(report: dict) -> dict:
    assert report["task_count"] == 1, report["task_count"]
    return report["tasks"][0]


def codes(report: dict) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def load_fixture(number: str) -> tuple[bytes, dict]:
    matches = sorted(FIXTURES.glob(f"fx-{number}-*.jsonl"))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one fixture fx-{number}-*, found {matches}")
    sidecar = FIXTURES / f"fx-{number}-provider-observations.json"
    observations = json.loads(sidecar.read_bytes()) if sidecar.is_file() else {}
    return matches[0].read_bytes(), observations


# ---------------------------------------------------------------------------
# 1. Fixture integrity
# ---------------------------------------------------------------------------


class FixtureIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads((FIXTURES / "manifest.json").read_bytes())

    def test_manifest_digests_match_committed_fixture_bytes(self) -> None:
        self.assertEqual(self.manifest["fixture_count"], 16)
        for entry in self.manifest["fixtures"]:
            raw = (FIXTURES / entry["fixture"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"], entry["fixture"])
            self.assertEqual(len(raw), entry["bytes"], entry["fixture"])
            for sidecar in entry["sidecars"]:
                blob = (FIXTURES / sidecar["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(), sidecar["sha256"])
                self.assertEqual(len(blob), sidecar["bytes"])

    def test_generator_reproduces_committed_fixtures_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            regenerated = Path(tmp) / "fixtures"
            make_fixtures.build(regenerated)
            committed = sorted(path.name for path in FIXTURES.iterdir())
            self.assertEqual(committed, sorted(path.name for path in regenerated.iterdir()))
            for name in committed:
                self.assertEqual(
                    (FIXTURES / name).read_bytes(),
                    (regenerated / name).read_bytes(),
                    f"{name} is not reproducible from the committed generator",
                )

    def test_fixtures_carry_no_live_identifiers(self) -> None:
        forbidden = (
            "bc-b1956656",
            "b1956656-b897-4889-aeab-82c4556c1a9f",
            "asibrahim336",
            "obzio-ai-coordination-temp",
            "552b12eacee637716451492a98980fb0da19ff3e",
            "6559606ac8db12e3f484e9bb74c2b4a05cc3a998",
            "100bc2079ced",
        )
        for path in sorted(FIXTURES.glob("*.json*")):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, text, f"{path.name} leaks {needle}")


# ---------------------------------------------------------------------------
# 2. Fixture expectations, asserted independently of the generator
# ---------------------------------------------------------------------------


class FixtureExpectations(unittest.TestCase):
    def test_fx01_clean_lifecycle_needs_no_recovery(self) -> None:
        raw, obs = load_fixture("01")
        report = scan_bytes(raw, provider_observations=obs)
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertEqual(report["recovery_required"], [])
        self.assertEqual(only_task(report)["obzio_state"], "ACCEPTED")
        self.assertEqual(rs.exit_code_for(report), 0)

    def test_fx02_lost_callback_is_committed_not_ingested_and_replays_ingest(self) -> None:
        raw, obs = load_fixture("02")
        report = scan_bytes(raw, provider_observations=obs)
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "COMMITTED_NOT_INGESTED")
        self.assertEqual(task["recovery_action"], "REPLAY_PARENT_INGESTION")
        self.assertEqual(report["committed_not_ingested"], ["PO03-FX-002"])
        directive = task["replay_directive"]
        self.assertEqual(directive["operation"], "PARENT_INGEST")
        self.assertTrue(directive["idempotent"])
        self.assertTrue(directive["result_commit_id"])
        self.assertEqual(rs.exit_code_for(report), 1)

    def test_fx02_never_proposes_rerunning_a_committed_producer(self) -> None:
        raw, _ = load_fixture("02")
        report = scan_bytes(raw)
        self.assertNotIn("RERUN_FROM_IMMUTABLE_INPUT", report["action_histogram"])

    def test_fx03_provider_completion_without_commit_is_uncommitted(self) -> None:
        raw, obs = load_fixture("03")
        report = scan_bytes(raw, provider_observations=obs)
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED")
        self.assertEqual(task["recovery_action"], "RERUN_FROM_IMMUTABLE_INPUT")
        self.assertEqual(report["provider_completed_uncommitted"], ["PO03-FX-003"])
        self.assertEqual(task["replay_directive"]["required_fence_token"], 2)

    def test_fx03_without_provider_observation_is_merely_in_flight(self) -> None:
        raw, _ = load_fixture("03")
        report = scan_bytes(raw)
        self.assertEqual(only_task(report)["obzio_state"], "IN_FLIGHT")
        self.assertEqual(report["provider_completed_uncommitted"], [])

    def test_fx04_false_completion_is_refused_not_admitted(self) -> None:
        raw, _ = load_fixture("04")
        report = scan_bytes(raw)
        self.assertIn("FALSE_COMPLETION_REFUSED", codes(report))
        self.assertEqual(report["false_completion_admitted"], [])
        self.assertEqual(report["false_completion_refused"], {"PO03-FX-004": 1})
        self.assertFalse(only_task(report)["live_attempt"]["completed"])
        self.assertEqual(report["integrity"], "CRITICAL_VIOLATION")
        self.assertEqual(rs.exit_code_for(report), 2)

    def test_fx05_stale_worker_cannot_commit_after_ownership_transfer(self) -> None:
        raw, _ = load_fixture("05")
        report = scan_bytes(raw)
        refusals = [f for f in report["findings"] if f["code"] == "STALE_FENCE_EVENT_REFUSED"]
        self.assertEqual(len(refusals), 2)
        self.assertEqual(
            sorted(f["refused_to_state"] for f in refusals),
            ["PARENT_INGESTED", "RESULT_COMMITTED"],
        )
        task = only_task(report)
        self.assertIsNone(task["live_attempt"]["result_commit_id"])
        self.assertFalse(task["live_attempt"]["parent_ingested"])
        self.assertEqual(report["committed_not_ingested"], [])
        self.assertEqual(task["recovery_action"], "REDISPATCH_UNDER_NEW_FENCE")

    def test_fx06_duplicate_callbacks_are_harmless(self) -> None:
        raw, _ = load_fixture("06")
        report = scan_bytes(raw)
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertGreaterEqual(report["ledger"]["duplicate_events_ignored"], 4)
        self.assertEqual(only_task(report)["obzio_state"], "COMPLETED_AWAITING_INDEPENDENT_ACCEPTANCE")
        self.assertNotIn("FILE_ORDER_NOT_SEQ_ORDER", codes(report))

    def test_fx06_duplicates_yield_the_same_state_as_the_deduplicated_prefix(self) -> None:
        raw, _ = load_fixture("06")
        with_duplicates = only_task(scan_bytes(raw))["live_attempt"]
        seen: set[str] = set()
        kept: list[str] = []
        for text in raw.decode().splitlines():
            identifier = json.loads(text)["event_id"]
            if identifier in seen:
                continue
            seen.add(identifier)
            kept.append(text)
        deduplicated = only_task(scan_bytes(ledger(*kept)))["live_attempt"]
        self.assertEqual(with_duplicates, deduplicated)

    def test_fx07_torn_tail_is_recoverable_and_prefix_still_reconstructs(self) -> None:
        raw, _ = load_fixture("07")
        self.assertFalse(raw.endswith(b"\n"))
        report = scan_bytes(raw)
        torn = [f for f in report["findings"] if f["code"] == "TORN_TAIL"]
        self.assertEqual(len(torn), 1)
        self.assertEqual(torn[0]["severity"], "ADVISORY")
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertEqual(only_task(report)["obzio_state"], "COMMITTED_NOT_INGESTED")

    def test_fx08_interior_corruption_is_critical_not_skipped(self) -> None:
        raw, _ = load_fixture("08")
        report = scan_bytes(raw)
        corrupt = [f for f in report["findings"] if f["code"] == "CORRUPT_INTERIOR_LINE"]
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0]["severity"], "CRITICAL")
        self.assertEqual(rs.exit_code_for(report), 2)

    def test_fx09_checkpoint_regression_does_not_move_the_checkpoint_back(self) -> None:
        raw, _ = load_fixture("09")
        report = scan_bytes(raw)
        self.assertIn("CHECKPOINT_REGRESSION", codes(report))
        self.assertEqual(report["integrity"], "DEFECTIVE")
        self.assertGreaterEqual(only_task(report)["live_attempt"]["checkpoint_seq"], 2)

    def test_fx10_expired_lease_with_no_commit_is_orphaned(self) -> None:
        raw, _ = load_fixture("10")
        report = scan_bytes(raw)
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "ORPHANED_LEASE_EXPIRED")
        self.assertEqual(task["recovery_action"], "REDISPATCH_UNDER_NEW_FENCE")
        self.assertTrue(task["live_attempt"]["lease_expired_at_evaluation_instant"])
        self.assertEqual(task["replay_directive"]["required_fence_token"], 2)

    def test_fx10_is_in_flight_before_its_lease_expires(self) -> None:
        raw, _ = load_fixture("10")
        report = scan_bytes(raw, now="2026-08-22T09:00:00Z")
        self.assertEqual(only_task(report)["obzio_state"], "IN_FLIGHT")

    def test_fx11_event_id_reuse_with_new_content_is_critical(self) -> None:
        raw, _ = load_fixture("11")
        report = scan_bytes(raw)
        self.assertIn("EVENT_ID_CONFLICT", codes(report))
        self.assertEqual(report["integrity"], "CRITICAL_VIOLATION")
        self.assertFalse(only_task(report)["live_attempt"]["parent_ingested"])

    def test_fx12_producer_cannot_record_completed(self) -> None:
        raw, _ = load_fixture("12")
        report = scan_bytes(raw)
        self.assertIn("UNAUTHORIZED_COMPLETION_ACTOR", codes(report))
        task = only_task(report)
        self.assertFalse(task["live_attempt"]["completed"])
        self.assertEqual(task["obzio_state"], "INGESTED_NOT_COMPLETED")

    def test_fx13_producer_cannot_accept_its_own_result(self) -> None:
        raw, _ = load_fixture("13")
        report = scan_bytes(raw)
        self.assertIn("PRODUCER_SELF_ACCEPTANCE", codes(report))
        self.assertIsNone(only_task(report)["live_attempt"]["review_state"])

    def test_fx14_storage_reordering_still_reconstructs_correctly(self) -> None:
        raw, _ = load_fixture("14")
        report = scan_bytes(raw)
        self.assertIn("FILE_ORDER_NOT_SEQ_ORDER", codes(report))
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "COMMITTED_NOT_INGESTED")
        self.assertEqual(
            task["live_attempt"]["states_reached"],
            [
                "CREATED",
                "LEASED",
                "RUNNING",
                "CHECKPOINTED",
                "RESULT_STAGING",
                "RESULT_STAGED",
                "RESULT_VERIFIED",
                "RESULT_COMMITTED",
            ],
        )

    def test_fx15_missing_committed_artifact_makes_the_commit_untrustworthy(self) -> None:
        raw, _ = load_fixture("15")
        with tempfile.TemporaryDirectory() as tmp:
            report = scan_bytes(raw, artifact_probe=rs.filesystem_artifact_probe(Path(tmp)))
        self.assertIn("COMMITTED_ARTIFACT_MISSING", codes(report))
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "RESULT_COMMITTED_ARTIFACTS_UNVERIFIABLE")
        self.assertEqual(task["recovery_action"], "REVERIFY_THEN_RERUN_FROM_IMMUTABLE_INPUT")
        self.assertEqual(report["committed_not_ingested"], [])

    def test_fx15_verified_artifact_leaves_the_commit_recoverable(self) -> None:
        raw, _ = load_fixture("15")
        declared = None
        for text in raw.decode().splitlines():
            event = json.loads(text)
            if event["to_state"] == "RESULT_COMMITTED":
                declared = event["manifest_sha256"]
        self.assertIsNotNone(declared)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def probe(descriptor: dict) -> dict:
                return {"exists": True, "sha256": declared, "bytes": 1}

            report = scan_bytes(raw, artifact_probe=probe)
            self.assertTrue(root.is_dir())
        self.assertEqual(only_task(report)["obzio_state"], "COMMITTED_NOT_INGESTED")
        self.assertEqual(report["integrity"], "CLEAN")

    def test_fx16_mixed_fleet_separates_every_disposition_in_one_pass(self) -> None:
        raw, obs = load_fixture("16")
        report = scan_bytes(raw, provider_observations=obs)
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertEqual(report["committed_not_ingested"], ["PO03-FX-102", "PO03-FX-107"])
        self.assertEqual(report["provider_completed_uncommitted"], ["PO03-FX-103"])
        self.assertEqual(report["orphaned_lease_expired"], ["PO03-FX-104"])
        self.assertEqual(report["false_completion_admitted"], [])
        states = {task["task_id"]: task["obzio_state"] for task in report["tasks"]}
        self.assertEqual(states["PO03-FX-101"], "ACCEPTED")
        self.assertEqual(states["PO03-FX-105"], "INGESTED_NOT_COMPLETED")
        self.assertEqual(states["PO03-FX-106"], "AWAITING_DISPATCH")

    def test_fx16_provider_completion_never_overrides_durable_evidence(self) -> None:
        raw, obs = load_fixture("16")
        report = scan_bytes(raw, provider_observations=obs)
        states = {task["task_id"]: task["obzio_state"] for task in report["tasks"]}
        # Both units carry provider_state COMPLETED in the sidecar.
        self.assertEqual(states["PO03-FX-101"], "ACCEPTED")
        self.assertEqual(states["PO03-FX-102"], "COMMITTED_NOT_INGESTED")

    def test_fx16_superseded_attempt_is_retained_not_lost(self) -> None:
        raw, obs = load_fixture("16")
        report = scan_bytes(raw, provider_observations=obs)
        task = next(t for t in report["tasks"] if t["task_id"] == "PO03-FX-107")
        self.assertEqual(task["live_attempt"]["attempt_id"], "PO03-FX-107-A02")
        self.assertEqual(len(task["superseded_attempts"]), 1)
        self.assertEqual(task["superseded_attempts"][0]["state"], "SUPERSEDED_BEFORE_DISPATCH")
        self.assertEqual(
            task["superseded_attempts"][0]["successor_attempt_id"], "PO03-FX-107-A02"
        )


# ---------------------------------------------------------------------------
# 3. Adversarial cases
# ---------------------------------------------------------------------------


class AdversarialLedgers(unittest.TestCase):
    def test_empty_ledger_is_scannable(self) -> None:
        report = scan_bytes(b"")
        self.assertEqual(report["task_count"], 0)
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertEqual(rs.exit_code_for(report), 0)

    def test_whitespace_only_ledger_is_scannable(self) -> None:
        report = scan_bytes(b"\n   \n\t\n")
        self.assertEqual(report["task_count"], 0)
        self.assertEqual(report["integrity"], "CLEAN")

    def test_valid_final_line_without_trailing_newline_is_not_a_torn_tail(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="RESULT_COMMITTED"), trailing_newline=False)
        report = scan_bytes(raw)
        self.assertNotIn("TORN_TAIL", codes(report))
        self.assertEqual(only_task(report)["obzio_state"], "COMMITTED_NOT_INGESTED")

    def test_malformed_final_line_in_newline_terminated_file_is_critical(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="RUNNING"), '{"broken":')
        report = scan_bytes(raw)
        self.assertIn("CORRUPT_INTERIOR_LINE", codes(report))

    def test_non_object_json_line_is_critical(self) -> None:
        for payload in ("[1,2,3]", '"a string"', "42", "null", "true"):
            with self.subTest(payload=payload):
                report = scan_bytes(ledger(*lifecycle_lines(stop_after="RUNNING"), payload))
                self.assertIn("NON_OBJECT_EVENT", codes(report))

    def test_missing_required_field_is_critical(self) -> None:
        for omit in ("event_id", "event_seq", "task_id", "to_state"):
            with self.subTest(omit=omit):
                fields = {
                    "event_id": "e1",
                    "event_seq": 99,
                    "task_id": "T-1",
                    "to_state": "CREATED",
                    "actor": COORD,
                    "from_state": None,
                }
                fields.pop(omit)
                report = scan_bytes(ledger(line(**fields)))
                self.assertIn("EVENT_MISSING_REQUIRED_FIELD", codes(report))

    def test_non_integer_or_boolean_event_seq_is_critical(self) -> None:
        for value in ("1", 1.5, True, None, [1]):
            with self.subTest(value=value):
                report = scan_bytes(
                    ledger(
                        line(
                            actor=COORD,
                            event_id="e1",
                            event_seq=value,
                            from_state=None,
                            task_id="T-1",
                            to_state="CREATED",
                        )
                    )
                )
                self.assertIn("EVENT_SEQ_NOT_INTEGER", codes(report))

    def test_non_positive_event_seq_is_critical(self) -> None:
        for value in (0, -1, -9999):
            with self.subTest(value=value):
                report = scan_bytes(
                    ledger(
                        line(
                            actor=COORD,
                            event_id="e1",
                            event_seq=value,
                            from_state=None,
                            task_id="T-1",
                            to_state="CREATED",
                        )
                    )
                )
                self.assertIn("EVENT_SEQ_NOT_POSITIVE", codes(report))

    def test_invalid_fence_token_is_critical(self) -> None:
        for value in (0, -1, True, "2", 1.5):
            with self.subTest(value=value):
                report = scan_bytes(
                    ledger(
                        line(
                            actor=COORD,
                            event_id="e1",
                            event_seq=1,
                            fence_token=value,
                            from_state=None,
                            task_id="T-1",
                            to_state="CREATED",
                        )
                    )
                )
                self.assertIn("FENCE_TOKEN_INVALID", codes(report))
                # Regression: a task whose only event is refused must be named
                # as unreconstructable rather than crashing the scan.
                self.assertEqual(report["task_count"], 0)
                self.assertEqual(report["unreconstructable_tasks"], ["T-1"])

    def test_a_task_whose_events_are_all_refused_is_never_silently_dropped(self) -> None:
        report = scan_bytes(
            ledger(
                line(
                    actor=COORD,
                    event_id="e1",
                    event_seq=1,
                    fence_token=0,
                    from_state=None,
                    task_id="T-LOST",
                    to_state="CREATED",
                )
            )
        )
        self.assertEqual(report["unreconstructable_tasks"], ["T-LOST"])
        self.assertEqual(report["integrity"], "CRITICAL_VIOLATION")

    def test_empty_event_id_or_task_id_is_critical(self) -> None:
        report = scan_bytes(
            ledger(
                line(actor=COORD, event_id="  ", event_seq=1, from_state=None, task_id="T-1", to_state="CREATED"),
                line(actor=COORD, event_id="e2", event_seq=2, from_state=None, task_id="", to_state="CREATED"),
            )
        )
        self.assertIn("EVENT_ID_EMPTY", codes(report))
        self.assertIn("TASK_ID_EMPTY", codes(report))

    def test_unknown_state_is_critical(self) -> None:
        report = scan_bytes(
            ledger(
                *lifecycle_lines(stop_after="RUNNING"),
                line(
                    actor=COORD,
                    event_id="evt-rogue",
                    event_seq=90,
                    fence_token=1,
                    from_state="RUNNING",
                    task_id="T-1",
                    to_state="DEFINITELY_DONE",
                ),
            )
        )
        self.assertIn("UNKNOWN_STATE", codes(report))
        self.assertEqual(only_task(report)["live_attempt"]["reconstructed_state"], "RUNNING")

    def test_duplicate_event_seq_with_distinct_ids_is_a_defect(self) -> None:
        lines = lifecycle_lines(stop_after="RUNNING")
        clash = line(
            actor=COORD,
            at="2026-08-22T10:02:30Z",
            event_id="evt-T-1-clash",
            event_seq=3,
            fence_token=1,
            from_state="RUNNING",
            task_id="T-1",
            to_state="CHECKPOINTED",
        )
        report = scan_bytes(ledger(*lines, clash))
        self.assertIn("DUPLICATE_EVENT_SEQ", codes(report))

    def test_skip_ahead_to_result_committed_is_refused(self) -> None:
        report = scan_bytes(
            ledger(
                *lifecycle_lines(stop_after="LEASED"),
                line(
                    actor=PRODUCER,
                    at="2026-08-22T10:05:00Z",
                    event_id="evt-T-1-jump",
                    event_seq=50,
                    fence_token=1,
                    from_state="RESULT_VERIFIED",
                    task_id="T-1",
                    to_state="RESULT_COMMITTED",
                    result_commit_id="f" * 40,
                ),
            )
        )
        self.assertIn("ILLEGAL_TRANSITION_REFUSED", codes(report))
        self.assertEqual(report["committed_not_ingested"], [])
        self.assertIsNone(only_task(report)["live_attempt"]["result_commit_id"])

    def test_backward_transition_is_refused(self) -> None:
        report = scan_bytes(
            ledger(
                *lifecycle_lines(stop_after="RESULT_STAGED"),
                line(
                    actor=PRODUCER,
                    at="2026-08-22T10:07:00Z",
                    event_id="evt-T-1-back",
                    event_seq=60,
                    fence_token=1,
                    from_state="RESULT_STAGED",
                    task_id="T-1",
                    to_state="RUNNING",
                ),
            )
        )
        self.assertIn("BACKWARD_TRANSITION_REFUSED", codes(report))
        self.assertEqual(only_task(report)["live_attempt"]["reconstructed_state"], "RESULT_STAGED")

    def test_fence_downgrade_cannot_reopen_a_fenced_attempt(self) -> None:
        lines = lifecycle_lines(stop_after="RUNNING")
        lines.append(
            line(
                actor=COORD,
                at="2026-08-22T10:10:00Z",
                event_id="evt-T-1-fence",
                event_seq=20,
                fence_token=7,
                from_state="RUNNING",
                task_id="T-1",
                to_state="FENCED",
                attempt_id="T-1-A01",
            )
        )
        for offset, forged in enumerate((6, 3, 1)):
            lines.append(
                line(
                    actor="producer:evicted",
                    at="2026-08-22T10:11:00Z",
                    event_id=f"evt-T-1-forge-{offset}",
                    event_seq=30 + offset,
                    fence_token=forged,
                    from_state="RESULT_VERIFIED",
                    task_id="T-1",
                    to_state="RESULT_COMMITTED",
                    attempt_id="T-1-A01",
                    result_commit_id="a" * 40,
                )
            )
        report = scan_bytes(ledger(*lines))
        self.assertEqual(report["ledger"]["stale_fence_events_refused"], 3)
        self.assertEqual(report["committed_not_ingested"], [])
        self.assertEqual(report["integrity"], "CRITICAL_VIOLATION")

    def test_equal_fence_token_continues_the_same_attempt(self) -> None:
        report = scan_bytes(ledger(*lifecycle_lines(stop_after="RESULT_COMMITTED", fence=4)))
        self.assertEqual(report["ledger"]["stale_fence_events_refused"], 0)
        self.assertEqual(only_task(report)["live_attempt"]["fence_token"], 4)

    def test_very_large_fence_token_is_accepted(self) -> None:
        report = scan_bytes(ledger(*lifecycle_lines(stop_after="RESULT_COMMITTED", fence=2**62)))
        self.assertEqual(only_task(report)["live_attempt"]["fence_token"], 2**62)
        self.assertEqual(report["integrity"], "CLEAN")

    def test_attempt_identity_is_unified_across_id_and_idempotency_key(self) -> None:
        """Regression: the live ledger names one attempt two different ways."""
        lines = [
            line(
                actor=COORD,
                at="2026-08-22T10:00:00Z",
                event_id="e1",
                event_seq=1,
                fence_token=1,
                from_state=None,
                idempotency_key="po03:abc:wa-x:a01",
                task_id="T-9",
                to_state="CREATED",
            ),
            line(
                actor=COORD,
                at="2026-08-22T10:01:00Z",
                event_id="e2",
                event_seq=2,
                fence_token=1,
                from_state="CREATED",
                idempotency_key="po03:abc:wa-x:a01",
                lease_expires_at="2026-08-22T14:00:00Z",
                lease_id="lease-x",
                task_id="T-9",
                to_state="LEASED",
            ),
            line(
                actor=COORD,
                at="2026-08-22T10:02:00Z",
                attempt_id="T-9-A01",
                event_id="e3",
                event_seq=3,
                fence_token=2,
                from_state="LEASED",
                task_id="T-9",
                to_state="FENCED",
            ),
        ]
        report = scan_bytes(ledger(*lines))
        task = only_task(report)
        self.assertEqual(report["integrity"], "CLEAN")
        self.assertEqual(task["live_attempt"]["reconstructed_state"], "FENCED")
        self.assertEqual(task["superseded_attempts"], [])
        self.assertNotIn("ILLEGAL_TRANSITION_REFUSED", codes(report))

    def test_annotation_event_does_not_advance_state_or_raise_a_defect(self) -> None:
        lines = lifecycle_lines(stop_after="LEASED")
        lines.append(
            line(
                actor=COORD,
                at="2026-08-22T10:03:00Z",
                event_id="evt-T-1-note",
                event_seq=40,
                event_type="PROVENANCE_DEFECT_CONFIRMED",
                fence_token=1,
                from_state="LEASED",
                task_id="T-1",
                to_state="LEASED",
            )
        )
        report = scan_bytes(ledger(*lines))
        self.assertIn("ANNOTATION_EVENT", codes(report))
        self.assertEqual(report["severity_counts"]["DEFECT"], 0)
        self.assertEqual(report["severity_counts"]["CRITICAL"], 0)
        self.assertEqual(only_task(report)["live_attempt"]["reconstructed_state"], "LEASED")

    def test_timestamps_cannot_reorder_the_lifecycle(self) -> None:
        """An adversary back-dates and forward-dates events; seq order must win."""
        lines = []
        stamps = [
            "2026-08-22T23:59:59Z",
            "2026-08-22T00:00:01Z",
            "2026-08-22T12:00:00Z",
            "2026-08-21T00:00:00Z",
        ]
        steps = [("CREATED", None, COORD), ("LEASED", "CREATED", COORD), ("RUNNING", "LEASED", PRODUCER), ("CHECKPOINTED", "RUNNING", PRODUCER)]
        for index, ((to_state, from_state, actor), stamp) in enumerate(zip(steps, stamps), start=1):
            extra = {"lease_expires_at": "2026-08-23T14:00:00Z", "lease_id": "lease-z"} if to_state == "LEASED" else {}
            lines.append(
                line(
                    actor=actor,
                    at=stamp,
                    event_id=f"evt-z-{index}",
                    event_seq=index,
                    fence_token=1,
                    from_state=from_state,
                    task_id="T-Z",
                    to_state=to_state,
                    **extra,
                )
            )
        report = scan_bytes(ledger(*lines), now="2026-08-23T00:00:00Z")
        task = only_task(report)
        self.assertEqual(task["live_attempt"]["reconstructed_state"], "CHECKPOINTED")
        self.assertIn("TIMESTAMP_NOT_MONOTONIC_WITH_SEQ", codes(report))
        self.assertEqual(report["severity_counts"]["CRITICAL"], 0)

    def test_unparseable_evaluation_instant_is_rejected(self) -> None:
        for bad in ("", "yesterday", "2026-08-22", "2026-08-22T08:00:00", None, 17):
            with self.subTest(bad=bad):
                with self.assertRaises(rs.LedgerIntegrityError):
                    rs.scan(b"", now=bad)  # type: ignore[arg-type]

    def test_lease_expiry_boundary_is_inclusive(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="RUNNING", lease_expires_at="2026-08-22T12:00:00Z"))
        at_boundary = scan_bytes(raw, now="2026-08-22T12:00:00Z")
        self.assertEqual(only_task(at_boundary)["obzio_state"], "ORPHANED_LEASE_EXPIRED")
        one_second_before = scan_bytes(raw, now="2026-08-22T11:59:59Z")
        self.assertEqual(only_task(one_second_before)["obzio_state"], "IN_FLIGHT")

    def test_zulu_and_numeric_offsets_are_equivalent(self) -> None:
        self.assertEqual(
            rs.parse_instant("2026-08-22T08:34:24Z"), rs.parse_instant("2026-08-22T08:34:24+00:00")
        )
        self.assertEqual(
            rs.parse_instant("2026-08-22T08:34:24Z"), rs.parse_instant("2026-08-22T09:34:24+01:00")
        )
        self.assertEqual(
            rs.parse_instant("2026-08-22T08:34:24Z"), rs.parse_instant("2026-08-22T08:34:24+0000")
        )
        for junk in ("2026-13-01T00:00:00Z", "not-a-time", "", "2026-08-22 08:00:00Z"):
            self.assertIsNone(rs.parse_instant(junk))

    def test_expired_lease_before_dispatch_is_orphaned_not_awaiting(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="LEASED", lease_expires_at="2026-08-22T09:00:00Z"))
        report = scan_bytes(raw)
        self.assertEqual(only_task(report)["obzio_state"], "ORPHANED_LEASE_EXPIRED")

    def test_provider_observation_accepts_bare_string_form(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="CHECKPOINTED"))
        report = scan_bytes(raw, provider_observations={"T-1": "COMPLETED"})
        self.assertEqual(only_task(report)["obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED")

    def test_provider_failure_without_commit_is_distinguished_from_completion(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="CHECKPOINTED"))
        report = scan_bytes(raw, provider_observations={"T-1": "FAILED"})
        task = only_task(report)
        self.assertEqual(task["obzio_state"], "PROVIDER_FAILED_UNCOMMITTED")
        self.assertEqual(report["provider_completed_uncommitted"], [])
        self.assertEqual(task["recovery_action"], "RERUN_FROM_IMMUTABLE_INPUT")

    def test_provider_observation_for_unknown_task_is_ignored(self) -> None:
        raw = ledger(*lifecycle_lines(stop_after="ACCEPTED"))
        report = scan_bytes(raw, provider_observations={"T-DOES-NOT-EXIST": "COMPLETED"})
        self.assertEqual(report["task_count"], 1)
        self.assertEqual(only_task(report)["obzio_state"], "ACCEPTED")


class DeterminismAndIdempotence(unittest.TestCase):
    def test_repeated_scans_produce_an_identical_digest(self) -> None:
        raw, obs = load_fixture("16")
        first = rs.report_digest(scan_bytes(raw, provider_observations=obs))
        second = rs.report_digest(scan_bytes(raw, provider_observations=obs))
        self.assertEqual(first, second)

    def test_parent_restart_rescan_is_idempotent_across_all_fixtures(self) -> None:
        for path in sorted(FIXTURES.glob("fx-*.jsonl")):
            with self.subTest(fixture=path.name):
                number = path.name.split("-")[1]
                raw, obs = load_fixture(number)
                digests = {
                    rs.report_digest(scan_bytes(raw, provider_observations=obs)) for _ in range(3)
                }
                self.assertEqual(len(digests), 1)

    def test_json_key_order_does_not_change_the_reconstruction(self) -> None:
        """Only the ledger digest may differ when key order and spacing change."""
        raw, obs = load_fixture("16")
        shuffled: list[str] = []
        for text in raw.decode().splitlines():
            event = json.loads(text)
            shuffled.append(json.dumps(dict(reversed(list(event.items())))))
        reordered = ledger(*shuffled)
        self.assertNotEqual(reordered, raw)
        original = scan_bytes(raw, provider_observations=obs)
        rewritten = scan_bytes(reordered, provider_observations=obs)
        for field in (
            "tasks",
            "findings",
            "state_histogram",
            "action_histogram",
            "severity_counts",
            "integrity",
            "committed_not_ingested",
            "provider_completed_uncommitted",
            "orphaned_lease_expired",
            "task_count",
        ):
            self.assertEqual(original[field], rewritten[field], field)
        self.assertNotEqual(original["ledger"]["sha256"], rewritten["ledger"]["sha256"])

    def test_report_leaks_no_host_state(self) -> None:
        raw, obs = load_fixture("16")
        text = rs.canonical_report_bytes(scan_bytes(raw, provider_observations=obs)).decode()
        for needle in ("/tmp", "/workspace", str(HERE), "2026-08-22T08:", "Traceback"):
            self.assertNotIn(needle, text, f"report leaks {needle}")

    def test_canonical_bytes_are_stable_and_newline_terminated(self) -> None:
        raw, obs = load_fixture("02")
        payload = rs.canonical_report_bytes(scan_bytes(raw, provider_observations=obs))
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), rs.report_digest(scan_bytes(raw, provider_observations=obs)))


class CommandLineInterface(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(HERE / "recovery_scan.py"), *args],
            capture_output=True,
            text=True,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
        )

    def test_clean_fixture_exits_zero(self) -> None:
        result = self._run(str(FIXTURES / "fx-01-clean-full-lifecycle.jsonl"), "--now", NOW, "--quiet")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovery_needed_exits_one(self) -> None:
        result = self._run(str(FIXTURES / "fx-02-committed-not-ingested.jsonl"), "--now", NOW, "--quiet")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_critical_violation_exits_two(self) -> None:
        result = self._run(str(FIXTURES / "fx-04-false-completion.jsonl"), "--now", NOW, "--quiet")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_ledger_exits_three(self) -> None:
        result = self._run(str(FIXTURES / "absent.jsonl"), "--now", NOW, "--quiet")
        self.assertEqual(result.returncode, 3)
        self.assertIn("UNSCANNABLE", result.stderr)

    def test_bad_evaluation_instant_exits_three(self) -> None:
        result = self._run(str(FIXTURES / "fx-01-clean-full-lifecycle.jsonl"), "--now", "soon", "--quiet")
        self.assertEqual(result.returncode, 3)

    def test_expect_digest_mismatch_exits_four(self) -> None:
        result = self._run(
            str(FIXTURES / "fx-01-clean-full-lifecycle.jsonl"),
            "--now",
            NOW,
            "--quiet",
            "--expect-digest",
            "0" * 64,
        )
        self.assertEqual(result.returncode, 4)
        self.assertIn("DIGEST_MISMATCH", result.stderr)

    def test_expect_digest_match_preserves_the_scan_exit_code(self) -> None:
        raw, _ = load_fixture("01")
        digest = rs.report_digest(scan_bytes(raw))
        result = self._run(
            str(FIXTURES / "fx-01-clean-full-lifecycle.jsonl"),
            "--now",
            NOW,
            "--quiet",
            "--expect-digest",
            digest,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_written_report_matches_the_printed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            result = self._run(
                str(FIXTURES / "fx-16-mixed-fleet.jsonl"),
                "--now",
                NOW,
                "--provider-observations",
                str(FIXTURES / "fx-16-provider-observations.json"),
                "--out",
                str(out),
            )
            self.assertIn(result.returncode, (0, 1), result.stderr)
            printed = [ln for ln in result.stdout.splitlines() if ln.startswith("report_sha256=")]
            self.assertEqual(len(printed), 1)
            self.assertEqual(
                printed[0].split("=", 1)[1],
                hashlib.sha256(out.read_bytes()).hexdigest(),
            )


# ---------------------------------------------------------------------------
# 4. Live-ledger regression
# ---------------------------------------------------------------------------


class LiveLedgerRegression(unittest.TestCase):
    LEDGER_EVALUATION_INSTANT = "2026-08-22T08:51:42Z"

    def setUp(self) -> None:
        self.ledger_path = repo_root() / "workstreams" / "po03" / "control" / "events" / "ledger.jsonl"
        self.report = scan_bytes(
            self.ledger_path.read_bytes(), now=self.LEDGER_EVALUATION_INSTANT
        )

    def test_every_live_event_is_applied_with_no_defect_or_violation(self) -> None:
        self.assertEqual(
            self.report["ledger"]["events_applied"], self.report["ledger"]["events_parsed"]
        )
        self.assertEqual(self.report["severity_counts"]["CRITICAL"], 0)
        self.assertEqual(self.report["severity_counts"]["DEFECT"], 0)
        self.assertEqual(self.report["integrity"], "CLEAN")

    def test_live_ledger_shows_no_false_completion(self) -> None:
        self.assertEqual(self.report["false_completion_admitted"], [])
        self.assertEqual(self.report["false_completion_refused"], {})

    def test_scanner_reconstructs_its_own_attempt_lineage(self) -> None:
        task = next(t for t in self.report["tasks"] if t["task_id"] == "PO03-WA-013")
        attempt = task["live_attempt"]
        self.assertEqual(attempt["attempt_id"], "PO03-WA-013-A02")
        self.assertEqual(attempt["fence_token"], 2)
        self.assertEqual(attempt["lease_id"], "lease-po03-wa-013-a02")
        self.assertEqual(len(task["superseded_attempts"]), 1)
        self.assertEqual(task["superseded_attempts"][0]["attempt_id"], "PO03-WA-013-A01")
        self.assertEqual(
            task["superseded_attempts"][0]["state"], "SUPERSEDED_BEFORE_DISPATCH"
        )

    def test_reconstruction_agrees_with_the_controller_recovery_state_on_leases(self) -> None:
        recovery_state = json.loads(
            (repo_root() / "workstreams" / "po03" / "control" / "recovery-state.json").read_bytes()
        )
        declared = {
            entry["task_id"]: entry
            for entry in recovery_state["active_leases"]
            if entry.get("state") in {"LEASED", "RUNNING"}
        }
        reconstructed = {task["task_id"]: task for task in self.report["tasks"]}
        compared = 0
        for task_id, entry in declared.items():
            task = reconstructed.get(task_id)
            self.assertIsNotNone(task, f"{task_id} is declared active but absent from the ledger")
            self.assertEqual(
                task["live_attempt"]["reconstructed_state"],
                entry["state"],
                f"{task_id}: ledger reconstruction disagrees with recovery-state.json",
            )
            self.assertEqual(task["live_attempt"]["lease_id"], entry["lease_id"], task_id)
            self.assertEqual(task["live_attempt"]["fence_token"], entry["fence_token"], task_id)
            compared += 1
        self.assertGreater(compared, 20)

    def test_rescanning_the_live_ledger_is_idempotent(self) -> None:
        again = scan_bytes(self.ledger_path.read_bytes(), now=self.LEDGER_EVALUATION_INSTANT)
        self.assertEqual(rs.report_digest(self.report), rs.report_digest(again))

    def test_live_ledger_task_count_matches_distinct_task_ids(self) -> None:
        distinct = {
            json.loads(text)["task_id"]
            for text in self.ledger_path.read_text(encoding="utf-8").splitlines()
            if text.strip()
        }
        self.assertEqual(self.report["task_count"], len(distinct))


if __name__ == "__main__":
    unittest.main(verbosity=2)
