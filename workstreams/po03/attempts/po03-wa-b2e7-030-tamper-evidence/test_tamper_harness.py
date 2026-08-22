"""Tests for PO-03 tamper evidence.

The hypothesis under test is that mutating a committed artifact after the fact
breaks the manifest and the event hash chain.  It holds for mutation, and the
tests assert it in both directions: a pristine artifact and a pristine chain
verify clean, and every mutation is caught.

Two things the chain does *not* catch were found and are asserted as gaps rather
than described as strengths: deleting the tail of a chain, and appending a
forged event with correct links.  If either ever starts being detected these
tests fail, which is the intended behaviour for a recorded gap.
"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
MODULE_PATH = UNIT_ROOT / "tamper_harness.py"
SPEC = importlib.util.spec_from_file_location("po03_tamper_harness", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)

REPO_ROOT = UNIT_ROOT.parents[3]


class HarnessOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        commit = HARNESS.git(REPO_ROOT, "rev-parse", "HEAD").decode("utf-8").strip()
        slot = HARNESS.choose_slot(commit)
        cls.cases = HARNESS.run_all(commit, slot, "po03-canary-001", Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def case(self, name):
        matches = [item for item in self.cases if item.name == name]
        self.assertEqual(1, len(matches), [item.name for item in self.cases])
        return matches[0]

    def test_every_case_behaved_as_expected(self):
        surprises = [item.as_dict() for item in self.cases if not item.satisfied]
        self.assertEqual([], surprises)

    def test_a_committed_artifact_matches_its_manifest_entry(self):
        self.assertFalse(self.case("committed-artifact-matches-its-manifest-entry").detected)

    def test_flipping_one_byte_of_a_materialised_artifact_breaks_its_hash(self):
        self.assertTrue(self.case("materialised-artifact-single-byte-flipped").detected)

    def test_truncating_a_materialised_artifact_breaks_its_byte_count(self):
        self.assertTrue(self.case("materialised-artifact-truncated").detected)

    def test_working_copy_tampering_cannot_change_committed_bytes(self):
        case = self.case("committed-bytes-unchanged-by-working-copy-tampering")
        self.assertFalse(case.detected)
        self.assertIn("identical=True", case.detail)

    def test_rewriting_a_manifest_entry_breaks_the_hash_the_result_cites(self):
        self.assertTrue(self.case("manifest-entry-rewritten-breaks-the-result-hash").detected)

    def test_a_pristine_chain_verifies_clean(self):
        self.assertFalse(self.case("pristine-chain-verifies").detected)

    def test_mutating_an_event_body_is_detected(self):
        case = self.case("event-body-mutated")
        self.assertTrue(case.detected)
        self.assertIn("event hash mismatch", case.detail)
        self.assertIn("previous hash mismatch", case.detail)

    def test_a_length_preserving_byte_flip_is_detected(self):
        case = self.case("single-byte-flip-preserving-length")
        self.assertTrue(case.detected)
        self.assertIn("original_bytes=388 tampered_bytes=388", case.detail)

    def test_deleting_a_middle_event_is_detected(self):
        case = self.case("middle-event-deleted")
        self.assertTrue(case.detected)
        self.assertIn("non-monotonic sequence", case.detail)

    def test_overwriting_an_event_self_hash_is_detected(self):
        self.assertTrue(self.case("self-hash-overwritten").detected)

    def test_rewriting_a_link_and_recomputing_the_self_hash_is_still_detected(self):
        self.assertTrue(self.case("previous-link-rewritten-and-self-hash-recomputed").detected)

    def test_tampering_a_copy_of_a_live_chain_is_detected(self):
        case = self.case("live-chain-copy-tampered:po03-canary-001")
        self.assertTrue(case.detected)
        self.assertIn("pristine_errors=[]", case.detail)

    def test_deleting_the_tail_of_a_chain_is_a_recorded_gap(self):
        case = self.case("tail-event-deleted")
        self.assertFalse(case.detected, "tail truncation is now detected; update this recorded gap")
        self.assertEqual(HARNESS.UNDETECTED, case.expectation)

    def test_appending_a_forged_event_is_a_recorded_gap(self):
        case = self.case("forged-event-appended-with-correct-links")
        self.assertFalse(case.detected, "forged append is now detected; update this recorded gap")
        self.assertEqual(HARNESS.UNDETECTED, case.expectation)

    def test_the_harness_is_not_vacuous_in_either_direction(self):
        detected = [item for item in self.cases if item.expectation == HARNESS.DETECTED]
        clean = [item for item in self.cases if item.expectation == "clean"]
        self.assertGreaterEqual(len(detected), 9)
        self.assertGreaterEqual(len(clean), 4)
        self.assertTrue(all(item.detected for item in detected))
        self.assertTrue(all(not item.detected for item in clean))


class LiveCustodyAuditTests(unittest.TestCase):
    """Verify every event chain the repository actually holds, using the live verifier."""

    def test_every_live_event_chain_verifies_under_the_real_verifier(self):
        source = REPO_ROOT / HARNESS.EVENTS_PREFIX
        tasks = sorted(item.name for item in source.iterdir() if item.is_dir())
        self.assertGreater(len(tasks), 0)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            destination = root / HARNESS.EVENTS_PREFIX
            destination.parent.mkdir(parents=True)
            shutil.copytree(source, destination)
            factory = HARNESS.load_factory(root)
            broken = {task: factory.verify_chain(task) for task in tasks}
            self.assertEqual({}, {task: errors for task, errors in broken.items() if errors})

    def test_tampering_any_one_live_chain_copy_breaks_it(self):
        source = REPO_ROOT / HARNESS.EVENTS_PREFIX
        tasks = sorted(item.name for item in source.iterdir() if item.is_dir())[:5]
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            destination = root / HARNESS.EVENTS_PREFIX
            destination.parent.mkdir(parents=True)
            shutil.copytree(source, destination)
            factory = HARNESS.load_factory(root)
            for task in tasks:
                event = sorted((destination / task).glob("*.json"))[0]
                document = json.loads(event.read_text(encoding="utf-8"))
                document["state"] = "COMPLETED"
                event.write_text(
                    json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                self.assertTrue(factory.verify_chain(task), task)


class NonInterferenceTests(unittest.TestCase):
    def test_the_harness_leaves_the_repository_untouched(self):
        def snapshot():
            status = subprocess.run(
                ("git", "status", "--porcelain"), cwd=REPO_ROOT, check=True,
                capture_output=True, text=True,
            ).stdout
            head = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True,
                capture_output=True, text=True,
            ).stdout
            return status, head

        before = snapshot()
        with tempfile.TemporaryDirectory() as scratch:
            commit = HARNESS.git(REPO_ROOT, "rev-parse", "HEAD").decode("utf-8").strip()
            HARNESS.run_all(commit, HARNESS.choose_slot(commit), "po03-canary-001", Path(scratch))
        self.assertEqual(before, snapshot())

    def test_live_event_files_are_not_modified_by_a_scratch_verification(self):
        source = REPO_ROOT / HARNESS.EVENTS_PREFIX / "po03-canary-001"
        digests_before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.glob("*.json"))
        }
        with tempfile.TemporaryDirectory() as scratch:
            HARNESS.real_chain_case(Path(scratch), "po03-canary-001")
        digests_after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.glob("*.json"))
        }
        self.assertEqual(digests_before, digests_after)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), *arguments), capture_output=True, text=True
        )

    def test_default_run_exits_zero_and_names_the_known_gaps(self):
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PO03_TAMPER_PASS", result.stdout)
        self.assertIn("KNOWN_GAP: tail-event-deleted", result.stdout)
        self.assertIn("KNOWN_GAP: forged-event-appended-with-correct-links", result.stdout)

    def test_json_mode_is_parseable(self):
        result = self.run_cli("--json")
        self.assertEqual(0, result.returncode, result.stderr)
        document = json.loads(result.stdout)
        self.assertTrue(all(entry["satisfied"] for entry in document["cases"]))
        self.assertGreaterEqual(len(document["cases"]), 15)

    def test_unknown_chain_task_exits_two(self):
        result = self.run_cli("--chain-task", "no-such-task")
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_TAMPER_ERROR", result.stderr)

    def test_slot_without_a_manifest_exits_two(self):
        result = self.run_cli("--slot", "workstreams/po03/attempts/no-such-slot")
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_TAMPER_ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main()
