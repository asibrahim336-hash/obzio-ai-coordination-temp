#!/usr/bin/env python3
"""Recurrence tests: one per G2 change, plus evidence for each disposition.

A mechanism change without a recurrence test is a change that can silently
revert.  Each test here does two things: it asserts G2 has the property, and it
asserts G1 does not.  The second half is what makes the test a recurrence test
rather than a feature test - it pins the exact behaviour that was wrong, so a
future edit that reintroduces it fails here and not in a score six steps later.

The last class carries the disposition evidence.  A SUPERSEDE is only real if
the superseded candidate was built and shown to be insufficient, and a RETEST is
only honest if the residual exposure is demonstrated rather than described.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g1 import factory as g1
from successor.g2 import successor as g2
from successor.harness.controller_api import Clock, canonical, sha256_text

ARTIFACT = "workstreams/po03/successor/scores/probe.json"
CONTENT = '{"probe":"durable result bytes"}'
COMMIT = "1f0e4c2b9a7d5e3f8c1b6a4d2e9f7c5b3a1d8e6f"
OWNER = "po03-worker-a8"
SPEC = {
    "owner": OWNER,
    "owned_prefixes": ["workstreams/po03/successor/"],
    "acceptance": {"assertion": "the unit leaves a durable, hash-verified result"},
    "pinned_inputs": {"workstreams/po03/COMMISSION.md": "0" * 64},
}


class _Fixture:
    """A controller on scratch state, driven through the shared operation set."""

    def __init__(self, module, stack: unittest.TestCase):
        self.scratch = tempfile.TemporaryDirectory()
        stack.addCleanup(self.scratch.cleanup)
        self.clock = Clock()
        self.controller = module.build(root=Path(self.scratch.name), clock=self.clock)

    def do(self, operation: str, **args):
        return self.controller.apply(operation, args)

    def dispatched(self, unit_id: str = "u1", *, worker: str = "w1", ttl: int = 3600):
        self.do("create", unit_id=unit_id, spec=SPEC)
        self.do("lease", unit_id=unit_id, worker=worker, ttl=ttl)
        self.do("write_artifact", path=ARTIFACT, content=CONTENT)
        return self

    def submit(self, *, unit_id: str = "u1", worker: str = "w1", fence_token: int = 1, **over):
        args = {
            "unit_id": unit_id,
            "worker": worker,
            "fence_token": fence_token,
            "provider_state": "COMPLETED",
            "claimed_state": "RESULT_COMMITTED",
            "artifacts": [{"artifact_id": "art-01", "path": ARTIFACT, "sha256": "@auto", "bytes": "@auto"}],
            "result_commit_id": COMMIT,
            "readback_verified": True,
            "idempotency_key": "u1:key-001",
        }
        args.update(over)
        return self.do("submit", **args)


class RecurrenceTests(unittest.TestCase):
    """Each change is asserted present in G2 and absent in G1."""

    def _pair(self):
        return _Fixture(g1, self), _Fixture(g2, self)

    def test_c01_forged_fence_is_refused(self):
        """C-01, from P13. A fence token never granted is not authority."""
        old, new = self._pair()
        self.assertTrue(old.dispatched().submit(fence_token=99).admitted, "G1 accepted an ungranted fence")
        outcome = new.dispatched().submit(fence_token=99)
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "FORGED_FENCE")

    def test_c01_a_granted_fence_belonging_to_another_worker_is_refused(self):
        """C-01 generalised: the grant is bound to a worker, not just to a number."""
        new = _Fixture(g2, self).dispatched(worker="w1")
        outcome = new.submit(worker="w2", fence_token=1)
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "FORGED_FENCE")

    def test_c01_stale_fence_after_transfer_is_still_refused(self):
        """C-01 must not lose the property G1 already had."""
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        new.do("lease", unit_id="u1", worker="w1", ttl=3600)
        new.do("lease", unit_id="u1", worker="w2", ttl=3600)
        new.do("write_artifact", path=ARTIFACT, content=CONTENT)
        outcome = new.submit(worker="w1", fence_token=1)
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "STALE_FENCE")

    def test_c02_expired_lease_cannot_commit(self):
        """C-02, from P14. Expiry was reported but never enforced."""
        old, new = self._pair()
        old.dispatched(ttl=60)
        old.do("advance_clock", seconds=600)
        self.assertTrue(old.submit().admitted, "G1 accepted a commit from an expired worker")

        new.dispatched(ttl=60)
        new.do("advance_clock", seconds=600)
        outcome = new.submit()
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "EXPIRED_LEASE")

    def test_c02_a_live_lease_still_commits(self):
        new = _Fixture(g2, self).dispatched(ttl=3600)
        new.do("advance_clock", seconds=60)
        self.assertTrue(new.submit().admitted)

    def test_c03_worker_cannot_complete(self):
        """C-03, from P08 and a6's H02. Authority was a label on an event."""
        for fixture, expect_admitted in ((_Fixture(g1, self), True), (_Fixture(g2, self), False)):
            fixture.dispatched()
            fixture.submit()
            fixture.do("ingest", unit_id="u1")
            outcome = fixture.do("complete", unit_id="u1", actor="w1")
            self.assertEqual(outcome.admitted, expect_admitted)
            if not expect_admitted:
                self.assertEqual(outcome.reason_code, "NOT_COORDINATOR")

    def test_c03_the_coordinator_can_still_complete(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        new.do("ingest", unit_id="u1")
        outcome = new.do("complete", unit_id="u1", actor="coordinator")
        self.assertTrue(outcome.admitted)
        self.assertEqual(outcome.detail["obzio_state"], "COMPLETED")

    def test_c03_a_worker_cannot_dispose_of_a_result(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        new.do("ingest", unit_id="u1")
        new.do("complete", unit_id="u1", actor="coordinator")
        outcome = new.do("review", unit_id="u1", reviewer="w1", decision="ACCEPTED")
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "SELF_ACCEPTANCE")

    def test_c04_dispatch_tamper_and_input_drift_detected(self):
        """C-04, from P04 and P05. G1 had lost a check G0 possessed."""
        old, new = self._pair()
        for fixture in (old, new):
            fixture.do("create", unit_id="u1", spec=SPEC)
            fixture.do(
                "tamper",
                target="record",
                kind="edit",
                unit_id="u1",
                fields={"acceptance": {"assertion": "anything the producer likes"}},
            )
        self.assertEqual(old.do("verify").detail["input_tampered"], [])
        self.assertEqual(new.do("verify").detail["input_tampered"], ["u1"])

        old2, new2 = self._pair()
        for fixture in (old2, new2):
            fixture.do("create", unit_id="u1", spec=SPEC)
            fixture.do(
                "tamper",
                target="record",
                kind="edit",
                unit_id="u1",
                fields={"pinned_inputs": {"workstreams/po03/COMMISSION.md": "1" * 64}},
            )
        self.assertEqual(old2.do("verify").detail["input_drift"], [])
        self.assertEqual(new2.do("verify").detail["input_drift"], ["u1"])

    def test_c04_an_untampered_dispatch_record_verifies_clean(self):
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        detail = new.do("verify").detail
        self.assertEqual(detail["input_tampered"], [])
        self.assertEqual(detail["input_drift"], [])

    def test_c05_post_admission_drift_detected(self):
        """C-05, from P21 and a6's H09. Hashing once is not hash coverage."""
        old, new = self._pair()
        for fixture in (old, new):
            fixture.dispatched()
            fixture.submit()
            fixture.do("ingest", unit_id="u1")
            fixture.do("tamper", target="artifact", kind="corrupt", path=ARTIFACT)
        self.assertEqual(old.do("verify").detail["drift_detected"], [])
        self.assertEqual(old.do("verify").detail["artifacts_reverified"], 0)

        outcome = new.do("verify")
        self.assertEqual(outcome.detail["drift_detected"], [ARTIFACT])
        self.assertEqual(outcome.detail["artifacts_reverified"], 1)
        self.assertEqual(outcome.reason_code, "ARTIFACT_DRIFT")

    def test_c05_a_deleted_artifact_is_also_drift(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        new.do("ingest", unit_id="u1")
        new.do("tamper", target="artifact", kind="delete", path=ARTIFACT)
        self.assertEqual(new.do("verify").detail["drift_detected"], [ARTIFACT])

    def test_c06_conflicting_replay_refused(self):
        """C-06, from P26. Deduplicating on content lets a conflict through."""
        second = "workstreams/po03/successor/scores/probe2.json"
        for module, expected_ingests in ((g1, 2), (g2, 1)):
            fixture = _Fixture(module, self).dispatched()
            fixture.do("write_artifact", path=second, content='{"probe":"different bytes"}')
            fixture.submit()
            fixture.do("ingest", unit_id="u1")
            fixture.submit(
                artifacts=[{"artifact_id": "art-01", "path": second, "sha256": "@auto", "bytes": "@auto"}],
                result_commit_id="d3adb33fd3adb33fd3adb33fd3adb33fd3adb33f",
            )
            outcome = fixture.do("ingest", unit_id="u1")
            state = fixture.do("state", unit_id="u1")
            self.assertEqual(state.detail["ingest_count"], expected_ingests, module.__name__)
            if module is g2:
                self.assertFalse(outcome.admitted)
                self.assertEqual(outcome.reason_code, "CONFLICTING_REPLAY")

    def test_c06_identical_replay_is_still_a_harmless_duplicate(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        new.do("ingest", unit_id="u1")
        outcome = new.do("ingest", unit_id="u1")
        self.assertEqual(outcome.reason_code, "DUPLICATE_IGNORED")
        self.assertEqual(new.do("state", unit_id="u1").detail["ingest_count"], 1)

    def test_c07_tail_truncation_detected(self):
        """C-07, from P29. Per-row chaining cannot see rows that are gone."""
        old, new = self._pair()
        for fixture in (old, new):
            fixture.dispatched()
            fixture.submit()
            fixture.do("tamper", target="ledger", kind="truncate")
        old_detail = old.do("verify").detail
        self.assertTrue(old_detail["ledger_chain_valid"], "G1 sees a shorter but self-consistent chain")
        self.assertFalse(old_detail["ledger_truncated"])

        outcome = new.do("verify")
        self.assertTrue(outcome.detail["ledger_chain_valid"], "the remaining rows still chain correctly")
        self.assertTrue(outcome.detail["ledger_truncated"])
        self.assertEqual(outcome.reason_code, "LEDGER_TRUNCATED")

    def test_c07_an_intact_log_is_not_reported_as_truncated(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        detail = new.do("verify").detail
        self.assertFalse(detail["ledger_truncated"])
        self.assertTrue(detail["ledger_chain_valid"])

    def test_c07_in_place_edits_and_reordering_are_still_caught(self):
        for kind in ("edit", "reorder"):
            new = _Fixture(g2, self).dispatched()
            new.submit()
            new.do("tamper", target="ledger", kind=kind)
            outcome = new.do("verify")
            self.assertEqual(outcome.reason_code, "LEDGER_CORRUPT", kind)
            self.assertFalse(outcome.detail["ledger_chain_valid"], kind)

    def test_c08_lost_callback_is_replayed_once(self):
        """C-08, from P30 and a6's H10. G1 stranded the result entirely."""
        old, new = self._pair()
        for fixture in (old, new):
            fixture.dispatched()
            fixture.submit()
            fixture.do("restart")

        old_recover = old.do("recover").detail
        self.assertEqual(old_recover["replayed_ingestions"], 0)
        self.assertNotIn("u1", old_recover["resumable_units"])
        self.assertEqual(old.do("state", unit_id="u1").detail["obzio_state"], "RESULT_COMMITTED")
        self.assertEqual(old.do("state", unit_id="u1").detail["ingest_count"], 0)

        new_recover = new.do("recover").detail
        self.assertEqual(new_recover["replayed_ingestions"], 1)
        self.assertEqual(new_recover["replayed_units"], ["u1"])
        self.assertEqual(new.do("state", unit_id="u1").detail["obzio_state"], "PARENT_INGESTED")
        self.assertEqual(new.do("state", unit_id="u1").detail["ingest_count"], 1)

    def test_c08_replay_is_idempotent_across_repeated_recovery_sweeps(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        first = new.do("recover").detail
        second = new.do("recover").detail
        self.assertEqual(first["replayed_ingestions"], 1)
        self.assertEqual(second["replayed_ingestions"], 0, "a second sweep must not ingest again")
        self.assertEqual(new.do("state", unit_id="u1").detail["ingest_count"], 1)

    def test_c08_recovery_still_reports_expired_leases_and_uncommitted_units(self):
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        new.do("lease", unit_id="u1", worker="w1", ttl=60)
        new.do("advance_clock", seconds=600)
        detail = new.do("recover").detail
        self.assertEqual(detail["expired_leases"], ["u1"])
        self.assertEqual(detail["replayed_ingestions"], 0)

    def test_c09_unresolvable_locator_refused(self):
        """C-09, from P31 and a6's rejection of unit a3-u01."""
        old, new = self._pair()
        for fixture in (old, new):
            fixture.dispatched()
            fixture.submit()
            fixture.do("tamper", target="locator", kind="delete", unit_id="u1")
        old_outcome = old.do("ingest", unit_id="u1")
        self.assertTrue(old_outcome.admitted, "G1 admitted a result whose record was absent at its locator")

        new_outcome = new.do("ingest", unit_id="u1")
        self.assertFalse(new_outcome.admitted)
        self.assertEqual(new_outcome.reason_code, "LOCATOR_UNRESOLVED")
        self.assertEqual(new.do("state", unit_id="u1").detail["ingest_count"], 0)

    def test_c09_bytes_at_the_locator_must_match_the_submitted_result(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        new.do("tamper", target="locator", kind="corrupt", unit_id="u1")
        outcome = new.do("ingest", unit_id="u1")
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "LOCATOR_UNRESOLVED")

    def test_c09_a_resolvable_locator_still_admits(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        self.assertTrue(new.do("ingest", unit_id="u1").admitted)

    # C-10 and C-11 come from cohort a10's independent audit of the same control
    # plane.  Neither is covered by a frozen suite case, because the suite was
    # frozen before a10 published; the audit reproducer is the evidence instead.

    ESCAPE = "./../workstreams/po03/successor/decoy.json"

    def _escape_submit(self, fixture):
        fixture.do("create", unit_id="u1", spec=SPEC)
        fixture.do("lease", unit_id="u1", worker="w1", ttl=3600)
        fixture.do("write_artifact", path=self.ESCAPE, content=CONTENT)
        return fixture.submit(
            artifacts=[{"artifact_id": "art-01", "path": self.ESCAPE, "sha256": "@auto", "bytes": "@auto"}]
        )

    def test_c10_path_escape_refused(self):
        """C-10, from a10's finding D1 (INV-6).

        The declared path's leading run is only dots and slashes, so G1's
        ``lstrip('./')`` removes all of it and the remainder looks owned and
        in-allowlist.  The raw string is what reaches the filesystem, and it
        lands outside the artifact store the guard believed it had checked.
        """
        old, new = self._pair()

        old_outcome = self._escape_submit(old)
        self.assertTrue(old_outcome.admitted, "G1 admitted an artifact from outside the store it verifies against")
        store = (Path(old.scratch.name) / "artifacts").resolve()
        landed = (store / self.ESCAPE).resolve()
        self.assertNotIn(store, landed.parents, "the fixture must genuinely escape or it proves nothing")

        new_outcome = self._escape_submit(new)
        self.assertFalse(new_outcome.admitted)
        self.assertEqual(new_outcome.reason_code, "OUT_OF_ALLOWLIST")
        self.assertEqual(new_outcome.detail["paths"], [self.ESCAPE])

    def test_c10_an_absolute_declared_path_is_refused(self):
        """The companion shape: `Path.__truediv__` discards the store entirely."""
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        new.do("lease", unit_id="u1", worker="w1", ttl=3600)
        outcome = new.submit(
            artifacts=[
                {"artifact_id": "art-01", "path": "/workstreams/po03/successor/x.json", "sha256": "0" * 64, "bytes": 1}
            ]
        )
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "OUT_OF_ALLOWLIST")

    def test_c10_an_escaping_path_also_reads_as_absent(self):
        """The guard and the read must agree, or the escape survives one step on."""
        controller = _Fixture(g2, self).controller
        controller.apply("write_artifact", {"path": self.ESCAPE, "content": CONTENT})
        self.assertIsNone(controller.read_artifact(self.ESCAPE))

    def test_c10_an_honest_relative_path_still_admits(self):
        new = _Fixture(g2, self).dispatched()
        self.assertTrue(new.submit().admitted)

    def test_c11_terminal_state_cannot_be_re_entered(self):
        """C-11, from a10's finding D4 (INV-3b).

        A resubmission against a COMPLETED unit walked G1's projection back to
        RESULT_COMMITTED, which is what let a second completion be recorded for
        one unit under a different result_commit_id.
        """
        for module, expect_terminal in ((g1, False), (g2, True)):
            fixture = _Fixture(module, self).dispatched()
            fixture.submit()
            fixture.do("ingest", unit_id="u1")
            fixture.do("complete", unit_id="u1", actor="coordinator")
            self.assertEqual(fixture.do("state", unit_id="u1").detail["obzio_state"], "COMPLETED")

            fixture.do("write_artifact", path=ARTIFACT, content=CONTENT + " second")
            outcome = fixture.submit(result_commit_id="b" * 40)
            state = fixture.do("state", unit_id="u1").detail["obzio_state"]
            if expect_terminal:
                self.assertFalse(outcome.admitted)
                self.assertEqual(outcome.reason_code, "TERMINAL_STATE")
                self.assertEqual(state, "COMPLETED")
                self.assertEqual(fixture.do("state", unit_id="u1").detail["result_commit_id"], COMMIT)
            else:
                self.assertTrue(outcome.admitted, "G1 accepted a resubmission after completion")
                self.assertEqual(state, "RESULT_COMMITTED", "G1's projection regressed out of a terminal state")

    def test_c11_a_second_completion_cannot_be_recorded(self):
        """The consequence a10 named: two COMPLETED rows for one unit."""
        for module, expect_second in ((g1, True), (g2, False)):
            fixture = _Fixture(module, self).dispatched()
            fixture.submit()
            fixture.do("ingest", unit_id="u1")
            fixture.do("complete", unit_id="u1", actor="coordinator")
            fixture.do("write_artifact", path=ARTIFACT, content=CONTENT + " second")
            fixture.submit(result_commit_id="b" * 40)
            fixture.do("ingest", unit_id="u1")
            fixture.do("complete", unit_id="u1", actor="coordinator")
            completions = [
                row for row in fixture.controller.ledger.rows()
                if row["unit_id"] == "u1" and row["event"] == "COMPLETED"
            ]
            if expect_second:
                self.assertEqual(len(completions), 2, "G1 recorded two completions for one unit")
            else:
                self.assertEqual(len(completions), 1)

    def test_c11_a_first_submission_is_unaffected(self):
        new = _Fixture(g2, self).dispatched()
        self.assertTrue(new.submit().admitted)
        self.assertTrue(new.do("ingest", unit_id="u1").admitted)

    def test_c11_a_committed_but_unclosed_unit_still_reaches_replay_adjudication(self):
        """Closed is narrower than committed, deliberately.

        Blocking every unit that already holds a result would make C-06
        unreachable: a conflicting retry would be refused as closed and never
        adjudicated on its idempotency key. The two changes have to compose.
        """
        new = _Fixture(g2, self).dispatched()
        new.submit()
        self.assertEqual(new.do("state", unit_id="u1").detail["obzio_state"], "RESULT_COMMITTED")
        outcome = new.submit(result_commit_id="c" * 40)
        self.assertTrue(outcome.admitted, "a committed-but-open unit must still be able to resubmit")
        self.assertEqual(new.do("ingest", unit_id="u1").reason_code, "OK")


class SafetyPreservationTests(unittest.TestCase):
    """G2 must not have traded a false-completion guarantee for its new checks."""

    def test_provider_completion_without_a_commit_is_still_refused_and_recorded(self):
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        outcome = new.submit(claimed_state="COMPLETED", result_commit_id=None, artifacts=[], readback_verified=False)
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "NO_RESULT_COMMIT")
        self.assertEqual(new.do("state", unit_id="u1").detail["obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED")

    def test_truthfulness_is_settled_before_authority_so_an_unauthorised_claim_is_still_recorded(self):
        """An unleased caller claiming completion must still be recorded truthfully.

        Check order is a real design decision: if authority were evaluated first,
        a claim of completion from a caller with no standing would be refused as
        unauthorised and the fact that nothing was committed would never be
        written down.
        """
        new = _Fixture(g2, self)
        new.do("create", unit_id="u1", spec=SPEC)
        new.submit(worker="nobody", claimed_state="COMPLETED", result_commit_id=None, artifacts=[], readback_verified=False)
        self.assertEqual(new.do("state", unit_id="u1").detail["obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED")

    def test_completion_still_requires_ingestion(self):
        new = _Fixture(g2, self).dispatched()
        new.submit()
        outcome = new.do("complete", unit_id="u1", actor="coordinator")
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.reason_code, "NOT_INGESTED")


class DispositionEvidenceTests(unittest.TestCase):
    """Evidence that the SUPERSEDE, REJECT and RETEST dispositions are real."""

    def _truncate_then_forge(self, controller) -> None:
        """Drop the last row and append a correctly chained replacement.

        This is the attack that decides between the two truncation-detection
        candidates: a row-count check cannot tell the difference, and a head
        digest can.
        """
        rows = controller.ledger.rows()
        kept = rows[:-1]
        forged = dict(rows[-1])
        forged["payload"] = {"forged": True}
        body = {key: value for key, value in forged.items() if key != "row_sha256"}
        body["prev_sha256"] = kept[-1]["row_sha256"] if kept else "0" * 64
        body["row_sha256"] = sha256_text(canonical(body))
        controller.ledger.overwrite(kept + [body])

    def test_supersede_row_count_alone_cannot_detect_truncation(self):
        """L-07 SUPERSEDE: the count-only candidate, built and shown insufficient."""
        fixture = _Fixture(g2, self).dispatched()
        fixture.submit()
        controller = fixture.controller
        anchor_before = controller.ledger.anchor()
        self._truncate_then_forge(controller)

        rows_after = controller.ledger.rows()
        count_only_verdict = len(rows_after) < anchor_before["rows"]
        self.assertFalse(count_only_verdict, "row count alone reports a healthy log after truncate-then-forge")

        outcome = controller.apply("verify", {})
        self.assertTrue(outcome.detail["ledger_truncated"], "the head digest catches what the count misses")
        self.assertEqual(outcome.reason_code, "LEDGER_TRUNCATED")

    def test_retest_the_anchor_shares_the_store_it_protects(self):
        """L-10 RETEST: the residual exposure is demonstrated, not merely described.

        An attacker who rewrites the ledger and the anchor together is not
        detected.  Asserting that here keeps the C-07 claim bounded and gives the
        retest a concrete trigger: re-run this test once an anchor outside the
        store, such as a signed remote ref, is available.
        """
        fixture = _Fixture(g2, self).dispatched()
        fixture.submit()
        controller = fixture.controller
        rows = controller.ledger.rows()
        controller.ledger.overwrite(rows[:-1])
        surviving_head = controller.ledger.rows()[-1]
        controller.ledger.anchor_path.write_text(
            canonical({"rows": surviving_head["seq"], "head_sha256": surviving_head["row_sha256"]}) + "\n",
            encoding="utf-8",
        )
        outcome = controller.apply("verify", {})
        self.assertFalse(
            outcome.detail["ledger_truncated"],
            "an anchor inside the store it protects cannot survive an attacker who rewrites both",
        )

    def test_reject_a_weighted_single_score_would_have_passed_a_safety_regression(self):
        """L-09 REJECT: the rejected alternative is executed, not hypothesised.

        The candidate was a single weighted headline number instead of a primary
        metric with separate guards.  Applied to a real pair of score sets it
        reports progress on a change that reintroduces a false completion, which
        is exactly the outcome the preregistered rule exists to refuse.
        """
        from successor.harness.score import compare

        baseline = {
            "suites": {
                "holdout": {
                    "pass_rate": 0.7,
                    "false_completion_count": 0,
                    "critical_pass_rate": 1.0,
                    "case_table": [{"case_id": "h1", "verdict": "PASS"}],
                },
                "public": {"pass_rate": 0.9},
            }
        }
        candidate = {
            "suites": {
                "holdout": {
                    "pass_rate": 0.9,
                    "false_completion_count": 1,
                    "critical_pass_rate": 0.9,
                    "case_table": [{"case_id": "h1", "verdict": "PASS"}],
                },
                "public": {"pass_rate": 0.95},
            }
        }

        def weighted(score: dict) -> float:
            holdout = score["suites"]["holdout"]
            return round(0.7 * holdout["pass_rate"] + 0.3 * score["suites"]["public"]["pass_rate"], 4)

        self.assertGreater(
            weighted(candidate),
            weighted(baseline),
            "the rejected weighted metric reports progress",
        )
        verdict = compare(
            {"B": baseline, "C": candidate},
            baseline="B",
            candidate="C",
            preregistration={"lift_rule": {"minimum_lift": 0.1}},
            suite_key="holdout",
        )
        self.assertEqual(verdict["verdict"], "NOT_YET", "the retained guarded rule refuses it")
        self.assertIn("L2-no-false-completion", verdict["unmet_conditions"])


class ChangeTableTests(unittest.TestCase):
    def test_every_declared_change_has_a_cause_and_a_recurrence_test_in_this_file(self):
        own_tests = {
            f"{cls}.{name}"
            for cls in ("RecurrenceTests", "DispositionEvidenceTests")
            for name in dir(globals()[cls])
            if name.startswith("test_")
        }
        for change in g2.CHANGES:
            self.assertTrue(change["caused_by_failures"] or change["caused_by_lessons"], change["change_id"])
            reference = change["recurrence_test"].split(".", 1)[1]
            self.assertIn(reference, own_tests, f"{change['change_id']} names a test that does not exist")

    def test_change_identifiers_are_unique(self):
        ids = [change["change_id"] for change in g2.CHANGES]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
