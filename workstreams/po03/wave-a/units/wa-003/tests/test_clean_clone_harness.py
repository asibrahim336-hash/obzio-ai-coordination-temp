"""Focused tests and adversarial fixtures for the PO-03 clean-clone harness.

Every contamination class the falsifiable hypothesis names - warm checkout,
uncommitted files, provider/session environment memory and system temporary
directory - gets a fixture that the gate must catch, plus a portable control the
gate must not flag.  The final case is a recurrence test against the enclosing
repository itself.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = UNIT_ROOT / "harness" / "clean_clone_harness.py"
SPEC = importlib.util.spec_from_file_location("po03_clean_clone_harness", HARNESS_PATH)
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
sys.modules["po03_clean_clone_harness"] = HARNESS
SPEC.loader.exec_module(HARNESS)

GIT = shutil.which("git")
PYTHON = shlex.quote(sys.executable)
SUITE_COMMAND = f"{PYTHON} -I -m unittest discover -s suite -p 'test_*.py'"

PASSING_SUITE = """import unittest


class Portable(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(2, 1 + 1)
"""

ENV_DEPENDENT_SUITE = """import os
import unittest


class NeedsProviderMemory(unittest.TestCase):
    def test_token_present(self):
        token = os.environ["PO03_FIXTURE_PROVIDER_TOKEN"]
        print("observed token", token)
        self.assertTrue(token)
"""

HOME_DEPENDENT_SUITE = """import unittest
from pathlib import Path


class NeedsHomeState(unittest.TestCase):
    def test_home_cache_present(self):
        self.assertTrue((Path.home() / ".po03-fixture-cache").is_file())
"""

UNTRACKED_DEPENDENT_SUITE = """import unittest
from pathlib import Path


class NeedsUncommittedFile(unittest.TestCase):
    def test_sibling_present(self):
        self.assertTrue((Path(__file__).parent / "uncommitted_fixture.txt").is_file())
"""

TMP_LITERAL_SUITE = """import unittest

STATE_PATH = "/tmp/po03-fixture-state"


class HardcodedSystemTemp(unittest.TestCase):
    def test_passes_anyway(self):
        self.assertTrue(STATE_PATH.endswith("po03-fixture-state"))
"""

TEMPFILE_SUITE = """import tempfile
import unittest
from pathlib import Path


class PortableTemp(unittest.TestCase):
    def test_uses_tempfile(self):
        with tempfile.NamedTemporaryFile(prefix="po03-fixture-", delete=False) as handle:
            handle.write(b"ok")
            created = Path(handle.name)
        self.assertTrue(created.is_file())
"""

CHECKOUT_MUTATING_SUITE = """import unittest
from pathlib import Path


class MutatesCheckout(unittest.TestCase):
    def test_writes_into_repository(self):
        Path("side-effect.txt").write_text("written by the suite", encoding="utf-8")
        self.assertTrue(Path("side-effect.txt").is_file())
"""


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def make_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(root)], check=True, capture_output=True)
    git(root, "config", "user.email", "po03-fixture@obzio.invalid")
    git(root, "config", "user.name", "PO03 Fixture")
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "fixture")
    return root


def fixture_base_env(**extra: str) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8"}
    env.update(extra)
    return env


def check(report: dict, check_id: str) -> dict:
    for entry in report["checks"]:
        if entry["id"] == check_id:
            return entry
    raise AssertionError(f"check {check_id} absent from report")


class PureHelperTests(unittest.TestCase):
    def test_glob_match_star_stops_at_separator(self):
        self.assertTrue(HARNESS.glob_match("a/b.txt", "a/*.txt"))
        self.assertFalse(HARNESS.glob_match("a/b/c.txt", "a/*.txt"))

    def test_glob_match_double_star_crosses_separators(self):
        pattern = "workstreams/po03/wave-a/units/wa-003/**"
        self.assertTrue(HARNESS.glob_match("workstreams/po03/wave-a/units/wa-003/result/result.json", pattern))
        self.assertTrue(HARNESS.glob_match("workstreams/po03/wave-a/units/wa-003/harness/x.py", pattern))
        self.assertFalse(HARNESS.glob_match("workstreams/po03/wave-a/units/wa-004/result/result.json", pattern))
        self.assertFalse(HARNESS.glob_match("workstreams/po03/control/inputs/wave-a/wa-003.json", pattern))

    def test_glob_match_denylist_prefixes(self):
        self.assertTrue(HARNESS.glob_match("state/operator-system/x.json", "state/**"))
        self.assertTrue(HARNESS.glob_match("workstreams/po01/a/b.md", "workstreams/po01/**"))
        self.assertFalse(HARNESS.glob_match("stateful/x.json", "state/**"))
        self.assertTrue(HARNESS.glob_match(".cursor/environment.json", ".cursor/environment.json"))

    def test_parse_unittest_summary(self):
        parsed = HARNESS.parse_unittest_summary("Ran 17 tests in 0.01s\n\nOK\n")
        self.assertEqual({"tests_ran": 17, "verdict": "OK"}, parsed)
        self.assertEqual({"tests_ran": None, "verdict": None}, HARNESS.parse_unittest_summary("nothing"))

    def test_scrubbed_env_drops_provider_and_secret_names(self):
        base = fixture_base_env(
            CURSOR_AGENT="1",
            CURSOR_CONVERSATION_ID="abc",
            ANTHROPIC_API_KEY="secret-value-123",
            SOME_SERVICE_PASSWORD="another-secret",
            PO03_FIXTURE_PROVIDER_TOKEN="fixture-token-value",
        )
        env = HARNESS.build_scrubbed_env(base, Path("/sandbox/home"), Path("/sandbox/tmp"))
        for dropped in (
            "CURSOR_AGENT",
            "CURSOR_CONVERSATION_ID",
            "ANTHROPIC_API_KEY",
            "SOME_SERVICE_PASSWORD",
            "PO03_FIXTURE_PROVIDER_TOKEN",
        ):
            self.assertNotIn(dropped, env)
        self.assertEqual("/sandbox/home", env["HOME"])
        self.assertEqual("/sandbox/tmp", env["TMPDIR"])
        self.assertEqual({"unexpected": [], "provider": [], "secret_shaped": []}, HARNESS.env_leaks(env))

    def test_env_leaks_flags_injected_provider_variable(self):
        env = HARNESS.build_scrubbed_env(fixture_base_env(), Path("/h"), Path("/t"))
        env["CURSOR_AGENT"] = "1"
        env["SERVICE_API_KEY"] = "x"
        leaks = HARNESS.env_leaks(env)
        self.assertIn("CURSOR_AGENT", leaks["provider"])
        self.assertIn("SERVICE_API_KEY", leaks["secret_shaped"])

    def test_redactor_masks_secret_shaped_values(self):
        base = fixture_base_env(PO03_FIXTURE_PROVIDER_TOKEN="fixture-token-value")
        pattern = HARNESS.build_redactor(base)
        self.assertEqual(
            "observed [REDACTED] here",
            HARNESS.redact("observed fixture-token-value here", pattern),
        )
        self.assertIsNone(HARNESS.build_redactor(fixture_base_env()))

    def test_static_scanner_positive_and_negative(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "suite").mkdir()
            (root / "suite" / "portable.py").write_text(PASSING_SUITE, encoding="utf-8")
            (root / "suite" / "leaky.py").write_text(TMP_LITERAL_SUITE, encoding="utf-8")
            (root / "suite" / "notes.md").write_text("see /tmp/ignored\n", encoding="utf-8")
            findings, scanned = HARNESS.scan_non_portable_literals(root, ["suite"], HARNESS.DEFAULT_SCAN_SUFFIXES, [])
            self.assertEqual(2, scanned, "markdown is outside the default code closure")
            self.assertEqual(["system_tmp"], sorted({item["pattern"] for item in findings}))
            self.assertEqual(["suite/leaky.py"], sorted({item["path"] for item in findings}))

            excluded, _ = HARNESS.scan_non_portable_literals(
                root, ["suite"], HARNESS.DEFAULT_SCAN_SUFFIXES, ["suite/leaky.py"]
            )
            self.assertEqual([], excluded)

    def test_bytecode_residue_classifier(self):
        self.assertTrue(HARNESS.is_bytecode_residue("suite/__pycache__/x.cpython-312.pyc"))
        self.assertTrue(HARNESS.is_bytecode_residue("suite/__pycache__"))
        self.assertTrue(HARNESS.is_bytecode_residue("a/b.pyo"))
        self.assertFalse(HARNESS.is_bytecode_residue("side-effect.txt"))
        self.assertFalse(HARNESS.is_bytecode_residue("suite/test_ok.py"))

    def test_porcelain_path_extraction(self):
        self.assertEqual(
            ["suite/__pycache__/", "side-effect.txt", "new/name.py"],
            HARNESS.porcelain_paths(
                ["?? suite/__pycache__/", " M side-effect.txt", 'R  "old/name.py" -> new/name.py']
            ),
        )

    def test_isolated_suite_command_detection(self):
        self.assertTrue(HARNESS.isolated_suite_command("python -I -m unittest discover"))
        self.assertTrue(HARNESS.isolated_suite_command("/usr/bin/python3 -E -m pytest"))
        self.assertTrue(HARNESS.isolated_suite_command("python3 -Im unittest"))
        self.assertFalse(HARNESS.isolated_suite_command("python -m unittest discover"))
        self.assertFalse(HARNESS.isolated_suite_command("make test --include=I"))

    def test_scanner_reports_missing_scan_path(self):
        with tempfile.TemporaryDirectory() as raw:
            findings, _ = HARNESS.scan_non_portable_literals(
                Path(raw), ["absent"], HARNESS.DEFAULT_SCAN_SUFFIXES, []
            )
            self.assertEqual("missing_scan_path", findings[0]["pattern"])


@unittest.skipUnless(GIT, "git is required for clean-clone fixtures")
class CleanCloneGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def harness(self, source: Path, *, work_name="work", **overrides):
        config_kwargs = {
            "source_repo": str(source),
            "commit": git(source, "rev-parse", "HEAD").strip(),
            "work_root": str(self.root / work_name),
            "suite_command": SUITE_COMMAND,
            "scan_paths": ("suite",),
            "recurrence_clones": 1,
            "base_env": fixture_base_env(),
            "timeout_seconds": 300,
        }
        config_kwargs.update(overrides)
        return HARNESS.run_harness(HARNESS.HarnessConfig(**config_kwargs))

    def test_portable_suite_passes_every_blocking_assertion(self):
        source = make_repo(self.root / "portable", {"suite/test_ok.py": PASSING_SUITE})
        report = self.harness(source, warm_baseline_dir=str(source))
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        self.assertEqual("SUPPORTED", report["hypothesis_outcome"])
        self.assertEqual([], report["blocking_failures"])
        for check_id in ("CC-01", "CC-02", "CC-03", "CC-04", "CC-05", "CC-08", "CC-09", "CC-10", "CC-11", "CC-12", "CC-15", "CC-16", "CC-18"):
            self.assertEqual("PASS", check(report, check_id)["disposition"], check_id)
        self.assertEqual(0, report["runs"]["clean_primary"]["exit_code"])
        self.assertEqual("OK", report["runs"]["clean_primary"]["summary"]["verdict"])

    def test_provider_environment_memory_is_caught_and_warm_run_diverges(self):
        source = make_repo(self.root / "envdep", {"suite/test_env.py": ENV_DEPENDENT_SUITE})
        base = fixture_base_env(PO03_FIXTURE_PROVIDER_TOKEN="fixture-token-value-1234")
        report = self.harness(source, base_env=base, warm_baseline_dir=str(source))
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("REFUTED", report["hypothesis_outcome"])
        self.assertEqual("FAIL", check(report, "CC-11")["disposition"])
        self.assertEqual("PASS", check(report, "CC-09")["disposition"], "scrubbing itself is correct")
        self.assertEqual("FAIL", check(report, "CC-15")["disposition"])
        self.assertIn("warm-only green", check(report, "CC-15")["evidence"])
        self.assertEqual(0, report["runs"]["warm_baseline"]["exit_code"])
        self.assertNotIn("PO03_FIXTURE_PROVIDER_TOKEN", check(report, "CC-09")["detail"]["admitted_names"])
        self.assertEqual(1, check(report, "CC-09")["detail"]["dropped_secret_shaped_count"])

    def test_secret_shaped_values_are_redacted_from_captured_output(self):
        source = make_repo(self.root / "redact", {"suite/test_env.py": ENV_DEPENDENT_SUITE})
        base = fixture_base_env(PO03_FIXTURE_PROVIDER_TOKEN="fixture-token-value-1234")
        report = self.harness(source, base_env=base, warm_baseline_dir=str(source))
        warm_output = report["runs"]["warm_baseline"]["stdout_tail"] + report["runs"]["warm_baseline"]["stderr_tail"]
        self.assertIn("observed token", warm_output)
        self.assertNotIn("fixture-token-value-1234", warm_output)
        self.assertIn("[REDACTED]", warm_output)

    def test_home_directory_state_dependency_is_caught(self):
        source = make_repo(self.root / "homedep", {"suite/test_home.py": HOME_DEPENDENT_SUITE})
        warm_home = self.root / "warm-home"
        warm_home.mkdir()
        (warm_home / ".po03-fixture-cache").write_text("warm", encoding="utf-8")
        report = self.harness(
            source,
            base_env=fixture_base_env(HOME=str(warm_home)),
            warm_baseline_dir=str(source),
        )
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("FAIL", check(report, "CC-11")["disposition"])
        self.assertEqual("FAIL", check(report, "CC-15")["disposition"])
        self.assertEqual("PASS", check(report, "CC-10")["disposition"])

    def test_uncommitted_file_dependency_is_caught(self):
        source = make_repo(self.root / "untracked", {"suite/test_untracked.py": UNTRACKED_DEPENDENT_SUITE})
        (source / "suite" / "uncommitted_fixture.txt").write_text("warm only", encoding="utf-8")
        report = self.harness(source, warm_baseline_dir=str(source))
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("PASS", check(report, "CC-04")["disposition"], "the clone itself is consistent")
        self.assertEqual("FAIL", check(report, "CC-11")["disposition"])
        self.assertEqual("FAIL", check(report, "CC-15")["disposition"])
        self.assertEqual("INCONCLUSIVE", check(report, "CC-16")["disposition"])
        self.assertIn("suite/uncommitted_fixture.txt", " ".join(check(report, "CC-16")["detail"]["porcelain"]))

    def test_hardcoded_system_temp_survives_tmpdir_redirection_but_fails_static_scan(self):
        source = make_repo(self.root / "tmplit", {"suite/test_tmp.py": TMP_LITERAL_SUITE})
        report = self.harness(source)
        self.assertEqual("PASS", check(report, "CC-11")["disposition"], "TMPDIR redirection cannot see a literal")
        self.assertEqual("FAIL", check(report, "CC-08")["disposition"])
        self.assertEqual(
            ["system_tmp"],
            sorted({item["pattern"] for item in check(report, "CC-08")["detail"]["findings"]}),
        )
        self.assertEqual("FAIL", report["overall"])

    def test_tempfile_using_suite_writes_only_into_the_sandbox(self):
        source = make_repo(self.root / "tempok", {"suite/test_temp.py": TEMPFILE_SUITE})
        report = self.harness(source)
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        sandbox_entries = check(report, "CC-13")["detail"]["sandbox_tmp_entries_after"]
        self.assertTrue(
            any(name.startswith("po03-fixture-") for name in sandbox_entries),
            sandbox_entries,
        )
        # The system temporary directory is shared, so CC-13 may only weaken to
        # INCONCLUSIVE; it must never be a blocking failure.
        self.assertIn(check(report, "CC-13")["disposition"], {"PASS", "INCONCLUSIVE"})
        self.assertFalse(check(report, "CC-13")["blocking"])

    def test_committed_warm_build_residue_is_caught(self):
        source = make_repo(
            self.root / "residue",
            {"suite/test_ok.py": PASSING_SUITE, "suite/__pycache__/test_ok.cpython-312.pyc": b"\x00stale"},
        )
        report = self.harness(source)
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("FAIL", check(report, "CC-05")["disposition"])
        self.assertIn(
            "suite/__pycache__/test_ok.cpython-312.pyc",
            check(report, "CC-05")["detail"]["residue"],
        )

    def test_isolated_mode_makes_bytecode_suppression_inert_and_is_reported(self):
        source = make_repo(self.root / "bytecode", {"suite/test_ok.py": PASSING_SUITE})
        report = self.harness(source)
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        hardening = check(report, "CC-20")
        self.assertEqual("INFO", hardening["disposition"])
        self.assertFalse(hardening["blocking"])
        self.assertTrue(hardening["detail"]["suite_command_isolated"])
        self.assertTrue(hardening["detail"]["probe_suite_flags"]["ignore_environment"])
        self.assertFalse(hardening["detail"]["probe_suite_flags"]["dont_write_bytecode"])
        self.assertTrue(
            hardening["detail"]["probe_without_isolation"]["dont_write_bytecode"],
            "without -I the same scrubbed environment does suppress bytecode",
        )
        residue = check(report, "CC-19")
        self.assertEqual("INFO", residue["disposition"])
        self.assertTrue(
            any("__pycache__" in path for path in residue["detail"]["bytecode_paths"]),
            residue["detail"],
        )
        self.assertEqual(
            "PASS",
            check(report, "CC-12")["disposition"],
            "bytecode caches are residue, not a semantic mutation",
        )

    def test_non_isolated_suite_command_suppresses_bytecode_entirely(self):
        source = make_repo(self.root / "dashb", {"suite/test_ok.py": PASSING_SUITE})
        report = self.harness(
            source,
            suite_command=f"{PYTHON} -B -m unittest discover -s suite -p 'test_*.py'",
        )
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        self.assertEqual("PASS", check(report, "CC-19")["disposition"])
        self.assertEqual([], check(report, "CC-19")["detail"]["bytecode_paths"])
        self.assertEqual("PASS", check(report, "CC-12")["disposition"])

    def test_suite_that_mutates_its_own_checkout_is_caught(self):
        source = make_repo(self.root / "mutating", {"suite/test_mutate.py": CHECKOUT_MUTATING_SUITE})
        report = self.harness(source)
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("PASS", check(report, "CC-11")["disposition"])
        self.assertEqual("FAIL", check(report, "CC-12")["disposition"])
        self.assertIn("side-effect.txt", " ".join(check(report, "CC-12")["detail"]["porcelain"]))

    def test_unresolvable_provenance_pin_is_caught_and_prefix_is_reported(self):
        source = make_repo(self.root / "pins", {"suite/test_ok.py": PASSING_SUITE})
        head = git(source, "rev-parse", "HEAD").strip()
        padded = head[:7] + "0" * 33
        self.assertNotEqual(head, padded)
        report = self.harness(source, require_pins=(f"{head}:ancestor", f"{padded}:ancestor"))
        self.assertEqual("FAIL", report["overall"])
        pins = {item["pin"]: item for item in check(report, "CC-06")["detail"]["pins"]}
        self.assertTrue(pins[head]["resolves"])
        self.assertTrue(pins[head]["ancestor_of_head"])
        self.assertFalse(pins[padded]["resolves"])
        self.assertEqual(head, pins[padded]["prefix_resolves_to"])

    def test_recurrence_across_two_independent_clean_clones(self):
        source = make_repo(self.root / "recurrence", {"suite/test_ok.py": PASSING_SUITE})
        report = self.harness(source, recurrence_clones=2)
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        recurrence = check(report, "CC-17")
        self.assertEqual("PASS", recurrence["disposition"])
        observations = recurrence["detail"]["observations"]
        self.assertEqual(2, len(observations))
        self.assertEqual(1, len({(o["head"], o["tree"], o["exit_code"]) for o in observations}))
        self.assertEqual({"clone-1", "clone-2"}, {o["clone"] for o in observations})

    def test_harness_refuses_to_reuse_a_warm_clone_target(self):
        source = make_repo(self.root / "reuse", {"suite/test_ok.py": PASSING_SUITE})
        (self.root / "work" / "clone-1").mkdir(parents=True)
        with self.assertRaises(HARNESS.HarnessError) as raised:
            self.harness(source)
        self.assertIn("clone-1", str(raised.exception))

    def test_harness_creates_nothing_outside_its_work_root(self):
        source = make_repo(self.root / "confined", {"suite/test_ok.py": PASSING_SUITE})
        before = {path.relative_to(self.root).as_posix() for path in self.root.rglob("*")}
        report = self.harness(source)
        after = {path.relative_to(self.root).as_posix() for path in self.root.rglob("*")}
        outside = sorted(path for path in after - before if path != "work" and not path.startswith("work/"))
        self.assertEqual([], outside)
        self.assertEqual("PASS", check(report, "CC-18")["disposition"])
        for created in check(report, "CC-18")["detail"]["created_paths"]:
            self.assertTrue(created.startswith(str(self.root / "work")), created)

    def test_cli_writes_receipt_and_returns_failure_exit_code(self):
        source = make_repo(self.root / "cli", {"suite/test_tmp.py": TMP_LITERAL_SUITE})
        head = git(source, "rev-parse", "HEAD").strip()
        receipt = self.root / "receipts" / "cli.json"
        code = HARNESS.main(
            [
                "--source-repo",
                str(source),
                "--commit",
                head,
                "--work-root",
                str(self.root / "cli-work"),
                "--suite-command",
                SUITE_COMMAND,
                "--scan-path",
                "suite",
                "--recurrence-clones",
                "1",
                "--receipt",
                str(receipt),
                "--label",
                "cli-fixture",
            ]
        )
        self.assertEqual(1, code)
        report = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual("FAIL", report["overall"])
        self.assertEqual("cli-fixture", report["label"])
        self.assertEqual(HARNESS.SCHEMA_VERSION, report["schema_version"])

    def test_cli_rejects_short_commit(self):
        source = make_repo(self.root / "shortsha", {"suite/test_ok.py": PASSING_SUITE})
        code = HARNESS.main(
            [
                "--source-repo",
                str(source),
                "--commit",
                "deadbee",
                "--work-root",
                str(self.root / "short-work"),
                "--suite-command",
                SUITE_COMMAND,
            ]
        )
        self.assertEqual(2, code)


def repository_root() -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(UNIT_ROOT), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


@unittest.skipUnless(GIT, "git is required for the repository recurrence test")
class RepositoryRecurrenceTests(unittest.TestCase):
    """Recurrence test on the repository-native PO-03 contract suite."""

    SEEDED_SUITE = f"{PYTHON} -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'"

    def test_seeded_po03_suite_recurs_from_two_independent_clean_clones(self):
        root = repository_root()
        if root is None:
            self.skipTest("not inside a git work tree")
        head = git(root, "rev-parse", "HEAD").strip()
        with tempfile.TemporaryDirectory() as raw:
            report = HARNESS.run_harness(
                HARNESS.HarnessConfig(
                    source_repo=str(root),
                    commit=head,
                    work_root=str(Path(raw) / "work"),
                    suite_command=self.SEEDED_SUITE,
                    scan_paths=(
                        "workstreams/po03/tests",
                        "workstreams/po03/tools/validate_contracts.py",
                        "workstreams/po03/contracts",
                    ),
                    recurrence_clones=2,
                    label="repository-recurrence",
                )
            )
        self.assertEqual("PASS", report["overall"], report["blocking_failures"])
        self.assertEqual("PASS", check(report, "CC-17")["disposition"])
        self.assertEqual("OK", report["runs"]["clean_primary"]["summary"]["verdict"])
        self.assertEqual("OK", report["runs"]["clean_recurrence_2"]["summary"]["verdict"])
        self.assertEqual(
            report["runs"]["clean_primary"]["summary"]["tests_ran"],
            report["runs"]["clean_recurrence_2"]["summary"]["tests_ran"],
        )


if __name__ == "__main__":
    unittest.main()
