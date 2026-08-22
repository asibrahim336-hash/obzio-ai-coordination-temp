#!/usr/bin/env python3
"""Build deterministic, hash-bounded, task-specific source capsules.

The request is the admission decision.  This builder validates that every
admitted source is explicitly task-tagged, byte-pinned, within both budgets,
and sufficient to cover the declared critical-source set.  It then writes
only those sources plus a deterministic manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn


PROTOCOL_VERSION = "OBZIO-SOURCE-CAPSULE-REQUEST-v1"
MANIFEST_VERSION = "OBZIO-SOURCE-CAPSULE-MANIFEST-v1"
SHA256_LENGTH = 64
REQUEST_FIELDS = {
    "protocol_version",
    "task_id",
    "source_locator",
    "source_snapshot_sha256",
    "budget",
    "allowed_relevance_tags",
    "required_sources",
    "sources",
}
SOURCE_FIELDS = {
    "path",
    "sha256",
    "critical",
    "relevance_tags",
    "rationale",
}


class CapsuleError(Exception):
    """A stable, machine-readable capsule rejection."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "details": self.details,
                "message": self.message,
            },
            "status": "REJECTED",
        }


@dataclass(frozen=True)
class AdmittedSource:
    path: str
    sha256: str
    content: bytes
    critical: bool
    relevance_tags: tuple[str, ...]
    rationale: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "bytes": len(self.content),
            "critical": self.critical,
            "path": self.path,
            "rationale": self.rationale,
            "relevance_tags": list(self.relevance_tags),
            "sha256": self.sha256,
        }


