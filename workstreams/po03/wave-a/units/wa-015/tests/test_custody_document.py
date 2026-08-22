#!/usr/bin/env python3
"""The WA-015 custody document must satisfy the seeded PO-03 result contract.

These tests import the seeded validator rather than reimplementing it, so the
active control is strengthened by use and never bypassed.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any

from _support import UNIT_ROOT  # noqa: F401  (path bootstrap)


_REPO_ROOT = UNIT_ROOT.parents[4]
_VALIDATOR_PATH = _REPO_ROOT / "workstreams" / "po03" / "tools" / "validate_contracts.py"
_SCHEMA_PATH = (
    _REPO_ROOT / "workstreams" / "po03" / "contracts" / "transactional-result.schema.json"
)
_DOCUMENT_PATH = UNIT_ROOT / "result" / "transactional-result.json"


def _load_validator() -> Any:
    spec = importlib.util.spec_from_file_location("seeded_validator", _VALIDATOR_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise unittest.SkipTest("seeded validator is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(_VALIDATOR_PATH.exists(), "seeded validator is not present")
class SeededContractCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = _load_validator()

    def document(self) -> dict[str, Any]:
        if not _DOCUMENT_PATH.exists():
            self.skipTest("custody document is written with the return commit")
        return json.loads(_DOCUMENT_PATH.read_text(encoding="utf-8"))

    def test_seeded_validator_accepts_the_custody_document(self) -> None:
        self.assertEqual(self.validator.validate_result(self.document()), [])

    def test_custody_document_matches_the_seeded_schema_shape(self) -> None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        document = self.document()
        self.assertEqual(
            sorted(schema["required"]), sorted(k for k in schema["required"])
        )
        for field in schema["required"]:
            self.assertIn(field, document)
        self.assertEqual(sorted(set(document)), sorted(set(schema["properties"])))

    def test_attempt_identity_is_the_dispatched_identity(self) -> None:
        attempt = self.document()["attempt"]
        self.assertEqual(attempt["attempt_id"], "PO03-WA-015-A02")
        self.assertEqual(attempt["idempotency_key"], "po03:100bc2079ced:wa-015:a02")
        self.assertEqual(attempt["lease_id"], "lease-po03-wa-015-a02")
        self.assertEqual(attempt["fence_token"], 2)

    def test_producer_does_not_complete_or_accept_its_own_result(self) -> None:
        document = self.document()
        self.assertIsNone(document["completion_actor"])
        self.assertNotEqual(document["obzio_state"], "COMPLETED")
        self.assertEqual(document["independent_acceptance"]["state"], "NOT_TESTED")
        self.assertIsNone(document["independent_acceptance"]["reviewer_id"])

    def test_a_forged_completion_is_refused(self) -> None:
        forged = dict(self.document(), obzio_state="COMPLETED", completion_actor="producer")
        errors = self.validator.validate_result(forged)
        self.assertTrue(
            any("only coordinator may set COMPLETED" in error for error in errors), errors
        )

    def test_a_forged_self_acceptance_is_refused(self) -> None:
        document = self.document()
        forged = dict(
            document,
            obzio_state="COMPLETED",
            completion_actor="coordinator",
            independent_acceptance={
                "state": "ACCEPTED",
                "reviewer_id": document["attempt"]["worker_id"],
                "receipt_uri": "workstreams/po03/control/reviews/wave-a/wa-015.json",
            },
        )
        errors = self.validator.validate_result(forged)
        self.assertTrue(
            any("producer cannot self-accept" in error for error in errors), errors
        )

    def test_provider_completion_without_a_commit_is_refused(self) -> None:
        forged = dict(self.document(), provider_state="COMPLETED")
        forged["result_transaction"] = dict(
            forged["result_transaction"], result_commit_id=None
        )
        errors = self.validator.validate_result(forged)
        self.assertTrue(
            any("PROVIDER_COMPLETED_UNCOMMITTED" in error for error in errors), errors
        )

    def test_byte_accounting_must_agree_with_the_artifact_list(self) -> None:
        document = self.document()
        transaction = document["result_transaction"]
        self.assertEqual(transaction["artifact_count"], len(document["artifacts"]))
        self.assertEqual(
            transaction["total_bytes"],
            sum(artifact["bytes"] for artifact in document["artifacts"]),
        )
        forged = dict(document)
        forged["result_transaction"] = dict(transaction, total_bytes=transaction["total_bytes"] + 1)
        self.assertTrue(self.validator.validate_result(forged))

    def test_every_artifact_was_read_back(self) -> None:
        for artifact in self.document()["artifacts"]:
            self.assertTrue(artifact["readback_verified_at"])
            self.assertTrue(artifact["content_uri"].startswith("git:"))


if __name__ == "__main__":
    unittest.main()
