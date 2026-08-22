import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = (
    REPO_ROOT / "workstreams" / "po03" / "tools" / "reconcile_wave_a_result.py"
)
TOOL_SPEC = importlib.util.spec_from_file_location(
    "reconcile_wave_a_result", TOOL_PATH
)
TOOL = importlib.util.module_from_spec(TOOL_SPEC)
assert TOOL_SPEC.loader is not None
sys.modules[TOOL_SPEC.name] = TOOL
TOOL_SPEC.loader.exec_module(TOOL)


class AttemptProjectionTests(unittest.TestCase):
    def test_a01_uses_canonical_input_and_outbox(self):
        attempt = {"attempt_id": "PO03-WA-009-A01"}
        self.assertEqual(
            TOOL._attempt_projection("PO03-WA-009", "wa-009", attempt),
            (
                "control/inputs/wave-a/wa-009.json",
                "outbox-po03-wa-009-dispatch-a01",
            ),
        )

    def test_a02_uses_successor_input_and_outbox(self):
        attempt = {"attempt_id": "PO03-WA-009-A02"}
        self.assertEqual(
            TOOL._attempt_projection("PO03-WA-009", "wa-009", attempt),
            (
                "control/inputs/wave-a/wa-009-a02.json",
                "outbox-po03-wa-009-dispatch-a02",
            ),
        )

    def test_wrong_task_identity_is_refused(self):
        with self.assertRaisesRegex(ValueError, "invalid active attempt identity"):
            TOOL._attempt_projection(
                "PO03-WA-009",
                "wa-009",
                {"attempt_id": "PO03-WA-010-A02"},
            )


class ProducerAttemptTests(unittest.TestCase):
    def setUp(self):
        self.attempt = {
            "attempt_id": "PO03-WA-009-A02",
            "idempotency_key": "po03:100bc2079ced:wa-009:a02",
            "lease_id": "lease-po03-wa-009-a02",
            "fence_token": 2,
        }

    def test_matching_attempt_is_accepted(self):
        TOOL._validate_producer_attempt(
            "PO03-WA-009",
            self.attempt,
            {"attempt": dict(self.attempt)},
            {"attempt": dict(self.attempt)},
        )

    def test_stale_fence_is_refused(self):
        stale = dict(self.attempt, fence_token=1)
        with self.assertRaisesRegex(ValueError, "stale or divergent"):
            TOOL._validate_producer_attempt(
                "PO03-WA-009",
                self.attempt,
                {"attempt": stale},
                {"attempt": dict(self.attempt)},
            )

    def test_missing_attempt_envelope_is_refused(self):
        with self.assertRaisesRegex(ValueError, "lacks an attempt envelope"):
            TOOL._validate_producer_attempt(
                "PO03-WA-009",
                self.attempt,
                {},
                {"attempt": dict(self.attempt)},
            )


class TrustedSourceBaseTests(unittest.TestCase):
    source_base = "a" * 40
    return_commit = "b" * 40
    ingestion_commit = "c" * 40

    def git_result(self, *args):
        if args[:2] == ("rev-parse", "--verify"):
            return (self.source_base + "\n").encode()
        if args[:2] == ("merge-base", "--is-ancestor"):
            return b""
        if args == ("merge-base", self.return_commit, self.ingestion_commit):
            return (self.source_base + "\n").encode()
        self.fail(f"unexpected git call: {args}")

    def test_exact_controller_divergence_is_trusted(self):
        with mock.patch.object(TOOL, "_git", side_effect=self.git_result):
            observed = TOOL._trusted_source_base(
                {"source_base_commit": self.source_base},
                self.return_commit,
                self.ingestion_commit,
            )
        self.assertEqual(observed, self.source_base)

    def test_non_divergence_claim_is_refused(self):
        def divergent_git(*args):
            if args == ("merge-base", self.return_commit, self.ingestion_commit):
                return ("d" * 40 + "\n").encode()
            return self.git_result(*args)

        with mock.patch.object(TOOL, "_git", side_effect=divergent_git):
            with self.assertRaisesRegex(ValueError, "exact producer/controller divergence"):
                TOOL._trusted_source_base(
                    {"source_base_commit": self.source_base},
                    self.return_commit,
                    self.ingestion_commit,
                )

    def test_malformed_source_base_is_refused_before_git(self):
        with mock.patch.object(TOOL, "_git") as git:
            with self.assertRaisesRegex(ValueError, "exact source_base_commit"):
                TOOL._trusted_source_base(
                    {"source_base_commit": "not-a-commit"},
                    self.return_commit,
                    self.ingestion_commit,
                )
        git.assert_not_called()


class ProjectionTimeTests(unittest.TestCase):
    def test_existing_later_dispatch_time_is_preserved(self):
        self.assertEqual(
            TOOL._later_time(
                "2026-08-22T08:22:00Z",
                "2026-08-22T08:21:00Z",
            ),
            "2026-08-22T08:22:00Z",
        )

    def test_missing_dispatch_time_uses_producer_start(self):
        self.assertEqual(
            TOOL._later_time(None, "2026-08-22T08:21:00Z"),
            "2026-08-22T08:21:00Z",
        )


if __name__ == "__main__":
    unittest.main()
