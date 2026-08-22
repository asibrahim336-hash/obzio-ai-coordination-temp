"""a11-u01 recurrence tests: actor authority, transition order, locator resolution.

Frozen hypothesis (dispatch a11-u01): "The generic event command lets a
non-coordinator actor append COMPLETED with a fabricated result_commit_id, and
the recovery scanner does not notice because it only checks for a missing commit
id rather than an unverifiable one."

The coordinator reproduced exactly that on 2026-08-22.  These tests hold both
halves shut: authority is checked for every event kind on the append path that
the ``event`` subcommand actually uses, and the scanner treats a terminal commit
id that cannot be resolved to a real object as a false completion rather than as
evidence of durability.
"""

from __future__ import annotations

import test_a11_support as support


class ActorAuthorityTests(support.ControlPlaneHarness):
    """No subordinate actor may author a coordinator-only custody event."""

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")

    def test_worker_cannot_append_completed_through_the_generic_event_path(self):
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event(
                "h-u01",
                "COMPLETED",
                actor=support.OWNER,
                provider_state="COMPLETED",
                payload={"result_commit_id": "f" * 40},
            )
        self.assertIn("COMPLETED", str(ctx.exception))
        self.assertNotIn("COMPLETED", self.events("h-u01"))

    def test_worker_cannot_append_parent_ingested(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event(
                "h-u01",
                "PARENT_INGESTED",
                actor=support.OWNER,
                payload={"result_commit_id": "f" * 40},
            )
        self.assertNotIn("PARENT_INGESTED", self.events("h-u01"))

    def test_worker_cannot_grant_itself_a_lease(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event(
                "h-u01",
                "LEASED",
                actor=support.OWNER,
                fence_token=9,
                payload={"lease_id": "self-granted", "worker_id": support.OWNER},
            )
        self.assertEqual(1, self.events("h-u01").count("LEASED"))

    def test_worker_cannot_append_a_disposition(self):
        for decision in ("ACCEPTED", "REJECTED"):
            with self.subTest(decision=decision):
                with self.assertRaises(self.cp.ControlPlaneError):
                    self.cp.append_event(
                        "h-u01", decision, actor=support.OWNER, payload={"reviewer_id": support.OWNER}
                    )

    def test_worker_cannot_create_a_unit(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event("h-u02", "CREATED", actor=support.OWNER)

    def test_worker_may_still_report_its_own_progress(self):
        for event in ("RUNNING", "CHECKPOINTED", "RESULT_STAGED", "RESULT_COMMITTED"):
            with self.subTest(event=event):
                self.cp.append_event(
                    "h-u01",
                    event,
                    actor=support.OWNER,
                    fence_token=1,
                    payload={"checkpoint_seq": 1, "result_commit_id": "f" * 40},
                )
        self.assertEqual("RESULT_COMMITTED", self.state_of("h-u01"))

    def test_coordinator_retains_authority_over_its_own_events(self):
        self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER, fence_token=1)
        self.cp.append_event(
            "h-u01",
            "PARENT_INGESTED",
            actor="coordinator",
            fence_token=1,
            payload={"result_commit_id": "f" * 40, "result_sha256": "a" * 64},
        )
        self.assertEqual("PARENT_INGESTED", self.state_of("h-u01"))


class TransitionOrderTests(support.ControlPlaneHarness):
    """No event may advance a unit out of order, whoever appends it."""

    def test_a_unit_cannot_be_created_twice(self):
        self.seed("h-u01", lease=False)
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event("h-u01", "CREATED", actor="coordinator")

    def test_work_cannot_start_before_a_lease_exists(self):
        self.seed("h-u01", lease=False)
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER)
        self.assertIn("lease", str(ctx.exception).lower())

    def test_an_event_for_an_unknown_unit_is_refused(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event("never-created", "RUNNING", actor="coordinator")

    def test_completion_requires_parent_ingestion_on_the_append_path(self):
        self.seed("h-u01")
        self.cp.append_event("h-u01", "RESULT_COMMITTED", actor=support.OWNER, fence_token=1)
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event(
                "h-u01",
                "COMPLETED",
                actor="coordinator",
                payload={"result_commit_id": "f" * 40},
            )
        self.assertIn("PARENT_INGESTED", str(ctx.exception))

    def test_ingestion_cannot_be_recorded_without_a_declared_commit(self):
        self.seed("h-u01")
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event(
                "h-u01", "PARENT_INGESTED", actor="coordinator", fence_token=1, payload={}
            )
        self.assertIn("result_commit_id", str(ctx.exception))

    def test_completion_requires_a_declared_commit(self):
        """A commit-less ingestion row written before the guard cannot complete."""
        self.seed("h-u01")
        self.forge_row("h-u01", "PARENT_INGESTED", "coordinator", {"result_sha256": "a" * 64})
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event("h-u01", "COMPLETED", actor="coordinator", payload={})
        self.assertIn("no durable result commit", str(ctx.exception))

    def test_a_disposition_requires_completion_and_an_independent_reviewer(self):
        self.seed("h-u01")
        self.cp.append_event(
            "h-u01",
            "PARENT_INGESTED",
            actor="coordinator",
            fence_token=1,
            payload={"result_commit_id": "f" * 40, "result_sha256": "a" * 64},
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event("h-u01", "ACCEPTED", actor="po03-worker-a6", payload={})
        self.cp.append_event(
            "h-u01", "COMPLETED", actor="coordinator", payload={"result_commit_id": "f" * 40}
        )
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.cp.append_event("h-u01", "ACCEPTED", actor=support.OWNER, payload={})
        self.assertIn("own work", str(ctx.exception))
        self.cp.append_event("h-u01", "ACCEPTED", actor="po03-worker-a6", payload={})
        self.assertEqual("ACCEPTED", self.cp.project_units()["h-u01"]["acceptance"])

    def test_production_events_cannot_resume_after_the_parent_ingested(self):
        self.seed("h-u01")
        self.cp.append_event(
            "h-u01",
            "PARENT_INGESTED",
            actor="coordinator",
            fence_token=1,
            payload={"result_commit_id": "f" * 40, "result_sha256": "a" * 64},
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event("h-u01", "RESULT_COMMITTED", actor=support.OWNER, fence_token=1)

    def test_a_re_lease_reopens_the_production_window(self):
        """Recovery must not be blocked by the order rule it shares with attacks."""
        self.seed("h-u01")
        self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER, fence_token=1)
        self.cp.append_event("h-u01", "RECOVERY_REQUIRED", actor="coordinator", payload={"reason": "test"})
        self.cp.append_event(
            "h-u01",
            "LEASED",
            actor="coordinator",
            fence_token=2,
            payload={"lease_id": "lease-h-u01-2", "worker_id": support.OWNER,
                     "expires_at": "2099-01-01T00:00:00Z"},
        )
        self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER, fence_token=2)
        self.assertEqual("RUNNING", self.state_of("h-u01"))


class UnresolvableTerminalCommitTests(support.ControlPlaneHarness):
    """The scanner must reject an unverifiable commit id, not only a missing one."""

    git_backed = True

    def test_fabricated_terminal_commit_id_is_a_false_completion(self):
        self.seed("h-u01")
        self.forge_row(
            "h-u01",
            "PARENT_INGESTED",
            "coordinator",
            {"result_commit_id": "f" * 40, "result_sha256": "a" * 64},
        )
        self.forge_row("h-u01", "COMPLETED", "po03-worker-a11test", {"result_commit_id": "f" * 40})
        state = self.cp.scan_recovery()
        self.assertIn("h-u01", state["unresolvable_result_commits"])
        self.assertIn("h-u01", state["false_completions"])
        self.assertTrue(state["recovery_required"])

    def test_a_real_commit_id_is_not_reported(self):
        self.seed("h-u01")
        commit, _sha, _size = self.commit_artifact("workstreams/po03/harness/h-u01.txt", b"real\n")
        self.forge_row(
            "h-u01", "PARENT_INGESTED", "coordinator",
            {"result_commit_id": commit, "result_sha256": "a" * 64},
        )
        self.forge_row("h-u01", "COMPLETED", "coordinator", {"result_commit_id": commit})
        state = self.cp.scan_recovery()
        self.assertEqual([], state["unresolvable_result_commits"])
        self.assertEqual([], state["false_completions"])

    def test_a_tree_or_blob_id_is_not_accepted_as_a_commit(self):
        """Resolution must pin the object type; a tree sha is not a commit."""
        self.seed("h-u01")
        self.commit_artifact("workstreams/po03/harness/h-u01.txt", b"real\n")
        tree = support.git("rev-parse", "HEAD^{tree}", cwd=self.repo)
        self.forge_row(
            "h-u01", "PARENT_INGESTED", "coordinator",
            {"result_commit_id": tree, "result_sha256": "a" * 64},
        )
        self.forge_row("h-u01", "COMPLETED", "coordinator", {"result_commit_id": tree})
        state = self.cp.scan_recovery()
        self.assertIn("h-u01", state["unresolvable_result_commits"])
        self.assertIn("h-u01", state["false_completions"])

    def test_missing_commit_id_is_still_a_false_completion(self):
        """The pre-existing check must survive the new one."""
        self.seed("h-u01")
        self.forge_row("h-u01", "COMPLETED", "coordinator", {})
        state = self.cp.scan_recovery()
        self.assertIn("h-u01", state["false_completions"])


class CoordinatorReproductionTests(support.ControlPlaneHarness):
    """End-to-end replay of the attack the coordinator reproduced on 2026-08-22."""

    git_backed = True

    def test_worker_cannot_fake_a_completion_and_the_scan_stays_clean(self):
        self.seed("h-u01")
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event(
                "h-u01",
                "COMPLETED",
                actor=support.OWNER,
                provider_state="COMPLETED",
                payload={"result_commit_id": "0123456789abcdef0123456789abcdef01234567"},
            )
        state = self.cp.scan_recovery()
        self.assertEqual([], state["false_completions"])
        self.assertNotEqual("COMPLETED", self.state_of("h-u01"))

    def test_cli_event_subcommand_refuses_the_same_attack(self):
        """The defect was that authority lived in cmd_complete, not on the path used."""
        self.seed("h-u01")
        args = self.cp.build_parser().parse_args(
            [
                "event",
                "h-u01",
                "COMPLETED",
                "--actor",
                support.OWNER,
                "--provider-state",
                "COMPLETED",
                "--payload",
                '{"result_commit_id": "0123456789abcdef0123456789abcdef01234567"}',
            ]
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            args.func(args)
        self.assertNotIn("COMPLETED", self.events("h-u01"))


if __name__ == "__main__":
    import unittest

    unittest.main()
