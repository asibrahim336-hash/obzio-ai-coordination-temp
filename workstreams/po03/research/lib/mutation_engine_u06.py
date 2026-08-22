"""Text-level mutation testing of the real validate_contracts.py (a5-u06).

Mutants are produced by exact substring replacement on the *source text*
read from the real, coordinator-owned file, then compiled and executed into
a fresh, isolated module object entirely in memory. The real file on disk is
never opened for writing and never modified.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

PO03_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_CONTRACTS_PATH = PO03_ROOT / "tools" / "validate_contracts.py"
TEST_VALIDATE_CONTRACTS_PATH = PO03_ROOT / "tests" / "test_validate_contracts.py"

_counter = 0


def _next_id() -> int:
    global _counter
    _counter += 1
    return _counter


MUTANTS: list[dict[str, str]] = [
    {
        "id": "M1_artifact_bytes_lower_bound_relaxed",
        "find": 'or artifact["bytes"] < 1:',
        "replace": 'or artifact["bytes"] < 0:',
        "description": "Allows a zero-byte artifact to pass validation (should require bytes >= 1).",
    },
    {
        "id": "M2_total_bytes_reconciliation_tolerant",
        "find": 'if txn["total_bytes"] != byte_sum:',
        "replace": 'if abs(txn["total_bytes"] - byte_sum) > 1:',
        "description": "Introduces a +/-1 byte tolerance into total_bytes reconciliation.",
    },
    {
        "id": "M3_acceptance_terminal_state_relaxed",
        "find": 'if state != "COMPLETED":',
        "replace": 'if state not in {"COMPLETED", "PARENT_INGESTED"}:',
        "description": "Allows a terminal independent_acceptance decision while obzio_state is only PARENT_INGESTED, not COMPLETED.",
    },
    {
        "id": "M4_duplicate_artifact_check_disabled",
        "find": 'if artifact["artifact_id"] in artifact_ids:\n            errors.append(f"{prefix}.artifact_id: duplicate")',
        "replace": 'if False:\n            errors.append(f"{prefix}.artifact_id: duplicate")',
        "description": "Disables the duplicate-artifact-id check entirely (control mutant expected to be caught by the existing suite).",
    },
    {
        "id": "M5_self_accept_check_disabled",
        "find": 'if acceptance.get("reviewer_id") == attempt.get("worker_id"):',
        "replace": "if False:",
        "description": "Disables the producer-cannot-self-accept check (control mutant expected to be caught by the existing suite).",
    },
]


def read_real_source() -> str:
    return VALIDATE_CONTRACTS_PATH.read_text(encoding="utf-8")


def apply_mutant(source_text: str, mutant: dict[str, str]) -> str:
    count = source_text.count(mutant["find"])
    if count != 1:
        raise ValueError(f"mutant {mutant['id']}: expected exactly 1 occurrence of anchor text, found {count}")
    return source_text.replace(mutant["find"], mutant["replace"], 1)


def load_module_from_source(source_text: str, module_name: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = str(VALIDATE_CONTRACTS_PATH)
    code = compile(source_text, filename=f"<mutant:{module_name}>", mode="exec")
    exec(code, module.__dict__)  # noqa: S102 -- controlled, in-memory only, never written to disk
    return module


def load_real_module() -> types.ModuleType:
    return load_module_from_source(read_real_source(), f"validate_contracts_real_{_next_id()}")


def run_existing_suite_against_module(module: types.ModuleType) -> dict[str, Any]:
    """Dynamically import a fresh copy of the real test_validate_contracts.py
    and repoint its module-level MODULE reference at ``module`` before
    running its TestCase classes. The real test file is read-only here."""
    unique_name = f"test_validate_contracts_probe_{_next_id()}"
    spec = importlib.util.spec_from_file_location(unique_name, TEST_VALIDATE_CONTRACTS_PATH)
    test_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[unique_name] = test_module
    try:
        spec.loader.exec_module(test_module)
        test_module.MODULE = module  # repoint at the mutant (or real) module under test

        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in dir(test_module):
            obj = getattr(test_module, name)
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
                suite.addTests(loader.loadTestsFromTestCase(obj))

        result = unittest.TestResult()
        suite.run(result)
        failures = [str(err[0]) for err in result.failures] + [str(err[0]) for err in result.errors]
        return {
            "tests_run": result.testsRun,
            "failures": failures,
            "killed": len(failures) > 0,
        }
    finally:
        sys.modules.pop(unique_name, None)
