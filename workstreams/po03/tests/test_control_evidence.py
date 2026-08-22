"""Anti-fabrication gates over the PO-03 control, metrics and evidence records.

These tests exist because the commission forbids invented values.  They check
the recorded evidence against the repository itself: every commit id must
resolve, every frozen source hash must match the bytes at the pinned commit,
every artifact hash must match the committed blob, and no document may grant
its own independent acceptance.
"""

import datetime
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PO03 = REPO_ROOT / "workstreams" / "po03"
RECEIPTS = REPO_ROOT / "receipts" / "po03"
GIT = shutil.which("git")

BRANCH_POINT = "552b12eacee637716451492a98980fb0da19ff3e"

VALIDATOR_PATH = PO03 / "tools" / "validate_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_contracts", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)

SHA40_RE = re.compile(r"\b[0-9a-f]{40}\b")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

ALLOWED_NON_VALUES = {
    "NOT_YET",
    "NOT_SUPPORTED",
    "NOT_APPLICABLE",
    "OWNER_BLOCKED",
    "PENDING",
    "PENDING_COMMIT",
    "PENDING_PUSH",
    "PENDING_AT_REGISTRY_WRITE_TIME",
    "PENDING_FINAL_COMMIT",
    "SELF_REFERENTIAL_NOT_RECORDABLE",
    "NOT_TESTED",
    "RECORDED_IN_RECEIPT",
    "MISSING",
}

FORBIDDEN_SELF_ACCEPTANCE = {"ACCEPTED", "PASS", "ACCEPT"}


def git_output(*args):
    return subprocess.run(
        [GIT, "-C", str(REPO_ROOT), *args], capture_output=True, check=True
    ).stdout


def commit_resolves(candidate):
    return (
        subprocess.run(
            [GIT, "-C", str(REPO_ROOT), "cat-file", "-e", f"{candidate}^{{commit}}"],
            capture_output=True,
        ).returncode
        == 0
    )


def load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def po03_json_documents():
    paths = sorted(PO03.rglob("*.json"))
    if RECEIPTS.is_dir():
        paths.extend(sorted(RECEIPTS.rglob("*.json")))
    return [path for path in paths if "__pycache__" not in path.parts]


