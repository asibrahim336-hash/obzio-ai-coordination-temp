#!/usr/bin/env python3
"""Prove that source-lock regeneration is reproducible and that source drift fails."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
FIXTURES = UNIT_ROOT / "fixtures" / "synthetic"

sys.path.insert(0, str(UNIT_ROOT / "tools"))

import source_lock  # noqa: E402

# Blob object names published by Git's own object-format documentation. They are an
# external oracle: our implementation must agree without ever calling Git.
GIT_BLOB_ORACLE = {
    b"": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
    b"hello\n": "ce013625030ba8dba906f756967f9e9ca394464a",
    b"what is up, doc?": "bd9dbf5aae1a3862dd1526723246b20206e5fc37",
}

ALLOWED_IMPORTS = {"__future__", "argparse", "hashlib", "json", "sys", "pathlib"}
FORBIDDEN_IMPORTS = {
    "asyncio",
    "ftplib",
    "http",
    "os",
    "requests",
    "socket",
    "ssl",
    "subprocess",
    "telnetlib",
    "urllib",
    "xmlrpc",
}


def apply_mutation(root: Path, mutation: dict) -> None:
    target = root / mutation["path"]
    kind = mutation["type"]
    if kind == "delete":
        target.unlink()
        return
    if kind == "replace_with_directory":
        target.unlink()
        target.mkdir()
        return
    if kind == "create":
        target.write_bytes(bytes.fromhex(mutation["hex"]))
        return
    payload = bytearray(target.read_bytes())
    if kind == "replace_bytes":
        offset = mutation["offset"]
        patch = bytes.fromhex(mutation["hex"])
        payload[offset : offset + len(patch)] = patch
    elif kind == "swap_bytes":
        first, second = mutation["offset_a"], mutation["offset_b"]
        payload[first], payload[second] = payload[second], payload[first]
    elif kind == "truncate":
        del payload[mutation["length"] :]
    elif kind == "append":
        payload.extend(bytes.fromhex(mutation["hex"]))
    elif kind == "crlf":
        payload = bytearray(bytes(payload).replace(b"\n", b"\r\n"))
    else:
        raise AssertionError(f"unsupported mutation type in fixture: {kind}")
    target.write_bytes(bytes(payload))


class GitBlobIdentityTest(unittest.TestCase):
    def test_matches_published_git_object_names(self) -> None:
        for payload, expected in GIT_BLOB_ORACLE.items():
            with self.subTest(length=len(payload)):
                self.assertEqual(source_lock.git_blob_sha1(payload), expected)

    def test_distinguishes_same_length_payloads(self) -> None:
        self.assertNotEqual(
            source_lock.git_blob_sha1(b"ab"),
            source_lock.git_blob_sha1(b"ba"),
        )


class HermeticityTest(unittest.TestCase):
    """The mechanism must be executable from bytes alone: no shell, no network."""

    def setUp(self) -> None:
        self.source = (UNIT_ROOT / "tools" / "source_lock.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def imported_roots(self) -> set[str]:
        roots: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        return roots

    def test_imports_are_within_the_declared_allowlist(self) -> None:
        self.assertEqual(self.imported_roots() - ALLOWED_IMPORTS, set())

    def test_no_process_or_network_imports(self) -> None:
        self.assertEqual(self.imported_roots() & FORBIDDEN_IMPORTS, set())

    def test_no_dynamic_execution(self) -> None:
        called = {
            node.func.id
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertEqual(called & {"eval", "exec", "compile", "__import__"}, set())


class RegenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = source_lock.load_spec(FIXTURES / "spec.json")
        self.committed = (FIXTURES / "source-lock.json").read_bytes()

    def test_regeneration_reproduces_committed_fixture_byte_for_byte(self) -> None:
        rebuilt = source_lock.canonical_json(
            source_lock.regenerate(FIXTURES / "tree", self.spec)
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(rebuilt).hexdigest(),
            hashlib.sha256(self.committed).hexdigest(),
        )
        self.assertEqual(rebuilt, self.committed)

    def test_regeneration_is_idempotent(self) -> None:
        first = source_lock.canonical_json(source_lock.regenerate(FIXTURES / "tree", self.spec))
        second = source_lock.canonical_json(source_lock.regenerate(FIXTURES / "tree", self.spec))
        self.assertEqual(first, second)

    def test_declaration_order_is_preserved(self) -> None:
        document = source_lock.regenerate(FIXTURES / "tree", self.spec)
        self.assertEqual(
            [entry["path"] for entry in document["sources"]],
            self.spec["source_paths"],
        )

    def test_no_derived_field_is_supplied_by_the_spec(self) -> None:
        raw = json.loads((FIXTURES / "spec.json").read_text(encoding="utf-8"))
        serialised = json.dumps(raw["metadata"])
        for field in source_lock.DERIVED_FIELDS:
            self.assertNotIn(field, serialised)


class DetectionMatrixTest(unittest.TestCase):
    """Every declared mutation case must produce its recorded verification outcome."""

    def setUp(self) -> None:
        self.cases = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]
        self.lock = source_lock.load_lock(FIXTURES / "source-lock.json")

    def run_case(self, case: dict) -> dict:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "tree"
            shutil.copytree(FIXTURES / "tree", root)
            for mutation in case["mutations"]:
                apply_mutation(root, mutation)
            return source_lock.verify(root, self.lock)

    def test_declared_cases_match_recorded_expectations(self) -> None:
        self.assertGreaterEqual(len(self.cases), 10)
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                report = self.run_case(case)
                kinds = sorted({str(item["kind"]) for item in report["findings"]})
                self.assertEqual(report["status"], case["expected_status"])
                self.assertEqual(report["mismatched_paths"], case["expected_mismatched_paths"])
                self.assertEqual(kinds, case["expected_kinds"])

    def test_at_least_one_case_proves_a_changed_hash_is_detected(self) -> None:
        detecting = [
            case
            for case in self.cases
            if case["expected_status"] == "FAIL" and "SHA256_MISMATCH" in case["expected_kinds"]
        ]
        self.assertGreaterEqual(len(detecting), 5)

    def test_findings_carry_expected_and_actual_values(self) -> None:
        report = self.run_case(
            {
                "mutations": [{"hex": "41", "offset": 0, "path": "alpha.txt", "type": "replace_bytes"}],
            }
        )
        digests = [item for item in report["findings"] if item["kind"] == "SHA256_MISMATCH"]
        self.assertEqual(len(digests), 1)
        self.assertNotEqual(digests[0]["expected"], digests[0]["actual"])
        self.assertEqual(digests[0]["path"], "alpha.txt")

    def test_head_sha_mismatch_is_reported(self) -> None:
        report = source_lock.verify(FIXTURES / "tree", self.lock, head_sha="f" * 40)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("HEAD_SHA_MISMATCH", {item["kind"] for item in report["findings"]})

    def test_matching_head_sha_passes(self) -> None:
        report = source_lock.verify(FIXTURES / "tree", self.lock, head_sha="0" * 40)
        self.assertEqual(report["status"], "PASS")


class InputValidationTest(unittest.TestCase):
    def write_json(self, document: object) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(document, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_spec_rejects_predeclared_derived_sources(self) -> None:
        path = self.write_json({"metadata": {"sources": []}, "source_paths": ["alpha.txt"]})
        with self.assertRaises(source_lock.SpecError):
            source_lock.load_spec(path)

    def test_spec_rejects_duplicate_paths(self) -> None:
        path = self.write_json({"metadata": {}, "source_paths": ["alpha.txt", "alpha.txt"]})
        with self.assertRaises(source_lock.SpecError):
            source_lock.load_spec(path)

    def test_spec_rejects_escaping_and_absolute_paths(self) -> None:
        for candidate in ("../escape.txt", "/etc/passwd", "nested//beta.json", "./alpha.txt"):
            with self.subTest(path=candidate):
                path = self.write_json({"metadata": {}, "source_paths": [candidate]})
                with self.assertRaises(source_lock.SpecError):
                    source_lock.load_spec(path)

    def test_lock_rejects_entry_missing_a_derived_field(self) -> None:
        path = self.write_json({"sources": [{"path": "alpha.txt", "sha256": "00"}]})
        with self.assertRaises(source_lock.SpecError):
            source_lock.load_lock(path)

    def test_lock_rejects_empty_source_list(self) -> None:
        path = self.write_json({"sources": []})
        with self.assertRaises(source_lock.SpecError):
            source_lock.load_lock(path)


class CommandLineTest(unittest.TestCase):
    def test_verify_exit_codes_and_report_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "tree"
            shutil.copytree(FIXTURES / "tree", root)
            report = Path(scratch) / "report.json"
            argv = [
                "verify",
                "--lock",
                str(FIXTURES / "source-lock.json"),
                "--root",
                str(root),
                "--report",
                str(report),
            ]
            self.assertEqual(source_lock.main(argv), 0)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "PASS")

            apply_mutation(root, {"hex": "41", "offset": 0, "path": "alpha.txt", "type": "replace_bytes"})
            self.assertEqual(source_lock.main(argv), 1)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "FAIL")

    def test_missing_input_returns_usage_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            argv = [
                "verify",
                "--lock",
                str(Path(scratch) / "absent.json"),
                "--root",
                str(FIXTURES / "tree"),
            ]
            self.assertEqual(source_lock.main(argv), 2)

    def test_compare_detects_byte_level_receipt_drift(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            expected = Path(scratch) / "expected.json"
            shutil.copyfile(FIXTURES / "source-lock.json", expected)
            argv = [
                "compare",
                "--spec",
                str(FIXTURES / "spec.json"),
                "--root",
                str(FIXTURES / "tree"),
                "--expected",
                str(expected),
            ]
            self.assertEqual(source_lock.main(argv), 0)
            expected.write_bytes(expected.read_bytes().replace(b'"bytes":44', b'"bytes":45'))
            self.assertEqual(source_lock.main(argv), 1)


class CommittedReceiptShapeTest(unittest.TestCase):
    """The real receipt must already be in the canonical form the mechanism emits."""

    RECEIPT = REPO_ROOT / "workstreams" / "po03" / "evidence" / "source-lock.json"

    @unittest.skipUnless(RECEIPT.is_file(), "committed receipt not present in this checkout")
    def test_receipt_is_canonical_and_loadable(self) -> None:
        raw = self.RECEIPT.read_bytes()
        lock = source_lock.load_lock(self.RECEIPT)
        self.assertEqual(source_lock.canonical_json(lock).encode("utf-8"), raw)
        self.assertEqual(lock["source_lock_version"], source_lock.LOCK_VERSION)


if __name__ == "__main__":
    unittest.main()
