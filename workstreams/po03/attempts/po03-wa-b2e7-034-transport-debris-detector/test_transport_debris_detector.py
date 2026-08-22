#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from transport_debris_detector import scan, scan_git_tree


class TransportDebrisDetectorTests(unittest.TestCase):
    def test_classifies_explicit_live_debris_and_unresolved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            live = root / "payload.md"
            debris = root / "payload.md.partial"
            unknown = root / "payload.bin"
            live.write_bytes(b"OBZIO-LIVE-SURFACE\n")
            debris.write_bytes(b"old bytes")
            unknown.write_bytes(b"uncategorised")
            report = scan([root], live_paths=[live.as_posix()])
        self.assertEqual(report["counts"], {"live": 1, "debris": 1, "unresolved": 1})
        self.assertEqual(
            {item["classification"] for item in report["artifacts"]},
            {"live", "debris", "unresolved"},
        )

    def test_missing_transport_root_is_reported_without_invention(self):
        report = scan([Path(__file__).parent / "does-not-exist"])
        self.assertEqual(report["artifacts"], [])
        self.assertEqual(len(report["unavailable_roots"]), 1)

    def test_reads_real_pinned_pack_tree_without_checkout(self):
        report = scan_git_tree(
            Path(__file__).parents[4],
            "1e6f53c323f8326d12af213557082a3665991f19",
            "packs",
        )
        self.assertEqual(report["source_commit"], "1e6f53c323f8326d12af213557082a3665991f19")
        self.assertGreater(len(report["artifacts"]), 0)
        self.assertEqual(sum(report["counts"].values()), len(report["artifacts"]))
        self.assertEqual(report["counts"]["debris"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
