"""a11-u07 recurrence tests: a rejection must leave a durable trace.

Frozen hypothesis (dispatch a11-u07): "Rejecting a corrupt or missing artifact
raises an exception but records nothing, so the unit is left in whatever state it
was in and the rejection is invisible to recovery."  Cohort a2 measured 20 of 20
rejections leaving no recovery state.

An exception is a message to one caller.  If that caller is a driver loop which
appends the reason to a list and moves on, the refusal exists only in that
process's memory: the ledger still shows a healthy unit, and a parent that
restarts has no way to learn that a result was ever refused.  So every
rejection writes RECOVERY_REQUIRED carrying its reason before the exception
propagates.  The table below enumerates twenty distinct rejection classes --
a2's exact measurement -- and each one is asserted to leave that trace.

The second half of the unit is that hashing once at ingestion time proves
nothing later.  ``rehash_committed_artifacts`` re-reads every ingested artifact
from the commit it was ingested from and compares bytes again.

Note on what "post-commit corruption" can actually mean: a git commit id is a
hash over its content, so no attacker can make a fixed commit id yield
different artifact bytes.  Real corruption therefore shows up either as an
object that has become unreadable (loss, a failed transfer, a pruned object
store) or as a ledger record that no longer agrees with the object store.  Both
are exercised; byte substitution at a fixed commit id is not simulated, because
it is not reachable.
"""

from __future__ import annotations

import unittest

import test_a11_support as support

#: Pinned literally rather than read off the module, so this file can be run
#: against a pre-fix control plane that has no such constant.
MANIFEST_SCHEME = "obzio-manifest-sha256"


