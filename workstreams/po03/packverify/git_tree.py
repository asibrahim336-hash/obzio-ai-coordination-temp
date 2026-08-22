"""Read immutable Git trees without checking out or modifying their refs."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitTreeError(RuntimeError):
    """An immutable tree could not be read safely."""


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    object_sha: str
    path: str


class GitTree:
    """Read blobs and paths at one full commit SHA."""

    def __init__(self, repository: Path | str, commit_sha: str):
        if not _SHA.fullmatch(commit_sha):
            raise ValueError("commit_sha must be a full lowercase 40-hex SHA")
        self.repository = Path(repository).resolve()
        self.commit_sha = commit_sha
        self._entries: tuple[TreeEntry, ...] | None = None

    def _git(self, *args: str) -> bytes:
        process = subprocess.run(
            ["git", *args],
            cwd=self.repository,
            check=False,
            capture_output=True,
        )
        if process.returncode:
            message = process.stderr.decode("utf-8", "replace").strip()
            raise GitTreeError(f"git {' '.join(args)} failed: {message}")
        return process.stdout

    def verify_commit(self) -> None:
        self._git("cat-file", "-e", f"{self.commit_sha}^{{commit}}")

    def entries(self) -> tuple[TreeEntry, ...]:
        if self._entries is None:
            raw = self._git(
                "ls-tree", "-r", "-z", "--full-tree", self.commit_sha
            )
            parsed: list[TreeEntry] = []
            for record in raw.split(b"\0"):
                if not record:
                    continue
                metadata, path = record.split(b"\t", 1)
                mode, object_type, object_sha = metadata.decode("ascii").split()
                parsed.append(
                    TreeEntry(
                        mode=mode,
                        object_type=object_type,
                        object_sha=object_sha,
                        path=path.decode("utf-8", "surrogateescape"),
                    )
                )
            self._entries = tuple(sorted(parsed, key=lambda entry: entry.path))
        return self._entries

    def paths(self) -> frozenset[str]:
        return frozenset(
            entry.path for entry in self.entries() if entry.object_type == "blob"
        )

    def blob(self, path: str) -> bytes:
        if path not in self.paths():
            raise GitTreeError(
                f"blob absent at {self.commit_sha}: {path}"
            )
        return self._git("cat-file", "blob", f"{self.commit_sha}:{path}")

    def json_blob(self, path: str) -> object:
        try:
            return json.loads(self.blob(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitTreeError(f"invalid UTF-8 JSON at {path}: {exc}") from exc

    def pack_roots(self) -> tuple[str, ...]:
        """Return roots selected by aggregate manifest bytes, not ref names."""
        roots: set[str] = set()
        for path in self.paths():
            if not path.endswith("/MANIFEST.json"):
                continue
            value = self.json_blob(path)
            if isinstance(value, dict) and isinstance(value.get("packs"), dict):
                roots.add(str(PurePosixPath(path).parent))
        return tuple(sorted(roots))

    def export(self, root: str, destination: Path | str) -> Path:
        """Safely export one committed subtree using ``git archive``."""
        root_path = PurePosixPath(root)
        if root_path.is_absolute() or ".." in root_path.parts or not root_path.parts:
            raise ValueError(f"unsafe archive root: {root}")

        target = Path(destination).resolve()
        target.mkdir(parents=True, exist_ok=False)
        archive = self._git("archive", "--format=tar", self.commit_sha, root)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
            for member in stream.getmembers():
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or member.issym()
                    or member.islnk()
                ):
                    raise GitTreeError(f"unsafe archive member: {member.name}")
                output = target.joinpath(*relative.parts)
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise GitTreeError(
                        f"unsupported archive member: {member.name}"
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                extracted = stream.extractfile(member)
                if extracted is None:
                    raise GitTreeError(f"cannot extract: {member.name}")
                output.write_bytes(extracted.read())
                os.chmod(output, member.mode & 0o777)
        return target / root
