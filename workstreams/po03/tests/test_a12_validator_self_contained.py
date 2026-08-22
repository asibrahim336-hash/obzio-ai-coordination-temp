"""Regression tests for the validator's standalone process boundary."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = REPO_ROOT / "workstreams/po03/tools/validate_contracts.py"
SCHEMA_PATH = (
    REPO_ROOT / "workstreams/po03/contracts/transactional-result.schema.json"
)
SCRATCH_ROOT = REPO_ROOT / "workstreams/po03/control/units/a12"
SPEC = importlib.util.spec_from_file_location("a12_standalone_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
H = "a" * 64


def recovery_result() -> dict:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "standalone-fixture",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
        "attempt": {
            "attempt_id": "attempt-2",
            "idempotency_key": "standalone-fixture:2",
            "lease_id": "lease-2",
            "fence_token": 2,
            "provider_run_id": "standalone-test",
            "worker_id": "po03-worker-a12",
            "heartbeat_at": None,
            "checkpoint_seq": 0,
        },
        "result_transaction": {
            "result_txn_id": "standalone-txn-2",
            "state": "RESERVED",
            "manifest_uri": None,
            "manifest_sha256": None,
            "artifact_count": 0,
            "total_bytes": 0,
            "committed_at": None,
            "verified_at": None,
            "parent_ingested_at": None,
            "result_commit_id": None,
        },
        "artifacts": [],
        "completion_actor": None,
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


class SelfContainedValidatorTests(unittest.TestCase):
    def test_executes_with_only_its_own_file_and_no_sibling_schema(self):
        valid = recovery_result()
        invalid = copy.deepcopy(valid)
        invalid["provider_state"] = "PROVIDER_SAYS_FINE"
        payload = base64.b64encode(
            json.dumps({"valid": valid, "invalid": invalid}).encode("utf-8")
        ).decode("ascii")
        driver = """
import base64
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
documents = json.loads(base64.b64decode(sys.argv[2]))
spec = importlib.util.spec_from_file_location("standalone_validator", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({
    "valid_errors": module.validate_result(documents["valid"]),
    "invalid_errors": module.validate_result(documents["invalid"]),
}, sort_keys=True))
"""
        with tempfile.TemporaryDirectory(
            prefix=".test-validator-standalone-", dir=SCRATCH_ROOT
        ) as temporary:
            scratch = Path(temporary)
            copied_module = scratch / "validate_contracts.py"
            shutil.copyfile(MODULE_PATH, copied_module)
            self.assertEqual([copied_module], list(scratch.iterdir()))
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    driver,
                    str(copied_module),
                    payload,
                ],
                cwd=scratch,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                0, completed.returncode, completed.stdout + completed.stderr
            )
            self.assertEqual([copied_module], list(scratch.iterdir()))
            observed = json.loads(completed.stdout)
            self.assertEqual([], observed["valid_errors"])
            self.assertTrue(
                any(
                    "$.provider_state" in error and "enum" in error
                    for error in observed["invalid_errors"]
                ),
                observed,
            )

    def test_embedded_schema_is_byte_identical_to_seeded_schema(self):
        self.assertEqual(
            SCHEMA_PATH.read_bytes(),
            MODULE.EMBEDDED_RESULT_SCHEMA_BYTES,
        )
        self.assertEqual(
            json.loads(SCHEMA_PATH.read_bytes()),
            MODULE.RESULT_SCHEMA,
        )


if __name__ == "__main__":
    unittest.main()
