import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = UNIT_ROOT / "portable_path_scanner.py"
MEASUREMENT_PATH = UNIT_ROOT / "measure_false_positives.py"
MANIFEST_PATH = UNIT_ROOT / "fixtures" / "case-manifest.json"
POSITIVE_PATH = UNIT_ROOT / "fixtures" / "positive.txt"
NEGATIVE_PATH = UNIT_ROOT / "fixtures" / "negative.txt"
ADVERSARIAL_PATH = UNIT_ROOT / "fixtures" / "adversarial.txt"
CHECKOUT_ROOT = "/var/lib/ci/checkouts/run-9281/repo"

SCANNER_SPEC = importlib.util.spec_from_file_location("wa007_scanner", SCANNER_PATH)
SCANNER = importlib.util.module_from_spec(SCANNER_SPEC)
assert SCANNER_SPEC.loader is not None
sys.modules[SCANNER_SPEC.name] = SCANNER
SCANNER_SPEC.loader.exec_module(SCANNER)

MEASUREMENT_SPEC = importlib.util.spec_from_file_location(
    "wa007_measurement", MEASUREMENT_PATH
)
MEASUREMENT = importlib.util.module_from_spec(MEASUREMENT_SPEC)
assert MEASUREMENT_SPEC.loader is not None
sys.modules[MEASUREMENT_SPEC.name] = MEASUREMENT
MEASUREMENT_SPEC.loader.exec_module(MEASUREMENT)


class DetectionTests(unittest.TestCase):
    def test_labelled_corpus_has_zero_false_positives_and_false_negatives(self):
        result = MEASUREMENT.measure(MANIFEST_PATH)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(
            {
                "case_count": 67,
                "positive_case_count": 23,
                "negative_case_count": 44,
                "true_positive": 23,
                "true_negative": 44,
                "false_positive": 0,
                "false_negative": 0,
                "false_positive_rate": 0.0,
                "recall": 1.0,
            },
            result["metrics"],
        )
        self.assertEqual([], result["category_misses"])
        self.assertEqual([], result["scan_errors"])

    def test_deliberate_negative_fixture_is_clean(self):
        report = SCANNER.scan_paths([NEGATIVE_PATH], checkout_roots=[CHECKOUT_ROOT])
        self.assertEqual("CLEAN", report["status"])
        self.assertEqual([], report["findings"])
        self.assertEqual(36, len(NEGATIVE_PATH.read_text(encoding="utf-8").splitlines()))

    def test_required_categories_are_all_observed(self):
        report = SCANNER.scan_paths([POSITIVE_PATH], checkout_roots=[CHECKOUT_ROOT])
        categories = {
            category
            for finding in report["findings"]
            for category in finding["categories"]
        }
        self.assertEqual(
            {
                "absolute-posix",
                "absolute-windows",
                "home-relative",
                "temporary",
                "checkout-specific",
            },
            categories,
        )

    def test_checkout_match_requires_component_boundary(self):
        report = SCANNER.scan_paths([ADVERSARIAL_PATH], checkout_roots=[CHECKOUT_ROOT])
        line_16 = next(
            finding for finding in report["findings"] if finding["line"] == 16
        )
        self.assertIn("absolute-posix", line_16["categories"])
        self.assertNotIn("checkout-specific", line_16["categories"])
        line_17 = next(
            finding for finding in report["findings"] if finding["line"] == 17
        )
        self.assertIn("checkout-specific", line_17["categories"])

    def test_quoted_and_escaped_spaces_remain_one_token(self):
        report = SCANNER.scan_paths([POSITIVE_PATH, ADVERSARIAL_PATH])
        tokens = {finding["token"] for finding in report["findings"]}
        self.assertIn("/home/alice/Project Files/report final.txt", tokens)
        self.assertIn("/home/alice/My\\ Project/out.txt", tokens)
        self.assertIn("D:/Build Agent/work/output.log", tokens)

    def test_file_uri_is_classified_by_underlying_path(self):
        findings = SCANNER.scan_text(
            "file:///tmp/output.json\n",
            logical_path="fixture.txt",
        )
        self.assertEqual(1, len(findings))
        self.assertEqual(
            ["absolute-posix", "temporary"],
            findings[0]["categories"],
        )

    def test_quoted_path_does_not_duplicate_bare_match(self):
        findings = SCANNER.scan_text(
            '"/home/alice/repo/file.txt"\n',
            logical_path="fixture.txt",
        )
        self.assertEqual(1, len(findings))

    def test_pseudo_paths_and_urls_are_suppressed(self):
        text = "\n".join(
            [
                "https://example.test/home/alice/output",
                "#/components/schemas/Thing",
                "^/home/alice/.*$",
                "/v3/users",
                "/users/{user_id}",
                "/healthz",
            ]
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(text, logical_path="pseudo.txt"),
        )


