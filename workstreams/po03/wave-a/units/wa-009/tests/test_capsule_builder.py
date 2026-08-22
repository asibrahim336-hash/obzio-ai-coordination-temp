from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
BUILDER_PATH = UNIT_ROOT / "capsule_builder.py"
SOURCE_ROOT = UNIT_ROOT / "fixtures" / "source"
REQUEST_ROOT = UNIT_ROOT / "fixtures" / "requests"
EXPECTED_CAPSULE = UNIT_ROOT / "reproduction" / "capsule"

SPEC = importlib.util.spec_from_file_location("wa009_capsule_builder", BUILDER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_request(name: str = "valid.json") -> dict:
    return json.loads((REQUEST_ROOT / name).read_text(encoding="utf-8"))


def refresh_snapshot(request: dict) -> None:
    request["source_snapshot_sha256"] = MODULE.source_snapshot_sha256(
        request["sources"]
    )


class CapsuleBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temp_root = Path(self.temporary.name)

    def write_request(self, request: dict, name: str = "request.json") -> Path:
        path = self.temp_root / name
        path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def assert_rejected(
        self,
        code: str,
        request: dict | None = None,
        request_name: str | None = None,
        source_root: Path = SOURCE_ROOT,
        output_name: str = "capsule",
    ):
        request_path = (
            REQUEST_ROOT / request_name
            if request_name is not None
            else self.write_request(request if request is not None else read_request())
        )
        output = self.temp_root / output_name
        with self.assertRaises(MODULE.CapsuleError) as caught:
            MODULE.build_capsule(source_root, request_path, output)
        self.assertEqual(code, caught.exception.code)
        self.assertFalse(output.exists(), "a rejected build left partial output")
        return caught.exception

    def test_build_admits_exact_sources_and_excludes_unrelated_file(self):
        output = self.temp_root / "capsule"
        manifest = MODULE.build_capsule(
            SOURCE_ROOT, REQUEST_ROOT / "valid.json", output
        )
        relative_files = sorted(
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        )
        self.assertEqual(
            [
                "capsule-manifest.json",
                "docs/critical.txt",
                "docs/relevant.txt",
            ],
            relative_files,
        )
        self.assertFalse((output / "docs" / "unrelated.txt").exists())
        self.assertEqual(2, manifest["source_count"])
        self.assertEqual(121, manifest["source_bytes"])

    def test_manifest_accounts_hashes_bytes_critical_set_and_budgets(self):
        output = self.temp_root / "capsule"
        manifest = MODULE.build_capsule(
            SOURCE_ROOT, REQUEST_ROOT / "valid.json", output
        )
        self.assertEqual(["docs/critical.txt"], manifest["critical_sources"])
        self.assertEqual(39, manifest["budget"]["remaining_bytes"])
        self.assertEqual(1, manifest["budget"]["remaining_sources"])
        for source in manifest["sources"]:
            content = (output / source["path"]).read_bytes()
            self.assertEqual(len(content), source["bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), source["sha256"])

    def test_repeated_builds_are_byte_identical(self):
        first = self.temp_root / "first"
        second = self.temp_root / "second"
        MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", first)
        MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", second)
        first_files = sorted(
            path.relative_to(first).as_posix()
            for path in first.rglob("*")
            if path.is_file()
        )
        second_files = sorted(
            path.relative_to(second).as_posix()
            for path in second.rglob("*")
            if path.is_file()
        )
        self.assertEqual(first_files, second_files)
        for relative in first_files:
            self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())

    def test_semantically_equivalent_source_order_has_same_manifest(self):
        request = read_request()
        request["sources"].reverse()
        request["allowed_relevance_tags"].reverse()
        request_path = self.write_request(request)
        first = self.temp_root / "first"
        second = self.temp_root / "second"
        MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", first)
        MODULE.build_capsule(SOURCE_ROOT, request_path, second)
        self.assertEqual(
            (first / "capsule-manifest.json").read_bytes(),
            (second / "capsule-manifest.json").read_bytes(),
        )

    def test_committed_reproduction_matches_fresh_build(self):
        fresh = self.temp_root / "fresh"
        MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", fresh)
        expected_files = sorted(
            path.relative_to(EXPECTED_CAPSULE).as_posix()
            for path in EXPECTED_CAPSULE.rglob("*")
            if path.is_file()
        )
        fresh_files = sorted(
            path.relative_to(fresh).as_posix()
            for path in fresh.rglob("*")
            if path.is_file()
        )
        self.assertEqual(expected_files, fresh_files)
        for relative in fresh_files:
            self.assertEqual(
                (EXPECTED_CAPSULE / relative).read_bytes(),
                (fresh / relative).read_bytes(),
            )

    def test_explicit_over_byte_budget_fixture_is_rejected(self):
        error = self.assert_rejected(
            "BYTE_BUDGET_EXCEEDED",
            request_name="over-byte-budget.json",
        )
        self.assertEqual(120, error.details["max_bytes"])
        self.assertEqual(121, error.details["observed_bytes"])

    def test_explicit_omitted_critical_fixture_is_rejected(self):
        error = self.assert_rejected(
            "MISSING_CRITICAL_SOURCE",
            request_name="omitted-critical-source.json",
        )
        self.assertEqual(["docs/critical.txt"], error.details["omitted"])

    def test_source_count_budget_is_enforced_before_output(self):
        request = read_request()
        request["budget"]["max_sources"] = 1
        self.assert_rejected("SOURCE_BUDGET_EXCEEDED", request)

    def test_exact_byte_budget_is_admitted(self):
        request = read_request()
        request["budget"]["max_bytes"] = 121
        output = self.temp_root / "capsule"
        manifest = MODULE.build_capsule(
            SOURCE_ROOT, self.write_request(request), output
        )
        self.assertEqual(0, manifest["budget"]["remaining_bytes"])

    def test_source_hash_mismatch_is_rejected(self):
        request = read_request()
        request["sources"][1]["sha256"] = "0" * 64
        refresh_snapshot(request)
        self.assert_rejected("SOURCE_HASH_MISMATCH", request)

    def test_source_snapshot_mismatch_is_rejected(self):
        request = read_request()
        request["source_snapshot_sha256"] = "0" * 64
        self.assert_rejected("SNAPSHOT_HASH_MISMATCH", request)

    def test_duplicate_source_is_rejected(self):
        request = read_request()
        request["sources"].append(copy.deepcopy(request["sources"][0]))
        self.assert_rejected("DUPLICATE_SOURCE", request)

    def test_required_source_must_be_marked_critical(self):
        request = read_request()
        request["sources"][0]["critical"] = False
        self.assert_rejected("CRITICAL_SET_MISMATCH", request)

    def test_critical_flag_requires_required_source_declaration(self):
        request = read_request()
        request["sources"][1]["critical"] = True
        self.assert_rejected("CRITICAL_SET_MISMATCH", request)

    def test_each_source_requires_relevance_tags(self):
        request = read_request()
        request["sources"][1]["relevance_tags"] = []
        self.assert_rejected("MISSING_RELEVANCE", request)

    def test_disallowed_relevance_tag_is_rejected(self):
        request = read_request()
        request["sources"][1]["relevance_tags"] = ["unrelated-strategy"]
        self.assert_rejected("IRRELEVANT_SOURCE", request)

    def test_empty_relevance_rationale_is_rejected(self):
        request = read_request()
        request["sources"][1]["rationale"] = " "
        self.assert_rejected("MISSING_RELEVANCE", request)

    def test_noncanonical_and_escaping_paths_are_rejected(self):
        for path in ("/etc/passwd", "../escape.txt", "docs\\relevant.txt", "."):
            with self.subTest(path=path):
                request = read_request()
                request["sources"][1]["path"] = path
                self.assert_rejected(
                    "INVALID_PATH",
                    request,
                    output_name=f"capsule-{hashlib.sha256(path.encode()).hexdigest()[:8]}",
                )

    def test_symlink_source_is_rejected(self):
        copied_source = self.temp_root / "source"
        shutil.copytree(SOURCE_ROOT, copied_source)
        relevant = copied_source / "docs" / "relevant.txt"
        relevant.unlink()
        os.symlink("critical.txt", relevant)
        self.assert_rejected("SYMLINK_SOURCE", source_root=copied_source)

    def test_missing_source_is_rejected(self):
        request = read_request()
        request["sources"][1]["path"] = "docs/missing.txt"
        refresh_snapshot(request)
        self.assert_rejected("SOURCE_NOT_FOUND", request)

    def test_directory_cannot_be_admitted_as_source(self):
        request = read_request()
        request["sources"][1]["path"] = "docs"
        refresh_snapshot(request)
        self.assert_rejected("SOURCE_NOT_REGULAR", request)

    def test_existing_output_is_never_overwritten(self):
        output = self.temp_root / "capsule"
        output.mkdir()
        marker = output / "marker"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(MODULE.CapsuleError) as caught:
            MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", output)
        self.assertEqual("OUTPUT_EXISTS", caught.exception.code)
        self.assertEqual("preserve", marker.read_text(encoding="utf-8"))

    def test_missing_output_parent_is_rejected_without_creation(self):
        output = self.temp_root / "missing" / "capsule"
        with self.assertRaises(MODULE.CapsuleError) as caught:
            MODULE.build_capsule(SOURCE_ROOT, REQUEST_ROOT / "valid.json", output)
        self.assertEqual("OUTPUT_PARENT_MISSING", caught.exception.code)
        self.assertFalse(output.parent.exists())

    def test_malformed_request_json_is_rejected(self):
        request_path = self.temp_root / "bad.json"
        request_path.write_text("{", encoding="utf-8")
        output = self.temp_root / "capsule"
        with self.assertRaises(MODULE.CapsuleError) as caught:
            MODULE.build_capsule(SOURCE_ROOT, request_path, output)
        self.assertEqual("INVALID_REQUEST_JSON", caught.exception.code)
        self.assertFalse(output.exists())

    def test_unexpected_request_field_is_rejected(self):
        request = read_request()
        request["ambient_context"] = "not admitted"
        self.assert_rejected("INVALID_REQUEST_FIELDS", request)

    def test_cli_success_is_machine_readable(self):
        output = self.temp_root / "capsule"
        completed = subprocess.run(
            [
                sys.executable,
                str(BUILDER_PATH),
                "--source-root",
                str(SOURCE_ROOT),
                "--request",
                str(REQUEST_ROOT / "valid.json"),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual("BUILT", response["status"])
        self.assertEqual(2, response["source_count"])
        self.assertEqual(121, response["source_bytes"])

    def test_cli_rejection_is_machine_readable(self):
        output = self.temp_root / "capsule"
        completed = subprocess.run(
            [
                sys.executable,
                str(BUILDER_PATH),
                "--source-root",
                str(SOURCE_ROOT),
                "--request",
                str(REQUEST_ROOT / "over-byte-budget.json"),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, completed.returncode)
        response = json.loads(completed.stderr)
        self.assertEqual("REJECTED", response["status"])
        self.assertEqual("BYTE_BUDGET_EXCEEDED", response["error"]["code"])
        self.assertFalse(output.exists())

    def test_repository_recurrence_entrypoint(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(UNIT_ROOT / "verify_recurrence.py"),
                "--repo-root",
                str(UNIT_ROOT.parents[4]),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual("PASS", response["status"])
        self.assertEqual(2, response["deterministic_rebuilds"])
        self.assertEqual(2, len(response["negative_fixtures"]))


if __name__ == "__main__":
    unittest.main()
