#!/usr/bin/env python3
"""Focused tests for the WA-015 deterministic artifact manifest compiler."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import UNIT_ROOT, silenced

import compile_artifact_manifest as compiler


class SyntheticRootCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa015-manifest-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.write("mechanism.py", "print('one')\n")
        self.write("fixtures/workload.json", '{"a":1}\n')
        self.write("result/result.json", '{"b":2}\n')

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestDiscovery(SyntheticRootCase):
    def test_payloads_are_sorted_by_utf8_bytes(self) -> None:
        self.assertEqual(
            compiler.discover(self.root),
            ["fixtures/workload.json", "mechanism.py", "result/result.json"],
        )

    def test_return_envelopes_are_excluded(self) -> None:
        for name in compiler.EXCLUDED_ENVELOPES:
            self.write(name, '{"envelope":true}\n')
        discovered = compiler.discover(self.root)
        for name in compiler.EXCLUDED_ENVELOPES:
            self.assertNotIn(name, discovered)
        self.assertIn("result/result.json", discovered)

    def test_bytecode_directories_are_ignored(self) -> None:
        self.write("__pycache__/mechanism.cpython-312.pyc", "x")
        self.write("tests/__pycache__/t.cpython-312.pyc", "x")
        self.assertEqual(
            compiler.discover(self.root),
            ["fixtures/workload.json", "mechanism.py", "result/result.json"],
        )

    def test_temporary_artifact_is_refused(self) -> None:
        self.write("draft.tmp", "x")
        with self.assertRaises(compiler.ManifestError):
            compiler.discover(self.root)

    def test_hidden_artifact_is_refused(self) -> None:
        self.write(".hidden", "x")
        with self.assertRaises(compiler.ManifestError):
            compiler.discover(self.root)

    def test_symlink_is_refused(self) -> None:
        (self.root / "link.py").symlink_to(self.root / "mechanism.py")
        with self.assertRaises(compiler.ManifestError):
            compiler.discover(self.root)

    def test_non_nfc_path_is_refused(self) -> None:
        self.write("cafe\u0301.txt", "x")
        with self.assertRaises(compiler.ManifestError):
            compiler.discover(self.root)

    def test_empty_subtree_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wa015-empty-") as empty:
            with self.assertRaises(compiler.ManifestError):
                compiler.discover(Path(empty))

    def test_empty_artifact_is_refused(self) -> None:
        self.write("blank.txt", "")
        with self.assertRaises(compiler.ManifestError):
            compiler.compile_manifest(self.root)


class TestManifestContent(SyntheticRootCase):
    def test_counts_and_bytes_are_internally_consistent(self) -> None:
        manifest = compiler.compile_manifest(self.root)
        self.assertEqual(manifest["artifact_count"], len(manifest["artifacts"]))
        self.assertEqual(
            manifest["total_bytes"],
            sum(row["bytes"] for row in manifest["artifacts"]),
        )

    def test_compilation_is_deterministic(self) -> None:
        self.assertEqual(
            compiler.render(compiler.compile_manifest(self.root)),
            compiler.render(compiler.compile_manifest(self.root)),
        )

    def test_artifact_ids_are_unique_and_derived_from_the_logical_name(self) -> None:
        manifest = compiler.compile_manifest(self.root)
        identifiers = [row["artifact_id"] for row in manifest["artifacts"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for row in manifest["artifacts"]:
            self.assertEqual(row["artifact_id"], compiler.artifact_id(row["logical_name"]))

    def test_content_tree_digest_reacts_to_content(self) -> None:
        before = compiler.compile_manifest(self.root)["manifest_content_tree_sha256"]
        self.write("mechanism.py", "print('two')\n")
        self.assertNotEqual(
            before, compiler.compile_manifest(self.root)["manifest_content_tree_sha256"]
        )

    def test_content_tree_digest_reacts_to_renaming(self) -> None:
        before = compiler.compile_manifest(self.root)["manifest_content_tree_sha256"]
        (self.root / "mechanism.py").rename(self.root / "engine.py")
        self.assertNotEqual(
            before, compiler.compile_manifest(self.root)["manifest_content_tree_sha256"]
        )

    def test_media_types_are_declared(self) -> None:
        self.assertEqual(compiler.media_type("a.py"), "text/x-python; charset=utf-8")
        self.assertEqual(compiler.media_type("a.json"), "application/json")
        self.assertEqual(compiler.media_type("a.md"), "text/markdown; charset=utf-8")
        self.assertEqual(compiler.media_type("a.txt"), "text/plain; charset=utf-8")
        self.assertEqual(compiler.media_type("a.bin"), compiler.DEFAULT_MEDIA_TYPE)

    def test_content_uris_are_repository_relative(self) -> None:
        for row in compiler.compile_manifest(self.root)["artifacts"]:
            self.assertTrue(row["content_uri"].startswith(compiler.REPO_PREFIX + "/"))
            self.assertTrue(row["content_uri"].endswith(row["logical_name"]))

    def test_attempt_identity_is_carried_verbatim(self) -> None:
        manifest = compiler.compile_manifest(self.root)
        self.assertEqual(
            manifest["attempt"],
            {
                "attempt_id": "PO03-WA-015-A02",
                "idempotency_key": "po03:100bc2079ced:wa-015:a02",
                "lease_id": "lease-po03-wa-015-a02",
                "fence_token": 2,
            },
        )
        self.assertEqual(manifest["task_id"], "PO03-WA-015")
        self.assertEqual(manifest["decision_changed"], [])

    def test_hash_closure_names_exactly_the_self_referential_envelopes(self) -> None:
        closure = compiler.compile_manifest(self.root)["hash_closure"]
        self.assertEqual(
            closure["excluded_envelopes"],
            [
                "result/artifact-manifest.json",
                "result/ready-to-commit.json",
                "result/transactional-result.json",
            ],
        )

    def test_rendered_manifest_is_stable_json_with_one_trailing_newline(self) -> None:
        rendered = compiler.render(compiler.compile_manifest(self.root))
        self.assertTrue(rendered.endswith(b"\n"))
        self.assertFalse(rendered[:-1].endswith(b"\n"))
        self.assertEqual(
            rendered,
            (json.dumps(json.loads(rendered), indent=2, sort_keys=True) + "\n").encode(),
        )


class TestOwnedSubtree(unittest.TestCase):
    def test_the_real_subtree_compiles(self) -> None:
        manifest = compiler.compile_manifest(UNIT_ROOT)
        self.assertGreaterEqual(manifest["artifact_count"], 10)
        self.assertGreater(manifest["total_bytes"], 0)

    def test_every_declared_artifact_hashes_to_its_recorded_digest(self) -> None:
        import hashlib

        for row in compiler.compile_manifest(UNIT_ROOT)["artifacts"]:
            data = (UNIT_ROOT / row["logical_name"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual(len(data), row["bytes"])

    def test_immutable_input_and_contract_digests_are_pinned(self) -> None:
        manifest = compiler.compile_manifest(UNIT_ROOT)
        self.assertEqual(
            manifest["immutable_input_manifest_sha256"],
            "f06c344679f09cf4bc523fe904a98970b3fe82dce4026115ccd5d787da08e2f5",
        )
        self.assertEqual(
            manifest["acceptance_contract_sha256"],
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
        )
        self.assertEqual(
            manifest["source_base_commit"],
            "7f9425655d6faa95219dc16d820bfbe18b91553f",
        )


class TestCommandLine(SyntheticRootCase):
    def test_output_is_written_and_then_reported_current(self) -> None:
        target = self.root / "result" / "artifact-manifest.json"
        with silenced():
            self.assertEqual(
                compiler.main(["--unit-root", str(self.root), "--output", str(target)]), 0
            )
        self.assertTrue(target.exists())
        with silenced():
            self.assertEqual(
                compiler.main(
                    ["--unit-root", str(self.root), "--output", str(target), "--check"]
                ),
                0,
            )

    def test_a_stale_output_is_reported(self) -> None:
        target = self.root / "result" / "artifact-manifest.json"
        target.write_text("{}\n", encoding="utf-8")
        with silenced():
            self.assertEqual(
                compiler.main(
                    ["--unit-root", str(self.root), "--output", str(target), "--check"]
                ),
                1,
            )

    def test_a_missing_output_is_reported_stale(self) -> None:
        with silenced():
            self.assertEqual(
                compiler.main(
                    [
                        "--unit-root",
                        str(self.root),
                        "--output",
                        str(self.root / "absent.json"),
                        "--check",
                    ]
                ),
                1,
            )

    def test_stdout_mode_emits_the_manifest(self) -> None:
        with silenced():
            self.assertEqual(compiler.main(["--unit-root", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