class RejectionRecordingTests(support.ControlPlaneHarness):
    """Every way a result can be refused, and the trace each one must leave."""

    git_backed = True

    #: (label, method name).  Each mutation is a method so it binds to the
    #: fresh harness it is run against rather than to the fixture that declared
    #: it: a rejection class must be provable on a ledger containing nothing
    #: but that one rejection.
    CASES = (
        ("invalid result contract", "_break_contract"),
        ("no immutable dispatch record", "_remove_dispatch"),
        ("wrong immutable input manifest", "_wrong_input_manifest"),
        ("wrong acceptance contract", "_wrong_acceptance_contract"),
        ("unissued higher fence token", "_unissued_fence"),
        ("stale lower fence token", "_stale_fence"),
        ("artifact outside the allowlist", "_outside_allowlist"),
        ("artifact the owner does not own", "_not_owned"),
        ("path traversal in a locator", "_traversal"),
        ("unresolvable result commit", "_unresolvable_result_commit"),
        ("tree sha instead of a commit", "_tree_instead_of_commit"),
        ("blob sha instead of a commit", "_blob_instead_of_commit"),
        ("artifact locator naming no commit", "_locator_without_commit"),
        ("unresolvable artifact commit", "_unresolvable_artifact_commit"),
        ("artifact absent from the declared commit", "_absent_at_commit"),
        ("artifact hash mismatch", "_hash_mismatch"),
        ("artifact byte count mismatch", "_byte_mismatch"),
        ("manifest that does not derive", "_manifest_does_not_derive"),
        ("uncommitted artifact missing on disk", "_uncommitted_missing"),
        ("uncommitted artifact corrupt on disk", "_uncommitted_corrupt"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")
        self.body = b"durable-result\n"
        self.relative = f"{support.OWNED_PREFIX}h-u01.txt"
        self.commit, self.sha, self.size = self.commit_artifact(self.relative, self.body)

    # -- fixture helpers --------------------------------------------------

    def good(self):
        """A result that would be admitted unmodified."""
        return self.result_doc(
            "h-u01", commit_id=self.commit, body=self.body, write_artifact=False
        )

    def sibling(self):
        """A second, independent harness with its own ledger and repository."""
        other = type(self)(self._testMethodName)
        other.setUp()
        self.addCleanup(other.doCleanups)
        return other

    def uncommit(self, doc, state: str) -> None:
        """Restate the document as work that was never durably committed."""
        doc["obzio_state"] = state
        doc["provider_state"] = "UNKNOWN"
        doc["result_transaction"].update(
            state="RESERVED",
            manifest_uri=None,
            manifest_sha256=None,
            committed_at=None,
            verified_at=None,
            result_commit_id=None,
        )
        doc["artifacts"][0]["readback_verified_at"] = None

    def locator(self, doc, relative: str, commit: str | None = None) -> None:
        commit = self.commit if commit is None else commit
        doc["artifacts"][0]["content_uri"] = f"git:branch@{commit}:{relative}"

    # -- the twenty rejection classes ------------------------------------

    def _break_contract(self, doc) -> None:
        doc["protocol_version"] = "OBZIO-TRANSACTIONAL-RESULT-v0"

    def _remove_dispatch(self, doc) -> None:
        (self.cp.DISPATCH_DIR / "h-u01.json").unlink()

    def _wrong_input_manifest(self, doc) -> None:
        doc["immutable_input_manifest_sha256"] = "b" * 64

    def _wrong_acceptance_contract(self, doc) -> None:
        doc["acceptance_contract_sha256"] = "c" * 64

    def _unissued_fence(self, doc) -> None:
        doc["attempt"]["fence_token"] = 99

    def _stale_fence(self, doc) -> None:
        self.cp.append_event(
            "h-u01",
            "LEASED",
            actor="coordinator",
            provider_state="RUNNING",
            fence_token=2,
            payload={
                "lease_id": "lease-h-u01-2",
                "worker_id": support.OWNER,
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        doc["attempt"]["fence_token"] = 1

    def _outside_allowlist(self, doc) -> None:
        self.locator(doc, "modules/operators/not-in-scope.json")

    def _not_owned(self, doc) -> None:
        self.locator(doc, "workstreams/po03/review/harness/not-mine.json")

    def _traversal(self, doc) -> None:
        self.locator(doc, "workstreams/po03/../../etc/passwd")

    def _unresolvable_result_commit(self, doc) -> None:
        doc["result_transaction"]["result_commit_id"] = "f" * 40

    def _tree_instead_of_commit(self, doc) -> None:
        doc["result_transaction"]["result_commit_id"] = support.git(
            "rev-parse", "HEAD^{tree}", cwd=self.repo
        )

    def _blob_instead_of_commit(self, doc) -> None:
        doc["result_transaction"]["result_commit_id"] = support.git(
            "rev-parse", f"HEAD:{self.relative}", cwd=self.repo
        )

    def _locator_without_commit(self, doc) -> None:
        doc["artifacts"][0]["content_uri"] = f"file:{self.relative}"

    def _unresolvable_artifact_commit(self, doc) -> None:
        self.locator(doc, self.relative, commit="e" * 40)

    def _absent_at_commit(self, doc) -> None:
        self.locator(doc, f"{support.OWNED_PREFIX}never-committed.txt")

    def _hash_mismatch(self, doc) -> None:
        doc["artifacts"][0]["sha256"] = "0" * 64

    def _byte_mismatch(self, doc) -> None:
        doc["artifacts"][0]["bytes"] += 1
        doc["result_transaction"]["total_bytes"] += 1

    def _manifest_does_not_derive(self, doc) -> None:
        doc["result_transaction"]["manifest_uri"] = f"{MANIFEST_SCHEME}:{'0' * 64}"
        doc["result_transaction"]["manifest_sha256"] = "0" * 64

    def _uncommitted_missing(self, doc) -> None:
        self.uncommit(doc, "PROVIDER_COMPLETED_UNCOMMITTED")
        doc["artifacts"][0]["content_uri"] = f"file:{support.OWNED_PREFIX}absent.txt"
        (self.repo / self.relative).unlink()

    def _uncommitted_corrupt(self, doc) -> None:
        self.uncommit(doc, "PROVIDER_COMPLETED_UNCOMMITTED")
        doc["artifacts"][0]["content_uri"] = f"file:{self.relative}"
        (self.repo / self.relative).write_bytes(b"tampered after hashing\n")

    # -- assertions -------------------------------------------------------

    def assert_recorded(self, harness, label: str) -> dict:
        rows = [r for r in harness.cp.ledger_rows() if r["event"] == "RECOVERY_REQUIRED"]
        self.assertTrue(rows, f"{label}: the rejection left no durable trace")
        row = rows[-1]
        payload = row["payload"]
        self.assertEqual("coordinator", row["actor"], f"{label}: recorded by the wrong actor")
        self.assertEqual("ingest_result", payload.get("rejected_by"), label)
        self.assertTrue(
            isinstance(payload.get("detail"), str) and payload["detail"].strip(),
            f"{label}: recorded without a reason",
        )
        self.assertEqual(
            "RECOVERY_REQUIRED",
            harness.state_of("h-u01"),
            f"{label}: the unit was left in its previous state",
        )
        return payload

    def test_the_case_table_covers_a2s_twenty_measured_rejections(self):
        self.assertEqual(20, len(self.CASES))
        self.assertEqual(20, len({label for label, _ in self.CASES}))

    def test_twenty_rejection_classes_each_leave_recovery_state(self):
        recorded = 0
        for label, method in self.CASES:
            with self.subTest(case=label):
                harness = self.sibling()
                doc = harness.good()
                getattr(harness, method)(doc)
                with self.assertRaises(harness.cp.ControlPlaneError):
                    harness.ingest(doc)
                self.assert_recorded(harness, label)
                recorded += 1
        self.assertEqual(20, recorded)

    def test_the_recorded_reason_names_what_was_wrong(self):
        expectations = {
            "_hash_mismatch": "hash mismatch",
            "_unresolvable_result_commit": "does not resolve to a commit",
            "_wrong_input_manifest": "immutable input manifest",
            "_wrong_acceptance_contract": "acceptance contract",
            "_break_contract": "contract",
            "_remove_dispatch": "dispatch record",
            "_unissued_fence": "never issued",
            "_absent_at_commit": "missing on read-back",
        }
        for method, expected in expectations.items():
            with self.subTest(case=method):
                harness = self.sibling()
                doc = harness.good()
                getattr(harness, method)(doc)
                with self.assertRaises(harness.cp.ControlPlaneError):
                    harness.ingest(doc)
                payload = self.assert_recorded(harness, method)
                self.assertIn(expected, payload["detail"])

    def test_a_restarted_parent_sees_the_rejection(self):
        """The trace has to survive the process that made it."""
        doc = self.good()
        doc["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)
        fresh = self.fresh_control_plane()
        self.assertEqual("RECOVERY_REQUIRED", fresh.project_units()["h-u01"]["obzio_state"])
        scan = fresh.scan_recovery(repo=self.repo)
        self.assertIn("h-u01", scan["resumable_units"])
        self.assertTrue(scan["recovery_required"])

    def test_the_rejection_is_visible_in_the_materialised_registry(self):
        doc = self.good()
        doc["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)
        registry = self.cp.REGISTRY_PATH.read_text(encoding="utf-8")
        self.assertIn("RECOVERY_REQUIRED", registry)

    def test_a_rejection_does_not_admit_the_result(self):
        doc = self.good()
        doc["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)
        self.assertNotIn("PARENT_INGESTED", self.events("h-u01"))

    def test_a_corrected_result_is_admitted_after_a_rejection(self):
        """Recovery state must not become a dead end."""
        doc = self.good()
        doc["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)
        outcome = self.ingest(self.good())
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])
        self.assertEqual("PARENT_INGESTED", self.state_of("h-u01"))

    def test_a_successful_ingestion_records_no_rejection(self):
        self.ingest(self.good())
        self.assertNotIn("RECOVERY_REQUIRED", self.events("h-u01"))

    def test_an_unknown_unit_is_refused_and_the_limit_is_honest(self):
        """A unit with no ledger history has nothing to record a rejection against.

        This is the one rejection that cannot leave a per-unit trace, because
        there is no unit.  It is asserted rather than papered over, so the
        boundary is documented instead of discovered later.
        """
        self.dispatch_record("h-u99")
        doc = self.result_doc("h-u99", commit_id=self.commit, body=self.body, write_artifact=False)
        with self.assertRaises(self.cp.ControlPlaneError) as caught:
            self.ingest(doc)
        self.assertIn("unknown unit", str(caught.exception))
        self.assertEqual([], [r for r in self.cp.ledger_rows() if r["unit_id"] == "h-u99"])


class RehashSweepTests(support.ControlPlaneHarness):
    """Hashing once at ingestion says nothing about the object store later."""

    git_backed = True

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")
        self.body = b"durable-result\n"
        self.relative = f"{support.OWNED_PREFIX}h-u01.txt"
        self.commit, self.sha, self.size = self.commit_artifact(self.relative, self.body)
        self.ingest(
            self.result_doc(
                "h-u01", commit_id=self.commit, body=self.body, write_artifact=False
            )
        )

    def drop_objects(self) -> None:
        """Make the artifact genuinely unreadable in this object database."""
        support.git("gc", "--quiet", "--prune=now", cwd=self.repo)
        objects = self.repo / ".git" / "objects"
        for child in objects.iterdir():
            if child.name in {"info"}:
                continue
            for item in child.rglob("*"):
                if item.is_file():
                    item.unlink()

    def test_a_clean_sweep_reports_every_artifact_verified(self):
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual("OK", report["status"])
        self.assertEqual(1, report["units_swept"])
        self.assertEqual(1, report["artifacts_rehashed"])
        self.assertEqual([], report["corrupt"])
        self.assertEqual([], report["unreadable"])
        self.assertFalse(report["recovery_required"])
        self.assertNotIn("RECOVERY_REQUIRED", self.events("h-u01"))

    def test_a_clean_sweep_appends_nothing(self):
        before = len(self.cp.ledger_rows())
        self.cp.rehash_committed_artifacts(repo=self.repo)
        self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(before, len(self.cp.ledger_rows()))

    def test_an_object_that_has_become_unreadable_is_detected(self):
        self.drop_objects()
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(["h-u01"], [item["unit_id"] for item in report["unreadable"]])
        self.assertTrue(report["recovery_required"])
        self.assertIn("RECOVERY_REQUIRED", self.events("h-u01"))
        row = [r for r in self.cp.ledger_rows() if r["event"] == "RECOVERY_REQUIRED"][-1]
        self.assertEqual("rehash_sweep", row["payload"]["rejected_by"])
        self.assertIn(self.relative, row["payload"]["detail"])
        self.assertEqual("RECOVERY_REQUIRED", self.state_of("h-u01"))

    def test_the_sweep_is_idempotent_over_the_same_corruption(self):
        self.drop_objects()
        self.cp.rehash_committed_artifacts(repo=self.repo)
        after_first = len(self.cp.ledger_rows())
        second = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(after_first, len(self.cp.ledger_rows()))
        self.assertTrue(second["recovery_required"])
        self.assertEqual(1, len([r for r in self.cp.ledger_rows() if r["event"] == "RECOVERY_REQUIRED"]))

    def test_a_recorded_hash_that_disagrees_with_the_object_store_is_detected(self):
        """Defence in depth: the ledger's own record is re-checked, not trusted."""
        rows = self.cp.ledger_rows()
        target = next(r for r in rows if r["event"] == "PARENT_INGESTED")
        target["payload"]["verified_artifacts"][0]["sha256"] = "0" * 64
        previous = rows[target["seq"] - 2]["row_sha256"] if target["seq"] > 1 else self.cp.GENESIS_HASH
        for row in rows[target["seq"] - 1:]:
            row["prev_sha256"] = previous
            body = {k: v for k, v in row.items() if k != "row_sha256"}
            row["row_sha256"] = self.cp.sha256_text(self.cp.canonical(body))
            previous = row["row_sha256"]
        self.cp.LEDGER_PATH.write_text(
            "".join(self.cp.canonical(row) + "\n" for row in rows), encoding="utf-8"
        )
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(["h-u01"], [item["unit_id"] for item in report["corrupt"]])
        self.assertTrue(report["recovery_required"])
        self.assertIn("RECOVERY_REQUIRED", self.events("h-u01"))

    def test_the_sweep_reports_honestly_when_it_cannot_resolve_anything(self):
        outside = self.base / "not-a-repo"
        outside.mkdir()
        report = self.cp.rehash_committed_artifacts(repo=outside)
        self.assertFalse(report["commit_resolution_available"])
        self.assertEqual("NOT_SUPPORTED", report["status"])
        self.assertEqual(0, report["artifacts_rehashed"])
        self.assertNotIn("RECOVERY_REQUIRED", self.events("h-u01"))

    def test_the_sweep_covers_only_ingested_units(self):
        self.seed("h-u02")
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(["h-u01"], report["units"])

    def test_an_uncommitted_result_is_not_swept(self):
        """Nothing was committed, so there is no object to re-hash."""
        self.seed("h-u03")
        doc = self.result_doc(
            "h-u03", state="PROVIDER_COMPLETED_UNCOMMITTED", body=b"draft\n"
        )
        doc["artifacts"][0]["content_uri"] = f"file:{support.OWNED_PREFIX}h-u03.txt"
        self.ingest(doc)
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(["h-u01"], report["units"])

    def test_a_legacy_ingestion_row_is_reported_not_assumed_verified(self):
        """Rows written before the immutable read-back rule name no commit.

        The live ledger already holds these.  A sweep that counted them as
        verified would report clean custody it never checked, so they are
        reported as un-sweepable and left alone: the hardened rule applies to
        results ingested from here on.
        """
        self.seed("h-u04")
        self.forge_row(
            "h-u04",
            "PARENT_INGESTED",
            "coordinator",
            {
                "result_commit_id": self.commit,
                "verified_artifacts": [
                    {"logical_name": "h-u04.txt", "sha256": self.sha, "bytes": self.size}
                ],
            },
        )
        report = self.cp.rehash_committed_artifacts(repo=self.repo)
        self.assertEqual(["h-u04"], report["units_not_immutably_located"])
        self.assertEqual(1, report["artifacts_rehashed"], "only h-u01 is re-hashable")
        self.assertEqual(["h-u01"], sorted({item["unit_id"] for item in report["verified"]}))
        self.assertFalse(report["recovery_required"])
        self.assertNotIn("RECOVERY_REQUIRED", self.events("h-u04"))

    def test_the_cli_exposes_the_sweep(self):
        self.assertEqual(0, self.cp.main(["rehash", "--repo", str(self.repo)]))
        self.drop_objects()
        self.assertEqual(2, self.cp.main(["rehash", "--repo", str(self.repo)]))


if __name__ == "__main__":
    unittest.main()
