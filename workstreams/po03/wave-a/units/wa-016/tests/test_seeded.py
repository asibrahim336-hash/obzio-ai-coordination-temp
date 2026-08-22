"""The read-only seeded controls this unit composes are the pinned ones.

If a control that gates the repository drifts from the digest the frozen task
input pinned, "valid" has quietly changed meaning and this unit's evidence no
longer describes the control it claims to have tested.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness.seeded import (
    PINNED_DIGEST_KEYS,
    SEEDED_RELS,
    TASK_INPUT_REL,
    SeededControlError,
    acceptance_contract,
    control_digests,
    load_validator,
    repository_root,
    sha256_file,
    task_input,
)

UNIT_ROOT = Path(__file__).resolve().parents[1]
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-016"


class LocationTests(unittest.TestCase):
    def test_the_repository_root_is_found_from_the_unit(self):
        root = repository_root()
        self.assertTrue((root / SEEDED_RELS["validator"]).exists())
        self.assertTrue((root / TASK_INPUT_REL).exists())

    def test_this_unit_lives_where_the_frozen_input_says_it_may_write(self):
        root = repository_root()
        relative = UNIT_ROOT.relative_to(root).as_posix()
        self.assertEqual(OWNED_PREFIX, relative)
        globs = task_input(root)["ownership"]["allowed_write_globs"]
        self.assertEqual([f"{OWNED_PREFIX}/**"], globs)

    def test_no_seeded_control_lives_inside_the_owned_subtree(self):
        for name, rel in SEEDED_RELS.items():
            self.assertFalse(rel.startswith(OWNED_PREFIX), name)


class PinTests(unittest.TestCase):
    def test_every_seeded_control_matches_its_pinned_digest(self):
        for digest in control_digests():
            with self.subTest(control=digest.name):
                self.assertIsNotNone(digest.pinned_sha256, digest.relative_path)
                self.assertTrue(
                    digest.matches_pin,
                    f"{digest.relative_path}: observed {digest.observed_sha256} != pinned {digest.pinned_sha256}",
                )
                self.assertGreater(digest.bytes, 0)

    def test_every_pinned_digest_key_names_a_seeded_control(self):
        self.assertEqual(set(SEEDED_RELS), set(PINNED_DIGEST_KEYS))

    def test_the_acceptance_contract_matches_the_digest_the_input_pinned(self):
        root = repository_root()
        contract, observed = acceptance_contract(root)
        self.assertEqual(task_input(root)["acceptance_contract"]["sha256"], observed)
        self.assertEqual("READY_TO_COMMIT", contract["producer_terminal_report"])
        self.assertEqual(12, len(contract["required_assertions"]))

    def test_a_missing_control_is_reported_rather_than_skipped(self):
        with self.assertRaises(SeededControlError):
            control_digests(Path("/nonexistent-repository-root"))

    def test_the_frozen_input_digest_is_the_one_recorded_in_the_source_claims(self):
        from harness.research import REPOSITORY_SOURCE_CLAIMS

        root = repository_root()
        claim = next(c for c in REPOSITORY_SOURCE_CLAIMS if c["path"] == TASK_INPUT_REL)
        self.assertEqual(sha256_file(root / TASK_INPUT_REL), claim["sha256"])


class ValidatorTests(unittest.TestCase):
    def test_the_validator_is_loaded_in_place_from_its_read_only_path(self):
        module = load_validator()
        loaded_from = Path(module.__file__).resolve()
        self.assertEqual((repository_root() / SEEDED_RELS["validator"]).resolve(), loaded_from)
        self.assertFalse(loaded_from.is_relative_to(UNIT_ROOT))

    def test_a_drifted_validator_refuses_to_load(self):
        """The pin is enforced, not merely recorded."""
        import harness.seeded as seeded

        original_cache, original_input = seeded._VALIDATOR, seeded.task_input
        seeded._VALIDATOR = None
        seeded.task_input = lambda root=None: {"source_base": {"validator_sha256": "0" * 64}}
        try:
            with self.assertRaises(SeededControlError):
                seeded.load_validator()
        finally:
            seeded._VALIDATOR, seeded.task_input = original_cache, original_input

    def test_the_validator_exposes_the_result_entry_point_this_unit_composes(self):
        self.assertTrue(callable(load_validator().validate_result))


class FrozenInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input = task_input()

    def test_the_input_is_the_one_this_unit_executes(self):
        self.assertEqual("PO03-WA-016", self.input["task_id"])
        self.assertEqual("H-PO03-WA-016", self.input["hypothesis_id"])
        self.assertEqual("OBZIO-IMMUTABLE-TASK-INPUT-v1", self.input["protocol_version"])

    def test_the_hypothesis_under_test_is_quoted_verbatim(self):
        self.assertEqual(
            "Every transaction transition can survive pre/post-write, process-loss, and callback-loss "
            "injection without false completion.",
            self.input["assignment"]["falsifiable_hypothesis"],
        )

    def test_the_required_executable_output_is_what_this_unit_built(self):
        self.assertEqual(
            "Fault injector, transition matrix runner, and tests.",
            self.input["assignment"]["required_executable_output"],
        )
        for module in ("harness/fault_injector.py", "harness/transition_matrix.py"):
            self.assertTrue((UNIT_ROOT / module).exists(), module)
        self.assertTrue(sorted((UNIT_ROOT / "tests").glob("test_*.py")))

    def test_the_seed_quotas_are_met_or_exceeded(self):
        from harness.reproductions import ALL_REPRODUCTIONS
        from harness.research import HYPOTHESES, MECHANISM_CHANGES

        assignment = self.input["assignment"]
        self.assertTrue(assignment["first_substantive_return_seed"])
        self.assertGreaterEqual(len(HYPOTHESES), assignment["minimum_current_method_hypotheses"])
        self.assertGreaterEqual(len(ALL_REPRODUCTIONS), assignment["minimum_sanitized_reproductions"])
        self.assertTrue(assignment["mechanism_change_or_rejection_required"])
        self.assertTrue(
            [m for m in MECHANISM_CHANGES if m["disposition"] in {"RETAIN", "EVIDENCE_BACKED_REJECTION"}]
        )

    def test_only_ready_to_commit_may_be_reported(self):
        self.assertEqual("READY_TO_COMMIT", self.input["producer_return_contract"]["only_permitted_terminal_report"])

    def test_the_attempt_identity_matches_the_fixtures_the_harness_drives(self):
        from harness import fixtures

        attempt = self.input["attempt"]
        self.assertEqual(attempt["attempt_id"], fixtures.ATTEMPT_ID)
        self.assertEqual(attempt["idempotency_key"], fixtures.IDEMPOTENCY_KEY)
        self.assertEqual(attempt["lease_id"], fixtures.LEASE_ID)
        self.assertEqual(self.input["commission_id"], fixtures.COMMISSION_ID)


if __name__ == "__main__":
    unittest.main()
