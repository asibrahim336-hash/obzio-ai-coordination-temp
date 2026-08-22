#!/usr/bin/env python3
"""Compile byte-deterministic manifests from regular files.

The wire representation contains no clock, host, absolute-root, filesystem
enumeration, or metadata fields. Relative paths are validated, file records
are sorted by their UTF-8 path bytes, and JSON is serialized canonically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


PROTOCOL_VERSION = "OBZIO-DETERMINISTIC-MANIFEST-v1"


class ManifestError(ValueError):
    """A stable, machine-readable manifest compilation failure."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_relative_path(value: str) -> str:
    """Return a canonical portable relative path or raise ManifestError."""

    if not isinstance(value, str) or not value:
        raise ManifestError("INVALID_PATH", "path must be a non-empty string")
    if "\x00" in value:
        raise ManifestError("INVALID_PATH", "NUL is prohibited")
    if "\\" in value:
        raise ManifestError("NON_CANONICAL_PATH", f"backslash is prohibited: {value!r}")
    if unicodedata.normalize("NFC", value) != value:
        raise ManifestError("NON_CANONICAL_PATH", f"path is not NFC: {value!r}")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ManifestError("NON_UTF8_PATH", repr(value)) from exc

    path = PurePosixPath(value)
    if path.is_absolute():
        raise ManifestError("ABSOLUTE_PATH", value)
    if value != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError("NON_CANONICAL_PATH", value)
    if not path.parts:
        raise ManifestError("INVALID_PATH", value)
    return value


def _tree_digest(entries: Sequence[dict[str, Any]]) -> str:
    """Hash an unambiguous framing of sorted path, size, and content digest."""

    digest = hashlib.sha256()
    digest.update(PROTOCOL_VERSION.encode("ascii") + b"\x00")
    for entry in entries:
        path_bytes = entry["path"].encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(entry["bytes"].to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry["sha256"]))
    return digest.hexdigest()


def compile_records(records: Iterable[tuple[str, bytes]]) -> dict[str, Any]:
    """Compile in-memory path/content records independent of input ordering."""

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path, raw_content in records:
        relative = canonical_relative_path(raw_path)
        if relative in seen:
            raise ManifestError("DUPLICATE_PATH", relative)
        seen.add(relative)
        if not isinstance(raw_content, bytes):
            raise ManifestError("INVALID_CONTENT", f"{relative}: expected bytes")
        entries.append(
            {
                "bytes": len(raw_content),
                "path": relative,
                "sha256": hashlib.sha256(raw_content).hexdigest(),
            }
        )

    entries.sort(key=lambda entry: entry["path"].encode("utf-8"))
    return {
        "artifact_count": len(entries),
        "artifacts": entries,
        "content_scope": "relative-path-and-file-bytes",
        "hash_algorithm": "sha256",
        "ordering": "ascending-utf8-relative-path-bytes",
        "protocol_version": PROTOCOL_VERSION,
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "tree_sha256": _tree_digest(entries),
    }


def discover_paths(root: Path) -> list[str]:
    """Discover every regular descendant without relying on discovery order."""

    if root.is_symlink():
        raise ManifestError("SYMLINK_ROOT", str(root))
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ManifestError("ROOT_NOT_DIRECTORY", str(root))

    discovered: list[str] = []
    for candidate in resolved.rglob("*"):
        relative = candidate.relative_to(resolved).as_posix()
        canonical_relative_path(relative)
        if candidate.is_symlink():
            raise ManifestError("SYMLINK_ARTIFACT", relative)
        if candidate.is_dir():
            continue
        try:
            mode = candidate.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise ManifestError("SOURCE_STAT_FAILED", relative) from exc
        if not stat.S_ISREG(mode):
            raise ManifestError("NON_REGULAR_ARTIFACT", relative)
        discovered.append(relative)
    return discovered


def _read_regular_file(root: Path, relative: str) -> bytes:
    path = root.joinpath(*PurePosixPath(relative).parts)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ManifestError("MISSING_ARTIFACT", relative) from exc
    except OSError as exc:
        raise ManifestError("ARTIFACT_OPEN_FAILED", relative) from exc

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ManifestError("NON_REGULAR_ARTIFACT", relative)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise ManifestError("ARTIFACT_CHANGED_DURING_READ", relative)
        content = b"".join(chunks)
        if len(content) != after.st_size:
            raise ManifestError("ARTIFACT_CHANGED_DURING_READ", relative)
        return content
    finally:
        os.close(descriptor)


def compile_manifest(root: Path, traversal: Iterable[str] | None = None) -> dict[str, Any]:
    """Read and compile a rooted file set in any caller-provided order."""

    if root.is_symlink():
        raise ManifestError("SYMLINK_ROOT", str(root))
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ManifestError("ROOT_NOT_DIRECTORY", str(root))
    paths = discover_paths(resolved) if traversal is None else list(traversal)
    records = [
        (canonical_relative_path(relative), _read_regular_file(resolved, canonical_relative_path(relative)))
        for relative in paths
    ]
    return compile_records(records)


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    """Serialize a manifest to the one canonical wire representation."""

    return (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def compile_manifest_bytes(root: Path, traversal: Iterable[str] | None = None) -> bytes:
    return canonical_json_bytes(compile_manifest(root, traversal))


def load_traversal_fixture(path: Path, order: str | None) -> list[str]:
    """Load either a direct path array or one named order from a fixture."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("INVALID_TRAVERSAL_FIXTURE", str(path)) from exc

    if isinstance(document, list):
        if order is not None:
            raise ManifestError("UNEXPECTED_ORDER", order)
        paths = document
    elif isinstance(document, dict):
        orders = document.get("orders")
        if not isinstance(orders, dict) or order is None or order not in orders:
            raise ManifestError("UNKNOWN_ORDER", str(order))
        paths = orders[order]
    else:
        raise ManifestError("INVALID_TRAVERSAL_FIXTURE", "expected array or object")
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise ManifestError("INVALID_TRAVERSAL_FIXTURE", "order must be a string array")
    return paths


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--paths-json", type=Path)
    parser.add_argument("--order")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        traversal = (
            load_traversal_fixture(args.paths_json, args.order)
            if args.paths_json is not None
            else None
        )
        if args.paths_json is None and args.order is not None:
            raise ManifestError("UNEXPECTED_ORDER", args.order)
        payload = compile_manifest_bytes(args.root, traversal)
        if args.output is None:
            sys.stdout.buffer.write(payload)
        else:
            root = args.root.resolve(strict=True)
            output = args.output.resolve(strict=False)
            if output == root or root in output.parents:
                raise ManifestError(
                    "OUTPUT_INSIDE_SOURCE_ROOT",
                    "output would change the compiled source set",
                )
            _atomic_write(output, payload)
    except (ManifestError, OSError) as exc:
        code = exc.code if isinstance(exc, ManifestError) else "IO_ERROR"
        detail = exc.detail if isinstance(exc, ManifestError) else str(exc)
        print(
            json.dumps({"error_code": code, "error": detail, "status": "FAIL"}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
