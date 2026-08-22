#!/usr/bin/env python3
"""Adversarial execution harness for wave-a-041.

The shared gate is loaded from its read-only repository path by file location.
It is never copied into this subtree, never mutated, and never shadowed on
`sys.path`; the candidate repair lives in a separately named module under
`candidate/`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import minischema

HERE = Path(__file__).resolve().parent
ATTEMPT_ROOT = HERE.parent
PO03_ROOT = ATTEMPT_ROOT.parents[2]
REPO_ROOT = PO03_ROOT.parents[1]

SHARED_GATE_PATH = PO03_ROOT / "tools" / "validate_contracts.py"
SCHEMA_PATH = PO03_ROOT / "contracts" / "transactional-result.schema.json"
CASES_PATH = ATTEMPT_ROOT / "adversarial-cases.json"

EXPECTED_GATE_SHA256 = "3c2ebd7f06b0230c35355ae0b569283e8dbf90ed87127dedddb7d389b1c62bc7"
EXPECTED_SCHEMA_SHA256 = "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_shared_gate():
    """Import the shared validator in place, under a private module name."""
    digest = sha256_file(SHARED_GATE_PATH)
    if digest != EXPECTED_GATE_SHA256:
        raise AssertionError(
            f"shared gate changed: expected {EXPECTED_GATE_SHA256}, observed {digest}. "
            "Frozen findings no longer apply to this source."
        )
    spec = importlib.util.spec_from_file_location("po03_shared_gate_readonly", SHARED_GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_schema() -> dict[str, Any]:
    digest = sha256_file(SCHEMA_PATH)
    if digest != EXPECTED_SCHEMA_SHA256:
        raise AssertionError(f"schema changed: expected {EXPECTED_SCHEMA_SHA256}, observed {digest}")
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_cases() -> dict[str, Any]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def schema_errors(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return minischema.validate(document, schema)


def jsonschema_errors(document: dict[str, Any], schema: dict[str, Any]) -> list[str] | None:
    """Cross-check with the reference implementation when it is importable."""
    try:
        import jsonschema
    except ImportError:
        return None
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(document)]


def evaluate_case(case: dict[str, Any], gate, schema: dict[str, Any]) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for index, document in enumerate(case["documents"]):
        gate_errs = gate.validate_result(json.loads(json.dumps(document)))
        mini = schema_errors(document, schema)
        reference = jsonschema_errors(document, schema)
        documents.append(
            {
                "index": index,
                "gate_outcome": "ACCEPT" if not gate_errs else "REJECT",
                "gate_errors": gate_errs,
                "schema_outcome": "VALID" if not mini else "INVALID",
                "schema_errors": mini,
                "reference_schema_outcome": (
                    None if reference is None else ("VALID" if not reference else "INVALID")
                ),
                "reference_schema_errors": reference,
                "reference_agrees_with_minischema": (
                    None if reference is None else (bool(reference) == bool(mini))
                ),
            }
        )

    gate_outcome = "ACCEPT" if all(d["gate_outcome"] == "ACCEPT" for d in documents) else "REJECT"
    schema_outcome = "VALID" if all(d["schema_outcome"] == "VALID" for d in documents) else "INVALID"
    kind = case["case_id"][0]

    if case["family"] == "control":
        observed = "CONTROL_ACCEPT" if gate_outcome == "ACCEPT" else "CONTROL_FAILURE"
    elif kind == "C":
        if gate_outcome == "REJECT":
            observed = "BLOCKED"
        else:
            observed = "EXPLOIT_BOTH" if schema_outcome == "VALID" else "EXPLOIT_GATE_ONLY"
    elif kind == "U":
        observed = "UNREPRESENTABLE" if gate_outcome == "REJECT" else "REPRESENTABLE"
    elif kind == "B":
        observed = "BLOCKED" if gate_outcome == "REJECT" else "CONTROL_FAILURE"
    else:
        raise ValueError(f"unclassifiable case id: {case['case_id']}")

    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "title": case["title"],
        "predicted_gate": case["predicted_gate"],
        "observed_gate": gate_outcome,
        "predicted_schema": case["predicted_schema"],
        "observed_schema": schema_outcome,
        "predicted_classification": case["predicted_classification"],
        "observed_classification": observed,
        "prediction_held": (
            gate_outcome == case["predicted_gate"]
            and schema_outcome == case["predicted_schema"]
            and observed == case["predicted_classification"]
        ),
        "documents": documents,
    }


def run_all() -> dict[str, Any]:
    gate = load_shared_gate()
    schema = load_schema()
    cases = load_cases()
    results = [evaluate_case(case, gate, schema) for case in cases["cases"]]
    exploits = [r["case_id"] for r in results if r["observed_classification"].startswith("EXPLOIT")]
    return {
        "cases_version": cases["cases_version"],
        "cases_sha256": sha256_file(CASES_PATH),
        "gate_sha256": sha256_file(SHARED_GATE_PATH),
        "schema_sha256": sha256_file(SCHEMA_PATH),
        "reference_validator": _reference_identity(),
        "results": results,
        "exploit_case_ids": exploits,
        "blocked_case_ids": [r["case_id"] for r in results if r["observed_classification"] == "BLOCKED"],
        "unrepresentable_case_ids": [
            r["case_id"] for r in results if r["observed_classification"] == "UNREPRESENTABLE"
        ],
        "mispredicted_case_ids": [r["case_id"] for r in results if not r["prediction_held"]],
    }


def _reference_identity() -> dict[str, Any]:
    try:
        import importlib.metadata

        import jsonschema  # noqa: F401
    except ImportError:
        return {"available": False, "note": "jsonschema absent; minischema subset checker used alone"}
    return {
        "available": True,
        "implementation": "jsonschema",
        "version": importlib.metadata.version("jsonschema"),
    }


if __name__ == "__main__":
    print(json.dumps(run_all(), indent=2, sort_keys=True, ensure_ascii=False))