class ClosureTests(unittest.TestCase):
    def test_binary_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(b"text\0binary")
            report = SCANNER.scan_paths([path])
        self.assertEqual("ERROR", report["status"])
        self.assertEqual("BINARY_FILE_NOT_EXCLUDED", report["errors"][0]["code"])

    def test_invalid_utf8_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.txt"
            path.write_bytes(b"\xff")
            report = SCANNER.scan_paths([path])
        self.assertEqual("ERROR", report["status"])
        self.assertEqual("NON_UTF8_FILE_NOT_EXCLUDED", report["errors"][0]["code"])

    def test_explicit_exclusion_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.txt").write_text("portable\n", encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            (cache / "skip.bin").write_bytes(b"\0")
            report = SCANNER.scan_paths([root], exclude_globs=["cache/**"])
        self.assertEqual("CLEAN", report["status"])
        self.assertEqual(1, report["closure"]["scanned_file_count"])
        self.assertEqual(1, report["closure"]["excluded_path_count"])
        self.assertEqual("cache/**", report["closure"]["excluded"][0]["pattern"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            target.write_text("portable\n", encoding="utf-8")
            (root / "link.txt").symlink_to(target)
            report = SCANNER.scan_paths([root])
        self.assertEqual("ERROR", report["status"])
        self.assertTrue(
            any(error["code"] == "SYMLINK_IN_CLOSURE" for error in report["errors"])
        )

    def test_overlapping_roots_fail_as_duplicate_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "artifact.txt"
            path.write_text("portable\n", encoding="utf-8")
            report = SCANNER.scan_paths([root, path])
        self.assertEqual("ERROR", report["status"])
        self.assertTrue(
            any(
                error["code"] == "DUPLICATE_FILE_IN_CLOSURE"
                for error in report["errors"]
            )
        )

    def test_checkout_root_must_be_absolute(self):
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            SCANNER.scan_paths([NEGATIVE_PATH], checkout_roots=["relative/checkout"])


class BlackBoxCliTests(unittest.TestCase):
    def run_cli(self, program, *arguments):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(program), *map(str, arguments)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_positive_cli_returns_one_with_json_findings(self):
        process = self.run_cli(
            SCANNER_PATH,
            "--checkout-root",
            CHECKOUT_ROOT,
            POSITIVE_PATH,
        )
        self.assertEqual(1, process.returncode, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("FINDINGS", report["status"])
        self.assertEqual(14, report["summary"]["finding_count"])

    def test_negative_cli_returns_zero(self):
        process = self.run_cli(SCANNER_PATH, NEGATIVE_PATH)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("CLEAN", json.loads(process.stdout)["status"])

    def test_missing_root_returns_two_and_structured_error(self):
        process = self.run_cli(SCANNER_PATH, UNIT_ROOT / "does-not-exist")
        self.assertEqual(2, process.returncode, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("ERROR", report["status"])
        self.assertEqual("MISSING_ROOT", report["errors"][0]["code"])

    def test_measurement_cli_passes_in_isolated_mode(self):
        process = self.run_cli(MEASUREMENT_PATH, "--manifest", MANIFEST_PATH)
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(0.0, result["metrics"]["false_positive_rate"])


if __name__ == "__main__":
    unittest.main()
