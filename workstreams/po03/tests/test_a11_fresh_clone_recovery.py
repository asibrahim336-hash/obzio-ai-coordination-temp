"""a11-u09 recurrence tests: recover committed results from a fresh clone.

Frozen hypothesis (dispatch a11-u09): "A fresh clone cannot discover subordinate
result branches, so total runtime loss loses committed results in practice even
though the bytes exist on the remote."  Cohort a2 measured 0 of 10 committed
results recovered from fresh clones.

Two separate things have to be true.  The clone must be able to *find* the
branches -- which means reading committed configuration and confirming it
against the remote's refs, not guessing at names -- and it must then verify the
bytes it finds, at the commit each artifact declared, with no working tree and
no local history to lean on.

Discovery deliberately refuses to ingest from a branch that committed
configuration never declared, even when the remote is offering it.  A driver
that ingests whatever it finds pushed is a driver that can be fed a result by
anybody with push access.  Undeclared branches are reported instead.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import test_a11_support as support

#: a2's measurement was over ten committed results.
COHORT_UNITS = tuple(f"h-u{index:02d}" for index in range(1, 11))


class FreshCloneFixture(support.WaveFixture):
    """A remote holding ten published results, and clones that know nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.write_cohort_ownership()
        self.bodies = {
            unit_id: f"durable result for {unit_id}\n".encode("utf-8") for unit_id in COHORT_UNITS
        }
        self.records = {}

    def publish_ten(self) -> None:
        for unit_id in COHORT_UNITS:
            self.seed_unit_events(unit_id)
            self.records[unit_id] = self.publish_unit(unit_id, body=self.bodies[unit_id])

    def clone(self, name: str) -> Path:
        """A clone with no local state beyond the remote's default branch."""
        target = self.base / name
        subprocess.run(
            ["git", "clone", "--quiet", str(self.remote), str(target)],
            check=True,
            capture_output=True,
        )
        support.git("config", "user.name", "PO03 A11 Recovery", cwd=target)
        support.git("config", "user.email", "po03-a11@example.invalid", cwd=target)
        return target

    def driver_for(self, clone: Path, cp=None):
        module = support.load_module(support.INGEST_WAVE_PATH, "iw")
        module.REPO_ROOT = clone
        cp = cp if cp is not None else self.cp
        for attribute in (
            "LEDGER_PATH",
            "REGISTRY_PATH",
            "RECOVERY_PATH",
            "DISPATCH_DIR",
            "PATH_OWNERSHIP_PATH",
        ):
            setattr(module.CP, attribute, getattr(cp, attribute))
        module.CP.REPO_ROOT = clone
        return module

    def local_refs(self, clone: Path) -> list[str]:
        listing = support.git("for-each-ref", "--format=%(refname)", cwd=clone)
        return [line for line in listing.splitlines() if line]


