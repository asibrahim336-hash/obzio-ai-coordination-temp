#!/usr/bin/env python3
"""Compile explicit current-source pointers into a deterministic manifest.

The compiler treats pointer metadata as a claim that must agree with the
hash-bound source document.  It selects exactly one CURRENT candidate for
each logical source and fails closed before writing output when selection is
missing, conflicting, ambiguous, or not reproducible from repository bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn


POINTER_PROTOCOL = "OBZIO-CURRENT-SOURCE-POINTER-v1"
SOURCE_PROTOCOL = "OBZIO-CURRENT-SOURCE-v1"
OUTPUT_PROTOCOL = "OBZIO-CURRENT-SOURCE-COMPILATION-v1"
COMPILER_VERSION = "1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_STANDINGS = {"CURRENT", "SUPERSEDED"}
POINTER_FIELDS = {"protocol_version", "pointer_id", "scope", "status", "selections"}
SELECTION_FIELDS = {"logical_name", "candidates"}
SOURCE_FIELDS = {"protocol_version", "source_id", "logical_name", "standing", "payload"}
COMMON_CANDIDATE_FIELDS = {"source_id", "path", "sha256", "standing"}


class CompilationError(ValueError):
    """A stable, machine-readable fail-closed compiler error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> NoReturn:
    raise CompilationError(code, message)


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_JSON_KEY", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("INVALID_UTF8", f"{label}: {exc}")
    try:
        value = json.loads(decoded, object_pairs_hook=_object_without_duplicate_keys)
    except json.JSONDecodeError as exc:
        _fail("INVALID_JSON", f"{label}: {exc}")
    if not isinstance(value, dict):
        _fail("INVALID_DOCUMENT", f"{label}: root must be an object")
    return value


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        _fail("SOURCE_UNREADABLE", f"{label}: {exc}")


