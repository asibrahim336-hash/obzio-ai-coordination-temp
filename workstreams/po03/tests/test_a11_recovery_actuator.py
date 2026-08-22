"""a11-u08 recurrence tests: detection without remediation is not recovery.

Frozen hypothesis (dispatch a11-u08): "The recovery scanner detects but never
remediates, so the commission's requirement of automatic resume or rerun of
uncommitted tasks from immutable input is unmet."  Cohort a2 measured 0 of 7
in-flight units resuming.

The actuator is deliberately separate from the scanner.  ``scan_recovery`` is
run by ``verify``, by subordinates, and by a read-only clean-clone check; a
detector that appends to the shared ledger every time somebody asks it a
question is a detector that cannot be run safely.  So the scanner stays pure
and ``recover_units`` is the writer.  The last test in this file pins that
separation, because it is a deliberate divergence from a2's frozen expectation
that ``scan_recovery`` itself transfers an expired lease.

What "resume" means here: the control plane dispatches work, it does not
execute it.  Recovery therefore has to leave, in the ledger, everything a
worker needs to continue without a human deciding anything -- the immutable
dispatch input, a fresh fence, and the checkpoint to resume from rather than
zero.  Every assertion below is made against a control plane rebuilt from the
ledger alone, because a resume that only exists in the actuating process is the
defect restated.
"""

from __future__ import annotations

import unittest

import test_a11_support as support

#: 2026-08-22T07:00:00Z, comfortably after the expired leases below.
NOW = 1787727600.0
PAST = "2026-08-22T06:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"


class ActuatorHarness(support.ControlPlaneHarness):
    """Units posed in each in-flight shape recovery has to handle."""

    def expired(self, unit_id: str) -> None:
        self.seed(unit_id, lease=True, expires_at=PAST)

    def running(self, unit_id: str, *, expires_at: str = PAST) -> None:
        self.seed(unit_id, lease=True, expires_at=expires_at)
        self.cp.append_event(unit_id, "RUNNING", actor=support.OWNER, fence_token=1)

    def checkpointed(self, unit_id: str, seq: int = 3, *, expires_at: str = PAST) -> None:
        self.running(unit_id, expires_at=expires_at)
        for step in range(1, seq + 1):
            self.cp.append_event(
                unit_id,
                "CHECKPOINTED",
                actor=support.OWNER,
                fence_token=1,
                payload={"checkpoint_seq": step, "note": f"stage-{step}"},
            )

    def rejected(self, unit_id: str) -> None:
        """A unit whose result was refused: the u07 rejection trace, actuated."""
        self.running(unit_id, expires_at=FUTURE)
        self.cp.record_rejection(unit_id, f"{unit_id}: artifact hash mismatch on read-back")

    def uncommitted(self, unit_id: str) -> None:
        self.running(unit_id, expires_at=FUTURE)
        self.cp.append_event(
            unit_id,
            "PROVIDER_COMPLETED_UNCOMMITTED",
            actor="coordinator",
            provider_state="COMPLETED",
            fence_token=1,
            payload={"reason": "provider reported completion with nothing durable"},
        )

    def completed(self, unit_id: str) -> None:
        self.running(unit_id, expires_at=FUTURE)
        self.cp.append_event(
            unit_id,
            "PARENT_INGESTED",
            actor="coordinator",
            fence_token=1,
            payload={"result_commit_id": "a" * 40, "artifact_count": 1, "total_bytes": 3},
        )
        self.cp.append_event(
            unit_id,
            "COMPLETED",
            actor="coordinator",
            fence_token=1,
            payload={"result_commit_id": "a" * 40},
        )

    def actions_for(self, report, unit_id: str) -> list[dict]:
        return [item for item in report["actions"] if item["unit_id"] == unit_id]

    def action_for(self, report, unit_id: str) -> dict:
        actions = self.actions_for(report, unit_id)
        self.assertEqual(1, len(actions), f"expected exactly one action for {unit_id}: {actions}")
        return actions[0]

    def recover(self, **kwargs):
        kwargs.setdefault("now", NOW)
        return self.cp.recover_units(**kwargs)

    def last(self, unit_id: str, event: str) -> dict:
        rows = [
            row
            for row in self.cp.ledger_rows()
            if row["unit_id"] == unit_id and row["event"] == event
        ]
        self.assertTrue(rows, f"{unit_id} has no {event} row")
        return rows[-1]


