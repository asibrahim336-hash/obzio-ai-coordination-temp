from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
MODULE_PATH = UNIT_ROOT / "repository_debris_detector.py"
SPEC = importlib.util.spec_from_file_location("repository_debris_detector", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact(
    artifact_id: str,
    path: str,
    data: bytes,
    *,
    role: str = "MATERIAL",
    standing: str = "CURRENT",
    superseded_by: str | None = None,
    claims: list[str] | None = None,
) -> dict:
    return {
        "artifact_id": artifact_id,
        "path": path,
        "role": role,
        "standing": standing,
        "expected_sha256": sha(data),
        "expected_bytes": len(data),
        "superseded_by": superseded_by,
        "evidence_claims": [] if claims is None else claims,
    }


class DetectorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wa005-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, name: str) -> Path:
        return UNIT_ROOT / "fixtures" / name / "inventory.json"

    def disposition_by_id(self, result: dict, artifact_id: str) -> dict:
        return next(
            item for item in result["dispositions"] if item["artifact_id"] == artifact_id
        )

    def make_inventory(
        self, artifacts: list[dict], files: dict[str, bytes], name: str = "inventory.json"
    ) -> Path:
        fixture = self.root / name.removesuffix(".json")
        files_root = fixture / "files"
        files_root.mkdir(parents=True)
        for relative, data in files.items():
            target = files_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        document = {
            "protocol_version": MODULE.INVENTORY_PROTOCOL,
            "root": "files",
            "artifacts": artifacts,
        }
        inventory_path = fixture / name
        inventory_path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return inventory_path

    def test_positive_fixture_classifies_only_verified_duplicate_as_debris(self):
        result = MODULE.scan_inventory(self.fixture("positive"))
        current = self.disposition_by_id(result, "current-package")
        debris = self.disposition_by_id(result, "generated-copy")
        self.assertEqual("CURRENT_MATERIAL", current["classification"])
        self.assertEqual("REDUNDANT_DEBRIS", debris["classification"])
        self.assertEqual("REVIEW_FOR_REMOVAL", debris["disposition"])
        self.assertTrue(debris["removal_eligible_after_review"])
        self.assertFalse(result["mutation_performed"])

    def test_negative_fixture_does_not_infer_from_delete_me_filename(self):
        result = MODULE.scan_inventory(self.fixture("negative"))
        item = self.disposition_by_id(result, "misleading-current-name")
        self.assertEqual("CURRENT_MATERIAL", item["classification"])
        self.assertEqual("RETAIN", item["disposition"])
        self.assertFalse(item["removal_eligible_after_review"])

    def test_superseded_transport_fixture_is_classified_but_retained(self):
        result = MODULE.scan_inventory(self.fixture("superseded"))
        item = self.disposition_by_id(result, "legacy-transport")
        self.assertEqual("SUPERSEDED_TRANSPORT_REDUNDANT", item["classification"])
        self.assertEqual("SUPERSEDE_RETAIN", item["disposition"])
        self.assertTrue(item["removal_eligible_after_review"])

    def test_superseded_unique_evidence_fixture_is_protected(self):
        result = MODULE.scan_inventory(self.fixture("unique-evidence"))
        item = self.disposition_by_id(result, "superseded-with-receipt")
        self.assertEqual("SUPERSEDED_UNIQUE_EVIDENCE", item["classification"])
        self.assertEqual("RETAIN_AS_EVIDENCE", item["disposition"])
        self.assertTrue(item["protection_required"])
        self.assertTrue(item["evidence"]["has_unique_evidence"])
        self.assertEqual(2, len(item["evidence"]["unique_claims"]))

    def test_unique_bytes_protect_superseded_artifact_without_claims(self):
        current = b"current\n"
        legacy = b"legacy byte evidence\n"
        inventory = self.make_inventory(
            [
                artifact("current", "current.txt", current),
                artifact(
                    "legacy",
                    "legacy.txt",
                    legacy,
                    role="TRANSPORT",
                    standing="SUPERSEDED",
                    superseded_by="current",
                ),
            ],
            {"current.txt": current, "legacy.txt": legacy},
        )
        item = self.disposition_by_id(MODULE.scan_inventory(inventory), "legacy")
        self.assertEqual("RETAIN_AS_EVIDENCE", item["disposition"])
        self.assertTrue(item["content"]["unique_bytes"])

    def test_unique_claim_protects_byte_duplicate(self):
        data = b"same bytes\n"
        inventory = self.make_inventory(
            [
                artifact("current", "current.txt", data),
                artifact(
                    "legacy",
                    "legacy.txt",
                    data,
                    role="TRANSPORT",
                    standing="SUPERSEDED",
                    superseded_by="current",
                    claims=["receipt-only-on-legacy"],
                ),
            ],
            {"current.txt": data, "legacy.txt": data},
        )
        item = self.disposition_by_id(MODULE.scan_inventory(inventory), "legacy")
        self.assertEqual("SUPERSEDED_UNIQUE_EVIDENCE", item["classification"])
        self.assertEqual(["receipt-only-on-legacy"], item["evidence"]["unique_claims"])

    def test_hash_mismatch_fails_closed(self):
        data = b"actual\n"
        record = artifact("item", "item.txt", b"claimed\n")
        inventory = self.make_inventory([record], {"item.txt": data})
        item = self.disposition_by_id(MODULE.scan_inventory(inventory), "item")
        self.assertEqual("CLAIM_MISMATCH", item["integrity"]["status"])
        self.assertEqual("AMBIGUOUS_REVIEW", item["classification"])
        self.assertEqual("RETAIN_PENDING_REVIEW", item["disposition"])
        self.assertTrue(item["protection_required"])

    def test_missing_successor_fails_closed(self):
        data = b"orphan\n"
        inventory = self.make_inventory(
            [
                artifact(
                    "orphan",
                    "orphan.txt",
                    data,
                    role="TRANSPORT",
                    standing="SUPERSEDED",
                    superseded_by="missing",
                )
            ],
            {"orphan.txt": data},
        )
        item = self.disposition_by_id(MODULE.scan_inventory(inventory), "orphan")
        self.assertIn("SUCCESSOR_NOT_IN_INVENTORY", item["supersession"]["relation_errors"])
        self.assertEqual("RETAIN_PENDING_REVIEW", item["disposition"])

    def test_supersession_cycle_fails_closed(self):
        data = b"cycle\n"
        inventory = self.make_inventory(
            [
                artifact(
                    "a",
                    "a.txt",
                    data,
                    standing="SUPERSEDED",
                    superseded_by="b",
                ),
                artifact(
                    "b",
                    "b.txt",
                    data,
                    standing="SUPERSEDED",
                    superseded_by="a",
                ),
            ],
            {"a.txt": data, "b.txt": data},
        )
        result = MODULE.scan_inventory(inventory)
        for item in result["dispositions"]:
            self.assertEqual("RETAIN_PENDING_REVIEW", item["disposition"])
            self.assertTrue(item["protection_required"])

    def test_symlink_is_never_followed(self):
        data = b"outside evidence\n"
        fixture = self.root / "symlink"
        files = fixture / "files"
        files.mkdir(parents=True)
        outside = fixture / "outside.txt"
        outside.write_bytes(data)
        (files / "linked.txt").symlink_to(outside)
        document = {
            "protocol_version": MODULE.INVENTORY_PROTOCOL,
            "root": "files",
            "artifacts": [artifact("link", "linked.txt", data)],
        }
        inventory = fixture / "inventory.json"
        inventory.write_text(json.dumps(document), encoding="utf-8")
        item = MODULE.scan_inventory(inventory)["dispositions"][0]
        self.assertEqual("SYMLINK_REFUSED", item["integrity"]["status"])
        self.assertEqual("RETAIN_PENDING_REVIEW", item["disposition"])

    def test_parent_symlink_escape_is_refused(self):
        data = b"outside evidence\n"
        fixture = self.root / "parent-link"
        files = fixture / "files"
        outside = fixture / "outside"
        files.mkdir(parents=True)
        outside.mkdir()
        (outside / "item.txt").write_bytes(data)
        (files / "linked-parent").symlink_to(outside, target_is_directory=True)
        document = {
            "protocol_version": MODULE.INVENTORY_PROTOCOL,
            "root": "files",
            "artifacts": [artifact("escape", "linked-parent/item.txt", data)],
        }
        inventory = fixture / "inventory.json"
        inventory.write_text(json.dumps(document), encoding="utf-8")
        item = MODULE.scan_inventory(inventory)["dispositions"][0]
        self.assertEqual("PARENT_ESCAPE_REFUSED", item["integrity"]["status"])

    def test_path_traversal_is_rejected(self):
        data = b"x"
        record = artifact("escape", "../outside.txt", data)
        inventory = self.make_inventory([record], {})
        with self.assertRaisesRegex(MODULE.DetectorError, "traversal"):
            MODULE.scan_inventory(inventory)

    def test_absolute_path_is_rejected(self):
        data = b"x"
        record = artifact("absolute", "/tmp/outside.txt", data)
        inventory = self.make_inventory([record], {})
        with self.assertRaisesRegex(MODULE.DetectorError, "canonical relative"):
            MODULE.scan_inventory(inventory)

    def test_backslash_path_is_rejected(self):
        data = b"x"
        record = artifact("windows", r"..\outside.txt", data)
        inventory = self.make_inventory([record], {})
        with self.assertRaisesRegex(MODULE.DetectorError, "backslashes"):
            MODULE.scan_inventory(inventory)

    def test_duplicate_artifact_id_is_rejected(self):
        data = b"x"
        inventory = self.make_inventory(
            [artifact("same", "a.txt", data), artifact("same", "b.txt", data)],
            {"a.txt": data, "b.txt": data},
        )
        with self.assertRaisesRegex(MODULE.DetectorError, "duplicate"):
            MODULE.scan_inventory(inventory)

    def test_duplicate_artifact_path_is_rejected(self):
        data = b"x"
        inventory = self.make_inventory(
            [artifact("a", "same.txt", data), artifact("b", "same.txt", data)],
            {"same.txt": data},
        )
        with self.assertRaisesRegex(MODULE.DetectorError, "duplicate"):
            MODULE.scan_inventory(inventory)

    def test_boolean_byte_count_is_rejected(self):
        data = b"x"
        record = artifact("a", "a.txt", data)
        record["expected_bytes"] = True
        inventory = self.make_inventory([record], {"a.txt": data})
        with self.assertRaisesRegex(MODULE.DetectorError, "integer"):
            MODULE.scan_inventory(inventory)

    def test_invalid_hash_is_rejected(self):
        data = b"x"
        record = artifact("a", "a.txt", data)
        record["expected_sha256"] = "not-a-hash"
        inventory = self.make_inventory([record], {"a.txt": data})
        with self.assertRaisesRegex(MODULE.DetectorError, "SHA-256"):
            MODULE.scan_inventory(inventory)

    def test_scan_is_deterministic(self):
        first = MODULE.scan_inventory(self.fixture("positive"))
        second = MODULE.scan_inventory(self.fixture("positive"))
        self.assertEqual(first, second)
        self.assertEqual(MODULE._json_bytes(first), MODULE._json_bytes(second))

    def test_scan_does_not_mutate_fixture_tree(self):
        source = UNIT_ROOT / "fixtures" / "unique-evidence"

        def tree_digest() -> str:
            digest = hashlib.sha256()
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                digest.update(path.relative_to(source).as_posix().encode())
                digest.update(path.read_bytes())
            return digest.hexdigest()

        before = tree_digest()
        MODULE.scan_inventory(source / "inventory.json")
        self.assertEqual(before, tree_digest())

    def test_output_cannot_be_written_inside_inventoried_root(self):
        inventory = self.fixture("positive")
        root = MODULE._inventory_root(inventory)
        with self.assertRaisesRegex(MODULE.DetectorError, "inventoried root"):
            MODULE._write_new(root / "disposition.json", b"{}", protected_root=root)

    def test_existing_output_is_not_overwritten(self):
        target = self.root / "existing.json"
        target.write_bytes(b"original")
        with self.assertRaisesRegex(MODULE.DetectorError, "refusing to overwrite"):
            MODULE._write_new(target, b"replacement")
        self.assertEqual(b"original", target.read_bytes())

    def test_cli_writes_and_validates_disposition(self):
        output = self.root / "disposition.json"
        self.assertEqual(
            0,
            MODULE.main(
                ["scan", str(self.fixture("superseded")), "--output", str(output)]
            ),
        )
        self.assertEqual(0, MODULE.main(["validate", str(output)]))
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([], MODULE.validate_disposition(document))

    def test_validator_rejects_relaxed_unique_evidence_disposition(self):
        result = MODULE.scan_inventory(self.fixture("unique-evidence"))
        tampered = copy.deepcopy(result)
        item = self.disposition_by_id(tampered, "superseded-with-receipt")
        item["disposition"] = "REVIEW_FOR_REMOVAL"
        item["protection_required"] = False
        self.assertTrue(
            any("unique evidence" in error for error in MODULE.validate_disposition(tampered))
        )

    def test_schema_is_strict_json_and_names_every_runtime_classification(self):
        schema = json.loads(
            (UNIT_ROOT / "disposition.schema.json").read_text(encoding="utf-8")
        )
        enum = set(
            schema["properties"]["dispositions"]["items"]["properties"][
                "classification"
            ]["enum"]
        )
        self.assertEqual(MODULE.CLASSIFICATIONS, enum)
        self.assertFalse(schema["additionalProperties"])

    def test_detector_has_no_deletion_primitive(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        forbidden = {"remove", "unlink", "rmdir", "removedirs"}
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(forbidden & (calls | names))

    def test_fixture_copy_remains_byte_identical_after_cli_scan(self):
        source = UNIT_ROOT / "fixtures" / "positive"
        copied = self.root / "copied"
        shutil.copytree(source, copied)
        before = {
            path.relative_to(copied): path.read_bytes()
            for path in copied.rglob("*")
            if path.is_file()
        }
        output = self.root / "copy-result.json"
        self.assertEqual(
            0,
            MODULE.main(["scan", str(copied / "inventory.json"), "--output", str(output)]),
        )
        after = {
            path.relative_to(copied): path.read_bytes()
            for path in copied.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
