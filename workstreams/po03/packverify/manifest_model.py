"""Normalize the manifest formats present in immutable pack trees."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping

try:
    from .git_tree import GitTree
except ImportError:  # pragma: no cover - direct command entry point
    from git_tree import GitTree


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ManifestDocument:
    path: str
    value: Mapping[str, object]


@dataclass(frozen=True)
class ManifestEntry:
    manifest_path: str
    logical_path: str
    tree_path: str
    expected_sha256: str | None
    expected_bytes: int | None

    @property
    def has_valid_hash(self) -> bool:
        return bool(
            self.expected_sha256 and _SHA256.fullmatch(self.expected_sha256)
        )


def load_documents(tree: GitTree, root: str) -> tuple[ManifestDocument, ...]:
    prefix = root.rstrip("/") + "/"
    documents: list[ManifestDocument] = []
    for path in sorted(tree.paths()):
        if not path.startswith(prefix):
            continue
        if PurePosixPath(path).name not in {"MANIFEST.json", "MANIFEST_ALL.json"}:
            continue
        value = tree.json_blob(path)
        if not isinstance(value, dict):
            continue
        documents.append(ManifestDocument(path=path, value=value))
    return tuple(documents)


def _metadata(value: object) -> tuple[str | None, int | None]:
    if not isinstance(value, Mapping):
        return None, None
    digest = value.get("sha256")
    byte_count = value.get("bytes")
    return (
        digest if isinstance(digest, str) else None,
        byte_count if isinstance(byte_count, int) else None,
    )


def _join(parent: PurePosixPath, path: str, root: str) -> str:
    candidate = PurePosixPath(path)
    root_path = PurePosixPath(root)
    if candidate.parts[: len(root_path.parts)] == root_path.parts:
        return str(candidate)
    return str(parent / candidate)


def entries_for_document(
    document: ManifestDocument, root: str
) -> tuple[ManifestEntry, ...]:
    """Return every file claim carrying or requiring provenance metadata."""
    value = document.value
    parent = PurePosixPath(document.path).parent
    entries: list[ManifestEntry] = []

    files = value.get("files")
    if isinstance(files, Mapping):
        items: Iterable[tuple[str, object]] = (
            (path, metadata)
            for path, metadata in files.items()
            if isinstance(path, str)
        )
    elif isinstance(files, list):
        list_items: list[tuple[str, object]] = []
        for item in files:
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                list_items.append((item["path"], item))
        items = list_items
    else:
        items = ()

    for logical_path, metadata in items:
        digest, byte_count = _metadata(metadata)
        entries.append(
            ManifestEntry(
                manifest_path=document.path,
                logical_path=logical_path,
                tree_path=_join(parent, logical_path, root),
                expected_sha256=digest,
                expected_bytes=byte_count,
            )
        )

    requires = value.get("requires")
    if isinstance(requires, Mapping) and isinstance(requires.get("files"), Mapping):
        spine_dir = requires.get("spine_dir")
        if isinstance(spine_dir, str):
            for logical_path, metadata in requires["files"].items():
                if not isinstance(logical_path, str):
                    continue
                digest, byte_count = _metadata(metadata)
                entries.append(
                    ManifestEntry(
                        manifest_path=document.path,
                        logical_path=f"{spine_dir}/{logical_path}",
                        tree_path=str(parent.parent / spine_dir / logical_path),
                        expected_sha256=digest,
                        expected_bytes=byte_count,
                    )
                )

    for field in ("loose_files", "shared_spine"):
        claimed = value.get(field)
        if not isinstance(claimed, Mapping):
            continue
        published_at = claimed.get("published_at")
        if (
            field == "shared_spine"
            and isinstance(published_at, str)
            and isinstance(claimed.get("sha256"), str)
        ):
            digest, byte_count = _metadata(claimed)
            entries.append(
                ManifestEntry(
                    manifest_path=document.path,
                    logical_path=published_at,
                    tree_path=_join(parent, published_at, root),
                    expected_sha256=digest,
                    expected_bytes=byte_count,
                )
            )
            continue
        for logical_path, metadata in claimed.items():
            if not isinstance(logical_path, str):
                continue
            digest, byte_count = _metadata(metadata)
            entries.append(
                ManifestEntry(
                    manifest_path=document.path,
                    logical_path=logical_path,
                    tree_path=_join(parent, logical_path, root),
                    expected_sha256=digest,
                    expected_bytes=byte_count,
                )
            )

    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.tree_path,
                entry.manifest_path,
                entry.logical_path,
            ),
        )
    )


def all_entries(
    documents: Iterable[ManifestDocument], root: str
) -> tuple[ManifestEntry, ...]:
    entries = [
        entry
        for document in documents
        for entry in entries_for_document(document, root)
    ]
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.tree_path,
                entry.manifest_path,
                entry.logical_path,
            ),
        )
    )
