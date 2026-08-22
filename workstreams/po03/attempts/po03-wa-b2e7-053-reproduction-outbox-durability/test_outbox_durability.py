#!/usr/bin/env python3
"""Tests for the outbox durability reproduction."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("experiment.py")
SPEC = importlib.util.spec_from_file_location("outbox_experiment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class OutboxDurabilityTests(unittest.TestCase):
    def test_outbox_recovers_all_injected_losses(self) -> None:
        preregister = json.loads(Path(__file__).with_name("preregister.json").read_text())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            result = experiment.run(preregister, Path(directory) / "scratch")
        self.assertEqual("PASS", result["verdict"])
        self.assertGreater(result["losses_injected"], 0)
        self.assertEqual(1.0, result["arms"]["transactional_outbox_with_readback"]["recovered_result_fraction"])

    def test_readback_refuses_corruption(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path, digest = experiment.commit_outbox(Path(directory), {"task_id": "one", "value": 1})
            path.write_bytes(b"corrupt\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                experiment.verified_readback(path, digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
