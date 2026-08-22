from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = UNIT_ROOT / "result" / "build_manifest.py"
SPEC = importlib.util.spec_from_file_location("wa021_manifest", BUILDER_PATH)
BUILDER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BUILDER)


class ArtifactManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = BUILDER.build()

    def test_build_is_deterministic(self) -> None:
        self.assertEqual(BUILDER.encoded(self.document), BUILDER.encoded(BUILDER.build()))

    def test_self_referential_files_are_excluded(self) -> None:
        paths = {item["content_uri"] for item in self.document["artifacts"]}
        self.assertTrue(paths.isdisjoint(BUILDER.EXCLUDED))
        self.assertEqual(sorted(BUILDER.EXCLUDED), self.document["excluded_self_referential"])

    def test_every_artifact_digest_and_byte_count_match(self) -> None:
        for artifact in self.document["artifacts"]:
            data = (BUILDER.REPO_ROOT / artifact["content_uri"]).read_bytes()
            self.assertEqual(len(data), artifact["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact["sha256"])

    def test_totals_reconcile(self) -> None:
        artifacts = self.document["artifacts"]
        self.assertEqual(len(artifacts), self.document["artifact_count"])
        self.assertEqual(sum(item["bytes"] for item in artifacts), self.document["total_bytes"])
        self.assertEqual(
            len(artifacts),
            sum(totals["count"] for totals in self.document["by_role"].values()),
        )

    def test_every_owned_file_is_accounted_or_explicitly_excluded(self) -> None:
        actual = {
            path.relative_to(BUILDER.REPO_ROOT).as_posix()
            for path in BUILDER.UNIT_ROOT.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        accounted = {item["content_uri"] for item in self.document["artifacts"]}
        self.assertEqual(actual - BUILDER.EXCLUDED, accounted)


if __name__ == "__main__":
    unittest.main()
