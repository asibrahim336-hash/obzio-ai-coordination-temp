"""The probes: repository ground truth, isolation of each mutation, read-only conduct."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness.probes import (
    SCHEMA_RELPATH,
    VALIDATOR_RELPATH,
    ProbeUnavailable,
    RepositoryProbes,
    baseline_document,
    repository_root,
)

ROOT = repository_root()
PROBES = RepositoryProbes(ROOT)


class BaselineTests(unittest.TestCase):
    def test_the_unmutated_baseline_is_admitted(self) -> None:
        """Without this, an admitted mutation would prove nothing."""
        self.assertEqual(PROBES.baseline_is_admitted().disposition, "ADMITTED")

    def test_the_baseline_declares_a_fully_committed_result(self) -> None:
        document = baseline_document()
        self.assertEqual(document["obzio_state"], "COMPLETED")
        self.assertEqual(document["completion_actor"], "coordinator")
        self.assertEqual(document["result_transaction"]["state"], "INGESTED")

    def test_the_baseline_byte_accounting_reconciles(self) -> None:
        document = baseline_document()
        self.assertEqual(
            document["result_transaction"]["total_bytes"],
            sum(artifact["bytes"] for artifact in document["artifacts"]),
        )

    def test_the_baseline_carries_no_credential_shaped_value(self) -> None:
        text = repr(baseline_document())
        for marker in ("ghp_", "github_pat", "Bearer ", "x-access-token", "password"):
            self.assertNotIn(marker, text)


class GroundTruthTests(unittest.TestCase):
    """What the read-only control actually does, established by running it."""

    def test_the_control_rejects_a_non_coordinator_completion(self) -> None:
        observation = PROBES.completion_actor()
        self.assertEqual(observation.disposition, "REJECTED")
        self.assertTrue(any("completion_actor" in error for error in observation.reported_errors))

    def test_the_control_admits_an_undeclared_transaction_state(self) -> None:
        """The recurrence test for M5, and the fact the seeded false claim denies."""
        observation = PROBES.transaction_state_enum()
        self.assertEqual(observation.disposition, "ADMITTED")
        self.assertEqual(observation.reported_errors, [])

    def test_the_schema_does_declare_the_enumeration_the_control_ignores(self) -> None:
        """Why the seeded claim is attractive: true of the contract, false of the code."""
        observation = PROBES.schema_declares_state_enum()
        self.assertEqual(observation.disposition, "DECLARED")
        self.assertIn("INGESTED", observation.detail["enum"])

    def test_the_control_rejects_inconsistent_byte_accounting(self) -> None:
        self.assertEqual(PROBES.byte_accounting().disposition, "REJECTED")

    def test_the_control_admits_a_duplicate_logical_name(self) -> None:
        """The recurrence test for M6."""
        self.assertEqual(PROBES.logical_name_uniqueness().disposition, "ADMITTED")

    def test_the_control_rejects_producer_self_acceptance(self) -> None:
        self.assertEqual(PROBES.producer_self_acceptance().disposition, "REJECTED")

    def test_the_control_rejects_provider_completion_without_a_commit(self) -> None:
        self.assertEqual(PROBES.provider_completion_without_commit().disposition, "REJECTED")

    def test_the_seeded_control_suite_passes(self) -> None:
        observation = PROBES.seeded_control_suite()
        self.assertEqual(observation.disposition, "PASS")
        self.assertGreater(observation.detail["test_count"], 0)


class ObservationRecordTests(unittest.TestCase):
    def test_every_probe_records_a_reproducible_observation_digest(self) -> None:
        for probe_id, observation in PROBES.run_all().items():
            record = observation.as_record()
            self.assertEqual(record["probe_id"], probe_id)
            self.assertEqual(len(record["observation_sha256"]), 64)

    def test_observations_are_stable_across_runs(self) -> None:
        first = PROBES.transaction_state_enum().as_record()["observation_sha256"]
        second = PROBES.transaction_state_enum().as_record()["observation_sha256"]
        self.assertEqual(first, second)

    def test_the_recorded_command_carries_no_absolute_path(self) -> None:
        """A command naming this runner's checkout cannot be re-run from a clean clone."""
        for observation in PROBES.run_all().values():
            for part in observation.command:
                self.assertFalse(
                    part.startswith("/"),
                    f"{observation.probe_id} recorded an absolute path: {part}",
                )

    def test_the_recorded_command_names_the_control_by_repository_path(self) -> None:
        command = PROBES.completion_actor().command
        self.assertIn(VALIDATOR_RELPATH, command)
        self.assertEqual(command[-1], "<temporary document>")

    def test_an_unknown_probe_is_refused(self) -> None:
        with self.assertRaises(ProbeUnavailable):
            PROBES.run("PROBE-THAT-DOES-NOT-EXIST")

    def test_every_registered_probe_runs(self) -> None:
        self.assertEqual(sorted(PROBES.run_all()), sorted(PROBES.registry()))


class ReadOnlyConductTests(unittest.TestCase):
    def test_the_control_digests_match_the_pinned_source_base_values(self) -> None:
        observed = PROBES.control_digests().detail["observed_sha256"]
        self.assertEqual(
            observed[VALIDATOR_RELPATH],
            "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
        )
        self.assertEqual(
            observed[SCHEMA_RELPATH],
            "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
        )

    def test_running_every_probe_leaves_the_repository_unchanged(self) -> None:
        before = self._status()
        PROBES.run_all()
        self.assertEqual(self._status(), before)

    def test_running_the_probes_creates_no_bytecode_cache_beside_a_read_only_control(self) -> None:
        """A __pycache__ next to a read-only tool is a write outside the owned subtree.

        Asserted as a change rather than as an absolute state. A cache left behind
        by some earlier command in the same checkout is not this harness's doing,
        and deleting it to make the assertion simpler would itself be a write
        outside the subtree.
        """
        watched = [
            ROOT / relpath / "__pycache__"
            for relpath in ("workstreams/po03/tools", "workstreams/po03/contracts", "workstreams/po03/tests")
        ]
        before = {path: path.exists() for path in watched}
        PROBES.run_all()
        for path in watched:
            self.assertFalse(
                path.exists() and not before[path],
                f"the probes created {path}",
            )

    def test_probe_documents_are_written_outside_the_repository(self) -> None:
        unit_root = Path(__file__).resolve().parent.parent
        PROBES.completion_actor()
        self.assertEqual(sorted(path.name for path in unit_root.glob("document.json")), [])

    def _status(self) -> str:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return completed.stdout


if __name__ == "__main__":
    unittest.main()
