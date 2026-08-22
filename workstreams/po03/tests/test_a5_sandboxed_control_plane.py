"""Confirms the control-plane sandbox loader really redirects every write.

If this test ever failed, every reproduction built on top of it would be at
risk of writing into the coordinator's shared ledger, which is exactly the
kind of path collision the commission's allowlist guard exists to catch.
"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import sys

TESTS_DIR = Path(__file__).resolve().parent
RESEARCH_ROOT = TESTS_DIR.parent / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.sandboxed_control_plane import load_sandboxed_control_plane, RESEARCH_ROOT as LIB_RESEARCH_ROOT  # noqa: E402

REAL_LEDGER = TESTS_DIR.parent / "control" / "events" / "ledger.jsonl"


class TestSandboxedControlPlane(unittest.TestCase):
    def test_rejects_sandbox_outside_research_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_sandboxed_control_plane(Path(tmp))

    def test_redirects_ledger_path_away_from_shared_state(self) -> None:
        with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
            sandbox = Path(tmp)
            module = load_sandboxed_control_plane(sandbox)
            self.assertTrue(str(module.LEDGER_PATH).startswith(str(sandbox)))
            self.assertNotEqual(module.LEDGER_PATH, REAL_LEDGER)

    def test_real_ledger_untouched_after_sandboxed_writes(self) -> None:
        real_ledger_bytes_before = REAL_LEDGER.read_bytes() if REAL_LEDGER.exists() else None
        with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
            sandbox = Path(tmp)
            module = load_sandboxed_control_plane(sandbox)
            module.append_event("sandbox-u01", "CREATED", actor="test", provider_state="QUEUED")
            module.append_event("sandbox-u01", "LEASED", actor="test", fence_token=1)
            self.assertTrue(module.LEDGER_PATH.exists())
            rows = module.ledger_rows()
            self.assertEqual(len(rows), 2)
        real_ledger_bytes_after = REAL_LEDGER.read_bytes() if REAL_LEDGER.exists() else None
        self.assertEqual(real_ledger_bytes_before, real_ledger_bytes_after)

    def test_sandboxed_ingest_uses_sandbox_dispatch_and_ownership(self) -> None:
        with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
            sandbox = Path(tmp)
            module = load_sandboxed_control_plane(sandbox)
            from lib.ledger_io import write_json

            write_json(
                module.PATH_OWNERSHIP_PATH,
                {"owners": {"sandbox-worker": {"owned_prefixes": ["workstreams/po03/research/output/"]}}},
            )
            spec = {
                "commission_id": "TEST",
                "wave_id": "test-wave",
                "source_hashes": {},
                "units": [
                    {
                        "unit_id": "sandbox-u01",
                        "cohort_id": "test",
                        "function_id": "F0",
                        "hypothesis": "test",
                        "acceptance": {"assertion": "x", "artifact": "y", "falsified_if": "z"},
                        "owner": "sandbox-worker",
                        "owned_paths": ["workstreams/po03/research/output/"],
                        "model": "test-model",
                        "result_slot": {"unit_record": "sandbox-u01.json"},
                    }
                ],
            }
            spec_path = sandbox / "spec.json"
            write_json(spec_path, spec)
            module.cmd_create(argparse.Namespace(spec=str(spec_path)))
            rows = module.ledger_rows()
            self.assertEqual(rows[0]["event"], "CREATED")
            self.assertFalse(REAL_LEDGER.exists() and "sandbox-u01" in REAL_LEDGER.read_text())


if __name__ == "__main__":
    unittest.main()