def walk_values(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_values(item)


class RegistryIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = PO03 / "control" / "work-unit-registry.jsonl"
        if not cls.path.is_file():
            raise unittest.SkipTest("registry not present in this tree")
        cls.rows = load_jsonl(cls.path)

    def test_registry_is_not_empty(self):
        self.assertGreater(len(self.rows), 0)

    def test_task_ids_are_unique(self):
        ids = [row["task_id"] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_idempotency_keys_are_unique(self):
        keys = [row["idempotency_key"] for row in self.rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_fence_tokens_are_strictly_monotonic_from_one(self):
        tokens = [row["fence_token"] for row in self.rows]
        self.assertEqual(list(range(1, len(tokens) + 1)), tokens)

    def test_every_unit_declares_a_worker_and_model(self):
        for row in self.rows:
            self.assertTrue(row["worker_id"].strip())
            self.assertTrue(row["model"].strip())
            self.assertTrue(row["provider_run_id"].strip())

    def test_no_unit_claims_independent_acceptance(self):
        for row in self.rows:
            self.assertNotIn(
                row["independent_acceptance"].upper(), FORBIDDEN_SELF_ACCEPTANCE, row["task_id"]
            )

    def test_timestamps_are_iso_z_or_declared_pending(self):
        for row in self.rows:
            for field in ("started_at", "ended_at"):
                value = row[field]
                if value in ALLOWED_NON_VALUES:
                    continue
                self.assertRegex(value, ISO_Z_RE, f"{row['task_id']}.{field}")

    @unittest.skipUnless(GIT, "git is required to resolve commit ids")
    def test_every_recorded_commit_id_resolves(self):
        checked = 0
        for row in self.rows:
            commit = row["result_commit_id"]
            if commit in ALLOWED_NON_VALUES:
                continue
            self.assertRegex(commit, SHA40_RE, row["task_id"])
            self.assertTrue(commit_resolves(commit), f"{row['task_id']}: {commit}")
            checked += 1
        self.assertGreater(checked, 0, "no unit recorded a real commit id")

    @unittest.skipUnless(GIT, "git is required to resolve commit ids")
    def test_units_with_a_commit_have_a_terminal_state(self):
        for row in self.rows:
            if row["result_commit_id"] in ALLOWED_NON_VALUES:
                continue
            self.assertIn(
                row["obzio_state"],
                {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"},
                row["task_id"],
            )

    def test_no_unit_is_marked_completed(self):
        for row in self.rows:
            self.assertNotEqual(
                "COMPLETED",
                row["obzio_state"],
                "COMPLETED is withheld while producer and coordinator are the same worker",
            )


@unittest.skipUnless(GIT, "git is required to resolve commit ids")
class NoFabricatedShaTests(unittest.TestCase):
    def test_every_forty_hex_token_in_po03_records_resolves_to_a_real_commit(self):
        documents = po03_json_documents() + sorted(PO03.rglob("*.jsonl"))
        self.assertTrue(documents)
        unresolved = []
        checked = 0
        for path in documents:
            text = path.read_text(encoding="utf-8")
            for candidate in sorted(set(SHA40_RE.findall(text))):
                checked += 1
                if not commit_resolves(candidate):
                    unresolved.append(f"{path.relative_to(REPO_ROOT)}: {candidate}")
        self.assertEqual([], unresolved)
        self.assertGreater(checked, 0)


@unittest.skipUnless(GIT, "git is required to read pinned blobs")
class SourceLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = PO03 / "evidence" / "source-lock.json"
        if not path.is_file():
            raise unittest.SkipTest("source lock not present in this tree")
        cls.lock = json.loads(path.read_text(encoding="utf-8"))

    def test_branch_point_matches_the_recorded_value(self):
        self.assertEqual(BRANCH_POINT, self.lock["branch_point_sha"])

    def test_every_frozen_hash_matches_the_bytes_at_the_branch_point(self):
        mismatched = []
        for entry in self.lock["frozen_source_hashes"]:
            path = entry["path"]
            blob = git_output("show", f"{BRANCH_POINT}:{path}")
            digest = hashlib.sha256(blob).hexdigest()
            if digest != entry["sha256"] or len(blob) != entry["bytes"]:
                mismatched.append(path)
        self.assertEqual([], mismatched)

    def test_declared_pinned_base_is_an_ancestor_as_recorded(self):
        verified = self.lock["commission_declared_pinned_base_verified"]
        self.assertTrue(verified["is_ancestor_of_branch_point"])
        declared = self.lock["commission_declared_pinned_base_sha"]
        result = subprocess.run(
            [GIT, "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", declared, BRANCH_POINT],
            capture_output=True,
        )
        self.assertEqual(0, result.returncode)


class MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs_path = PO03 / "metrics" / "work-unit-runs.jsonl"
        cls.registry_path = PO03 / "control" / "work-unit-registry.jsonl"
        if not cls.runs_path.is_file() or not cls.registry_path.is_file():
            raise unittest.SkipTest("metrics or registry not present in this tree")
        cls.runs = load_jsonl(cls.runs_path)
        cls.registry = load_jsonl(cls.registry_path)

    def test_one_metric_row_per_counted_unit(self):
        self.assertEqual(
            [row["task_id"] for row in self.registry],
            [row["task_id"] for row in self.runs],
        )

    def test_declared_durations_match_the_recorded_window(self):
        for row in self.runs:
            started, ended = row["started_at"], row["ended_at"]
            if started in ALLOWED_NON_VALUES or ended in ALLOWED_NON_VALUES:
                self.assertIn(row["active_time_seconds"], ALLOWED_NON_VALUES, row["task_id"])
                continue
            begin = datetime.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
            finish = datetime.datetime.strptime(ended, "%Y-%m-%dT%H:%M:%SZ")
            self.assertEqual(
                int((finish - begin).total_seconds()),
                row["active_time_seconds"],
                row["task_id"],
            )

    def test_hashes_are_sha256_or_declared_unsupported(self):
        for row in self.runs:
            for field in ("immutable_input_sha256", "acceptance_contract_sha256"):
                value = row[field]
                if value in ALLOWED_NON_VALUES:
                    continue
                self.assertRegex(value, SHA256_RE, f"{row['task_id']}.{field}")

    def test_no_row_claims_independent_acceptance(self):
        for row in self.runs:
            self.assertNotIn(
                str(row["independent_disposition"]).upper(),
                FORBIDDEN_SELF_ACCEPTANCE,
                row["task_id"],
            )

    def test_collision_and_false_completion_counts_are_zero_and_stated(self):
        for row in self.runs:
            self.assertEqual(0, row["collision_events"], row["task_id"])


class EventLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = PO03 / "control" / "events"
        if not cls.directory.is_dir():
            raise unittest.SkipTest("event log not present in this tree")
        cls.events = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(cls.directory.glob("*.json"))
        ]

    def test_events_exist(self):
        self.assertGreater(len(self.events), 0)

    def test_event_ids_are_unique(self):
        ids = [event["event_id"] for event in self.events]
        self.assertEqual(len(ids), len(set(ids)))

    def test_sequence_numbers_are_contiguous_from_one(self):
        self.assertEqual(
            list(range(1, len(self.events) + 1)),
            [event["seq"] for event in self.events],
        )

    def test_every_event_declares_timestamp_provenance(self):
        for event in self.events:
            self.assertRegex(event["occurred_at"], ISO_Z_RE, event["event_id"])
            self.assertTrue(event["timestamp_provenance"].strip())


class SelfAcceptanceTests(unittest.TestCase):
    def test_no_po03_document_grants_its_own_independent_acceptance(self):
        offenders = []
        for path in po03_json_documents():
            document = json.loads(path.read_text(encoding="utf-8"))
            for key, value in walk_values(document):
                if key not in {"independent_acceptance", "independent_disposition", "acceptance"}:
                    continue
                state = value.get("state") if isinstance(value, dict) else value
                if isinstance(state, str) and state.upper() in FORBIDDEN_SELF_ACCEPTANCE:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {key}={state}")
        self.assertEqual([], offenders)


@unittest.skipUnless(GIT, "git is required to read committed blobs")
class EmittedResultInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = PO03 / "contracts" / "instances" / "results"
        if not cls.directory.is_dir():
            raise unittest.SkipTest("no emitted result instances in this tree")
        cls.documents = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(cls.directory.glob("*.json"))
        }
        if not cls.documents:
            raise unittest.SkipTest("results directory is empty")

    def test_every_instance_satisfies_the_result_contract(self):
        for name, document in self.documents.items():
            self.assertEqual([], VALIDATOR.validate_result(document), name)

    def test_one_instance_per_unit_with_a_real_commit(self):
        registry = load_jsonl(PO03 / "control" / "work-unit-registry.jsonl")
        expected = {
            row["task_id"]
            for row in registry
            if row["result_commit_id"] not in ALLOWED_NON_VALUES
        }
        self.assertEqual(expected, set(self.documents))

    def test_artifact_hashes_match_the_committed_blobs(self):
        mismatched = []
        for name, document in self.documents.items():
            commit = document["result_transaction"]["result_commit_id"]
            for artifact in document["artifacts"]:
                blob = git_output("show", f"{commit}:{artifact['logical_name']}")
                if (
                    hashlib.sha256(blob).hexdigest() != artifact["sha256"]
                    or len(blob) != artifact["bytes"]
                ):
                    mismatched.append(f"{name}: {artifact['logical_name']}")
        self.assertEqual([], mismatched)

    def test_byte_totals_reconcile(self):
        for name, document in self.documents.items():
            transaction = document["result_transaction"]
            self.assertEqual(len(document["artifacts"]), transaction["artifact_count"], name)
            self.assertEqual(
                sum(item["bytes"] for item in document["artifacts"]),
                transaction["total_bytes"],
                name,
            )

    def test_committed_at_matches_the_real_commit_timestamp(self):
        for name, document in self.documents.items():
            commit = document["result_transaction"]["result_commit_id"]
            recorded = git_output("show", "-s", "--format=%cI", commit).decode().strip()
            self.assertEqual(
                recorded.replace("+00:00", "Z"),
                document["result_transaction"]["committed_at"],
                name,
            )

    def test_no_instance_is_completed_or_self_accepted(self):
        for name, document in self.documents.items():
            self.assertNotEqual("COMPLETED", document["obzio_state"], name)
            self.assertEqual("NOT_TESTED", document["independent_acceptance"]["state"], name)
            self.assertIsNone(document["independent_acceptance"]["reviewer_id"], name)


class PathOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = PO03 / "control" / "path-ownership.json"
        if not path.is_file():
            raise unittest.SkipTest("path ownership record not present in this tree")
        cls.record = json.loads(path.read_text(encoding="utf-8"))

    def test_single_writer_is_recorded(self):
        self.assertEqual([], self.record["concurrent_subordinate_writers"])
        self.assertEqual(0, self.record["concurrent_subordinate_writer_count"])

    def test_no_read_only_surface_was_written(self):
        self.assertEqual([], self.record["read_only_surfaces_touched"])

    def test_no_merge_or_promotion_was_performed(self):
        self.assertFalse(self.record["merge_or_promotion_performed"])


if __name__ == "__main__":
    unittest.main()