class ExpiredLeaseTests(ActuatorHarness):
    #: One test ingests a real result to prove the evicted fence is dead.
    git_backed = True

    def test_an_expired_lease_is_transferred_with_a_fresh_fence(self):
        self.expired("h-u01")
        before = self.cp.project_units()["h-u01"]["fence_token"]
        report = self.recover()
        action = self.action_for(report, "h-u01")
        self.assertEqual("re_lease", action["action"])
        self.assertIn("h-u01", report["re_leased"])
        events = self.events("h-u01")
        self.assertEqual(["CREATED", "LEASED", "LEASE_EXPIRED", "RETRY_SCHEDULED", "LEASED"], events)
        unit = self.cp.project_units()["h-u01"]
        self.assertGreater(unit["fence_token"], before)
        self.assertEqual(FUTURE > unit["lease"]["expires_at"], True)
        self.assertEqual(support.OWNER, unit["lease"]["worker_id"])

    def test_the_fresh_fence_is_the_only_admissible_one_afterwards(self):
        """Re-leasing has to invalidate the evicted worker, not just add a row."""
        self.expired("h-u01")
        self.recover()
        unit = self.cp.project_units()["h-u01"]
        self.assertEqual([1, 2], unit["issued_fence_tokens"])
        commit, sha, size = self.commit_artifact(f"{support.OWNED_PREFIX}h-u01.txt", b"late\n")
        stale = self.result_doc("h-u01", commit_id=commit, body=b"late\n", fence=1, write_artifact=False)
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(stale)
        fresh = self.result_doc("h-u01", commit_id=commit, body=b"late\n", fence=2, write_artifact=False)
        self.assertEqual("PARENT_INGESTED", self.ingest(fresh)["ingest_event"])

    def test_a_live_lease_is_left_alone(self):
        self.seed("h-u01", expires_at=FUTURE)
        before = len(self.cp.ledger_rows())
        report = self.recover()
        self.assertEqual([], self.actions_for(report, "h-u01"))
        self.assertEqual(before, len(self.cp.ledger_rows()))

    def test_re_leasing_is_idempotent(self):
        self.expired("h-u01")
        self.recover()
        settled = len(self.cp.ledger_rows())
        for _ in range(3):
            report = self.recover()
            self.assertEqual([], report["actions"])
        self.assertEqual(settled, len(self.cp.ledger_rows()))


class ResumeTests(ActuatorHarness):
    def test_a_checkpointed_unit_resumes_at_its_last_checkpoint(self):
        self.checkpointed("h-u01", seq=3)
        report = self.recover()
        action = self.action_for(report, "h-u01")
        self.assertEqual("resume", action["action"])
        self.assertEqual(3, action["resume_from_checkpoint"])
        self.assertNotEqual(0, action["resume_from_checkpoint"])
        lease = self.last("h-u01", "LEASED")
        self.assertEqual(3, lease["payload"]["resume_from_checkpoint"])
        self.assertEqual({"checkpoint_seq": 3, "note": "stage-3"}, lease["payload"]["resume_checkpoint"])

    def test_the_resume_point_survives_a_parent_restart(self):
        self.checkpointed("h-u01", seq=5)
        self.recover()
        fresh = self.fresh_control_plane()
        rows = [
            row
            for row in fresh.ledger_rows()
            if row["unit_id"] == "h-u01" and row["event"] == "LEASED"
        ]
        self.assertEqual(5, rows[-1]["payload"]["resume_from_checkpoint"])
        self.assertEqual(5, fresh.project_units()["h-u01"]["checkpoint_seq"])

    def test_an_uncheckpointed_unit_reruns_from_zero_and_says_so(self):
        self.running("h-u01")
        action = self.action_for(self.recover(), "h-u01")
        self.assertEqual("re_lease", action["action"])
        self.assertEqual(0, action["resume_from_checkpoint"])

    def test_resume_carries_the_immutable_dispatch_input(self):
        record = self.dispatch_record("h-u02")
        self.checkpointed("h-u02", seq=2)
        self.recover()
        retry = self.last("h-u02", "RETRY_SCHEDULED")
        self.assertEqual(
            record["immutable_input_manifest_sha256"],
            retry["payload"]["immutable_input_manifest_sha256"],
        )
        self.assertEqual(record["idempotency_key"], retry["payload"]["idempotency_key"])
        self.assertEqual(
            record["acceptance_contract_sha256"], retry["payload"]["acceptance_contract_sha256"]
        )
        self.assertEqual(record["result_slot"], retry["payload"]["result_slot"])

    def test_a_unit_with_no_dispatch_record_is_escalated_not_guessed(self):
        self.checkpointed("h-u01")
        (self.cp.DISPATCH_DIR / "h-u01.json").unlink()
        report = self.recover()
        action = self.action_for(report, "h-u01")
        self.assertEqual("escalate", action["action"])
        self.assertIn("dispatch", action["reason"])
        self.assertIn("h-u01", report["escalated"])
        self.assertNotIn("LEASED", self.events("h-u01")[2:])


