import hashlib
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = UNIT_ROOT.parents[4]
RUNNER_PATH = UNIT_ROOT / "tools" / "run_g0.py"
SUITE_PATH = UNIT_ROOT / "fixtures" / "g0-suite.json"
SOURCE_MANIFEST_PATH = UNIT_ROOT / "frozen_inputs" / "source-manifest.json"
OBSERVED_RESULT_PATH = UNIT_ROOT / "observed" / "result-contract.json"
MANIFEST_PATH = UNIT_ROOT / "manifest.json"

SPEC = importlib.util.spec_from_file_location("po03_g0_runner", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNNER)


class FrozenSourceTests(unittest.TestCase):
    def test_source_manifest_matches_local_and_historical_git_bytes(self):
        verification = RUNNER.verify_frozen_sources(SOURCE_MANIFEST_PATH)
        self.assertEqual("1bb843b2a81fd8d73617caf2f1db81909266bb6e", verification[
            "manifest"
        ]["historical_controller_head"])
        for source in verification["manifest"]["sources"]:
            historical = subprocess.run(
                (
                    "git",
                    "show",
                    f"1bb843b2a81fd8d73617caf2f1db81909266bb6e:{source['repository_path']}",
                ),
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            ).stdout
            local = (UNIT_ROOT / source["path"]).read_bytes()
            self.assertEqual(historical, local, source["repository_path"])
            self.assertEqual(source["sha256"], hashlib.sha256(historical).hexdigest())

    def test_fixture_suite_is_unique_and_explicit(self):
        suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
        identifiers = [case["id"] for case in suite["cases"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all("expected_decision" in case for case in suite["cases"]))
        self.assertTrue(all("critical" in case for case in suite["cases"]))
        self.assertFalse(suite["public_source"]["network_required_at_execution"])


class G0ExecutionTests(unittest.TestCase):
    def run_suite(self):
        return RUNNER.run_suite(SUITE_PATH, SOURCE_MANIFEST_PATH)

    def test_execution_is_deterministic(self):
        self.assertEqual(self.run_suite(), self.run_suite())

    def test_reconstruction_succeeds_without_false_green_quality_claim(self):
        result = self.run_suite()
        self.assertEqual("PASS", result["reconstruction_status"])
        self.assertEqual("FAIL", result["baseline_quality_status"])
        self.assertEqual("NOT_YET", result["successor_lift_claim"])
        self.assertFalse(result["metrics"]["critical_correctness"]["meets_100_percent"])
        self.assertGreater(result["metrics"]["false_green_count"], 0)

    def test_known_critical_false_greens_are_exposed(self):
        result = self.run_suite()
        false_greens = set(result["metrics"]["false_green_case_ids"])
        self.assertTrue(
            {
                "hash-valid-wrong-task-event",
                "commit-transition-without-artifacts",
                "short-result-commit-id",
                "source-lock-worktree-drift",
            }.issubset(false_greens)
        )

    def test_missing_historical_evidence_fixture_refuses_success_claim(self):
        result = self.run_suite()
        observation = next(
            item
            for item in result["observations"]
            if item["case_id"] == "historical-generation-evidence-unavailable"
        )
        self.assertEqual("NOT_YET", observation["observed_decision"])
        self.assertEqual("MATCH", observation["outcome"])
        self.assertFalse(observation["details"]["historical_success_inferred"])

    def test_durable_result_is_exact_current_execution(self):
        self.assertTrue(OBSERVED_RESULT_PATH.is_file())
        self.assertEqual(
            RUNNER.canonical_json(self.run_suite()),
            OBSERVED_RESULT_PATH.read_bytes(),
        )

    def test_manifest_covers_every_durable_file(self):
        self.assertTrue(MANIFEST_PATH.is_file())
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        declared = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
        actual = {
            path.relative_to(UNIT_ROOT).as_posix(): path
            for path in UNIT_ROOT.rglob("*")
            if path.is_file()
            and path != MANIFEST_PATH
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        }
        self.assertEqual(set(actual), set(declared))
        self.assertEqual(len(actual), manifest["artifact_count"])
        self.assertEqual(
            sum(path.stat().st_size for path in actual.values()),
            manifest["total_artifact_bytes_excluding_manifest"],
        )
        for relative, path in actual.items():
            content = path.read_bytes()
            self.assertEqual(len(content), declared[relative]["bytes"])
            self.assertEqual(
                hashlib.sha256(content).hexdigest(),
                declared[relative]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
