import importlib.util
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