class SevenInFlightUnitsTests(ActuatorHarness):
    """a2's measurement: 0 of 7 in-flight units resumed.  All seven must."""

    SHAPES = (
        ("h-u01", "expired", "re_lease"),
        ("h-u02", "running", "re_lease"),
        ("h-u03", "checkpointed", "resume"),
        ("h-u04", "rejected", "rerun"),
        ("h-u05", "uncommitted", "rerun"),
        ("h-u06", "orphaned", "re_lease"),
        ("h-u07", "checkpointed_live", "resume"),
    )

    def orphaned(self, unit_id: str) -> None:
        """Leased, then the lease expired and was already recorded."""
        self.seed(unit_id, expires_at=PAST)
        self.cp.append_event(
            unit_id,
            "LEASE_EXPIRED",
            actor="coordinator",
            fence_token=1,
            payload={"reason": "ttl elapsed"},
        )

    def checkpointed_live(self, unit_id: str) -> None:
        """Checkpointed, lease still valid, but the result was refused."""
        self.checkpointed(unit_id, seq=2, expires_at=FUTURE)
        self.cp.record_rejection(unit_id, f"{unit_id}: declared commit does not resolve")

    def setUp(self) -> None:
        super().setUp()
        for unit_id, shape, _ in self.SHAPES:
            getattr(self, shape)(unit_id)

    def test_all_seven_in_flight_units_are_actuated(self):
        report = self.recover()
        self.assertEqual(7, report["units_actuated"])
        self.assertEqual([], report["escalated"])
        for unit_id, _, expected in self.SHAPES:
            with self.subTest(unit=unit_id):
                action = self.action_for(report, unit_id)
                self.assertEqual(expected, action["action"])
                unit = self.cp.project_units()[unit_id]
                self.assertEqual("LEASED", unit["obzio_state"])
                self.assertGreater(unit["fence_token"], 1)
                self.assertEqual(support.OWNER, unit["lease"]["worker_id"])

    def test_no_unit_needs_manual_intervention_to_resume(self):
        """The dispatch record's falsifier: any unit still needing a human."""
        self.recover()
        scan = self.cp.scan_recovery(now=NOW, repo=self.repo)
        self.assertEqual([], scan["expired_leases"])
        self.assertEqual([], scan["recorded_rejections"])
        self.assertEqual([], scan["provider_completed_uncommitted"])
        self.assertEqual([], scan["orphaned_units"])

    def test_the_whole_fleet_is_idempotent_under_repeated_invocation(self):
        self.recover()
        settled = self.cp.LEDGER_PATH.read_text(encoding="utf-8")
        for _ in range(3):
            report = self.recover()
            self.assertEqual(0, report["units_actuated"])
        self.assertEqual(settled, self.cp.LEDGER_PATH.read_text(encoding="utf-8"))

    def test_the_chain_stays_verifiable_across_recovery(self):
        self.recover()
        self.assertEqual([], self.cp.verify_chain(self.cp.ledger_rows()))

    def test_a_dry_run_plans_the_same_actions_and_writes_nothing(self):
        before = self.cp.LEDGER_PATH.read_text(encoding="utf-8")
        planned = self.recover(apply=False)
        self.assertTrue(planned["dry_run"])
        self.assertEqual(before, self.cp.LEDGER_PATH.read_text(encoding="utf-8"))
        applied = self.recover()
        self.assertEqual(
            [(item["unit_id"], item["action"]) for item in planned["actions"]],
            [(item["unit_id"], item["action"]) for item in applied["actions"]],
        )

    def test_recovery_can_be_scoped_to_named_units(self):
        report = self.recover(unit_ids=["h-u03"])
        self.assertEqual(["h-u03"], [item["unit_id"] for item in report["actions"]])
        self.assertEqual(2, self.cp.project_units()["h-u03"]["fence_token"])
        self.assertEqual(1, self.cp.project_units()["h-u01"]["fence_token"])
        self.assertEqual(["h-u01", "h-u02"], self.cp.scan_recovery(now=NOW)["expired_leases"])


