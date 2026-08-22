"""Schema-closure tests for the dependency-free transactional result validator."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PO03_ROOT = Path(__file__).parents[1]
MODULE_PATH = PO03_ROOT / "tools" / "validate_contracts.py"
SCHEMA_PATH = PO03_ROOT / "contracts" / "transactional-result.schema.json"
SPEC = importlib.util.spec_from_file_location("a12_validate_contracts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
H = "a" * 64


def committed_result() -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "po03-test-1",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "po03-test-1:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-run-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T06:00:00Z",
            "checkpoint_seq": 4,
        },
        "result_transaction": {
            "result_txn_id": "result-1",
            "state": "INGESTED",
            "manifest_uri": "git:po03/run/po03-test-1@abc:manifest.json",
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 1,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "abc123",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.json",
                "content_uri": "git:po03/run/po03-test-1@abc:result.json",
                "sha256": H,
                "bytes": 1,
                "media_type": "application/json",
                "readback_verified_at": "2026-08-22T06:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "ACCEPTED",
            "reviewer_id": "reviewer-2",
            "receipt_uri": "git:po03/review@def:receipt.json",
        },
    }


def recovery_result() -> dict[str, Any]:
    doc = committed_result()
    doc["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
    doc["result_transaction"].update(
        state="RESERVED",
        manifest_uri=None,
        manifest_sha256=None,
        artifact_count=0,
        total_bytes=0,
        committed_at=None,
        verified_at=None,
        parent_ingested_at=None,
        result_commit_id=None,
    )
    doc["artifacts"] = []
    doc["completion_actor"] = None
    doc["independent_acceptance"] = {
        "state": "NOT_TESTED",
        "reviewer_id": None,
        "receipt_uri": None,
    }
    return doc


def running_result_with_artifact() -> dict[str, Any]:
    doc = recovery_result()
    doc["provider_state"] = "RUNNING"
    doc["obzio_state"] = "RUNNING"
    doc["result_transaction"].update(artifact_count=1, total_bytes=1)
    doc["artifacts"] = copy.deepcopy(committed_result()["artifacts"])
    doc["artifacts"][0]["readback_verified_at"] = None
    return doc


def set_path(doc: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = doc
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def add_extra(path: tuple[str | int, ...]) -> Callable[[dict[str, Any]], None]:
    def mutate(doc: dict[str, Any]) -> None:
        target: Any = doc
        for part in path:
            target = target[part]
        target["undeclared"] = True

    return mutate


def replace(path: tuple[str | int, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda doc: set_path(doc, path, value)


@dataclass(frozen=True)
class DivergenceFixture:
    name: str
    base: Callable[[], dict[str, Any]]
    mutate: Callable[[dict[str, Any]], None]
    schema_path: tuple[str, ...]
    keyword: str
    instance_path: tuple[str | int, ...]


DIVERGENCE_FIXTURES = (
    DivergenceFixture("root additional property", committed_result, add_extra(()), (), "additionalProperties", ()),
    DivergenceFixture(
        "attempt additional property",
        committed_result,
        add_extra(("attempt",)),
        ("attempt",),
        "additionalProperties",
        ("attempt",),
    ),
    DivergenceFixture(
        "transaction additional property",
        committed_result,
        add_extra(("result_transaction",)),
        ("result_transaction",),
        "additionalProperties",
        ("result_transaction",),
    ),
    DivergenceFixture(
        "artifact additional property",
        committed_result,
        add_extra(("artifacts", 0)),
        ("artifacts", "items"),
        "additionalProperties",
        ("artifacts", 0),
    ),
    DivergenceFixture(
        "acceptance additional property",
        committed_result,
        add_extra(("independent_acceptance",)),
        ("independent_acceptance",),
        "additionalProperties",
        ("independent_acceptance",),
    ),
    DivergenceFixture(
        "provider state enum",
        committed_result,
        replace(("provider_state",), "PROVIDER_SAYS_FINE"),
        ("provider_state",),
        "enum",
        ("provider_state",),
    ),
    DivergenceFixture(
        "transaction state enum",
        committed_result,
        replace(("result_transaction", "state"), "PUBLISHED"),
        ("result_transaction", "state"),
        "enum",
        ("result_transaction", "state"),
    ),
    DivergenceFixture(
        "acceptance state enum",
        recovery_result,
        replace(("independent_acceptance", "state"), "WAIVED"),
        ("independent_acceptance", "state"),
        "enum",
        ("independent_acceptance", "state"),
    ),
    DivergenceFixture(
        "heartbeat type",
        committed_result,
        replace(("attempt", "heartbeat_at"), 7),
        ("attempt", "heartbeat_at"),
        "type",
        ("attempt", "heartbeat_at"),
    ),
    DivergenceFixture(
        "boolean fence token",
        committed_result,
        replace(("attempt", "fence_token"), True),
        ("attempt", "fence_token"),
        "type",
        ("attempt", "fence_token"),
    ),
    DivergenceFixture(
        "boolean checkpoint sequence",
        committed_result,
        replace(("attempt", "checkpoint_seq"), False),
        ("attempt", "checkpoint_seq"),
        "type",
        ("attempt", "checkpoint_seq"),
    ),
    DivergenceFixture(
        "empty transaction id",
        recovery_result,
        replace(("result_transaction", "result_txn_id"), ""),
        ("result_transaction", "result_txn_id"),
        "minLength",
        ("result_transaction", "result_txn_id"),
    ),
    DivergenceFixture(
        "uncommitted manifest URI type",
        recovery_result,
        replace(("result_transaction", "manifest_uri"), 7),
        ("result_transaction", "manifest_uri"),
        "type",
        ("result_transaction", "manifest_uri"),
    ),
    DivergenceFixture(
        "uncommitted manifest hash type",
        recovery_result,
        replace(("result_transaction", "manifest_sha256"), 7),
        ("result_transaction", "manifest_sha256"),
        "anyOf",
        ("result_transaction", "manifest_sha256"),
    ),
    DivergenceFixture(
        "boolean artifact count",
        recovery_result,
        replace(("result_transaction", "artifact_count"), False),
        ("result_transaction", "artifact_count"),
        "type",
        ("result_transaction", "artifact_count"),
    ),
    DivergenceFixture(
        "boolean total bytes",
        recovery_result,
        replace(("result_transaction", "total_bytes"), False),
        ("result_transaction", "total_bytes"),
        "type",
        ("result_transaction", "total_bytes"),
    ),
    DivergenceFixture(
        "uncommitted committed-at type",
        recovery_result,
        replace(("result_transaction", "committed_at"), 7),
        ("result_transaction", "committed_at"),
        "type",
        ("result_transaction", "committed_at"),
    ),
    DivergenceFixture(
        "uncommitted verified-at type",
        recovery_result,
        replace(("result_transaction", "verified_at"), 7),
        ("result_transaction", "verified_at"),
        "type",
        ("result_transaction", "verified_at"),
    ),
    DivergenceFixture(
        "uncommitted parent-ingested-at type",
        recovery_result,
        replace(("result_transaction", "parent_ingested_at"), 7),
        ("result_transaction", "parent_ingested_at"),
        "type",
        ("result_transaction", "parent_ingested_at"),
    ),
    DivergenceFixture(
        "uncommitted commit-id type",
        recovery_result,
        replace(("result_transaction", "result_commit_id"), 7),
        ("result_transaction", "result_commit_id"),
        "type",
        ("result_transaction", "result_commit_id"),
    ),
    DivergenceFixture(
        "boolean artifact bytes",
        running_result_with_artifact,
        replace(("artifacts", 0, "bytes"), True),
        ("artifacts", "items", "bytes"),
        "type",
        ("artifacts", 0, "bytes"),
    ),
    DivergenceFixture(
        "uncommitted readback timestamp type",
        running_result_with_artifact,
        replace(("artifacts", 0, "readback_verified_at"), 7),
        ("artifacts", "items", "readback_verified_at"),
        "type",
        ("artifacts", 0, "readback_verified_at"),
    ),
    DivergenceFixture(
        "completion actor type",
        recovery_result,
        replace(("completion_actor",), 7),
        ("completion_actor",),
        "type",
        ("completion_actor",),
    ),
    DivergenceFixture(
        "untested reviewer type",
        recovery_result,
        replace(("independent_acceptance", "reviewer_id"), 7),
        ("independent_acceptance", "reviewer_id"),
        "type",
        ("independent_acceptance", "reviewer_id"),
    ),
    DivergenceFixture(
        "untested receipt type",
        recovery_result,
        replace(("independent_acceptance", "receipt_uri"), 7),
        ("independent_acceptance", "receipt_uri"),
        "type",
        ("independent_acceptance", "receipt_uri"),
    ),
)


def schema_node(path: tuple[str, ...]) -> dict[str, Any]:
    node = SCHEMA
    for part in path:
        if part == "items":
            node = node["items"]
        else:
            node = node["properties"][part]
        while "$ref" in node:
            ref = node["$ref"]
            assert ref.startswith("#/$defs/")
            node = SCHEMA["$defs"][ref.rsplit("/", 1)[-1]]
    return node


def instance_value(doc: dict[str, Any], path: tuple[str | int, ...]) -> Any:
    value: Any = doc
    for part in path:
        value = value[part]
    return value


def json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
    }[expected]


class TransactionalSchemaClosureTests(unittest.TestCase):
    def assert_declared_schema_violation(
        self, fixture: DivergenceFixture, doc: dict[str, Any]
    ) -> None:
        node = schema_node(fixture.schema_path)
        value = instance_value(doc, fixture.instance_path)
        self.assertIn(fixture.keyword, node)
        if fixture.keyword == "additionalProperties":
            self.assertIs(node[fixture.keyword], False)
            self.assertIn("undeclared", value)
            self.assertNotIn("undeclared", node["properties"])
        elif fixture.keyword == "enum":
            self.assertNotIn(value, node["enum"])
        elif fixture.keyword == "minLength":
            self.assertIsInstance(value, str)
            self.assertLess(len(value), node["minLength"])
        elif fixture.keyword == "type":
            allowed = node["type"]
            allowed_types = [allowed] if isinstance(allowed, str) else allowed
            self.assertFalse(any(json_type_matches(value, kind) for kind in allowed_types))
        elif fixture.keyword == "anyOf":
            alternatives = []
            for alternative in node["anyOf"]:
                if "$ref" in alternative:
                    ref = alternative["$ref"]
                    self.assertTrue(ref.startswith("#/$defs/"))
                    alternative = SCHEMA["$defs"][ref.rsplit("/", 1)[-1]]
                alternatives.append(alternative)
            self.assertFalse(
                any(
                    "type" in alternative
                    and any(
                        json_type_matches(value, kind)
                        for kind in (
                            [alternative["type"]]
                            if isinstance(alternative["type"], str)
                            else alternative["type"]
                        )
                    )
                    for alternative in alternatives
                )
            )
        else:  # pragma: no cover - fixture catalog is intentionally closed
            self.fail(f"unsupported fixture keyword: {fixture.keyword}")

    def test_every_exhibited_schema_divergence_is_rejected(self):
        for fixture in DIVERGENCE_FIXTURES:
            with self.subTest(fixture=fixture.name):
                doc = fixture.base()
                fixture.mutate(doc)
                self.assert_declared_schema_violation(fixture, doc)
                self.assertTrue(MODULE.validate_result(doc), fixture.name)

    def test_schema_validation_keywords_are_systematically_supported(self):
        used: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                used.update(
                    key
                    for key in node
                    if key
                    in {
                        "$ref",
                        "additionalProperties",
                        "anyOf",
                        "const",
                        "enum",
                        "items",
                        "minimum",
                        "minLength",
                        "pattern",
                        "properties",
                        "required",
                        "type",
                    }
                )
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(SCHEMA)
        self.assertEqual(used, MODULE.SUPPORTED_SCHEMA_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
