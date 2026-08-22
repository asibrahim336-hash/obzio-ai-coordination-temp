"""a1-u06 — a partial write is unobservable as committed, at every injection point.

Hypothesis (frozen in ``control/dispatch/a1-u06.json``): two-phase result
staging makes partial writes unobservable to the parent.

Acceptance, satisfied literally: a fault injected between stage and commit
leaves the unit recoverable and never observable as ``RESULT_COMMITTED``, for
every injection point.  Falsified if any injection point yields an observable
committed state with incomplete bytes.

"Every injection point" is enumerated by the engine itself
(``staging.INJECTION_POINTS``) and the test asserts it has covered all of them,
so adding a point to the mechanism without testing it fails the suite rather
than passing silently.  Two points are expected to be genuinely committed —
those after the atomic publish — and for those the test demands complete,
correct bytes rather than merely a non-committed state.
"""

from __future__ import annotations

import unittest

from test_a1_support import ScratchCase

from engine.ledger import HashChainedLedger
from engine.staging import (
    ARTIFACT_DIR,
    COMMIT_MARKER_NAME,
    CORRUPT,
    INJECTION_POINTS,
    MANIFEST_NAME,
    RESULT_COMMITTED,
    ResultStager,
    StagingError,
    stage_and_publish,
)

UNIT = "a1-u06-subject"
TXN = "a1-u06-txn-1"
ARTIFACTS = {
    "result.json": b'{"unit":"a1-u06","state":"RESULT_VERIFIED"}\n',
    "evidence.txt": b"x" * 9000,
    "log.txt": b"staged\nverified\npublished\n",
}
TOTAL_BYTES = sum(len(value) for value in ARTIFACTS.values())

# The only points that occur after the atomic publish; everything earlier must
# leave the result unobservable as committed.
POST_PUBLISH = {"after_publish_rename", "after_ledger_commit_event"}


class InjectedFault(RuntimeError):
    pass


class Environment:
    """One isolated result-staging world: its own ledger, root and stager."""

    def __init__(self, root) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.ledger = HashChainedLedger(root / "ledger.jsonl")
        self.stager = ResultStager(root / "results", self.ledger)

    def failing_at(self, point: str) -> ResultStager:
        """A second stager over the same state that crashes at one point."""

        def hook(fired: str) -> None:
            if fired == point:
                raise InjectedFault(point)

        return ResultStager(self.root / "results", self.ledger, fault_hook=hook)


