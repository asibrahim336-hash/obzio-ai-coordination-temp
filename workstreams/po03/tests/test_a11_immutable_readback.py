"""a11-u05 recurrence tests: read back from the declared commit, not the tip.

Frozen hypothesis (dispatch a11-u05): "The ingestion driver materialises a
subordinate branch at its HEAD rather than at the commit each result declares,
so it is not reading back by immutable SHA and a later edit to an artifact makes
an earlier honest result fail verification."

This is not hypothetical.  Cohort a2's unit a2-u01 was really rejected for a
fault_lab.py hash mismatch caused solely by a later commit on the same branch.
The result was honest and its bytes were durable; the driver was reading the
wrong bytes.
"""

from __future__ import annotations

import unittest

import test_a11_support as support


class DeclaredCommitReadbackTests(support.WaveFixture):
    def setUp(self) -> None:
        super().setUp()
        self.write_cohort_ownership()

    def test_an_earlier_result_still_verifies_after_the_branch_advances(self):
        """The a2-u01 rejection, reproduced and then fixed."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        self.publish_unit("h-u01", advance_branch_after=True)

        iw = self.load_ingest_wave()
        outcome = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual([], outcome["rejected"])
        self.assertEqual(["h-u01"], outcome["ingested"])
        self.assertEqual(1, outcome["results_found"])
        self.assertEqual("PARENT_INGESTED", self.state_of("h-u01"))

    def test_the_artifact_is_read_from_the_commit_the_result_named(self):
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        record = self.publish_unit("h-u01", advance_branch_after=True)
        declared_commit = record["artifacts"][0]["content_uri"].split("@")[1].split(":")[0]

        iw = self.load_ingest_wave()
        iw.ingest_cohort(self.cohort, self.branch, complete=False)
        row = [r for r in self.cp.ledger_rows() if r["event"] == "PARENT_INGESTED"][-1]
        verified = row["payload"]["verified_artifacts"][0]
        self.assertEqual(f"git:{declared_commit}:{record['artifacts'][0]['content_uri'].split(':', 2)[2]}",
                         verified["read_from"])
        self.assertEqual(record["artifacts"][0]["sha256"], verified["sha256"])

    def test_a_result_that_names_a_commit_from_another_branch_still_verifies(self):
        """Immutability, not branch membership, is what a locator promises."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        self.publish_unit("h-u01")
        support.git("checkout", "--quiet", "-b", "side-branch", cwd=self.producer)
        self.producer_commit("workstreams/po03/harness/side.txt", b"side\n", "side work")
        support.git("checkout", "--quiet", self.branch, cwd=self.producer)

        iw = self.load_ingest_wave()
        outcome = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual(["h-u01"], outcome["ingested"])

    def test_a_genuinely_corrupt_artifact_is_still_rejected(self):
        """Anchoring to a commit must not become a way of not checking."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        relative = f"{support.OWNED_PREFIX}h-u01.txt"
        artifact_commit = self.producer_commit(relative, b"real bytes\n", "artifact")
        record = self.producer_result(
            "h-u01", relative=relative, body=b"different bytes than were committed\n",
            artifact_commit=artifact_commit,
        )
        import json

        self.producer_commit(
            f"workstreams/po03/control/units/{self.cohort}/h-u01.json",
            (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "result record",
        )
        self.publish()

        iw = self.load_ingest_wave()
        outcome = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual([], outcome["ingested"])
        self.assertEqual(1, len(outcome["rejected"]))
        self.assertIn("hash mismatch", outcome["rejected"][0]["reason"])

    def test_an_unpushed_cohort_yields_no_ingestion(self):
        outcome = self.load_ingest_wave().ingest_cohort(
            self.cohort, "cursor/po03-never-pushed-ed20", complete=False
        )
        self.assertEqual("NOT_PUSHED", outcome["state"])
        self.assertEqual(0, outcome["results_found"])

    def test_records_are_read_without_materialising_a_worktree(self):
        """A committed result needs objects, not a checkout."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        self.publish_unit("h-u01")
        iw = self.load_ingest_wave()
        outcome = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual(["h-u01"], outcome["ingested"])
        self.assertFalse(outcome["worktree_materialised"])
        self.assertEqual([], support.git("worktree", "list", "--porcelain", cwd=self.coordinator)
                         .split("\n\n")[1:])

    def test_an_uncommitted_result_still_gets_a_working_tree(self):
        """An honest failure has no objects to read, so a checkout is needed."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        self.publish_unit("h-u01", state="PROVIDER_COMPLETED_UNCOMMITTED")
        iw = self.load_ingest_wave()
        outcome = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual(["h-u01"], outcome["ingested"])
        self.assertTrue(outcome["worktree_materialised"])
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", self.state_of("h-u01"))

    def test_ingestion_is_idempotent_across_two_runs(self):
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        self.publish_unit("h-u01")
        iw = self.load_ingest_wave()
        first = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        second = iw.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual(["h-u01"], first["ingested"])
        self.assertEqual(["h-u01"], second["duplicates"])
        self.assertEqual(1, len([r for r in self.cp.ledger_rows() if r["event"] == "PARENT_INGESTED"]))


if __name__ == "__main__":
    unittest.main()