class DiscoveryTests(FreshCloneFixture):
    def test_a_fresh_clone_has_no_local_knowledge_of_the_result_branch(self):
        """The premise of the unit, stated precisely rather than assumed.

        A clone does receive the remote's refs, so the missing thing is not the
        bytes: it is any local record of *which* refs carry subordinate results
        and any checkout containing them.  Discovery has to establish that from
        committed configuration.
        """
        self.publish_ten()
        clone = self.clone("audit")
        refs = self.local_refs(clone)
        self.assertNotIn(f"refs/heads/{self.branch}", refs)
        self.assertEqual(
            [], [ref for ref in refs if ref.startswith("refs/heads/") and self.cohort in ref]
        )
        self.assertFalse(
            (clone / "workstreams" / "po03" / "control" / "units" / self.cohort).exists(),
            "no result record is present in the fresh checkout",
        )

    def test_discovery_enumerates_declared_branches_and_confirms_them_remotely(self):
        self.publish_ten()
        driver = self.driver_for(self.clone("discover"))
        found = driver.discover_result_branches()
        self.assertIn(self.branch, found["branches"])
        entry = found["branches"][self.branch]
        self.assertEqual([self.cohort], entry["cohorts"])
        self.assertIn("path-ownership", entry["sources"])
        self.assertTrue(entry["on_remote"])
        self.assertEqual(
            support.git("rev-parse", self.branch, cwd=self.producer), entry["remote_sha"]
        )

    def test_a_dispatch_result_slot_is_a_discovery_source_of_its_own(self):
        """Configuration, not convention: the slot names the branch per unit."""
        self.publish_ten()
        self.cp.write_json(
            self.cp.PATH_OWNERSHIP_PATH,
            {"owners": {"coordinator": {"owned_prefixes": ["workstreams/po03/control/"]}}},
        )
        driver = self.driver_for(self.clone("slots"))
        found = driver.discover_result_branches()
        self.assertIn(self.branch, found["branches"])
        self.assertIn("dispatch-result-slot", found["branches"][self.branch]["sources"])

    def test_a_declared_branch_the_remote_does_not_have_is_reported(self):
        self.dispatch_record("h-u01", self.producer_owner)
        self.cp.write_json(
            self.cp.PATH_OWNERSHIP_PATH,
            {
                "owners": {
                    "coordinator": {"owned_prefixes": ["workstreams/po03/control/"]},
                    "po03-worker-zz": {
                        "owned_prefixes": ["workstreams/po03/zz/"],
                        "branch": "cursor/po03-zz-never-pushed-ed20",
                    },
                }
            },
        )
        driver = self.driver_for(self.clone("missing"))
        found = driver.discover_result_branches()
        self.assertIn("cursor/po03-zz-never-pushed-ed20", found["declared_but_absent"])
        self.assertFalse(found["branches"]["cursor/po03-zz-never-pushed-ed20"]["on_remote"])

    def test_an_undeclared_remote_branch_is_reported_and_not_ingested(self):
        """Push access must not be the same thing as custody authority."""
        self.publish_ten()
        support.git("push", "--quiet", "origin", "HEAD:cursor/po03-stranger-ed20", cwd=self.producer)
        driver = self.driver_for(self.clone("stranger"))
        found = driver.discover_result_branches()
        self.assertIn("cursor/po03-stranger-ed20", found["undeclared_on_remote"])
        self.assertNotIn("cursor/po03-stranger-ed20", found["branches"])

    def test_discovery_reads_the_remote_without_writing_the_ledger(self):
        self.publish_ten()
        driver = self.driver_for(self.clone("readonly"))
        before = self.cp.LEDGER_PATH.read_text(encoding="utf-8")
        driver.discover_result_branches()
        self.assertEqual(before, self.cp.LEDGER_PATH.read_text(encoding="utf-8"))