class BoundaryTests(ActuatorHarness):
    def test_a_completed_unit_is_never_re_leased(self):
        self.completed("h-u01")
        before = len(self.cp.ledger_rows())
        report = self.recover()
        self.assertEqual([], self.actions_for(report, "h-u01"))
        self.assertEqual(before, len(self.cp.ledger_rows()))
        self.assertEqual("COMPLETED", self.state_of("h-u01"))

    def test_an_honest_terminal_failure_is_not_silently_retried(self):
        self.running("h-u01", expires_at=FUTURE)
        self.cp.append_event(
            "h-u01", "FAILED_TERMINAL", actor=support.OWNER, fence_token=1,
            payload={"reason": "the hypothesis was falsified"},
        )
        report = self.recover()
        self.assertEqual([], self.actions_for(report, "h-u01"))
        self.assertEqual("FAILED_TERMINAL", self.state_of("h-u01"))

    def test_a_committed_result_awaiting_ingestion_is_reported_not_rerun(self):
        """Re-running a unit whose bytes are already durable would destroy work."""
        self.running("h-u01", expires_at=FUTURE)
        self.cp.append_event(
            "h-u01", "RESULT_COMMITTED", actor=support.OWNER, fence_token=1,
            payload={"result_commit_id": "b" * 40},
        )
        report = self.recover()
        action = self.action_for(report, "h-u01")
        self.assertEqual("awaiting_ingestion", action["action"])
        self.assertIn("h-u01", report["awaiting_ingestion"])
        self.assertEqual("RESULT_COMMITTED", self.state_of("h-u01"))

    def test_the_retry_budget_is_bounded_and_escalates_once(self):
        self.rejected("h-u01")
        for _ in range(6):
            self.recover(max_attempts=3)
            unit = self.cp.project_units()["h-u01"]
            if unit["obzio_state"] == "LEASED":
                self.cp.record_rejection("h-u01", "h-u01: refused again")
        report = self.recover(max_attempts=3)
        self.assertIn("h-u01", report["escalated"])
        escalations = [
            row
            for row in self.cp.ledger_rows()
            if row["unit_id"] == "h-u01"
            and (row.get("payload") or {}).get("escalated_after_attempts")
        ]
        self.assertEqual(1, len(escalations), "escalation must be recorded exactly once")
        self.assertLessEqual(self.cp.project_units()["h-u01"]["retries"], 3)

    def test_an_unknown_unit_is_refused(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.recover(unit_ids=["h-u99"])

    def test_the_cli_exposes_the_actuator(self):
        self.expired("h-u01")
        self.assertEqual(0, self.cp.main(["recover", "--dry-run"]))
        self.assertEqual(["CREATED", "LEASED"], self.events("h-u01"))
        self.assertEqual(0, self.cp.main(["recover"]))
        self.assertIn("RETRY_SCHEDULED", self.events("h-u01"))

    def test_the_scanner_remains_a_pure_detector(self):
        """Deliberate divergence from a2's frozen expectation, pinned here.

        a2's ``test_defect_scanner_must_automatically_transfer_an_expired_lease``
        expects ``scan_recovery`` itself to append LEASE_EXPIRED and raise the
        fence.  ``verify`` calls the scanner, subordinates call ``verify``, and
        a clean-clone check calls it with no write authority at all, so a
        scanner that mutates the shared ledger cannot be run safely.  The
        remediation lives in ``recover_units``; the scanner only reports.
        """
        self.expired("h-u01")
        before = self.cp.LEDGER_PATH.read_text(encoding="utf-8")
        state = self.cp.scan_recovery(now=NOW, repo=self.repo)
        self.assertEqual(["h-u01"], state["expired_leases"])
        self.assertEqual(before, self.cp.LEDGER_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
