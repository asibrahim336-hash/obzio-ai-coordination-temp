#!/usr/bin/env python3
"""Focused, deterministic tests for the PO03-WA-008 hidden-state detector.

Run with the standard library only:

    python3 -m unittest -v test_differential_run

The suite covers, in order: per-class detection, clean controls that must not
produce false positives, interaction attribution, refusal to attribute
nondeterminism, the documented false-negative bound, refusal to over-claim an
unattributable divergence, deterministic recurrence of the classification
digest, checkout independence, environment sanitisation, secret non-disclosure,
path-normalisation, timeout handling and the command-line contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import differential_run as D  # noqa: E402
import hidden_state_fixtures as F  # noqa: E402


def build_and_run(fixture_id, repeats=2):
    factory = F.FixtureFactory()
    try:
        spec = factory.build(fixture_id)
        report = F.run_fixture(spec, repeats=repeats)
        return spec, report
    finally:
        factory.cleanup()


def probe_by_classes(report, classes):
    wanted = sorted(classes)
    for probe in report["probes"]:
        if probe["applied_classes"] == wanted:
            return probe
    return None


def make_repo(root: Path, files, ignore=None):
    root.mkdir(parents=True, exist_ok=True)
    D.run_git(["init", "--quiet", "--initial-branch=fixture-main", str(root)])
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (root / ".gitignore").write_text("\n".join(ignore or []) + "\n", encoding="utf-8")
    D.run_git(["add", "--all"], cwd=root)
    D.run_git(
        ["-c", "user.name=T", "-c", "user.email=t@obzio.invalid", "commit", "--quiet", "-m", "t"],
        cwd=root,
    )
    return D.run_git(["rev-parse", "HEAD"], cwd=root).stdout.strip()


class PerClassDetectionTests(unittest.TestCase):
    def assert_single_class(self, fixture_id, expected_class):
        spec, report = build_and_run(fixture_id)
        self.assertEqual(D.VERDICT_ATTRIBUTED, report["verdict"], report["verdict"])
        self.assertEqual([expected_class], report["attributed_classes"])
        self.assertTrue(report["divergent"])
        self.assertFalse(report["interaction_required"])
        self.assertEqual(0, report["warm"]["exit_code"])
        self.assertNotEqual(0, report["clean"]["exit_code"])
        single = probe_by_classes(report, [expected_class])
        self.assertIsNotNone(single)
        self.assertTrue(single["reproduces_warm"])
        return report

    def test_untracked_file_dependency_is_detected_and_attributed(self):
        report = self.assert_single_class("untracked-file-dependency", D.CLASS_UNTRACKED)
        paths = [record["path"] for record in report["hidden_state_inventory"]["untracked_paths"]]
        self.assertIn("local_overrides.json", paths)

    def test_environment_leakage_is_detected_and_attributed(self):
        report = self.assert_single_class("environment-leakage", D.CLASS_ENVIRONMENT)
        keys = [record["key"] for record in report["hidden_state_inventory"]["environment_delta"]]
        self.assertEqual([F.FIXTURE_TOKEN_KEY], keys)

    def test_warm_repo_local_cache_is_detected_and_attributed(self):
        report = self.assert_single_class("warm-cache-repo-local", D.CLASS_WARM_CACHE)
        cache_paths = [record["path"] for record in report["hidden_state_inventory"]["cache_paths"]]
        self.assertIn(".po03-cache/verify.json", cache_paths)
        untracked = [record["path"] for record in report["hidden_state_inventory"]["untracked_paths"]]
        self.assertNotIn(".po03-cache/verify.json", untracked)

    def test_warm_external_cache_is_detected_and_attributed(self):
        report = self.assert_single_class("warm-cache-external-home", D.CLASS_WARM_CACHE)
        external = [
            record["path"] for record in report["hidden_state_inventory"]["external_cache_paths"]
        ]
        self.assertIn("po03-wa-008/entitlement.json", external)


class CleanControlTests(unittest.TestCase):
    def test_pure_control_reports_no_dependency_and_no_hidden_state(self):
        spec, report = build_and_run("clean-control-pure")
        self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
        self.assertFalse(report["divergent"])
        self.assertEqual([], report["probes"])
        self.assertFalse(report["attribution_attempted"])
        self.assertEqual(
            {name: False for name in D.HIDDEN_STATE_CLASSES},
            report["hidden_state_inventory"]["class_present"],
        )

    def test_present_but_unused_hidden_state_is_not_a_false_positive(self):
        spec, report = build_and_run("clean-control-contaminated-but-unused")
        self.assertEqual(
            {name: True for name in D.HIDDEN_STATE_CLASSES},
            report["hidden_state_inventory"]["class_present"],
        )
        self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
        self.assertEqual([], report["attributed_classes"])
        self.assertEqual(0, report["warm"]["exit_code"])
        self.assertEqual(0, report["clean"]["exit_code"])


class InteractionTests(unittest.TestCase):
    def test_two_class_interaction_is_attributed_to_both_necessary_classes(self):
        spec, report = build_and_run("interaction-untracked-and-environment")
        self.assertEqual(D.VERDICT_ATTRIBUTED, report["verdict"])
        self.assertTrue(report["interaction_required"])
        self.assertEqual(
            [D.CLASS_ENVIRONMENT, D.CLASS_UNTRACKED], sorted(report["attributed_classes"])
        )
        for name in (D.CLASS_ENVIRONMENT, D.CLASS_UNTRACKED):
            single = probe_by_classes(report, [name])
            self.assertIsNotNone(single, name)
            self.assertFalse(single["reproduces_warm"], name)
            self.assertEqual("NOT_SUFFICIENT_ALONE", single["role"])
        self.assertIsNotNone(report["closure"])
        self.assertTrue(report["closure"]["reproduces_warm"])
        self.assertEqual(
            [D.CLASS_ENVIRONMENT, D.CLASS_UNTRACKED], sorted(report["necessary_classes"])
        )


class AdversarialBoundTests(unittest.TestCase):
    def test_nondeterministic_command_is_never_attributed_to_hidden_state(self):
        spec, report = build_and_run("nondeterministic-command", repeats=3)
        self.assertEqual(D.VERDICT_NONDETERMINISTIC, report["verdict"])
        self.assertEqual([], report["attributed_classes"])
        self.assertEqual([], report["probes"])
        self.assertFalse(report["attribution_attempted"])
        self.assertIn("warm", report["nondeterministic_sides"])
        # The decoy untracked file is inventoried but not blamed.
        self.assertTrue(report["hidden_state_inventory"]["class_present"][D.CLASS_UNTRACKED])

    def test_silent_hidden_state_read_is_a_documented_false_negative(self):
        spec, report = build_and_run("silent-hidden-state-dependency")
        self.assertTrue(spec["known_false_negative"])
        self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
        self.assertTrue(report["hidden_state_inventory"]["class_present"][D.CLASS_UNTRACKED])
        self.assertEqual([], report["attributed_classes"])

    def test_unattributable_divergence_is_reported_not_blamed(self):
        spec, report = build_and_run("unattributed-git-ref-state")
        self.assertEqual(D.VERDICT_UNATTRIBUTED, report["verdict"])
        self.assertTrue(report["divergent"])
        self.assertEqual([], report["attributed_classes"])
        self.assertIn("unattributed_reason", report)
        self.assertIsNotNone(report["closure"])
        self.assertFalse(report["closure"]["reproduces_warm"])

    def test_differing_checkout_locations_do_not_create_a_false_positive(self):
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-paths-"))
        try:
            repo = root / "source"
            commit = make_repo(
                repo,
                {
                    "workload.py": (
                        "import os, sys\n"
                        "sys.stdout.write('CWD ' + os.getcwd() + '\\n')\n"
                        "raise SystemExit(0)\n"
                    )
                },
            )
            warm = root / "warm"
            D.materialise_clean_checkout(repo, commit, warm)
            report = D.differential_run(
                repo=repo,
                commit=commit,
                command=[sys.executable, "workload.py"],
                warm_checkout=warm,
                warm_env=D.sanitised_environment(root / "h", root / "t", root / "c"),
                warm_cache_root=root / "c",
                repeats=2,
            )
            self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
            self.assertEqual("CWD <CHECKOUT>", report["warm"]["stdout"])
            self.assertEqual("CWD <CHECKOUT>", report["clean"]["stdout"])
            self.assertEqual(report["warm"]["digest"], report["clean"]["digest"])
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_timeout_is_recorded_identically_on_both_sides(self):
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-timeout-"))
        try:
            repo = root / "source"
            commit = make_repo(
                repo, {"workload.py": "import time\ntime.sleep(30)\n"}
            )
            warm = root / "warm"
            D.materialise_clean_checkout(repo, commit, warm)
            report = D.differential_run(
                repo=repo,
                commit=commit,
                command=[sys.executable, "workload.py"],
                warm_checkout=warm,
                warm_env=D.sanitised_environment(root / "h", root / "t", root / "c"),
                warm_cache_root=root / "c",
                repeats=1,
                timeout=1,
            )
            self.assertEqual(124, report["warm"]["exit_code"])
            self.assertEqual(124, report["clean"]["exit_code"])
            self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


class RecurrenceTests(unittest.TestCase):
    def test_classification_digest_recurs_across_independent_fixture_builds(self):
        digests = []
        commits = []
        for _ in range(2):
            spec, report = build_and_run("untracked-file-dependency")
            digests.append(report["classification_digest"])
            commits.append(spec["commit"])
        self.assertEqual(commits[0], commits[1])
        self.assertEqual(digests[0], digests[1])

    def test_classification_digest_separates_distinct_classes(self):
        _, untracked = build_and_run("untracked-file-dependency")
        _, environment = build_and_run("environment-leakage")
        self.assertNotEqual(
            untracked["classification_digest"], environment["classification_digest"]
        )

    def test_report_excludes_wall_time_from_the_classification_digest(self):
        spec, report = build_and_run("clean-control-pure")
        recomputed = dict(report)
        recomputed["timing"] = {"wall_time_seconds": report["timing"]["wall_time_seconds"] + 99.0}
        recomputed["warm"] = dict(report["warm"], wall_time_seconds=123.0)
        recomputed["clean"] = dict(report["clean"], wall_time_seconds=456.0)
        self.assertEqual(
            report["classification_digest"], D.classification_digest(recomputed)
        )


class IsolationTests(unittest.TestCase):
    def test_materialised_checkout_is_pristine_and_shares_no_inode(self):
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-isolation-"))
        try:
            repo = root / "source"
            commit = make_repo(repo, {"payload.txt": "po03-wa-008 isolation payload\n"})
            first = root / "first"
            second = root / "second"
            D.materialise_clean_checkout(repo, commit, first)
            D.materialise_clean_checkout(repo, commit, second)
            self.assertEqual(
                "",
                D.run_git(["status", "--porcelain", "--ignored"], cwd=first).stdout.strip(),
            )
            source_stat = (repo / "payload.txt").stat()
            first_stat = (first / "payload.txt").stat()
            second_stat = (second / "payload.txt").stat()
            self.assertNotEqual(source_stat.st_ino, first_stat.st_ino)
            self.assertNotEqual(first_stat.st_ino, second_stat.st_ino)
            self.assertEqual(1, first_stat.st_nlink)
            # Object stores are independent: no alternates pointing at the source.
            self.assertFalse((first / ".git" / "objects" / "info" / "alternates").exists())
            (first / "payload.txt").write_text("mutated\n", encoding="utf-8")
            self.assertEqual(
                "po03-wa-008 isolation payload\n", (repo / "payload.txt").read_text(encoding="utf-8")
            )
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_clean_side_does_not_inherit_the_ambient_process_environment(self):
        marker_key = "PO03_WA_008_AMBIENT_MARKER"
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-ambient-"))
        previous = os.environ.get(marker_key)
        os.environ[marker_key] = "ambient-value-must-not-reach-the-clean-side"
        try:
            repo = root / "source"
            commit = make_repo(
                repo,
                {
                    "workload.py": (
                        "import os, sys\n"
                        "sys.stdout.write('MARKER ' + str(os.environ.get('"
                        + marker_key
                        + "')) + '\\n')\n"
                    )
                },
            )
            warm = root / "warm"
            D.materialise_clean_checkout(repo, commit, warm)
            report = D.differential_run(
                repo=repo,
                commit=commit,
                command=[sys.executable, "workload.py"],
                warm_checkout=warm,
                warm_cache_root=root / "c",
                repeats=1,
            )
            self.assertIn("MARKER None", report["clean"]["stdout"])
            self.assertIn("MARKER ambient-value", report["warm"]["stdout"])
            self.assertEqual(D.VERDICT_ATTRIBUTED, report["verdict"])
            self.assertIn(D.CLASS_ENVIRONMENT, report["attributed_classes"])
        finally:
            if previous is None:
                os.environ.pop(marker_key, None)
            else:
                os.environ[marker_key] = previous
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_environment_values_are_never_written_to_the_report(self):
        secret_shaped = "po03-wa-008-value-shaped-like-a-credential-0123456789"
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-redaction-"))
        try:
            repo = root / "source"
            commit = make_repo(repo, {"workload.py": "import sys\nsys.stdout.write('ok\\n')\n"})
            warm = root / "warm"
            D.materialise_clean_checkout(repo, commit, warm)
            env = D.sanitised_environment(root / "h", root / "t", root / "c")
            env["PO03_WA_008_PSEUDO_CREDENTIAL"] = secret_shaped
            report = D.differential_run(
                repo=repo,
                commit=commit,
                command=[sys.executable, "workload.py"],
                warm_checkout=warm,
                warm_env=env,
                warm_cache_root=root / "c",
                repeats=1,
            )
            serialised = json.dumps(report)
            self.assertNotIn(secret_shaped, serialised)
            recorded = {
                item["key"]: item
                for item in report["hidden_state_inventory"]["environment_delta"]
            }
            self.assertIn("PO03_WA_008_PSEUDO_CREDENTIAL", recorded)
            self.assertEqual(
                D.sha256_text(secret_shaped),
                recorded["PO03_WA_008_PSEUDO_CREDENTIAL"]["value_sha256"],
            )
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


class ClassificationUnitTests(unittest.TestCase):
    def test_glob_set_claims_cache_directories_and_their_contents(self):
        globs = D.GlobSet(D.DEFAULT_CACHE_GLOBS)
        for path in (
            ".po03-cache/verify.json",
            "nested/dir/.po03-cache/deep/verify.json",
            "pkg/__pycache__/module.cpython-312.pyc",
            "module.pyc",
            ".cache/tool/state.bin",
        ):
            self.assertTrue(globs.matches(path), path)
        for path in ("src/module.py", "cache-notes.md", "data/po03-cache.json"):
            self.assertFalse(globs.matches(path), path)

    def test_cache_and_untracked_classes_are_disjoint(self):
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-inventory-"))
        try:
            repo = root / "source"
            commit = make_repo(repo, {"tracked.txt": "tracked\n"})
            (repo / "extra.txt").write_text("extra\n", encoding="utf-8")
            cache_file = repo / ".po03-cache" / "state.json"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text("{}\n", encoding="utf-8")
            tracked = D.tracked_paths(repo, commit)
            untracked, cache = D.inventory_worktree_extras(
                repo, tracked, D.GlobSet(D.DEFAULT_CACHE_GLOBS)
            )
            untracked_paths = [record["path"] for record in untracked]
            cache_paths = [record["path"] for record in cache]
            self.assertIn("extra.txt", untracked_paths)
            self.assertIn(".po03-cache/state.json", cache_paths)
            self.assertEqual(set(), set(untracked_paths) & set(cache_paths))
            self.assertNotIn("tracked.txt", untracked_paths + cache_paths)
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_volatile_environment_keys_are_not_reported_as_leakage(self):
        baseline = {"PATH": "/usr/bin", "LANG": "C"}
        ambient = {"PATH": "/usr/bin", "LANG": "C", "PWD": "/somewhere", "SHLVL": "3", "_": "/x"}
        self.assertEqual({}, D.environment_delta(ambient, baseline))

    def test_redirected_sandbox_keys_are_not_reported_as_leakage(self):
        baseline = {"HOME": "/sandbox/home", "TMPDIR": "/sandbox/tmp", "XDG_CACHE_HOME": "/sandbox/cache"}
        ambient = {"HOME": "/real/home", "TMPDIR": "/real/tmp", "XDG_CACHE_HOME": "/real/cache"}
        self.assertEqual({}, D.environment_delta(ambient, baseline))


class CommandLineTests(unittest.TestCase):
    def run_cli(self, spec, json_path):
        command = [
            sys.executable,
            str(HERE / "differential_run.py"),
            "--repo",
            str(spec["repo"]),
            "--commit",
            spec["commit"],
            "--command",
            " ".join([sys.executable, "workload.py"]),
            "--warm-checkout",
            str(spec["warm_checkout"]),
            "--warm-cache-root",
            str(spec["warm_cache_root"]),
            "--repeats",
            "1",
            "--json",
            str(json_path),
        ]
        env = dict(spec["warm_env"])
        env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
        return subprocess.run(command, capture_output=True, text=True, env=env)

    def test_cli_exit_codes_encode_the_verdict(self):
        factory = F.FixtureFactory()
        root = Path(tempfile.mkdtemp(prefix="po03-wa-008-cli-"))
        try:
            attributed = factory.build("untracked-file-dependency")
            clean = factory.build("clean-control-pure")

            attributed_json = root / "attributed.json"
            completed = self.run_cli(attributed, attributed_json)
            self.assertEqual(
                D.EXIT_BY_VERDICT[D.VERDICT_ATTRIBUTED], completed.returncode, completed.stderr
            )
            report = json.loads(attributed_json.read_text(encoding="utf-8"))
            self.assertEqual(D.VERDICT_ATTRIBUTED, report["verdict"])
            self.assertEqual([D.CLASS_UNTRACKED], report["attributed_classes"])
            self.assertEqual(D.PROTOCOL_VERSION, report["protocol_version"])

            clean_json = root / "clean.json"
            completed = self.run_cli(clean, clean_json)
            self.assertEqual(
                D.EXIT_BY_VERDICT[D.VERDICT_CLEAN], completed.returncode, completed.stderr
            )
            report = json.loads(clean_json.read_text(encoding="utf-8"))
            self.assertEqual(D.VERDICT_CLEAN, report["verdict"])
        finally:
            factory.cleanup()
            import shutil

            shutil.rmtree(root, ignore_errors=True)


class FixtureMatrixTests(unittest.TestCase):
    def test_every_fixture_matches_its_frozen_expectation(self):
        summary = F.run_matrix(repeats=2)
        failures = [row for row in summary["fixtures"] if row["outcome"] != "PASS"]
        self.assertEqual([], failures, json.dumps(failures, indent=2))
        self.assertEqual(len(F.FIXTURE_IDS), summary["fixture_count"])
        self.assertEqual("PASS", summary["outcome"])
        self.assertGreaterEqual(summary["warm_only_green_mutant_count"], 5)
        self.assertGreaterEqual(summary["clean_control_count"], 2)
        self.assertEqual(1, summary["known_false_negative_count"])
        covered = {row["class_under_test"] for row in summary["fixtures"]}
        for name in D.HIDDEN_STATE_CLASSES:
            self.assertIn(name, covered, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
