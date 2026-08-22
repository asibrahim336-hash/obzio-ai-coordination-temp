#!/usr/bin/env python3
"""Refuse fabricated metric rows.

The validator is the enforcement half of the collection harness.  It reads the
frozen metric definitions, the emitted rows, the boundary record and the field
source registry, and rejects any row that invents a value, hides a missing value
behind a plausible default, or emits ``NOT_SUPPORTED`` without an exact observed
boundary.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

UNSUPPORTED = "NOT_SUPPORTED"
MIN_BOUNDARY_CHARS = 80

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

# Values that look like data but assert nothing observed.
PLACEHOLDER_VALUES = {
    "",
    "-",
    "?",
    "unknown",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "tbd",
    "todo",
    "pending",
    "placeholder",
    "example",
    "estimated",
    "approx",
    "assumed",
    "0x0",
}
PLACEHOLDER_BOUNDARY_RE = re.compile(
    r"^(not supported|unsupported|no data|n/?a|unknown|see above|as noted)\.?$", re.IGNORECASE
)

SHA_FIELDS = ("prompt_sha256", "source_sha256", "context_sha256")
COUNT_FIELDS = (
    "checkpoint_count",
    "retry_count",
    "defect_count",
    "rework_count",
    "founder_action_count",
    "collision_count",
    "recovery_events",
)
READBACK_STATES = {"VERIFIED", "MISMATCH", "UNREADABLE", "NO_RESULT_OBSERVED"}
VERDICTS = {"PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {number}: row must be a JSON object")
        rows.append(value)
    return rows


def _boundary_index(boundaries: dict[str, Any]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    field_level = {entry["field"]: entry.get("boundary", "") for entry in boundaries.get("field_level", [])}
    row_level = {
        (entry["task_id"], entry["field"]): entry.get("boundary", "")
        for entry in boundaries.get("row_level", [])
    }
    return field_level, row_level


def validate(
    rows: list[dict[str, Any]],
    definitions: dict[str, Any],
    boundaries: dict[str, Any],
    registry: dict[str, Any],
    expected_task_ids: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    required_fields = list(definitions["required_fields"])
    unsupported_value = definitions.get("unsupported_value", UNSUPPORTED)
    field_level, row_level = _boundary_index(boundaries)
    field_specs = registry.get("fields", {})

    if not rows:
        errors.append("no rows emitted; a counted wave must produce one row per counted unit")

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        label = row.get("task_id", f"row[{index}]")
        if set(row) != set(required_fields):
            missing = sorted(set(required_fields) - set(row))
            extra = sorted(set(row) - set(required_fields))
            errors.append(f"{label}: field set does not match frozen definitions missing={missing} extra={extra}")
            continue
        task_id = row["task_id"]
        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"row[{index}]: task_id must be a non-empty string")
            continue
        if task_id in seen:
            errors.append(f"{task_id}: duplicate row (first seen at index {seen[task_id]})")
        seen[task_id] = index

        for field in required_fields:
            value = row[field]
            spec = field_specs.get(field)
            if spec is None:
                errors.append(f"{task_id}.{field}: no provenance entry in the field source registry")
                continue
            if value == unsupported_value:
                boundary = row_level.get((task_id, field)) or field_level.get(field, "")
                if not boundary.strip():
                    errors.append(f"{task_id}.{field}: {unsupported_value} without an observed boundary")
                elif len(boundary.strip()) < MIN_BOUNDARY_CHARS or PLACEHOLDER_BOUNDARY_RE.match(boundary.strip()):
                    errors.append(f"{task_id}.{field}: boundary is not an exact observation: {boundary!r}")
                continue
            if spec["kind"] == "PROVIDER_UNSUPPORTED":
                errors.append(
                    f"{task_id}.{field}: field has no durable source in this runtime, so value "
                    f"{value!r} would be invented; {unsupported_value} is required"
                )
                continue
            if value is None:
                errors.append(f"{task_id}.{field}: null is not an observation")
                continue
            if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_VALUES:
                errors.append(f"{task_id}.{field}: placeholder value {value!r} is not an observation")
                continue
            if isinstance(value, str) and not value.strip():
                errors.append(f"{task_id}.{field}: empty string is not an observation")
                continue
            if isinstance(value, bool):
                errors.append(f"{task_id}.{field}: boolean is not an accepted metric value")
                continue
            if isinstance(value, (int, float)) and value < 0:
                errors.append(f"{task_id}.{field}: negative sentinel {value!r} is not an observation")

        for field in SHA_FIELDS:
            value = row[field]
            if value != unsupported_value and not (isinstance(value, str) and SHA256_RE.fullmatch(value)):
                errors.append(f"{task_id}.{field}: must be a lowercase SHA-256 or {unsupported_value}")
        for field in COUNT_FIELDS:
            value = row[field]
            if value != unsupported_value and not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                errors.append(f"{task_id}.{field}: must be an integer >= 0 or {unsupported_value}")
        if row["wall_ms"] != unsupported_value and not (
            isinstance(row["wall_ms"], int) and not isinstance(row["wall_ms"], bool)
        ):
            errors.append(f"{task_id}.wall_ms: must be an integer millisecond interval or {unsupported_value}")
        if row["result_commit_id"] != unsupported_value and not (
            isinstance(row["result_commit_id"], str) and GIT_OBJECT_RE.fullmatch(row["result_commit_id"])
        ):
            errors.append(f"{task_id}.result_commit_id: must be a full Git object id or {unsupported_value}")
        if row["readback_state"] not in READBACK_STATES:
            errors.append(f"{task_id}.readback_state: {row['readback_state']!r} is not a measured read-back state")
        if row["first_pass_outcome"] != unsupported_value and row["first_pass_outcome"] not in VERDICTS:
            errors.append(f"{task_id}.first_pass_outcome: {row['first_pass_outcome']!r} is not a contract verdict")

        # Internal consistency: a verified read-back cannot exist without a commit,
        # and an unobserved unit cannot carry downstream observations.
        if row["readback_state"] == "VERIFIED" and row["result_commit_id"] == unsupported_value:
            errors.append(f"{task_id}: readback_state VERIFIED without an observed result_commit_id")
        if row["readback_state"] == "NO_RESULT_OBSERVED":
            for field in ("result_commit_id", "first_pass_outcome", "independent_disposition", "wall_ms"):
                if row[field] != unsupported_value:
                    errors.append(
                        f"{task_id}.{field}: no result was observed, so {row[field]!r} cannot have been measured"
                    )

    if expected_task_ids is not None:
        expected = set(expected_task_ids)
        observed = set(seen)
        for task_id in sorted(expected - observed):
            errors.append(f"{task_id}: counted unit has no metric row")
        for task_id in sorted(observed - expected):
            errors.append(f"{task_id}: row emitted for a unit that is not a counted unit")

    return errors


def counted_task_ids(repo: Path) -> list[str]:
    path = repo / "workstreams/po03/control/work-unit-registry.jsonl"
    task_ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("registry_event") == "CREATED" and entry.get("wave") == "A":
            if entry["task_id"] not in task_ids:
                task_ids.append(entry["task_id"])
    return task_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--boundaries", required=True)
    parser.add_argument("--field-sources", required=True)
    parser.add_argument("--no-registry-check", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    definitions = load_json(repo / "workstreams/po03/metrics/metric-definitions.json")
    rows = load_rows(Path(args.rows))
    boundaries = load_json(Path(args.boundaries))
    registry = load_json(Path(args.field_sources))
    expected = None if args.no_registry_check else counted_task_ids(repo)

    errors = validate(rows, definitions, boundaries, registry, expected)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(f"VALID rows={len(rows)} fields={len(definitions['required_fields'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