class FreshCloneRecoveryTests(FreshCloneFixture):
    def recovered_hashes(self) -> dict[str, str]:
        rows = [row for row in self.cp.ledger_rows() if row["event"] == "PARENT_INGESTED"]
        return {
            row["unit_id"]: row["payload"]["verified_artifacts"][0]["sha256"] for row in rows
        }

    def test_ten_committed_results_are_recovered_from_a_fresh_clone(self):
        """a2 measured 0 of 10.  All ten, with the bytes checked."""
        self.publish_ten()
        clone = self.clone("recovery")
        driver = self.driver_for(clone)
        report = driver.recover_from_remote()
        self.assertEqual(10, report["totals"]["results_found"])
        self.assertEqual(10, report["totals"]["recovered"])
        self.assertEqual(0, report["totals"]["rejected"])
        recovered = self.recovered_hashes()
        self.assertEqual(set(COHORT_UNITS), set(recovered))
        for unit_id in COHORT_UNITS:
            with self.subTest(unit=unit_id):
                self.assertEqual(support.sha256_bytes(self.bodies[unit_id]), recovered[unit_id])
                self.assertEqual("PARENT_INGESTED", self.state_of(unit_id))

    def test_the_cohort_driver_alone_already_recovers_this_shape(self):
        """Kept honest: this passes against the pre-fix driver as well.

        a2 measured 0 of 10 recovered from a fresh clone, but the cause was the
        absence of a discovery pass, not an inability to verify bytes once a
        branch was named.  Asserting that here stops this unit from claiming a
        repair to something that was not broken.
        """
        self.publish_ten()
        driver = self.driver_for(self.clone("baseline"))
        outcome = driver.ingest_cohort(self.cohort, self.branch, complete=False)
        self.assertEqual(10, outcome["results_found"])
        self.assertEqual(sorted(COHORT_UNITS), sorted(outcome["ingested"]))

    def test_recovery_verifies_bytes_at_the_declared_commit_not_the_tip(self):
        self.publish_ten()
        # A later commit rewrites every artifact.  The earlier honest results
        # must still recover, because they named immutable commits.
        for unit_id in COHORT_UNITS:
            self.producer_commit(
                f"{support.OWNED_PREFIX}{unit_id}.txt", b"a later unit edited this\n", "later work"
            )
        self.publish()
        driver = self.driver_for(self.clone("advanced"))
        report = driver.recover_from_remote()
        self.assertEqual(10, report["totals"]["recovered"])
        for unit_id in COHORT_UNITS:
            self.assertEqual(
                support.sha256_bytes(self.bodies[unit_id]), self.recovered_hashes()[unit_id]
            )

    def test_a_corrupt_result_is_refused_while_the_rest_recover(self):
        """Recovery must not become a way of not checking."""
        self.publish_ten()
        unit_id = "h-u04"
        relative = f"{support.OWNED_PREFIX}{unit_id}.txt"
        commit = self.producer_commit(relative, b"real bytes\n", "honest artifact")
        record = self.producer_result(
            unit_id, relative=relative, body=b"bytes that were never committed\n",
            artifact_commit=commit,
        )
        self.producer_commit(
            f"workstreams/po03/control/units/{self.cohort}/{unit_id}.json",
            (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "overwrite the result record",
        )
        self.publish()
        driver = self.driver_for(self.clone("mixed"))
        report = driver.recover_from_remote()
        self.assertEqual(9, report["totals"]["recovered"])
        self.assertEqual(1, report["totals"]["rejected"])
        self.assertNotIn(unit_id, self.recovered_hashes())
        self.assertEqual("RECOVERY_REQUIRED", self.state_of(unit_id))

    def test_an_artifact_on_another_branch_is_fetched_before_it_is_judged(self):
        """A locator carries its branch; a fresh clone has to use it."""
        self.seed_unit_events("h-u01")
        self.dispatch_record("h-u01", self.producer_owner)
        side = "cursor/po03-h-side-ed20"
        support.git("checkout", "--quiet", "-b", "side", cwd=self.producer)
        relative = f"{support.OWNED_PREFIX}h-u01.txt"
        body = b"committed on a side branch\n"
        artifact_commit = self.producer_commit(relative, body, "side artifact")
        support.git("push", "--quiet", "origin", f"HEAD:{side}", cwd=self.producer)
        support.git("checkout", "--quiet", self.branch, cwd=self.producer)
        record = self.producer_result(
            "h-u01", relative=relative, body=body, artifact_commit=artifact_commit
        )
        record["artifacts"][0]["content_uri"] = f"git:{side}@{artifact_commit}:{relative}"
        self.producer_commit(
            f"workstreams/po03/control/units/{self.cohort}/h-u01.json",
            (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "result record naming a side branch",
        )
        self.publish()
        driver = self.driver_for(self.clone("cross-branch"))
        report = driver.recover_from_remote()
        self.assertEqual([], [item for cohort in report["cohorts"] for item in cohort["rejected"]])
        self.assertEqual(1, report["totals"]["recovered"])
        self.assertIn(side, report["fetched_branches"])

    def test_recovery_needs_no_working_tree_for_committed_results(self):
        self.publish_ten()
        driver = self.driver_for(self.clone("no-tree"))
        report = driver.recover_from_remote()
        self.assertTrue(all(not cohort["worktree_materialised"] for cohort in report["cohorts"]))

    def test_a_second_fresh_clone_recovers_idempotently(self):
        self.publish_ten()
        first = self.driver_for(self.clone("first")).recover_from_remote()
        self.assertEqual(10, first["totals"]["recovered"])
        second = self.driver_for(self.clone("second")).recover_from_remote()
        self.assertEqual(0, second["totals"]["recovered"])
        self.assertEqual(10, second["totals"]["duplicates"])
        rows = [row for row in self.cp.ledger_rows() if row["event"] == "PARENT_INGESTED"]
        self.assertEqual(10, len(rows), "one ingestion row per unit, not two")

    def test_a_totally_independent_coordinator_recovers_the_same_ten(self):
        """No shared local state at all: new clone, new ledger, new projections."""
        self.publish_ten()
        fresh_cp = self.fresh_control_plane()
        fresh_cp.LEDGER_PATH = self.base / "restored" / "events" / "ledger.jsonl"
        fresh_cp.REGISTRY_PATH = self.base / "restored" / "registry.jsonl"
        fresh_cp.RECOVERY_PATH = self.base / "restored" / "recovery.json"
        fresh_cp.DISPATCH_DIR = self.base / "restored" / "dispatch"
        fresh_cp.PATH_OWNERSHIP_PATH = self.base / "restored" / "path-ownership.json"
        # Committed configuration is what survives runtime loss: the roster, the
        # immutable dispatch records, and the units they created.
        for path in sorted(self.cp.DISPATCH_DIR.glob("*.json")):
            fresh_cp.write_json(
                fresh_cp.DISPATCH_DIR / path.name,
                json.loads(path.read_text(encoding="utf-8")),
            )
        fresh_cp.write_json(
            fresh_cp.PATH_OWNERSHIP_PATH,
            json.loads(self.cp.PATH_OWNERSHIP_PATH.read_text(encoding="utf-8")),
        )
        for unit_id in COHORT_UNITS:
            fresh_cp.append_event(
                unit_id, "CREATED", actor="coordinator", provider_state="QUEUED",
                payload={"owner": self.producer_owner},
            )
            fresh_cp.append_event(
                unit_id, "LEASED", actor="coordinator", provider_state="RUNNING", fence_token=1,
                payload={
                    "lease_id": f"lease-{unit_id}-1",
                    "worker_id": self.producer_owner,
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        driver = self.driver_for(self.clone("independent"), cp=fresh_cp)
        report = driver.recover_from_remote()
        self.assertEqual(10, report["totals"]["recovered"])
        units = fresh_cp.project_units()
        for unit_id in COHORT_UNITS:
            self.assertEqual("PARENT_INGESTED", units[unit_id]["obzio_state"])
        self.assertEqual([], fresh_cp.verify_chain(fresh_cp.ledger_rows()))

    def test_an_unpublished_result_recovers_nothing_rather_than_being_invented(self):
        """Provider completion is not result custody."""
        self.dispatch_record("h-u01", self.producer_owner)
        self.seed_unit_events("h-u01")
        driver = self.driver_for(self.clone("unpublished"))
        report = driver.recover_from_remote()
        self.assertEqual(0, report["totals"]["results_found"])
        self.assertEqual(0, report["totals"]["recovered"])
        self.assertEqual("LEASED", self.state_of("h-u01"))

    def test_a_declared_branch_absent_from_the_remote_yields_no_ingestion(self):
        self.publish_ten()
        ownership = json.loads(self.cp.PATH_OWNERSHIP_PATH.read_text(encoding="utf-8"))
        ownership["owners"]["po03-worker-zz"] = {
            "owned_prefixes": ["workstreams/po03/zz/"],
            "branch": "cursor/po03-zz-never-pushed-ed20",
        }
        self.cp.write_json(self.cp.PATH_OWNERSHIP_PATH, ownership)
        driver = self.driver_for(self.clone("absent"))
        report = driver.recover_from_remote()
        self.assertEqual(["zz"], report["totals"]["not_pushed"])
        self.assertEqual(10, report["totals"]["recovered"])
        self.assertIn(
            "cursor/po03-zz-never-pushed-ed20", report["discovery"]["declared_but_absent"]
        )

    def test_the_cli_exposes_discovery_and_recovery(self):
        self.publish_ten()
        driver = self.driver_for(self.clone("cli"))
        self.assertEqual(0, driver.main(["--discover"]))
        self.assertEqual([], [row for row in self.cp.ledger_rows() if row["event"] == "PARENT_INGESTED"])
        self.assertEqual(0, driver.main(["--recover"]))
        self.assertEqual(10, len([r for r in self.cp.ledger_rows() if r["event"] == "PARENT_INGESTED"]))


if __name__ == "__main__":
    unittest.main()