def _reject(code: str, message: str, **details: Any) -> NoReturn:
    raise CapsuleError(code, message, **details)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _pretty_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_relative_path(value: Any, field: str) -> str:
    if not _nonempty_string(value):
        _reject("INVALID_PATH", f"{field} must be a non-empty POSIX path", field=field)
    assert isinstance(value, str)
    if "\\" in value or "\x00" in value:
        _reject(
            "INVALID_PATH",
            f"{field} must use canonical POSIX separators",
            field=field,
            path=value,
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() == "."
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _reject(
            "INVALID_PATH",
            f"{field} must be canonical and relative",
            field=field,
            path=value,
        )
    canonical = path.as_posix()
    if canonical != value:
        _reject(
            "INVALID_PATH",
            f"{field} is not canonical",
            field=field,
            path=value,
        )
    return canonical


def _normalized_request(request: dict[str, Any]) -> dict[str, Any]:
    """Normalize order-insensitive fields for a semantic request digest."""
    return {
        "allowed_relevance_tags": sorted(request["allowed_relevance_tags"]),
        "budget": {
            "max_bytes": request["budget"]["max_bytes"],
            "max_sources": request["budget"]["max_sources"],
        },
        "protocol_version": request["protocol_version"],
        "required_sources": sorted(request["required_sources"]),
        "source_locator": request["source_locator"],
        "source_snapshot_sha256": request["source_snapshot_sha256"],
        "sources": sorted(
            (
                {
                    "critical": source["critical"],
                    "path": source["path"],
                    "rationale": source["rationale"],
                    "relevance_tags": sorted(source["relevance_tags"]),
                    "sha256": source["sha256"],
                }
                for source in request["sources"]
            ),
            key=lambda source: source["path"],
        ),
        "task_id": request["task_id"],
    }


def source_snapshot_sha256(sources: list[dict[str, Any]]) -> str:
    """Digest the sorted path/content-hash pairs that define a source snapshot."""
    pins = sorted(
        ({"path": source["path"], "sha256": source["sha256"]} for source in sources),
        key=lambda pin: pin["path"],
    )
    return hashlib.sha256(_canonical_json(pins)).hexdigest()


def _load_request(request_path: Path) -> dict[str, Any]:
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _reject("INVALID_REQUEST_JSON", "request is not readable JSON", reason=str(exc))
    if not isinstance(request, dict):
        _reject("INVALID_REQUEST", "request root must be an object")
    unexpected = sorted(set(request) - REQUEST_FIELDS)
    missing = sorted(REQUEST_FIELDS - set(request))
    if unexpected or missing:
        _reject(
            "INVALID_REQUEST_FIELDS",
            "request fields do not match the protocol",
            missing=missing,
            unexpected=unexpected,
        )
    return request


def _validate_request(request: dict[str, Any]) -> dict[str, Any]:
    if request["protocol_version"] != PROTOCOL_VERSION:
        _reject(
            "UNSUPPORTED_PROTOCOL",
            "request protocol is not supported",
            observed=request["protocol_version"],
        )
    for field in ("task_id", "source_locator"):
        if not _nonempty_string(request[field]):
            _reject("INVALID_REQUEST", f"{field} must be a non-empty string", field=field)
    if not _is_sha256(request["source_snapshot_sha256"]):
        _reject(
            "INVALID_SNAPSHOT_HASH",
            "source_snapshot_sha256 must be a lowercase SHA-256",
        )

    budget = request["budget"]
    if not isinstance(budget, dict) or set(budget) != {"max_bytes", "max_sources"}:
        _reject(
            "INVALID_BUDGET",
            "budget must contain only max_bytes and max_sources",
        )
    for field in ("max_bytes", "max_sources"):
        if not _positive_integer(budget[field]):
            _reject(
                "INVALID_BUDGET",
                f"budget.{field} must be an integer >= 1",
                field=field,
            )

    allowed_tags = request["allowed_relevance_tags"]
    if (
        not isinstance(allowed_tags, list)
        or not allowed_tags
        or any(not _nonempty_string(tag) for tag in allowed_tags)
        or len(set(allowed_tags)) != len(allowed_tags)
    ):
        _reject(
            "INVALID_RELEVANCE_POLICY",
            "allowed_relevance_tags must contain unique non-empty strings",
        )

    required = request["required_sources"]
    if not isinstance(required, list):
        _reject("INVALID_CRITICAL_SET", "required_sources must be an array")
    normalized_required = [
        _safe_relative_path(path, "required_sources[]") for path in required
    ]
    if len(set(normalized_required)) != len(normalized_required):
        _reject(
            "DUPLICATE_CRITICAL_SOURCE",
            "required_sources contains duplicates",
        )

    sources = request["sources"]
    if not isinstance(sources, list) or not sources:
        _reject("INVALID_SOURCES", "sources must be a non-empty array")
    if len(sources) > budget["max_sources"]:
        _reject(
            "SOURCE_BUDGET_EXCEEDED",
            "declared sources exceed max_sources",
            max_sources=budget["max_sources"],
            observed_sources=len(sources),
        )

    seen_paths: set[str] = set()
    critical_paths: set[str] = set()
    allowed_tag_set = set(allowed_tags)
    normalized_sources: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            _reject(
                "INVALID_SOURCE",
                "every source must be an object",
                source_index=index,
            )
        unexpected = sorted(set(source) - SOURCE_FIELDS)
        missing = sorted(SOURCE_FIELDS - set(source))
        if unexpected or missing:
            _reject(
                "INVALID_SOURCE_FIELDS",
                "source fields do not match the protocol",
                missing=missing,
                source_index=index,
                unexpected=unexpected,
            )
        path = _safe_relative_path(source["path"], f"sources[{index}].path")
        if path in seen_paths:
            _reject("DUPLICATE_SOURCE", "source path is duplicated", path=path)
        seen_paths.add(path)
        if not _is_sha256(source["sha256"]):
            _reject(
                "INVALID_SOURCE_HASH",
                "source sha256 must be lowercase SHA-256",
                path=path,
            )
        if not isinstance(source["critical"], bool):
            _reject(
                "INVALID_CRITICAL_FLAG",
                "source critical must be boolean",
                path=path,
            )
        tags = source["relevance_tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or any(not _nonempty_string(tag) for tag in tags)
            or len(set(tags)) != len(tags)
        ):
            _reject(
                "MISSING_RELEVANCE",
                "source must have unique non-empty relevance tags",
                path=path,
            )
        disallowed_tags = sorted(set(tags) - allowed_tag_set)
        if disallowed_tags:
            _reject(
                "IRRELEVANT_SOURCE",
                "source uses tags outside the task relevance policy",
                disallowed_tags=disallowed_tags,
                path=path,
            )
        if not _nonempty_string(source["rationale"]):
            _reject(
                "MISSING_RELEVANCE",
                "source rationale must be a non-empty string",
                path=path,
            )
        if source["critical"]:
            critical_paths.add(path)
        normalized_sources.append(
            {
                "critical": source["critical"],
                "path": path,
                "rationale": source["rationale"].strip(),
                "relevance_tags": sorted(tags),
                "sha256": source["sha256"],
            }
        )

    required_set = set(normalized_required)
    omitted = sorted(required_set - seen_paths)
    if omitted:
        _reject(
            "MISSING_CRITICAL_SOURCE",
            "one or more required sources were omitted",
            omitted=omitted,
        )
    incorrectly_optional = sorted(required_set - critical_paths)
    undeclared_critical = sorted(critical_paths - required_set)
    if incorrectly_optional or undeclared_critical:
        _reject(
            "CRITICAL_SET_MISMATCH",
            "required_sources must exactly match sources marked critical",
            incorrectly_optional=incorrectly_optional,
            undeclared_critical=undeclared_critical,
        )

    normalized = dict(request)
    normalized["allowed_relevance_tags"] = sorted(allowed_tags)
    normalized["required_sources"] = sorted(normalized_required)
    normalized["sources"] = sorted(normalized_sources, key=lambda item: item["path"])
    observed_snapshot = source_snapshot_sha256(normalized["sources"])
    if observed_snapshot != request["source_snapshot_sha256"]:
        _reject(
            "SNAPSHOT_HASH_MISMATCH",
            "source snapshot digest does not match declared source pins",
            expected=request["source_snapshot_sha256"],
            observed=observed_snapshot,
        )
    return normalized


def _read_regular_file(source_root: Path, relative_path: str) -> bytes:
    root = source_root.resolve(strict=True)
    candidate = root
    for part in PurePosixPath(relative_path).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            _reject(
                "SYMLINK_SOURCE",
                "source paths may not traverse symlinks",
                path=relative_path,
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        metadata = resolved.stat()
    except FileNotFoundError:
        _reject("SOURCE_NOT_FOUND", "source file does not exist", path=relative_path)
    except ValueError:
        _reject(
            "SOURCE_OUTSIDE_ROOT",
            "source resolved outside source root",
            path=relative_path,
        )
    except OSError as exc:
        _reject(
            "SOURCE_UNREADABLE",
            "source metadata could not be read",
            path=relative_path,
            reason=str(exc),
        )
    if not stat.S_ISREG(metadata.st_mode):
        _reject(
            "SOURCE_NOT_REGULAR",
            "source must be a regular file",
            path=relative_path,
        )
    try:
        return resolved.read_bytes()
    except OSError as exc:
        _reject(
            "SOURCE_UNREADABLE",
            "source bytes could not be read",
            path=relative_path,
            reason=str(exc),
        )


def _admit_sources(source_root: Path, request: dict[str, Any]) -> list[AdmittedSource]:
    admitted: list[AdmittedSource] = []
    total_bytes = 0
    max_bytes = request["budget"]["max_bytes"]
    for source in request["sources"]:
        content = _read_regular_file(source_root, source["path"])
        observed_sha256 = hashlib.sha256(content).hexdigest()
        if observed_sha256 != source["sha256"]:
            _reject(
                "SOURCE_HASH_MISMATCH",
                "source bytes do not match the declared SHA-256",
                expected=source["sha256"],
                observed=observed_sha256,
                path=source["path"],
            )
        total_bytes += len(content)
        if total_bytes > max_bytes:
            _reject(
                "BYTE_BUDGET_EXCEEDED",
                "admitted source bytes exceed max_bytes",
                max_bytes=max_bytes,
                observed_bytes=total_bytes,
                path=source["path"],
            )
        admitted.append(
            AdmittedSource(
                path=source["path"],
                sha256=observed_sha256,
                content=content,
                critical=source["critical"],
                relevance_tags=tuple(source["relevance_tags"]),
                rationale=source["rationale"],
            )
        )
    return admitted


def _manifest(request: dict[str, Any], admitted: list[AdmittedSource]) -> dict[str, Any]:
    source_bytes = sum(len(source.content) for source in admitted)
    semantic_request = _normalized_request(request)
    return {
        "budget": {
            "max_bytes": request["budget"]["max_bytes"],
            "max_sources": request["budget"]["max_sources"],
            "remaining_bytes": request["budget"]["max_bytes"] - source_bytes,
            "remaining_sources": request["budget"]["max_sources"] - len(admitted),
        },
        "critical_sources": list(request["required_sources"]),
        "hash_algorithm": "sha256",
        "protocol_version": MANIFEST_VERSION,
        "request_semantic_sha256": hashlib.sha256(
            _canonical_json(semantic_request)
        ).hexdigest(),
        "source_bytes": source_bytes,
        "source_count": len(admitted),
        "source_locator": request["source_locator"],
        "source_snapshot_sha256": request["source_snapshot_sha256"],
        "sources": [source.manifest_entry() for source in admitted],
        "task_id": request["task_id"],
    }


def build_capsule(
    source_root: Path,
    request_path: Path,
    output_directory: Path,
) -> dict[str, Any]:
    """Validate and atomically build a capsule, returning its manifest."""
    source_root = source_root.resolve(strict=True)
    request = _validate_request(_load_request(request_path))
    admitted = _admit_sources(source_root, request)
    manifest = _manifest(request, admitted)
    manifest_bytes = _pretty_json(manifest)

    output_directory = output_directory.absolute()
    if output_directory.exists() or output_directory.is_symlink():
        _reject(
            "OUTPUT_EXISTS",
            "output directory already exists; refusing to overwrite",
            output=str(output_directory),
        )
    parent = output_directory.parent
    if not parent.is_dir():
        _reject(
            "OUTPUT_PARENT_MISSING",
            "output parent directory does not exist",
            parent=str(parent),
        )

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.staging-", dir=parent)
    )
    try:
        for source in admitted:
            destination = temporary.joinpath(*PurePosixPath(source.path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.content)
        (temporary / "capsule-manifest.json").write_bytes(manifest_bytes)
        os.replace(temporary, output_directory)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic hash-bounded source capsule."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_capsule(args.source_root, args.request, args.output)
    except CapsuleError as exc:
        print(
            json.dumps(exc.as_dict(), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    manifest_path = args.output / "capsule-manifest.json"
    response = {
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_bytes": manifest["source_bytes"],
        "source_count": manifest["source_count"],
        "status": "BUILT",
    }
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
