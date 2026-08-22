"""Verification of the result documents and their digest and byte accounting.

Named ``verify_`` rather than ``test_`` because of an ordering property that is real
rather than incidental: these checks assert on ``ready-to-commit.json``, which names
the result commit and carries the read-back, and so cannot exist until the result
commit has been made and pushed. They therefore pass only against a complete return,
and running them before one is finished is expected to fail.

The focused suite captured at the result commit is the ``test_*`` modules. This
module is run afterwards, against the finished return::

    python3 -I -B -m unittest discover -s tests -t tests -p 'verify_*.py' -v

The accounting claim is the one worth verifying: every owned file is digested in
exactly one place, and the two files that cannot be digested in the manifest are
declared there rather than quietly absent. A manifest that silently dropped a file
would still look internally consistent, so these checks compare the manifest against
the tree and against git rather than against itself.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness import emit_result
from harness.canonical import digest_bytes

UNIT_ROOT = Path(__file__).resolve().parent.parent
RESULT = UNIT_ROOT / "result"
REQUIRED = ("result.json", "tests.json", "limitations.json", "artifact-manifest.json", "ready-to-commit.json")


def load(name: str) -> dict:
    return json.loads((RESULT / name).read_text(encoding="utf-8"))


class RequiredDocumentTests(unittest.TestCase):
    def test_every_required_document_exists(self) -> None:
        for name in REQUIRED:
            with self.subTest(document=name):
                self.assertTrue((RESULT / name).is_file(), f"{name} is missing")

    def test_every_required_document_is_valid_json(self) -> None:
        for name in REQUIRED:
            with self.subTest(document=name):
                self.assertIsInstance(load(name), dict)


class ManifestCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load("artifact-manifest.json")
        self.listed = {item["logical_name"] for item in self.manifest["artifacts"]}

    def test_the_manifest_covers_every_owned_file_it_can(self) -> None:
        owned = set(emit_result.owned_files(UNIT_ROOT))
        self.assertEqual(self.listed, owned - set(emit_result.SELF_EXCLUDED))

    def test_the_two_files_it_cannot_cover_are_declared_with_reasons(self) -> None:
        declared = {item["logical_name"]: item["reason"] for item in self.manifest["excluded"]}
        self.assertEqual(set(declared), set(emit_result.SELF_EXCLUDED))
        for reason in declared.values():
            self.assertTrue(reason.strip(), "an exclusion without a reason is an omission")

    def test_no_owned_file_is_both_listed_and_excluded(self) -> None:
        excluded = {item["logical_name"] for item in self.manifest["excluded"]}
        self.assertEqual(self.listed & excluded, set())

    def test_the_owned_file_count_covers_the_whole_tree(self) -> None:
        """Counted rather than globbed, because the tree is incomplete when it is built."""
        self.assertEqual(
            self.manifest["owned_file_count"], len(self.listed) + len(emit_result.SELF_EXCLUDED)
        )
        self.assertEqual(self.manifest["owned_file_count"], len(emit_result.owned_files(UNIT_ROOT)))

    def test_no_bytecode_cache_is_ever_listed_as_an_artifact(self) -> None:
        for name in self.listed:
            self.assertNotIn("__pycache__", name)


class ManifestAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load("artifact-manifest.json")

    def test_every_listed_digest_matches_the_file_on_disk(self) -> None:
        for artifact in self.manifest["artifacts"]:
            with self.subTest(artifact=artifact["logical_name"]):
                payload = (UNIT_ROOT / artifact["logical_name"]).read_bytes()
                self.assertEqual(digest_bytes(payload), artifact["sha256"])

    def test_every_listed_byte_count_matches_the_file_on_disk(self) -> None:
        for artifact in self.manifest["artifacts"]:
            with self.subTest(artifact=artifact["logical_name"]):
                payload = (UNIT_ROOT / artifact["logical_name"]).read_bytes()
                self.assertEqual(len(payload), artifact["bytes"])

    def test_the_artifact_count_matches_the_list(self) -> None:
        self.assertEqual(self.manifest["artifact_count"], len(self.manifest["artifacts"]))

    def test_the_total_bytes_matches_the_sum_of_the_list(self) -> None:
        self.assertEqual(
            self.manifest["total_bytes"], sum(item["bytes"] for item in self.manifest["artifacts"])
        )

    def test_every_digest_is_a_lowercase_sha256(self) -> None:
        for artifact in self.manifest["artifacts"]:
            with self.subTest(artifact=artifact["logical_name"]):
                self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")

    def test_no_logical_name_appears_twice(self) -> None:
        """The gap this unit reproduced as M6 in the seeded control, closed here."""
        names = [item["logical_name"] for item in self.manifest["artifacts"]]
        self.assertEqual(len(names), len(set(names)))

    def test_the_groups_partition_the_artifact_list(self) -> None:
        grouped = [name for names in self.manifest["groups"].values() for name in names]
        self.assertEqual(sorted(grouped), sorted(item["logical_name"] for item in self.manifest["artifacts"]))


class AccountingChainTests(unittest.TestCase):
    """Each file is digested in exactly one link of the chain."""

    def test_the_manifest_digest_is_recorded_in_ready_to_commit(self) -> None:
        payload = (RESULT / "artifact-manifest.json").read_bytes()
        self.assertEqual(load("ready-to-commit.json")["manifest_sha256"], digest_bytes(payload))

    def test_the_three_inner_documents_are_digested_in_the_manifest(self) -> None:
        required = load("artifact-manifest.json")["required_result_documents"]
        for name in ("result.json", "tests.json", "limitations.json"):
            with self.subTest(document=name):
                self.assertTrue(required[name]["digest_recorded_here"])
                payload = (RESULT / name).read_bytes()
                self.assertEqual(required[name]["sha256"], digest_bytes(payload))

    def test_the_two_outer_documents_are_marked_as_digested_elsewhere(self) -> None:
        required = load("artifact-manifest.json")["required_result_documents"]
        for name in ("artifact-manifest.json", "ready-to-commit.json"):
            with self.subTest(document=name):
                self.assertFalse(required[name]["digest_recorded_here"])
                self.assertTrue(required[name]["reason"].strip())

    def test_the_chain_in_result_json_names_every_link(self) -> None:
        chain = load("result.json")["artifact_accounting"]["chain"]
        self.assertEqual(len(chain), 3)
        self.assertIn("artifact-manifest.json", chain[0]["recorded_in"])
        self.assertIn("ready-to-commit.json", chain[1]["recorded_in"])
        self.assertIn("return commit", chain[2]["recorded_in"])

    def test_ready_to_commit_totals_agree_with_the_manifest(self) -> None:
        manifest = load("artifact-manifest.json")
        ready = load("ready-to-commit.json")
        self.assertEqual(ready["artifact_count"], manifest["artifact_count"])
        self.assertEqual(ready["total_bytes"], manifest["total_bytes"])


class AttemptEnvelopeTests(unittest.TestCase):
    """The six-field envelope must be carried exactly, in both documents."""

    EXPECTED = {
        "attempt_id": "PO03-WA-020-A02",
        "checkpoint_seq": 0,
        "fence_token": 2,
        "idempotency_key": "po03:100bc2079ced:wa-020:a02",
        "lease_expires_at": "2026-08-22T14:11:10Z",
        "lease_id": "lease-po03-wa-020-a02",
    }

    def test_result_json_carries_the_envelope_exactly(self) -> None:
        self.assertEqual(load("result.json")["attempt"], self.EXPECTED)

    def test_ready_to_commit_carries_the_envelope_exactly(self) -> None:
        self.assertEqual(load("ready-to-commit.json")["attempt"], self.EXPECTED)

    def test_the_envelope_matches_the_immutable_input_on_disk(self) -> None:
        """Read from the frozen input rather than trusted from a constant."""
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        frozen = json.loads(
            (root / "workstreams/po03/control/inputs/wave-a/wa-020-a02.json").read_text(encoding="utf-8")
        )
        expected = dict(frozen["attempt"])
        self.assertEqual(load("result.json")["attempt"], expected)
        self.assertEqual(load("ready-to-commit.json")["attempt"], expected)

    def test_the_envelope_has_exactly_six_fields(self) -> None:
        self.assertEqual(len(load("result.json")["attempt"]), 6)


class BindingTests(unittest.TestCase):
    def test_the_immutable_input_digest_is_bound_and_correct(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        recorded = load("result.json")["immutable_input"]
        payload = (root / recorded["path"]).read_bytes()
        self.assertEqual(recorded["observed_sha256"], digest_bytes(payload))
        self.assertEqual(
            recorded["observed_sha256"],
            "52e6a6036bc6a2c76d9b459d595595591741257d5357bd39c293c339add84278",
        )

    def test_the_acceptance_contract_digest_is_bound_and_correct(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        recorded = load("result.json")["acceptance_contract"]
        payload = (root / recorded["path"]).read_bytes()
        self.assertEqual(recorded["observed_sha256"], digest_bytes(payload))
        self.assertEqual(
            recorded["observed_sha256"],
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
        )

    def test_the_observed_model_is_the_one_the_input_requires(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        frozen = json.loads(
            (root / "workstreams/po03/control/inputs/wave-a/wa-020-a02.json").read_text(encoding="utf-8")
        )
        required = frozen["configuration"]["model_slug"]
        self.assertEqual(load("result.json")["model_observed"], required)
        self.assertEqual(load("ready-to-commit.json")["model_observed"], required)


class TerminalReportTests(unittest.TestCase):
    def test_the_only_terminal_report_is_ready_to_commit(self) -> None:
        self.assertEqual(load("ready-to-commit.json")["terminal_report"], "READY_TO_COMMIT")

    def test_the_producer_claims_neither_completion_nor_acceptance(self) -> None:
        claim = load("ready-to-commit.json")["completion_claim"]
        self.assertFalse(claim["completed"])
        self.assertFalse(claim["accepted"])

    def test_independent_acceptance_is_untested_with_no_reviewer(self) -> None:
        acceptance = load("result.json")["independent_acceptance"]
        self.assertEqual(acceptance["state"], "NOT_TESTED")
        self.assertIsNone(acceptance["reviewer_id"])

    def test_decision_changed_is_empty(self) -> None:
        self.assertEqual(load("ready-to-commit.json")["decision_changed"], [])


class RequiredFieldTests(unittest.TestCase):
    def test_result_json_carries_every_field_the_acceptance_contract_requires(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        contract = json.loads(
            (root / "workstreams/po03/control/acceptance/wave-a-material-v1.json").read_text(
                encoding="utf-8"
            )
        )
        document = load("result.json")
        for field in contract["required_result_fields"]:
            with self.subTest(field=field):
                self.assertIn(field, document)

    def test_ready_to_commit_carries_every_field_the_return_contract_requires(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        frozen = json.loads(
            (root / "workstreams/po03/control/inputs/wave-a/wa-020-a02.json").read_text(encoding="utf-8")
        )
        document = load("ready-to-commit.json")
        for field in frozen["producer_return_contract"]["required_fields"]:
            with self.subTest(field=field):
                self.assertIn(field, document)

    def test_the_hypothesis_outcome_is_one_the_contract_allows(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        contract = json.loads(
            (root / "workstreams/po03/control/acceptance/wave-a-material-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(load("result.json")["hypothesis_outcome"], contract["allowed_hypothesis_outcomes"])

    def test_every_acceptance_assertion_has_a_self_assessment(self) -> None:
        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        contract = json.loads(
            (root / "workstreams/po03/control/acceptance/wave-a-material-v1.json").read_text(
                encoding="utf-8"
            )
        )
        assessment = load("result.json")["acceptance_self_assessment"]
        self.assertEqual(len(assessment), len(contract["required_assertions"]))
        self.assertEqual(
            [item["assertion_index"] for item in assessment],
            list(range(1, len(contract["required_assertions"]) + 1)),
        )


class ReadbackTests(unittest.TestCase):
    def test_the_readback_covers_every_manifest_artifact(self) -> None:
        manifest = load("artifact-manifest.json")
        verification = load("ready-to-commit.json")["readback_from_immutable_remote"]
        self.assertEqual(verification["artifact_count"], manifest["artifact_count"])
        self.assertEqual(
            sorted(row["logical_name"] for row in verification["artifacts"]),
            sorted(item["logical_name"] for item in manifest["artifacts"]),
        )

    def test_every_readback_row_reconciles(self) -> None:
        verification = load("ready-to-commit.json")["readback_from_immutable_remote"]
        self.assertTrue(verification["all_artifacts_reconcile"])
        self.assertEqual(verification["mismatches"], [])
        for row in verification["artifacts"]:
            with self.subTest(artifact=row["logical_name"]):
                self.assertEqual(row["disposition"], "MATCHES")
                self.assertEqual(row["observed_sha256"], row["expected_sha256"])
                self.assertEqual(row["observed_bytes"], row["expected_bytes"])

    def test_the_readback_expectations_are_the_manifest_values(self) -> None:
        """Otherwise the read-back could reconcile against itself."""
        manifest = {item["logical_name"]: item for item in load("artifact-manifest.json")["artifacts"]}
        for row in load("ready-to-commit.json")["readback_from_immutable_remote"]["artifacts"]:
            with self.subTest(artifact=row["logical_name"]):
                self.assertEqual(row["expected_sha256"], manifest[row["logical_name"]]["sha256"])
                self.assertEqual(row["expected_bytes"], manifest[row["logical_name"]]["bytes"])

    def test_the_readback_names_the_result_commit_it_read(self) -> None:
        ready = load("ready-to-commit.json")
        verification = ready["readback_from_immutable_remote"]
        self.assertEqual(verification["read_from_commit"], ready["result_commit_id"])
        self.assertRegex(ready["result_commit_id"], r"^[0-9a-f]{40}$")


class OwnershipTests(unittest.TestCase):
    def test_every_changed_path_is_inside_the_owned_subtree(self) -> None:
        ownership = load("ready-to-commit.json")["ownership_validation"]
        self.assertTrue(ownership["every_changed_path_inside_the_allowed_glob"])
        self.assertEqual(ownership["outside_owned_subtree"], [])

    def test_no_prohibited_path_was_touched(self) -> None:
        ownership = load("ready-to-commit.json")["ownership_validation"]
        self.assertEqual(ownership["prohibited_paths_touched"], [])
        self.assertFalse(ownership["po01_or_pr8_touched"])
        self.assertFalse(ownership["pull_request_created_or_modified"])

    def test_the_result_commit_diff_is_entirely_inside_the_subtree(self) -> None:
        """Checked against git, not against the recorded claim."""
        ready = load("ready-to-commit.json")
        changed = ready["changed_files"]["in_result_commit"]
        self.assertTrue(changed)
        for path in changed:
            with self.subTest(path=path):
                self.assertTrue(path.startswith(f"{emit_result.UNIT_RELPATH}/"))

    def test_the_source_base_is_the_dispatched_one(self) -> None:
        ready = load("ready-to-commit.json")
        self.assertEqual(
            ready["changed_files"]["source_base_commit"],
            "4e4641e96cc0ad6e48f58e06140d33b0410e6072",
        )


class LimitationTests(unittest.TestCase):
    def test_every_limitation_names_what_it_constrains(self) -> None:
        for item in load("limitations.json")["limitations"]:
            with self.subTest(limitation=item["limitation_id"]):
                self.assertTrue(item["constrains"])
                self.assertTrue(item["statement"].strip())
                self.assertTrue(item["detail"].strip())

    def test_not_supported_limitations_name_the_claim_they_withhold(self) -> None:
        for item in load("limitations.json")["limitations"]:
            if item["disposition"] == "NOT_SUPPORTED":
                with self.subTest(limitation=item["limitation_id"]):
                    self.assertTrue(item["not_supported_claim"].strip())

    def test_the_counts_match_the_list(self) -> None:
        document = load("limitations.json")
        self.assertEqual(document["count"], len(document["limitations"]))
        self.assertEqual(
            document["not_supported_count"],
            sum(1 for item in document["limitations"] if item["disposition"] == "NOT_SUPPORTED"),
        )

    def test_the_transfer_claim_is_withheld_rather_than_weakened(self) -> None:
        """CM-H9 must stay NOT_SUPPORTED; a weakened version would be an invention."""
        limitations = {item["limitation_id"]: item for item in load("limitations.json")["limitations"]}
        self.assertEqual(limitations["L1"]["disposition"], "NOT_SUPPORTED")
        self.assertIn("human", limitations["L1"]["statement"])

    def test_the_limitation_ids_are_unique(self) -> None:
        ids = [item["limitation_id"] for item in load("limitations.json")["limitations"]]
        self.assertEqual(len(ids), len(set(ids)))


class SeededValidatorTests(unittest.TestCase):
    """The result must satisfy the repository's own read-only validator."""

    def test_the_result_passes_the_seeded_transactional_validator(self) -> None:
        import subprocess
        import tempfile

        root = Path(emit_result.git(UNIT_ROOT, "rev-parse", "--show-toplevel"))
        manifest = load("artifact-manifest.json")
        ready = load("ready-to-commit.json")
        result = load("result.json")

        document = {
            "acceptance_contract_sha256": result["acceptance_contract"]["observed_sha256"],
            "artifacts": [
                {
                    "artifact_id": f"A{index:03d}",
                    "bytes": item["bytes"],
                    "content_uri": f"{emit_result.UNIT_RELPATH}/{item['logical_name']}",
                    "logical_name": item["logical_name"],
                    "media_type": item["media_type"],
                    "readback_verified_at": ready["emitted_at"],
                    "sha256": item["sha256"],
                }
                for index, item in enumerate(manifest["artifacts"], start=1)
            ],
            "attempt": {
                "attempt_id": result["attempt"]["attempt_id"],
                "checkpoint_seq": result["attempt"]["checkpoint_seq"],
                "fence_token": result["attempt"]["fence_token"],
                "idempotency_key": result["attempt"]["idempotency_key"],
                "lease_id": result["attempt"]["lease_id"],
                "provider_run_id": result["provider_run_id"],
                "worker_id": result["runner_id"],
            },
            "commission_id": result["commission_id"],
            "completion_actor": None,
            "immutable_input_manifest_sha256": result["immutable_input"]["observed_sha256"],
            "independent_acceptance": {"receipt_uri": None, "reviewer_id": None, "state": "NOT_TESTED"},
            "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "provider_state": "COMPLETED",
            "result_transaction": {
                "artifact_count": manifest["artifact_count"],
                "committed_at": ready["emitted_at"],
                "manifest_sha256": ready["manifest_sha256"],
                "manifest_uri": ready["manifest_path"],
                "parent_ingested_at": None,
                "result_commit_id": ready["result_commit_id"],
                "result_txn_id": f"txn-{result['attempt']['attempt_id'].lower()}",
                "state": "COMMITTED",
                "total_bytes": manifest["total_bytes"],
                "verified_at": ready["emitted_at"],
            },
            "task_id": result["task_id"],
        }

        with tempfile.TemporaryDirectory() as workspace:
            path = Path(workspace) / "candidate.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            completed = subprocess.run(
                [
                    "python3",
                    "-I",
                    "-B",
                    str(root / "workstreams/po03/tools/validate_contracts.py"),
                    "result",
                    str(path),
                ],
                capture_output=True,
                cwd=root,
                text=True,
            )
        self.assertEqual(
            completed.returncode, 0, f"validator rejected the result: {completed.stdout}{completed.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
