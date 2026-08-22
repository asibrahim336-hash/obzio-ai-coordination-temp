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


class ProducerDocumentTests(unittest.TestCase):
    def test_result_payload_is_read_from_result_commit(self):
        with mock.patch.object(
            TOOL,
            "_show",
            side_effect=[
                b'{"artifact_count": 0, "artifacts": [], "total_bytes": 0}',
                b'{"terminal_report": "READY_TO_COMMIT"}',
                b'{"task_id": "PO03-WA-016"}',
            ],
        ) as show:
            manifest, ready, result = TOOL._load_producer_documents(
                "a" * 40,
                "b" * 40,
                "manifest.json",
                "ready.json",
                "result.json",
            )

        self.assertIn(b'"artifact_count"', manifest)
        self.assertIn(b'"terminal_report"', ready)
        self.assertEqual(result["task_id"], "PO03-WA-016")
        self.assertEqual(
            show.call_args_list,
            [
                mock.call("a" * 40, "manifest.json"),
                mock.call("b" * 40, "ready.json"),
                mock.call("a" * 40, "result.json"),
            ],
        )


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

    def test_top_level_return_and_unbound_result_are_accepted(self):
        TOOL._validate_producer_attempt(
            "PO03-WA-009",
            self.attempt,
            dict(self.attempt),
            {"task_id": "PO03-WA-009"},
        )

    def test_matching_partial_result_context_is_accepted(self):
        TOOL._validate_producer_attempt(
            "PO03-WA-009",
            self.attempt,
            dict(self.attempt),
            {"attempt_id": self.attempt["attempt_id"]},
        )

    def test_stale_partial_result_context_is_refused(self):
        with self.assertRaisesRegex(ValueError, "stale or divergent"):
            TOOL._validate_producer_attempt(
                "PO03-WA-009",
                self.attempt,
                dict(self.attempt),
                {"attempt_id": "PO03-WA-009-A01"},
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

    def test_partial_top_level_attempt_is_refused(self):
        with self.assertRaisesRegex(ValueError, "partial attempt envelope"):
            TOOL._validate_producer_attempt(
                "PO03-WA-009",
                self.attempt,
                {"attempt_id": self.attempt["attempt_id"]},
                {},
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

    def test_nested_controller_base_is_trusted(self):
        with mock.patch.object(TOOL, "_git", side_effect=self.git_result):
            observed = TOOL._trusted_source_base(
                {
                    "source_base": {
                        "immutable_controller_base": self.source_base,
                    }
                },
                self.return_commit,
                self.ingestion_commit,
            )
        self.assertEqual(observed, self.source_base)

    def test_nested_producer_start_commit_is_trusted(self):
        with mock.patch.object(TOOL, "_git", side_effect=self.git_result):
            observed = TOOL._trusted_source_base(
                {
                    "source_base": {
                        "producer_start_commit": self.source_base,
                    }
                },
                self.return_commit,
                self.ingestion_commit,
            )
        self.assertEqual(observed, self.source_base)

    def test_nested_immutable_producer_base_is_trusted(self):
        with mock.patch.object(TOOL, "_git", side_effect=self.git_result):
            observed = TOOL._trusted_source_base(
                {
                    "source_base": {
                        "immutable_producer_base": self.source_base,
                    }
                },
                self.return_commit,
                self.ingestion_commit,
            )
        self.assertEqual(observed, self.source_base)

    def test_changed_files_comparison_base_is_trusted(self):
        with mock.patch.object(TOOL, "_git", side_effect=self.git_result):
            observed = TOOL._trusted_source_base(
                {
                    "changed_files": {
                        "compared_against": self.source_base,
                    }
                },
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
    def test_existing_dispatch_time_is_preserved(self):
        self.assertEqual(
            TOOL._preserve_recorded_time(
                "2026-08-22T08:22:00Z",
                "2026-08-22T08:21:00Z",
            ),
            "2026-08-22T08:22:00Z",
        )

    def test_existing_earlier_dispatch_time_is_also_preserved(self):
        self.assertEqual(
            TOOL._preserve_recorded_time(
                "2026-08-22T08:22:00Z",
                "2026-08-22T08:24:00Z",
            ),
            "2026-08-22T08:22:00Z",
        )

    def test_missing_dispatch_time_uses_producer_start(self):
        self.assertEqual(
            TOOL._preserve_recorded_time(None, "2026-08-22T08:21:00Z"),
            "2026-08-22T08:21:00Z",
        )


class ActiveProjectionTests(unittest.TestCase):
    def test_completion_decrements_observed_active_count_once(self):
        self.assertEqual(TOOL._reconciled_active_count(8, 5, True), 7)

    def test_idempotent_reconciliation_does_not_decrement_again(self):
        self.assertEqual(TOOL._reconciled_active_count(7, 5, False), 7)

    def test_registry_count_repairs_low_observed_projection(self):
        self.assertEqual(TOOL._reconciled_active_count(3, 5, False), 5)


if __name__ == "__main__":
    unittest.main()