class StagingCase(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.env = Environment(self.scratch / "env")
        self.ledger = self.env.ledger
        self.stager = self.env.stager

    def fresh_env(self, name: str) -> Environment:
        return Environment(self.scratch / name)

    def stager_that_fails_at(self, point: str) -> ResultStager:
        return self.env.failing_at(point)


class HappyPathTests(StagingCase):
    def test_full_sequence_publishes_and_verifies(self):
        published = stage_and_publish(
            self.stager,
            TXN,
            UNIT,
            ARTIFACTS,
            result_commit_id="commit-abc",
            result_locator="git:branch@commit-abc:manifest",
        )
        observation = self.stager.observe(TXN)
        self.assertEqual(RESULT_COMMITTED, observation.state, observation.as_dict())
        self.assertEqual(len(ARTIFACTS), observation.artifact_count)
        self.assertEqual(TOTAL_BYTES, observation.total_bytes)
        for name, data in ARTIFACTS.items():
            self.assertEqual(data, (published / ARTIFACT_DIR / name).read_bytes())
            self.assertEqual(data, self.stager.read_published(TXN, name))
        self.assertEqual([], self.stager.recover())
        self.assertTrue(self.ledger.verify().ok)

    def test_state_sequence_is_recorded_in_order(self):
        stage_and_publish(
            self.stager,
            TXN,
            UNIT,
            ARTIFACTS,
            result_commit_id="commit-abc",
            result_locator="locator",
        )
        events = [row["event"] for row in self.ledger.events_for(UNIT)]
        self.assertEqual(
            ["RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED", "RESULT_COMMITTED"], events
        )

    def test_publishing_an_unverified_result_is_refused(self):
        staged = self.stager.reserve(TXN, UNIT)
        self.stager.stage_artifact(staged, "result.json", ARTIFACTS["result.json"])
        self.stager.seal(staged)
        with self.assertRaises(StagingError):
            self.stager.publish(staged, result_commit_id="c", result_locator="l")
        self.assertNotEqual(RESULT_COMMITTED, self.stager.observe(TXN).state)

    def test_a_transaction_id_is_single_use(self):
        stage_and_publish(
            self.stager, TXN, UNIT, ARTIFACTS, result_commit_id="c", result_locator="l"
        )
        with self.assertRaises(StagingError):
            self.stager.reserve(TXN, UNIT)


class EveryInjectionPointTests(StagingCase):
    """The acceptance assertion, driven over the engine's own point list."""

    def test_no_injection_point_before_publish_yields_a_committed_observation(self):
        covered: list[str] = []
        for point in INJECTION_POINTS:
            with self.subTest(injection_point=point):
                env = self.fresh_env(f"observe-{point}")
                raised = False
                try:
                    stage_and_publish(
                        env.failing_at(point),
                        TXN,
                        UNIT,
                        ARTIFACTS,
                        result_commit_id="commit-abc",
                        result_locator="git:branch@commit-abc:manifest",
                    )
                except InjectedFault:
                    raised = True
                self.assertTrue(raised, f"{point} was never reached; the point list is stale")

                observation = env.stager.observe(TXN)
                if point in POST_PUBLISH:
                    self.assertEqual(
                        RESULT_COMMITTED,
                        observation.state,
                        f"{point}: bytes were published atomically, so the result is committed",
                    )
                    self.assertEqual(TOTAL_BYTES, observation.total_bytes)
                    for name, data in ARTIFACTS.items():
                        self.assertEqual(data, env.stager.read_published(TXN, name))
                else:
                    self.assertNotEqual(
                        RESULT_COMMITTED,
                        observation.state,
                        f"{point} produced an observable commit with incomplete bytes: "
                        f"{observation.as_dict()}",
                    )
                    self.assertFalse(observation.committed)
                    self.assertNotEqual(
                        [], env.stager.recover(), f"{point} left nothing for recovery to find"
                    )
                self.assertTrue(env.ledger.verify().ok, f"{point} corrupted the ledger")
                covered.append(point)
        self.assertEqual(list(INJECTION_POINTS), covered)

    def test_every_pre_publish_injection_point_is_recoverable_by_rerun(self):
        for point in INJECTION_POINTS:
            if point in POST_PUBLISH:
                continue
            with self.subTest(injection_point=point):
                env = self.fresh_env(f"rerun-{point}")
                with self.assertRaises(InjectedFault):
                    stage_and_publish(
                        env.failing_at(point), TXN, UNIT, ARTIFACTS, result_commit_id="c", result_locator="l"
                    )
                self.assertNotEqual([], env.stager.recover())

                # Recovery re-runs from immutable input only.
                env.stager.discard(TXN)
                stage_and_publish(
                    env.stager,
                    TXN,
                    UNIT,
                    ARTIFACTS,
                    result_commit_id="commit-rerun",
                    result_locator="git:branch@commit-rerun:manifest",
                )
                observation = env.stager.observe(TXN)
                self.assertEqual(RESULT_COMMITTED, observation.state, f"{point}: {observation.as_dict()}")
                self.assertEqual(TOTAL_BYTES, observation.total_bytes)
                for name, data in ARTIFACTS.items():
                    self.assertEqual(data, env.stager.read_published(TXN, name))
                self.assertEqual(1, len(list(env.stager.committed_root.iterdir())))
                self.assertTrue(env.ledger.verify().ok)

    def test_a_partial_artifact_is_never_visible_in_the_staging_directory(self):
        stager = self.stager_that_fails_at("mid_artifact_write")
        with self.assertRaises(InjectedFault):
            stage_and_publish(stager, TXN, UNIT, ARTIFACTS, result_commit_id="c", result_locator="l")
        artifact_dir = self.stager.staging_root / TXN / ARTIFACT_DIR
        visible = sorted(p.name for p in artifact_dir.iterdir() if not p.name.startswith("."))
        partial = sorted(p.name for p in artifact_dir.iterdir() if p.name.startswith("."))
        self.assertNotIn("evidence.txt", visible)
        self.assertEqual([".evidence.txt.partial"], partial)
        # The half-written bytes exist on disk but are not an artifact.
        self.assertLess((artifact_dir / partial[0]).stat().st_size, len(ARTIFACTS["evidence.txt"]))
        self.assertNotEqual(RESULT_COMMITTED, self.stager.observe(TXN).state)


class TornPublicationTests(StagingCase):
    """Corrupt the published bytes directly: the strongest form of the claim."""

    def publish_once(self) -> None:
        stage_and_publish(
            self.stager,
            TXN,
            UNIT,
            ARTIFACTS,
            result_commit_id="commit-abc",
            result_locator="git:branch@commit-abc:manifest",
        )
        self.assertEqual(RESULT_COMMITTED, self.stager.observe(TXN).state)

    def test_truncating_a_published_artifact_is_observed_as_corrupt(self):
        self.publish_once()
        target = self.stager.committed_root / TXN / ARTIFACT_DIR / "evidence.txt"
        with target.open("r+b") as handle:
            handle.truncate(len(ARTIFACTS["evidence.txt"]) // 2)
        observation = self.stager.observe(TXN)
        self.assertEqual(CORRUPT, observation.state, observation.as_dict())
        self.assertTrue(any("evidence.txt" in problem for problem in observation.problems))
        with self.assertRaises(StagingError):
            self.stager.read_published(TXN, "evidence.txt")

    def test_flipping_a_bit_in_a_published_artifact_is_observed_as_corrupt(self):
        self.publish_once()
        target = self.stager.committed_root / TXN / ARTIFACT_DIR / "result.json"
        data = bytearray(target.read_bytes())
        data[3] ^= 0x08
        target.write_bytes(bytes(data))
        observation = self.stager.observe(TXN)
        self.assertEqual(CORRUPT, observation.state, observation.as_dict())
        self.assertTrue(any("result.json" in problem for problem in observation.problems))

    def test_removing_the_commit_marker_is_observed_as_corrupt(self):
        self.publish_once()
        (self.stager.committed_root / TXN / COMMIT_MARKER_NAME).unlink()
        self.assertEqual(CORRUPT, self.stager.observe(TXN).state)

    def test_an_extra_unmanifested_artifact_is_observed_as_corrupt(self):
        self.publish_once()
        (self.stager.committed_root / TXN / ARTIFACT_DIR / "smuggled.txt").write_bytes(b"not in the manifest")
        observation = self.stager.observe(TXN)
        self.assertEqual(CORRUPT, observation.state)
        self.assertTrue(any("smuggled.txt" in problem for problem in observation.problems))

    def test_a_swapped_manifest_is_observed_as_corrupt(self):
        self.publish_once()
        manifest_path = self.stager.committed_root / TXN / MANIFEST_NAME
        manifest_path.write_text('{"txn_id":"forged","artifacts":[],"artifact_count":0,"total_bytes":0}\n')
        observation = self.stager.observe(TXN)
        self.assertEqual(CORRUPT, observation.state)
        self.assertTrue(any("commit marker pins" in problem for problem in observation.problems))

    def test_a_corrupt_publication_is_quarantined_by_recovery(self):
        self.publish_once()
        target = self.stager.committed_root / TXN / ARTIFACT_DIR / "log.txt"
        target.write_bytes(b"tampered")
        recoverable = self.stager.recover()
        self.assertEqual([TXN], [item.txn_id for item in recoverable])
        self.assertEqual("QUARANTINE_AND_RESTAGE", recoverable[0].disposition)


class LostCallbackTests(StagingCase):
    """Publishing then losing the notification must be repairable, not fatal."""

    def test_publish_without_a_ledger_row_is_reconciled_idempotently(self):
        stager = self.stager_that_fails_at("after_publish_rename")
        with self.assertRaises(InjectedFault):
            stage_and_publish(
                stager,
                TXN,
                UNIT,
                ARTIFACTS,
                result_commit_id="commit-abc",
                result_locator="git:branch@commit-abc:manifest",
            )
        self.assertEqual(RESULT_COMMITTED, self.stager.observe(TXN).state)
        events = [row["event"] for row in self.ledger.events_for(UNIT)]
        self.assertNotIn("RESULT_COMMITTED", events)

        recoverable = self.stager.recover()
        self.assertEqual(["RECONCILE_LEDGER"], [item.disposition for item in recoverable])
        self.assertTrue(self.stager.reconcile(TXN))
        self.assertFalse(self.stager.reconcile(TXN), "reconciliation must be idempotent")
        committed = [
            row for row in self.ledger.events_for(UNIT) if row["event"] == "RESULT_COMMITTED"
        ]
        self.assertEqual(1, len(committed))
        self.assertTrue(committed[0]["payload"]["reconciled"])
        self.assertEqual([], self.stager.recover())

    def test_reconciliation_refuses_a_result_that_does_not_verify(self):
        stager = self.stager_that_fails_at("after_publish_rename")
        with self.assertRaises(InjectedFault):
            stage_and_publish(
                stager, TXN, UNIT, ARTIFACTS, result_commit_id="c", result_locator="l"
            )
        (self.stager.committed_root / TXN / ARTIFACT_DIR / "log.txt").write_bytes(b"tampered")
        with self.assertRaises(StagingError):
            self.stager.reconcile(TXN)
        self.assertNotIn(
            "RESULT_COMMITTED", [row["event"] for row in self.ledger.events_for(UNIT)]
        )


class NegativeControlTests(StagingCase):
    """Prove the observation is doing the work rather than a stored flag."""

    def test_a_marker_alone_is_not_enough_to_be_observed_as_committed(self):
        published = self.stager.committed_root / TXN
        (published / ARTIFACT_DIR).mkdir(parents=True)
        (published / COMMIT_MARKER_NAME).write_text(
            '{"txn_id":"a1-u06-txn-1","unit_id":"a1-u06-subject","manifest_sha256":'
            '"' + "a" * 64 + '","artifact_count":3,"total_bytes":9999,'
            '"result_commit_id":"forged","result_locator":"forged","committed_at":"2026-08-22T07:00:00Z"}\n'
        )
        observation = self.stager.observe(TXN)
        self.assertEqual(
            CORRUPT,
            observation.state,
            "a hand-written commit marker with no bytes must not read as committed",
        )
        self.assertFalse(observation.committed)

    def test_a_flag_based_observation_would_have_accepted_the_forgery(self):
        published = self.stager.committed_root / TXN
        (published / ARTIFACT_DIR).mkdir(parents=True)
        (published / COMMIT_MARKER_NAME).write_text("{}\n")
        # The implementation this replaces: existence of a marker as the test.
        self.assertTrue((published / COMMIT_MARKER_NAME).exists())
        self.assertNotEqual(RESULT_COMMITTED, self.stager.observe(TXN).state)


if __name__ == "__main__":
    unittest.main()
