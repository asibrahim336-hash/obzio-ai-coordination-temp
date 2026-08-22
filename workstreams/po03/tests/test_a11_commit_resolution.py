"""a11-u04 recurrence tests: a declared commit must resolve to a real object.

Frozen hypothesis (dispatch a11-u04): "A result_commit_id is accepted as durable
on the strength of being a non-empty string, without ever resolving it against a
remote, so an invented locator passes."  Cohort a2 measured 10 of 10 nonexistent
locators accepted.

The distinction this enforces is the whole point of the custody model: a commit
id is a claim about bytes, and until the object database answers for it, "durable"
is a word a worker typed.
"""

from __future__ import annotations

import unittest

import test_a11_support as support

INVENTED_LOCATORS = [
    "deadbeef",
    "0" * 40,
    "f" * 40,
    "1234567890abcdef1234567890abcdef12345678",
    "does-not-exist-in-any-remote",
    "durable-but-callback-lost",
    "seed-commit-a2-u01",
    "cafebabecafebabecafebabecafebabecafebabe",
    "HEAD~9999",
    "refs/heads/branch-that-was-never-pushed",
]


class CommitResolutionTests(support.ControlPlaneHarness):
    git_backed = True

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")
        self.commit, self.sha, self.size = self.commit_artifact(
            f"{support.OWNED_PREFIX}h-u01.txt", b"durable-result\n"
        )

    def test_a_real_commit_is_admitted(self):
        outcome = self.ingest(
            self.result_doc("h-u01", commit_id=self.commit, write_artifact=False)
        )
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])
        self.assertEqual(self.commit, self.cp.project_units()["h-u01"]["result_commit_id"])

    def test_ten_invented_locators_are_all_rejected(self):
        """a2's exact measurement: 10 of 10 nonexistent locators were accepted."""
        rejected = 0
        for locator in INVENTED_LOCATORS:
            with self.subTest(locator=locator):
                doc = self.result_doc(
                    "h-u01", commit_id=locator, artifact_commit=self.commit, write_artifact=False
                )
                with self.assertRaises(self.cp.ControlPlaneError) as ctx:
                    self.ingest(doc)
                self.assertIn("does not resolve to a commit", str(ctx.exception))
                rejected += 1
        self.assertEqual(len(INVENTED_LOCATORS), rejected)
        self.assertNotIn("PARENT_INGESTED", self.events("h-u01"))

    def test_a_tree_sha_is_not_a_commit(self):
        tree = support.git("rev-parse", "HEAD^{tree}", cwd=self.repo)
        doc = self.result_doc(
            "h-u01", commit_id=tree, artifact_commit=self.commit, write_artifact=False
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)

    def test_a_blob_sha_is_not_a_commit(self):
        blob = support.git(
            "rev-parse", f"HEAD:{support.OWNED_PREFIX}h-u01.txt", cwd=self.repo
        )
        doc = self.result_doc(
            "h-u01", commit_id=blob, artifact_commit=self.commit, write_artifact=False
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)

    def test_a_rejected_locator_is_recorded_durably(self):
        doc = self.result_doc(
            "h-u01", commit_id="f" * 40, artifact_commit=self.commit, write_artifact=False
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(doc)
        self.assertEqual("RECOVERY_REQUIRED", self.state_of("h-u01"))
        row = [r for r in self.cp.ledger_rows() if r["event"] == "RECOVERY_REQUIRED"][-1]
        self.assertIn("does not resolve", row["payload"]["detail"])

    def test_an_honest_failure_is_not_asked_for_a_commit(self):
        """A worker that never committed must still be able to report the truth."""
        doc = self.result_doc(
            "h-u01", state="FAILED_TERMINAL", commit_id=self.commit, write_artifact=True
        )
        outcome = self.ingest(doc)
        self.assertEqual("FAILED_TERMINAL", outcome["ingest_event"])
        self.assertIsNone(self.cp.project_units()["h-u01"]["result_commit_id"])

    def test_resolution_failure_is_reported_not_assumed_away(self):
        """With no repository to ask, a durability claim fails closed."""
        no_repo = self.base / "not-a-repo"
        no_repo.mkdir()
        doc = self.result_doc("h-u01", commit_id=self.commit, write_artifact=False)
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.ingest(doc, repo=no_repo)
        self.assertIn("does not resolve to a commit", str(ctx.exception))


class ResolutionPrimitiveTests(support.ControlPlaneHarness):
    git_backed = True

    def test_resolve_commits_batches_and_pins_the_object_type(self):
        commit, _sha, _size = self.commit_artifact(f"{support.OWNED_PREFIX}x.txt", b"x\n")
        tree = support.git("rev-parse", "HEAD^{tree}", cwd=self.repo)
        resolved = self.cp.resolve_commits([commit, tree, "f" * 40, "", None], self.repo)
        self.assertTrue(resolved[commit])
        self.assertFalse(resolved[tree])
        self.assertFalse(resolved["f" * 40])
        self.assertNotIn("", resolved)
        self.assertNotIn(None, resolved)

    def test_resolution_outside_a_repository_is_false_not_an_exception(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.assertFalse(self.cp.commit_resolves("f" * 40, outside))
        self.assertIsNone(self.cp.git_repo_root(outside / "missing"))

    def test_read_blob_returns_exact_bytes(self):
        body = b"bytes\x00with\xffnon-utf8\n"
        commit, sha, size = self.commit_artifact(f"{support.OWNED_PREFIX}b.bin", body)
        raw = self.cp.read_blob(commit, f"{support.OWNED_PREFIX}b.bin", self.repo)
        self.assertEqual(body, raw)
        self.assertEqual(size, len(raw))
        self.assertEqual(sha, support.sha256_bytes(raw))

    def test_read_blob_of_a_path_absent_from_the_commit_is_none(self):
        commit, _sha, _size = self.commit_artifact(f"{support.OWNED_PREFIX}a.txt", b"a\n")
        self.assertIsNone(self.cp.read_blob(commit, f"{support.OWNED_PREFIX}nope.txt", self.repo))


if __name__ == "__main__":
    unittest.main()
