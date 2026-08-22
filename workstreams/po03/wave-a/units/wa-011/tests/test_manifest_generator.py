from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
import unicodedata
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
MODULE_PATH = UNIT_ROOT / "manifest_generator.py"
SPEC = importlib.util.spec_from_file_location("wa011_manifest_generator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SOURCE_ROOT = UNIT_ROOT / "fixtures" / "source"
ORDER_FIXTURE = UNIT_ROOT / "fixtures" / "shuffled-orders.json"
EXPECTED_MANIFEST = UNIT_ROOT / "reproduction" / "expected-manifest.json"


def fixture_orders() -> dict[str, list[str]]:
    document = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    return document["orders"]


class DeterministicManifestTests(unittest.TestCase):
    def assert_error(self, code, function):
        with self.assertRaises(MODULE.ManifestError) as raised:
            function()
        self.assertEqual(code, raised.exception.code)

    def test_all_frozen_traversal_orders_are_byte_identical(self):
        outputs = {
            name: MODULE.compile_manifest_bytes(SOURCE_ROOT, order)
            for name, order in fixture_orders().items()
        }
        self.assertEqual(1, len(set(outputs.values())), outputs.keys())

    def test_default_filesystem_discovery_matches_frozen_orders(self):
        discovered = MODULE.compile_manifest_bytes(SOURCE_ROOT)
        ascending = MODULE.compile_manifest_bytes(
            SOURCE_ROOT, fixture_orders()["ascending"]
        )
        self.assertEqual(ascending, discovered)

    def test_compiled_bytes_match_committed_reproduction(self):
        actual = MODULE.compile_manifest_bytes(
            SOURCE_ROOT, fixture_orders()["seed-1102"]
        )
        self.assertEqual(EXPECTED_MANIFEST.read_bytes(), actual)

    def test_artifacts_are_sorted_by_utf8_path_bytes(self):
        manifest = MODULE.compile_manifest(
            SOURCE_ROOT, fixture_orders()["seed-1102"]
        )
        paths = [artifact["path"] for artifact in manifest["artifacts"]]
        self.assertEqual(fixture_orders()["ascending"], paths)

    def test_canonical_json_is_single_line_with_one_newline(self):
        payload = MODULE.compile_manifest_bytes(
            SOURCE_ROOT, fixture_orders()["reverse"]
        )
        self.assertTrue(payload.endswith(b"\n"))
        self.assertFalse(payload.endswith(b"\n\n"))
        self.assertEqual(1, payload.count(b"\n"))
        self.assertEqual(payload, MODULE.canonical_json_bytes(json.loads(payload)))

    def test_byte_and_artifact_accounting_is_exact(self):
        manifest = MODULE.compile_manifest(SOURCE_ROOT)
        self.assertEqual(3, manifest["artifact_count"])
        self.assertEqual(
            sum(path.stat().st_size for path in SOURCE_ROOT.rglob("*") if path.is_file()),
            manifest["total_bytes"],
        )
        self.assertEqual(
            manifest["total_bytes"],
            sum(artifact["bytes"] for artifact in manifest["artifacts"]),
        )

    def test_each_content_hash_matches_repository_fixture_bytes(self):
        manifest = MODULE.compile_manifest(SOURCE_ROOT)
        for artifact in manifest["artifacts"]:
            content = (SOURCE_ROOT / artifact["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])
            self.assertEqual(len(content), artifact["bytes"])

    def test_tree_digest_changes_when_identical_path_content_changes(self):
        before = MODULE.compile_records([("a.txt", b"one")])
        after = MODULE.compile_records([("a.txt", b"two")])
        self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])

    def test_tree_framing_distinguishes_ambiguous_concatenations(self):
        left = MODULE.compile_records([("a", b"bc")])
        right = MODULE.compile_records([("ab", b"c")])
        self.assertNotEqual(left["tree_sha256"], right["tree_sha256"])

    def test_empty_file_content_is_supported(self):
        manifest = MODULE.compile_records([("empty.bin", b"")])
        self.assertEqual(0, manifest["total_bytes"])
        self.assertEqual(hashlib.sha256(b"").hexdigest(), manifest["artifacts"][0]["sha256"])

    def test_in_memory_record_order_is_irrelevant(self):
        records = [("z", b"3"), ("a", b"1"), ("m", b"2")]
        expected = MODULE.canonical_json_bytes(MODULE.compile_records(records))
        for permutation in (
            records,
            list(reversed(records)),
            [records[1], records[2], records[0]],
        ):
            self.assertEqual(
                expected,
                MODULE.canonical_json_bytes(MODULE.compile_records(permutation)),
            )

    def test_duplicate_path_is_rejected(self):
        self.assert_error(
            "DUPLICATE_PATH",
            lambda: MODULE.compile_records([("a", b"1"), ("a", b"1")]),
        )

    def test_absolute_path_is_rejected(self):
        self.assert_error(
            "ABSOLUTE_PATH", lambda: MODULE.compile_records([("/escape", b"x")])
        )

    def test_parent_traversal_is_rejected(self):
        self.assert_error(
            "NON_CANONICAL_PATH",
            lambda: MODULE.compile_records([("../escape", b"x")]),
        )

    def test_dot_segment_is_rejected(self):
        self.assert_error(
            "NON_CANONICAL_PATH",
            lambda: MODULE.compile_records([("a/./b", b"x")]),
        )

    def test_backslash_path_is_rejected(self):
        self.assert_error(
            "NON_CANONICAL_PATH",
            lambda: MODULE.compile_records([("a\\b", b"x")]),
        )

    def test_non_nfc_path_is_rejected(self):
        decomposed = unicodedata.normalize("NFD", "café.txt")
        self.assertNotEqual("café.txt", decomposed)
        self.assert_error(
            "NON_CANONICAL_PATH",
            lambda: MODULE.compile_records([(decomposed, b"x")]),
        )

    def test_non_bytes_content_is_rejected(self):
        self.assert_error(
            "INVALID_CONTENT",
            lambda: MODULE.compile_records([("a", bytearray(b"x"))]),
        )

    def test_missing_artifact_is_rejected(self):
        self.assert_error(
            "MISSING_ARTIFACT",
            lambda: MODULE.compile_manifest(SOURCE_ROOT, ["missing.txt"]),
        )

    def test_directory_as_artifact_is_rejected(self):
        self.assert_error(
            "NON_REGULAR_ARTIFACT",
            lambda: MODULE.compile_manifest(SOURCE_ROOT, ["docs"]),
        )

    def test_unknown_fixture_order_is_rejected(self):
        self.assert_error(
            "UNKNOWN_ORDER",
            lambda: MODULE.load_traversal_fixture(ORDER_FIXTURE, "not-present"),
        )

    def test_cli_outputs_same_bytes_for_every_order(self):
        outputs = []
        for order in fixture_orders():
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--root",
                    str(SOURCE_ROOT),
                    "--paths-json",
                    str(ORDER_FIXTURE),
                    "--order",
                    order,
                ],
                check=False,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            outputs.append(completed.stdout)
        self.assertEqual(1, len(set(outputs)))

    def test_cli_refuses_output_inside_source_root_before_writing(self):
        prohibited = SOURCE_ROOT / "generated-manifest.json"
        self.assertFalse(prohibited.exists())
        completed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--root",
                str(SOURCE_ROOT),
                "--output",
                str(prohibited),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, completed.returncode)
        self.assertEqual("OUTPUT_INSIDE_SOURCE_ROOT", json.loads(completed.stderr)["error_code"])
        self.assertFalse(prohibited.exists())

    def test_wire_format_excludes_runtime_and_filesystem_metadata(self):
        manifest = MODULE.compile_manifest(SOURCE_ROOT)
        serialized = json.dumps(manifest, sort_keys=True)
        for prohibited in ("timestamp", "mtime", "inode", "hostname", str(SOURCE_ROOT)):
            self.assertNotIn(prohibited, serialized)


if __name__ == "__main__":
    unittest.main()
