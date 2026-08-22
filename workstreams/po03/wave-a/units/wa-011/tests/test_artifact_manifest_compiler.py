from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
MODULE_PATH = UNIT_ROOT / "compile_artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("wa011_artifact_compiler", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ArtifactManifestCompilerTests(unittest.TestCase):
    def test_compilation_is_deterministic(self):
        first = MODULE.canonical_bytes(MODULE.compile_artifact_manifest(UNIT_ROOT))
        second = MODULE.canonical_bytes(MODULE.compile_artifact_manifest(UNIT_ROOT))
        self.assertEqual(first, second)

    def test_complete_hash_and_byte_accounting(self):
        manifest = MODULE.compile_artifact_manifest(UNIT_ROOT)
        self.assertEqual(manifest["artifact_count"], len(manifest["artifacts"]))
        self.assertEqual(
            manifest["total_bytes"],
            sum(artifact["bytes"] for artifact in manifest["artifacts"]),
        )
        for artifact in manifest["artifacts"]:
            path = UNIT_ROOT / artifact["logical_name"]
            content = path.read_bytes()
            self.assertEqual(len(content), artifact["bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])

    def test_artifacts_are_sorted_and_envelopes_excluded(self):
        manifest = MODULE.compile_artifact_manifest(UNIT_ROOT)
        names = [artifact["logical_name"] for artifact in manifest["artifacts"]]
        self.assertEqual(sorted(names, key=lambda name: name.encode("utf-8")), names)
        self.assertTrue(MODULE.EXCLUDED_ENVELOPES.isdisjoint(names))

    def test_exact_attempt_envelope_is_frozen(self):
        manifest = MODULE.compile_artifact_manifest(UNIT_ROOT)
        self.assertEqual(
            {
                "attempt_id": "PO03-WA-011-A02",
                "fence_token": 2,
                "idempotency_key": "po03:100bc2079ced:wa-011:a02",
                "lease_id": "lease-po03-wa-011-a02",
            },
            manifest["attempt"],
        )
        self.assertEqual([], manifest["decision_changed"])


if __name__ == "__main__":
    unittest.main()