def _require_exact_fields(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        _fail("MISSING_FIELD", f"{label}: missing {', '.join(missing)}")
    if unknown:
        _fail("UNKNOWN_FIELD", f"{label}: unknown {', '.join(unknown)}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("INVALID_FIELD", f"{label}: must be a non-empty string")
    return value


def _sha256_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail("INVALID_SHA256", f"{label}: must be a lowercase SHA-256")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _repository_path(repository: Path, relative: Any, label: str) -> tuple[str, Path]:
    relative = _nonempty_string(relative, label)
    if "\\" in relative:
        _fail("NON_PORTABLE_PATH", f"{label}: backslashes are not permitted")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or relative != parsed.as_posix():
        _fail("NON_PORTABLE_PATH", f"{label}: must be a normalized relative POSIX path")
    if any(part in {"", ".", ".."} for part in parsed.parts):
        _fail("PATH_ESCAPE", f"{label}: traversal is not permitted")

    candidate = repository.joinpath(*parsed.parts)
    try:
        if candidate.is_symlink():
            _fail("SYMLINK_SOURCE", f"{label}: symlinks are not permitted")
        resolved = candidate.resolve(strict=True)
        root = repository.resolve(strict=True)
    except OSError as exc:
        _fail("SOURCE_UNREADABLE", f"{label}: {exc}")
    if resolved == root or root not in resolved.parents:
        _fail("PATH_ESCAPE", f"{label}: resolves outside repository")
    if not resolved.is_file():
        _fail("SOURCE_UNREADABLE", f"{label}: source is not a regular file")
    return parsed.as_posix(), resolved


def _validated_source(
    repository: Path,
    logical_name: str,
    candidate: dict[str, Any],
    candidate_label: str,
) -> dict[str, Any]:
    standing = candidate.get("standing")
    if standing not in SOURCE_STANDINGS:
        _fail(
            "INVALID_STANDING",
            f"{candidate_label}.standing: expected CURRENT or SUPERSEDED",
        )
    expected_fields = set(COMMON_CANDIDATE_FIELDS)
    if standing == "SUPERSEDED":
        expected_fields.add("superseded_by")
    _require_exact_fields(candidate, expected_fields, candidate_label)

    source_id = _nonempty_string(candidate["source_id"], f"{candidate_label}.source_id")
    declared_sha = _sha256_hex(candidate["sha256"], f"{candidate_label}.sha256")
    portable_path, source_path = _repository_path(
        repository, candidate["path"], f"{candidate_label}.path"
    )
    source_bytes = _read_bytes(source_path, portable_path)
    observed_sha = _sha256(source_bytes)
    if observed_sha != declared_sha:
        _fail(
            "HASH_MISMATCH",
            f"{candidate_label}.sha256: declared {declared_sha}, observed {observed_sha}",
        )

    source = _load_json_bytes(source_bytes, portable_path)
    _require_exact_fields(source, SOURCE_FIELDS, portable_path)
    if source["protocol_version"] != SOURCE_PROTOCOL:
        _fail("UNSUPPORTED_PROTOCOL", f"{portable_path}: unsupported source protocol")
    for field, expected in (
        ("source_id", source_id),
        ("logical_name", logical_name),
        ("standing", standing),
    ):
        if source[field] != expected:
            _fail(
                "DECLARATION_MISMATCH",
                f"{portable_path}.{field}: expected {expected!r}, observed {source[field]!r}",
            )
    if not isinstance(source["payload"], dict):
        _fail("INVALID_FIELD", f"{portable_path}.payload: must be an object")

    validated = {
        "logical_name": logical_name,
        "source_id": source_id,
        "path": portable_path,
        "sha256": observed_sha,
        "standing": standing,
    }
    if standing == "SUPERSEDED":
        validated["superseded_by"] = _nonempty_string(
            candidate["superseded_by"], f"{candidate_label}.superseded_by"
        )
    return validated


def compile_pointer(repository: Path, pointer: Path) -> dict[str, Any]:
    """Validate and compile one pointer document.

    No filesystem mutation occurs in this function.
    """

    root = repository.resolve(strict=True)
    if not root.is_dir():
        _fail("INVALID_REPOSITORY", f"{repository}: not a directory")
    try:
        pointer_resolved = pointer.resolve(strict=True)
    except OSError as exc:
        _fail("POINTER_UNREADABLE", str(exc))
    if pointer_resolved == root or root not in pointer_resolved.parents:
        _fail("PATH_ESCAPE", "pointer must be inside repository")
    if pointer_resolved.is_symlink() or not pointer_resolved.is_file():
        _fail("POINTER_UNREADABLE", "pointer must be a non-symlink regular file")

    pointer_bytes = _read_bytes(pointer_resolved, str(pointer))
    document = _load_json_bytes(pointer_bytes, str(pointer))
    _require_exact_fields(document, POINTER_FIELDS, "pointer")
    if document["protocol_version"] != POINTER_PROTOCOL:
        _fail("UNSUPPORTED_PROTOCOL", "pointer.protocol_version: unsupported")
    pointer_id = _nonempty_string(document["pointer_id"], "pointer.pointer_id")
    scope = _nonempty_string(document["scope"], "pointer.scope")
    if document["status"] != "CURRENT":
        _fail("POINTER_NOT_CURRENT", "pointer.status must be CURRENT")
    selections = document["selections"]
    if not isinstance(selections, list) or not selections:
        _fail("INVALID_FIELD", "pointer.selections must be a non-empty array")

    resolved_sources: list[dict[str, Any]] = []
    superseded_sources: list[dict[str, Any]] = []
    logical_names: set[str] = set()
    global_source_ids: set[str] = set()
    global_paths: set[str] = set()

    for selection_index, selection in enumerate(selections):
        label = f"pointer.selections[{selection_index}]"
        if not isinstance(selection, dict):
            _fail("INVALID_FIELD", f"{label}: must be an object")
        _require_exact_fields(selection, SELECTION_FIELDS, label)
        logical_name = _nonempty_string(
            selection["logical_name"], f"{label}.logical_name"
        )
        if logical_name in logical_names:
            _fail(
                "AMBIGUOUS_LOGICAL_SOURCE",
                f"{label}.logical_name: duplicate {logical_name}",
            )
        logical_names.add(logical_name)
        candidates = selection["candidates"]
        if not isinstance(candidates, list) or not candidates:
            _fail("NO_CURRENT_SOURCE", f"{label}.candidates: no candidates")

        validated_candidates: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(candidates):
            candidate_label = f"{label}.candidates[{candidate_index}]"
            if not isinstance(candidate, dict):
                _fail("INVALID_FIELD", f"{candidate_label}: must be an object")
            validated = _validated_source(
                root, logical_name, candidate, candidate_label
            )
            if validated["source_id"] in global_source_ids:
                _fail(
                    "DUPLICATE_SOURCE_ID",
                    f"{candidate_label}.source_id: duplicate {validated['source_id']}",
                )
            if validated["path"] in global_paths:
                _fail(
                    "DUPLICATE_SOURCE_PATH",
                    f"{candidate_label}.path: duplicate {validated['path']}",
                )
            global_source_ids.add(validated["source_id"])
            global_paths.add(validated["path"])
            validated_candidates.append(validated)

        current = [
            candidate
            for candidate in validated_candidates
            if candidate["standing"] == "CURRENT"
        ]
        if not current:
            _fail("NO_CURRENT_SOURCE", f"{logical_name}: no CURRENT candidate")
        if len(current) != 1:
            _fail(
                "AMBIGUOUS_CURRENT_SOURCE",
                f"{logical_name}: expected one CURRENT candidate, observed {len(current)}",
            )
        current_source = current[0]
        for candidate in validated_candidates:
            if (
                candidate["standing"] == "SUPERSEDED"
                and candidate["superseded_by"] != current_source["source_id"]
            ):
                _fail(
                    "BROKEN_SUPERSESSION",
                    f"{candidate['source_id']}: superseded_by does not select "
                    f"{current_source['source_id']}",
                )
        resolved_sources.append(current_source)
        superseded_sources.extend(
            candidate
            for candidate in validated_candidates
            if candidate["standing"] == "SUPERSEDED"
        )

    resolved_sources.sort(key=lambda item: (item["logical_name"], item["source_id"]))
    superseded_sources.sort(
        key=lambda item: (item["logical_name"], item["source_id"])
    )
    core = {
        "protocol_version": OUTPUT_PROTOCOL,
        "compiler_version": COMPILER_VERSION,
        "pointer": {
            "pointer_id": pointer_id,
            "scope": scope,
            "sha256": _sha256(pointer_bytes),
        },
        "resolved_sources": resolved_sources,
        "superseded_sources": superseded_sources,
    }
    core["resolution_sha256"] = _sha256(_canonical_json_bytes(core))
    return core


def write_compilation(output: Path, compilation: dict[str, Any]) -> None:
    """Atomically write compilation bytes after all checks have passed."""

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(compilation, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix=f".{output.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, output)
    except OSError as exc:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
        _fail("OUTPUT_WRITE_FAILED", str(exc))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve hash-bound CURRENT and SUPERSEDED repository sources."
    )
    parser.add_argument("pointer", type=Path, help="explicit pointer JSON")
    parser.add_argument(
        "--repository",
        type=Path,
        required=True,
        help="root against which repository-relative source paths resolve",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write deterministic compilation JSON; omit to print to stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        compilation = compile_pointer(args.repository, args.pointer)
        if args.output is None:
            print(json.dumps(compilation, indent=2, sort_keys=True))
        else:
            write_compilation(args.output, compilation)
    except CompilationError as exc:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": {"code": exc.code, "message": exc.message},
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
