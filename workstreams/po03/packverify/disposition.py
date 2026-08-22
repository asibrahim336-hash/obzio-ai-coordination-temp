#!/usr/bin/env python3
"""Compile current-source and supersession state from repository pointers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, Mapping


_NUMBERED_PATH = re.compile(r"^\d+\.\s+`([^`]+)`")
_LAUNCH_TOKEN = re.compile(
    r"(LAUNCH|ROUTE|REFERENCE|POINTER|HANDOFF|HANDOVER|PREFLIGHT|OPERATOR_D)",
    re.IGNORECASE,
)


class DispositionError(RuntimeError):
    """The current pointer chain is incomplete or inconsistent."""


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DispositionError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _must_exist(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise DispositionError(f"current pointer target is absent: {relative}")
    return path


def read_repository_route(root: Path) -> tuple[str, ...]:
    entrypoint = _must_exist(root, "operations/README.md")
    paths = []
    for line in entrypoint.read_text(encoding="utf-8").splitlines():
        match = _NUMBERED_PATH.match(line)
        if match:
            paths.append(match.group(1))
    if "state/operator-system/ACTIVE_INSTRUCTION_STACK.json" not in paths:
        raise DispositionError("repository route omits active instruction stack")
    for path in paths:
        _must_exist(root, path)
    return tuple(paths)


def _repository_files(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for directory in ("dispatch", "handoff", "handover", "state", "templates"):
        base = root / directory
        if not base.is_dir():
            continue
        paths.extend(
            path.relative_to(root).as_posix()
            for path in base.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
    return tuple(sorted(set(paths)))


def _launch_surfaces(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in paths
            if _LAUNCH_TOKEN.search(Path(path).name)
        )
    )


def _surface_disposition(
    path: str,
    current: frozenset[str],
    superseded_pointer: str | None,
) -> tuple[str, str]:
    upper = path.upper()
    if path in current:
        return "RETAIN_CURRENT", "selected by current pointer or active stack"
    if path == superseded_pointer or "V009" in upper:
        return (
            "SUPERSEDED_UNSENT_RETAIN_EVIDENCE",
            "v009 class is explicitly superseded by instruction-estate disposition",
        )
    if "OPERATOR_D" in upper:
        return (
            "SUPERSEDED_FOR_ACTIVE_ROUTING_RETAIN_EVIDENCE",
            "historical alias class is prohibited for active routing",
        )
    if "CLAUDE_EXTENSION" in upper and "V007" in upper:
        return (
            "SUPERSEDED_UNSENT_RETAIN_EVIDENCE",
            "v007 extension route/reference is explicitly superseded",
        )
    if "PRINCIPAL_AI_OPERATOR_HANDOVER" in upper:
        return (
            "QUARANTINED_OPERATOR_REPORT",
            "handover is explicitly non-controlling",
        )
    return (
        "NOT_SELECTED_RETAIN_EVIDENCE",
        "active stack supersession rule prevents filename-based activation",
    )


def compile_disposition(root: Path | str) -> dict[str, object]:
    repository = Path(root).resolve()
    read_order = read_repository_route(repository)
    active_control_path = "state/ACTIVE_CONTROL_POINTER_CURRENT.json"
    operator_pointer_path = (
        "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json"
    )
    active_control = _read_json(_must_exist(repository, active_control_path))
    operator_pointer = _read_json(_must_exist(repository, operator_pointer_path))
    stack_path = operator_pointer.get("instruction_stack")
    if not isinstance(stack_path, str):
        raise DispositionError("operator pointer has no instruction_stack path")
    stack = _read_json(_must_exist(repository, stack_path))

    resolve_in_order = stack.get("resolve_in_order")
    immutable_evidence = stack.get("immutable_execution_evidence")
    if not isinstance(resolve_in_order, list) or not all(
        isinstance(item, str) for item in resolve_in_order
    ):
        raise DispositionError("active stack resolve_in_order is invalid")
    if not isinstance(immutable_evidence, list) or not all(
        isinstance(item, str) for item in immutable_evidence
    ):
        raise DispositionError("active stack immutable evidence is invalid")

    resolved_paths = tuple(dict.fromkeys((*read_order, *resolve_in_order, *immutable_evidence)))
    for path in resolved_paths:
        _must_exist(repository, path)

    identity_fields = (
        "strategy_snapshot_id",
        "function_id",
        "appointment_id",
        "commission_id",
        "authority_envelope_id",
        "runtime_binding_id",
    )
    identity: dict[str, str] = {}
    for field in identity_fields:
        pointer_value = operator_pointer.get(field)
        stack_value = stack.get(field)
        if not isinstance(pointer_value, str) or pointer_value != stack_value:
            raise DispositionError(f"pointer/stack identity mismatch: {field}")
        identity[field] = pointer_value

    current_paths = set(resolved_paths)
    for field in (
        "selected_pointer",
        "selected_payload",
        "selected_manifest",
        "canonical_command",
    ):
        record = active_control.get(field)
        if isinstance(record, Mapping) and isinstance(record.get("path"), str):
            current_paths.add(record["path"])
            _must_exist(repository, record["path"])

    superseded_pointer_record = active_control.get("superseded_pointer")
    superseded_pointer = (
        superseded_pointer_record.get("path")
        if isinstance(superseded_pointer_record, Mapping)
        and isinstance(superseded_pointer_record.get("path"), str)
        else None
    )
    surfaces = _launch_surfaces(_repository_files(repository))
    dispositions = []
    for path in surfaces:
        disposition, reason = _surface_disposition(
            path, frozenset(current_paths), superseded_pointer
        )
        dispositions.append(
            {
                "path": path,
                "disposition": disposition,
                "reason": reason,
            }
        )

    source_paths = tuple(
        dict.fromkeys(
            (
                "operations/README.md",
                active_control_path,
                operator_pointer_path,
                stack_path,
                "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md",
                *resolved_paths,
            )
        )
    )
    source_hashes = {
        path: _sha256(_must_exist(repository, path))
        for path in sorted(source_paths)
    }
    return {
        "schema_version": "po03-repository-disposition-v1",
        "entrypoint": "operations/README.md",
        "read_order": list(read_order),
        "operator_system": identity,
        "active_instruction_stack": stack_path,
        "stack_resolution_order": list(resolve_in_order),
        "immutable_execution_evidence": list(immutable_evidence),
        "supersession_rule": stack.get("supersession_rule"),
        "launch_surface_rule": (
            "Every file under dispatch, handoff, handover, state, or templates "
            "whose basename contains LAUNCH, ROUTE, REFERENCE, POINTER, "
            "HANDOFF, HANDOVER, PREFLIGHT, or OPERATOR_D receives a disposition."
        ),
        "surface_count": len(dispositions),
        "surface_dispositions": dispositions,
        "source_sha256": source_hashes,
        "mutation": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = compile_disposition(args.root)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
