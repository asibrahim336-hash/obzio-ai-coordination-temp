#!/usr/bin/env python3
"""Measure scanner precision and recall against labelled portable fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence


UNIT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(UNIT_ROOT))

import portable_path_scanner as scanner  # noqa: E402


PROTOCOL_VERSION = "OBZIO-PORTABLE-PATH-MEASUREMENT-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(manifest_path: Path) -> dict[str, object]:
    manifest_data = manifest_path.read_bytes()
    manifest = json.loads(manifest_data.decode("utf-8"))
    if manifest.get("protocol_version") != "OBZIO-PORTABLE-PATH-FIXTURES-v1":
        raise ValueError("unsupported fixture manifest protocol")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture manifest requires non-empty cases")
    checkout_roots = manifest.get("checkout_roots", [])
    if not isinstance(checkout_roots, list):
        raise ValueError("checkout_roots must be an array")

    by_file: dict[str, list[dict[str, object]]] = {}
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("every case must be an object")
        case_id = case.get("case_id")
        filename = case.get("file")
        line = case.get("line")
        expected = case.get("expected_finding")
        categories = case.get("expected_categories")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("case_id must be unique and non-empty")
        if not isinstance(filename, str) or not filename:
            raise ValueError(f"{case_id}: file must be non-empty")
        if not isinstance(line, int) or line < 1:
            raise ValueError(f"{case_id}: line must be an integer >= 1")
        if not isinstance(expected, bool):
            raise ValueError(f"{case_id}: expected_finding must be boolean")
        if not isinstance(categories, list) or not all(
            isinstance(category, str) for category in categories
        ):
            raise ValueError(f"{case_id}: expected_categories must be strings")
        case_ids.add(case_id)
        by_file.setdefault(filename, []).append(case)

    findings_by_coordinate: dict[tuple[str, int], list[dict[str, object]]] = {}
    scan_errors: list[dict[str, str]] = []
    fixture_hashes: list[dict[str, object]] = []
    for filename in sorted(by_file):
        fixture = manifest_path.parent / filename
        if not fixture.is_file():
            raise ValueError(f"fixture is missing: {filename}")
        line_count = len(fixture.read_text(encoding="utf-8").splitlines())
        declared_lines = {int(case["line"]) for case in by_file[filename]}
        expected_lines = set(range(1, line_count + 1))
        if declared_lines != expected_lines:
            raise ValueError(
                f"{filename}: every physical line must have exactly one label; "
                f"declared={sorted(declared_lines)} physical={sorted(expected_lines)}"
            )
        report = scanner.scan_paths(
            [fixture],
            checkout_roots=checkout_roots,
        )
        scan_errors.extend(report["errors"])
        fixture_hashes.append(
            {
                "file": filename,
                "sha256": _sha256(fixture),
                "bytes": len(fixture.read_bytes()),
                "case_count": len(by_file[filename]),
            }
        )
        for finding in report["findings"]:
            findings_by_coordinate.setdefault(
                (filename, int(finding["line"])), []
            ).append(finding)

    true_positive = 0
    true_negative = 0
    false_positive = 0
    false_negative = 0
    category_misses: list[dict[str, object]] = []
    false_positive_cases: list[str] = []
    false_negative_cases: list[str] = []
    observed_cases: list[dict[str, object]] = []

    for case in cases:
        case_id = str(case["case_id"])
        key = (str(case["file"]), int(case["line"]))
        observed = findings_by_coordinate.get(key, [])
        expected = bool(case["expected_finding"])
        has_finding = bool(observed)
        observed_categories = sorted(
            {
                str(category)
                for finding in observed
                for category in finding["categories"]
            }
        )
        required_categories = sorted(str(value) for value in case["expected_categories"])
        missing_categories = sorted(set(required_categories) - set(observed_categories))

        if expected and has_finding:
            true_positive += 1
        elif expected:
            false_negative += 1
            false_negative_cases.append(case_id)
        elif has_finding:
            false_positive += 1
            false_positive_cases.append(case_id)
        else:
            true_negative += 1
        if missing_categories:
            category_misses.append(
                {
                    "case_id": case_id,
                    "missing_categories": missing_categories,
                    "observed_categories": observed_categories,
                }
            )
        observed_cases.append(
            {
                "case_id": case_id,
                "expected_finding": expected,
                "observed_finding": has_finding,
                "expected_categories": required_categories,
                "observed_categories": observed_categories,
            }
        )

    negative_count = true_negative + false_positive
    positive_count = true_positive + false_negative
    false_positive_rate = false_positive / negative_count if negative_count else None
    recall = true_positive / positive_count if positive_count else None
    status = (
        "PASS"
        if not scan_errors
        and not false_positive_cases
        and not false_negative_cases
        and not category_misses
        else "FAIL"
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "fixture_manifest": {
            "sha256": hashlib.sha256(manifest_data).hexdigest(),
            "bytes": len(manifest_data),
        },
        "fixtures": fixture_hashes,
        "metrics": {
            "case_count": len(cases),
            "positive_case_count": positive_count,
            "negative_case_count": negative_count,
            "true_positive": true_positive,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "false_positive_rate": false_positive_rate,
            "recall": recall,
        },
        "false_positive_cases": false_positive_cases,
        "false_negative_cases": false_negative_cases,
        "category_misses": category_misses,
        "scan_errors": scan_errors,
        "observed_cases": observed_cases,
        "decision_changed": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=UNIT_ROOT / "fixtures" / "case-manifest.json",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = measure(args.manifest)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"MEASUREMENT_ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(
        result,
        sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    )
    sys.stdout.write("\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
