#!/usr/bin/env python3
"""Shared recurrence suite; it must fail against the reverted mechanism fixtures."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
PARSER = argparse.ArgumentParser(add_help=False)
PARSER.add_argument("mechanism_root", type=Path)
ARGS, UNITTEST_ARGS = PARSER.parse_known_args()
sys.argv = [sys.argv[0], *UNITTEST_ARGS]


def load(name: str):
    path = ARGS.mechanism_root / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"recurrence_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


context_capsule = load("context_capsule")
durable_outbox = load("durable_outbox")


class MechanismRecurrenceTests(unittest.TestCase):
    def test_bounded_capsule_admits_all_and_only_required_fields(self) -> None:
        context = {f"noise_{number}": number for number in range(20)}
        context.update({"task_id": "T-1", "fence_token": 7, "acceptance_hash": "abc"})
        required = ["task_id", "fence_token", "acceptance_hash"]
        capsule = context_capsule.build_capsule(context, required, 3)
        self.assertEqual(set(required), set(capsule["payload"]))
        self.assertTrue(context_capsule.verify_capsule(capsule))

    def test_capsule_hash_detects_reverted_verification(self) -> None:
        capsule = context_capsule.build_capsule({"task_id": "T-1"}, ["task_id"], 1)
        capsule["payload"]["task_id"] = "tampered"
        self.assertFalse(context_capsule.verify_capsule(capsule))

    def test_outbox_is_durable_before_return_and_reads_back(self) -> None:
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=root) as directory:
            record = {"task_id": "T-2", "state": "COMMITTED", "value": 42}
            locator = durable_outbox.write_result(Path(directory), record)
            self.assertTrue(Path(locator["path"]).is_file())
            self.assertEqual(record, durable_outbox.read_result(locator))

    def test_outbox_readback_detects_corruption(self) -> None:
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=root) as directory:
            record = {"task_id": "T-3", "state": "COMMITTED"}
            locator = durable_outbox.write_result(Path(directory), record)
            Path(locator["path"]).write_bytes(b"corrupt\n")
            with self.assertRaises(ValueError):
                durable_outbox.read_result(locator)


if __name__ == "__main__":
    unittest.main(verbosity=2)
