"""a11-u06 recurrence tests: a declared locator must resolve to bytes.

Frozen hypothesis (dispatch a11-u06): "The result emitter stamps the commit that
exists at emission time, but the result record itself is committed afterwards, so
every result declares a commit that does not contain it."  Cohort a6 found five
such discrepancies independently, in a3-u01, a7-u01, a7-u02, a6-u01 and a6-u02.

A record cannot name the commit that contains it: the commit's tree covers the
record, and the record would have to contain that commit's own id.  The
self-reference is therefore removed rather than repaired.  What replaces it:

* ``result_commit_id`` names the commit that actually contains every declared
  artifact, and the emitter proves that by reading each artifact back out of
  that commit before writing the record.
* ``manifest_uri`` becomes ``obzio-manifest-sha256:<hash>``, a derivation a
  reader can recompute from the artifacts at ``result_commit_id`` instead of a
  git path that never existed.
* the record's own immutable locator is published by a second ``--seal`` pass
  in a sidecar, which names the commit that contains the record.  A sidecar can
  name the record because nothing names the sidecar.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_a11_support as support

UNIT = "h-u01"
ARTIFACT = f"{support.OWNED_PREFIX}{UNIT}.txt"


class EmitterLocatorTests(support.ControlPlaneHarness):
    git_backed = True

    def setUp(self) -> None:
        super().setUp()
        # make_result.py reads the dispatch record from the worktree it is
        # pointed at, so the dispatch directory has to live inside the repo.
        self.cp.DISPATCH_DIR = self.repo / "workstreams/po03/control/dispatch"
        self.dispatch = self.dispatch_record(UNIT, support.OWNER)
        self.dispatch["result_slot"]["unit_record"] = (
            f"workstreams/po03/control/units/h/{UNIT}.json"
        )
        self.cp.write_json(self.cp.DISPATCH_DIR / f"{UNIT}.json", self.dispatch)
        self.body = b"durable artifact bytes\n"
        (self.repo / ARTIFACT).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / ARTIFACT).write_bytes(self.body)
        self.artifact_commit = support.commit_all(self.repo, "artifact and dispatch")

    def emit(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(support.MAKE_RESULT_PATH),
                UNIT,
                "--root",
                str(self.repo),
                "--provider-run-id",
                "po03-a11-harness",
                "--artifact",
                ARTIFACT,
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def record_path(self) -> Path:
        return self.repo / self.dispatch["result_slot"]["unit_record"]

    def record(self) -> dict:
        return json.loads(self.record_path().read_text(encoding="utf-8"))

    # -- the artifact half ------------------------------------------------

    def test_every_declared_artifact_resolves_at_the_declared_commit(self):
        self.assertEqual(0, self.emit().returncode)
        doc = self.record()
        for artifact in doc["artifacts"]:
            _branch, commit, relative = self.cp.parse_content_uri(artifact["content_uri"])
            self.assertIsNotNone(commit, "an artifact locator must name a commit")
            raw = self.cp.read_blob(commit, relative, self.repo)
            self.assertIsNotNone(raw, f"{commit}:{relative} must resolve to bytes")
            self.assertEqual(artifact["sha256"], support.sha256_bytes(raw))
            self.assertEqual(artifact["bytes"], len(raw))

    def test_the_result_commit_contains_every_artifact(self):
        self.assertEqual(0, self.emit().returncode)
        doc = self.record()
        commit = doc["result_transaction"]["result_commit_id"]
        self.assertTrue(self.cp.commit_resolves(commit, self.repo))
        for artifact in doc["artifacts"]:
            _branch, _commit, relative = self.cp.parse_content_uri(artifact["content_uri"])
            self.assertIsNotNone(self.cp.read_blob(commit, relative, self.repo))

    def test_an_uncommitted_edit_is_refused_rather_than_stamped(self):
        """A locator must describe committed bytes, not the working copy."""
        (self.repo / ARTIFACT).write_bytes(b"edited but not committed\n")
        proc = self.emit()
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("does not match the committed bytes", proc.stderr + proc.stdout)

    # -- the manifest half ------------------------------------------------

    def test_the_manifest_uri_is_a_derivation_not_a_path_that_never_existed(self):
        self.assertEqual(0, self.emit().returncode)
        doc = self.record()
        manifest_uri = doc["result_transaction"]["manifest_uri"]
        self.assertTrue(manifest_uri.startswith("obzio-manifest-sha256:"), manifest_uri)
        self.assertEqual(
            doc["result_transaction"]["manifest_sha256"],
            manifest_uri.split(":", 1)[1],
        )

    def test_a_reader_can_recompute_the_manifest_from_the_declared_commit(self):
        self.assertEqual(0, self.emit().returncode)
        doc = self.record()
        commit = doc["result_transaction"]["result_commit_id"]
        rebuilt = []
        for artifact in sorted(doc["artifacts"], key=lambda item: item["artifact_id"]):
            _branch, _commit, relative = self.cp.parse_content_uri(artifact["content_uri"])
            raw = self.cp.read_blob(commit, relative, self.repo)
            rebuilt.append(
                {
                    "logical_name": artifact["logical_name"],
                    "sha256": support.sha256_bytes(raw),
                    "bytes": len(raw),
                }
            )
        manifest = {
            "unit_id": doc["task_id"],
            "commit": commit,
            "artifacts": rebuilt,
        }
        self.assertEqual(
            doc["result_transaction"]["manifest_sha256"],
            self.cp.sha256_text(self.cp.canonical(manifest)),
        )

    # -- the record half --------------------------------------------------

    def test_the_unsealed_record_makes_no_claim_about_its_own_location(self):
        """The paradox is removed, not hidden: nothing points at the record yet."""
        self.assertEqual(0, self.emit().returncode)
        doc = self.record()
        commit = doc["result_transaction"]["result_commit_id"]
        blob = self.cp.read_blob(commit, self.dispatch["result_slot"]["unit_record"], self.repo)
        self.assertIsNone(blob, "the record cannot be inside the commit it names")
        self.assertNotIn(
            self.dispatch["result_slot"]["unit_record"],
            doc["result_transaction"]["manifest_uri"],
        )

    def test_sealing_publishes_an_immutable_locator_for_the_record(self):
        self.assertEqual(0, self.emit().returncode)
        record_commit = support.commit_all(self.repo, "result record")
        proc = self.emit("--seal")
        self.assertEqual(0, proc.returncode, proc.stderr)
        seal = json.loads(
            (self.repo / f"workstreams/po03/control/units/h/{UNIT}.locator.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("OBZIO-RESULT-LOCATOR-v1", seal["protocol_version"])
        self.assertEqual(record_commit, seal["record_commit_id"])
        raw = self.cp.read_blob(seal["record_commit_id"], seal["record_path"], self.repo)
        self.assertIsNotNone(raw, "the sealed locator must resolve to the record bytes")
        self.assertEqual(seal["record_sha256"], support.sha256_bytes(raw))
        self.assertEqual(seal["record_bytes"], len(raw))
        self.assertEqual(self.record(), json.loads(raw.decode("utf-8")))

    def test_sealing_refuses_an_uncommitted_record(self):
        self.assertEqual(0, self.emit().returncode)
        proc = self.emit("--seal")
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("is not committed", proc.stderr + proc.stdout)

    def test_a_third_party_clone_resolves_the_sealed_locator(self):
        """The end-to-end property: bytes recoverable by someone who was not there."""
        self.assertEqual(0, self.emit().returncode)
        support.commit_all(self.repo, "result record")
        self.assertEqual(0, self.emit("--seal").returncode)
        support.commit_all(self.repo, "sealed locator")

        clone = self.base / "third-party"
        subprocess.run(
            ["git", "clone", "--quiet", str(self.repo), str(clone)], check=True, capture_output=True
        )
        seal = json.loads(
            (clone / f"workstreams/po03/control/units/h/{UNIT}.locator.json").read_text(
                encoding="utf-8"
            )
        )
        raw = self.cp.read_blob(seal["record_commit_id"], seal["record_path"], clone)
        self.assertEqual(seal["record_sha256"], support.sha256_bytes(raw))
        doc = json.loads(raw.decode("utf-8"))
        for artifact in doc["artifacts"]:
            _branch, commit, relative = self.cp.parse_content_uri(artifact["content_uri"])
            bytes_read = self.cp.read_blob(commit, relative, clone)
            self.assertEqual(artifact["sha256"], support.sha256_bytes(bytes_read))

    # -- the self-check entry point ---------------------------------------

    def test_the_emitter_can_verify_its_own_declared_locators(self):
        self.assertEqual(0, self.emit().returncode)
        support.commit_all(self.repo, "result record")
        self.assertEqual(0, self.emit("--seal").returncode)
        proc = self.emit("--verify")
        self.assertEqual(0, proc.returncode, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertTrue(report["result_commit_resolves"])
        self.assertTrue(report["manifest_sha256_reproduced"])
        self.assertTrue(report["record_resolves_from_seal"])
        self.assertEqual([], report["failures"])

    def test_verification_fails_when_the_declared_bytes_change(self):
        self.assertEqual(0, self.emit().returncode)
        support.commit_all(self.repo, "result record")
        self.assertEqual(0, self.emit("--seal").returncode)
        doc = self.record()
        doc["artifacts"][0]["sha256"] = "0" * 64
        self.record_path().write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        proc = self.emit("--verify")
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("sha256 mismatch", proc.stdout + proc.stderr)


class LegacyLocatorTests(support.ControlPlaneHarness):
    """Records emitted by the pre-fix emitter must still ingest."""

    git_backed = True

    def test_a_legacy_manifest_uri_is_tolerated_and_flagged(self):
        self.seed("h-u01")
        commit, _sha, _size = self.commit_artifact(f"{support.OWNED_PREFIX}h-u01.txt", b"legacy\n")
        doc = self.result_doc("h-u01", commit_id=commit, body=b"legacy\n", write_artifact=False)
        doc["result_transaction"]["manifest_uri"] = f"git:branch@{commit}:h-u01"
        outcome = self.ingest(doc)
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])
        row = [r for r in self.cp.ledger_rows() if r["event"] == "PARENT_INGESTED"][-1]
        self.assertEqual("legacy-unresolvable-manifest-uri", row["payload"]["manifest_uri_scheme"])

    def test_a_derivable_manifest_uri_is_verified(self):
        self.seed("h-u02")
        body = b"derivable\n"
        relative = f"{support.OWNED_PREFIX}h-u02.txt"
        commit, sha, size = self.commit_artifact(relative, body)
        doc = self.result_doc("h-u02", commit_id=commit, body=body, write_artifact=False)
        manifest = {
            "unit_id": "h-u02",
            "commit": commit,
            "artifacts": [{"logical_name": "h-u02.txt", "sha256": sha, "bytes": size}],
        }
        digest = self.cp.sha256_text(self.cp.canonical(manifest))
        doc["result_transaction"]["manifest_sha256"] = digest
        doc["result_transaction"]["manifest_uri"] = f"obzio-manifest-sha256:{digest}"
        outcome = self.ingest(doc)
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])
        row = [r for r in self.cp.ledger_rows() if r["event"] == "PARENT_INGESTED"][-1]
        self.assertEqual("obzio-manifest-sha256", row["payload"]["manifest_uri_scheme"])

    def test_a_derivable_manifest_uri_that_does_not_derive_is_rejected(self):
        self.seed("h-u03")
        relative = f"{support.OWNED_PREFIX}h-u03.txt"
        commit, _sha, _size = self.commit_artifact(relative, b"wrong\n")
        doc = self.result_doc("h-u03", commit_id=commit, body=b"wrong\n", write_artifact=False)
        doc["result_transaction"]["manifest_sha256"] = "0" * 64
        doc["result_transaction"]["manifest_uri"] = "obzio-manifest-sha256:" + "0" * 64
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("manifest", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
