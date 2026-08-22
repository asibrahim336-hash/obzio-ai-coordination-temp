#!/usr/bin/env python3
"""Byte-determinism checker for PO-03 generated artifacts (unit a3-u05).

Runs each declared generator twice, as two separate processes, and requires the
two outputs to be byte-identical once the declared volatile fields are masked.

Why masking rather than pattern matching
----------------------------------------
The obvious implementation ignores fields whose names look like timestamps.
That also ignores a genuinely non-deterministic field that happens to be named
``created_at``, and it silently tolerates new volatile fields as they appear.
Here every permitted field is enumerated in ``determinism-contract.json`` with
its kind and its reason, and any other difference is a finding.  Masking
replaces the declared fields with a constant sentinel and then compares the two
canonical encodings byte for byte, so declaring a field volatile narrows the
comparison but never skips it.

Array elements are addressed as ``items[].salt``: a per-index declaration would
make the contract depend on how many elements a run happened to produce.

Dependency-free: standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]
DEFAULT_CONTRACT = RUNTIME_DIR / "determinism-contract.json"

REPORT_SCHEMA = "po03-determinism-report-v1"
MASK = "<<volatile>>"


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != "po03-determinism-contract-v1":
        raise ValueError(f"unexpected contract schema: {contract.get('schema')!r}")
    return contract


def canonical(document: Any) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def flatten(document: Any, prefix: str = "") -> dict[str, Any]:
    """Map a document to {field_path: leaf_value}, with [] for array indices."""
    flat: dict[str, Any] = {}
    if isinstance(document, dict):
        for key, value in document.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten(value, child))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            flat.update(flatten(value, f"{prefix}[{index}]"))
    else:
        flat[prefix] = document
    return flat


def declared_path(field_path: str) -> str:
    """Collapse concrete array indices so declarations are index independent."""
    result: list[str] = []
    depth = 0
    for character in field_path:
        if character == "[":
            depth += 1
            result.append("[")
        elif character == "]":
            depth -= 1
            result.append("]")
        elif depth == 0:
            result.append(character)
    return "".join(result)


def mask(document: Any, volatile: set[str], prefix: str = "") -> Any:
    if isinstance(document, dict):
        return {
            key: mask(value, volatile, f"{prefix}.{key}" if prefix else str(key))
            for key, value in document.items()
        }
    if isinstance(document, list):
        return [mask(value, volatile, f"{prefix}[]") for value in document]
    return MASK if prefix in volatile else document


def run_generator(spec: dict[str, Any], scratch: Path) -> Any:
    argv = [
        token.replace("{python}", sys.executable)
        .replace("{repo}", str(REPO_ROOT))
        .replace("{scratch}", str(scratch))
        for token in spec["argv"]
    ]
    result = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True)
    # Some generators are gates and exit non-zero by design; the contract states
    # the code each one is expected to produce so an unexpected code is a failure
    # rather than a silently accepted difference.
    expected_exit = spec.get("expected_exit_code", 0)
    # "unconstrained" is for a generator whose exit code tracks something other
    # than its own correctness -- a whole-tree gate exits 1 while the tree has
    # findings, which is another gate's business. Pinning a number there would
    # be asserting that a defect currently exists, and would break the moment
    # the routed findings landed.
    if expected_exit != "unconstrained" and result.returncode != expected_exit:
        raise RuntimeError(
            f"generator for {spec['artifact_class']} exited {result.returncode}, "
            f"expected {expected_exit}: {result.stderr.strip()}"
        )
    if spec["capture"] == "stdout":
        return json.loads(result.stdout)
    target = Path(
        spec["output_file"].replace("{scratch}", str(scratch)).replace("{repo}", str(REPO_ROOT))
    )
    return json.loads(target.read_text(encoding="utf-8"))


def compare(spec: dict[str, Any], first: Any, second: Any) -> dict[str, Any]:
    volatile = {entry["path"] for entry in spec.get("volatile_fields", [])}

    flat_first = flatten(first)
    flat_second = flatten(second)

    differing = sorted(
        path
        for path in set(flat_first) | set(flat_second)
        if flat_first.get(path, object()) != flat_second.get(path, object())
    )
    undeclared = sorted({declared_path(path) for path in differing} - volatile)

    masked_first = canonical(mask(first, volatile))
    masked_second = canonical(mask(second, volatile))
    byte_identical = masked_first == masked_second

    declared_but_stable = sorted(
        path for path in volatile if path not in {declared_path(item) for item in differing}
    )

    return {
        "artifact_class": spec["artifact_class"],
        "declared_volatile_fields": sorted(volatile),
        "declared_volatile_kinds": {
            entry["path"]: entry["kind"] for entry in spec.get("volatile_fields", [])
        },
        "differing_field_paths": differing,
        "undeclared_variance": undeclared,
        "declared_but_did_not_vary": declared_but_stable,
        "byte_identical_after_masking": byte_identical,
        "verdict": "PASS" if not undeclared and byte_identical else "FAIL",
    }


def check_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for spec in specs:
        with tempfile.TemporaryDirectory(prefix="po03-determinism-first-") as scratch_a:
            first = run_generator(spec, Path(scratch_a))
        # A second, independent scratch directory: reusing one would let a
        # generator appear deterministic only because it read back its own
        # previous output.
        with tempfile.TemporaryDirectory(prefix="po03-determinism-second-") as scratch_b:
            second = run_generator(spec, Path(scratch_b))
        outcomes.append(compare(spec, first, second))
    return outcomes


def build_report(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "artifact_classes_checked": len(outcomes),
        "runs_per_class": 2,
        "enumerated_timestamp_fields": sorted(
            {
                path
                for outcome in outcomes
                for path, kind in outcome["declared_volatile_kinds"].items()
                if kind == "timestamp"
            }
        ),
        "enumerated_entropy_fields": sorted(
            {
                path
                for outcome in outcomes
                for path, kind in outcome["declared_volatile_kinds"].items()
                if kind == "entropy"
            }
        ),
        "failing_classes": [o["artifact_class"] for o in outcomes if o["verdict"] == "FAIL"],
        "verdict": "FAIL" if any(o["verdict"] == "FAIL" for o in outcomes) else "PASS",
        "classes": outcomes,
    }


def emit(report: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for outcome in report["classes"]:
            print(f"{outcome['verdict']} {outcome['artifact_class']}")
            for path in outcome["undeclared_variance"]:
                print(f"  UNDECLARED_VARIANCE: {path}")
            for path in outcome["declared_but_did_not_vary"]:
                print(f"  DECLARED_BUT_STABLE: {path}")
        if report["verdict"] == "FAIL":
            print(f"FAIL {len(report['failing_classes'])} artifact class(es) are not deterministic")
        else:
            print(
                f"PASS {report['artifact_classes_checked']} artifact class(es) byte-identical across "
                f"{report['runs_per_class']} runs with "
                f"{len(report['enumerated_timestamp_fields'])} enumerated timestamp field(s)"
            )
    return 1 if report["verdict"] == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO-03 artifact determinism checker")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="check the planted fixture generators instead of the real artifact classes",
    )
    args = parser.parse_args(argv)

    try:
        contract = load_contract(Path(args.contract))
        key = "fixture_generators" if args.fixtures else "generators"
        report = build_report(check_specs(contract[key]))
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"DETERMINISM_ERROR: {exc}", file=sys.stderr)
        return 2
    return emit(report, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
