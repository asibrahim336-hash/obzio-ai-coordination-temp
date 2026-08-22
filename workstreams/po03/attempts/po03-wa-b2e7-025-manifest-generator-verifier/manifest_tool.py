#!/usr/bin/env python3
"""Generate and verify total hash/byte coverage over a set of PO-03 artifacts.

The generator enumerates artifacts from an authoritative source and emits a
PO03-MANIFEST-v1 document carrying a SHA-256 and an exact byte count for every
artifact.  The verifier re-enumerates the same source and fails closed on any
divergence: a file the manifest does not cover, a manifest entry with no file,
a hash mismatch, a byte-count mismatch, a duplicate entry, a malformed line or
a trailer that disagrees with the entries it summarises.

Coverage is only meaningful relative to a stated source.  A directory source
sees the working tree, so it detects files a producer forgot to stage.  A git
source sees committed bytes at an immutable commit, so it detects nothing about
unstaged files.  Both sources are offered and the manifest records which one
produced it.

Exit codes: 0 verified, 1 verification failed, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

HEADER = "PO03-MANIFEST-v1"
SEPARATOR = "  "
SKIP_DIRECTORY_NAMES = frozenset({".git"})


class ManifestError(Exception):
    """Raised for an unusable source, path or manifest document."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def check_manifest_safe_path(path: str) -> str:
    """Refuse any path the line-oriented manifest format cannot represent."""
    if not path:
        raise ManifestError("empty artifact path")
    if any(character in path for character in ("\n", "\r", "\x00")):
        raise ManifestError(f"artifact path is not representable in a manifest line: {path!r}")
    if SEPARATOR in path:
        raise ManifestError(f"artifact path collides with the field separator: {path!r}")
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or str(value) != path:
        raise ManifestError(f"non-canonical artifact path: {path!r}")
    return path


class Source:
    """An authoritative enumeration of artifact bytes."""

    kind = "abstract"
    locator = ""

    def paths(self) -> list[str]:
        raise NotImplementedError

    def read(self, path: str) -> bytes:
        raise NotImplementedError


class DirectorySource(Source):
    """Enumerate the working tree below a directory."""

    kind = "directory"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise ManifestError(f"not a directory: {self.root}")
        self.locator = self.root.as_posix()

    def paths(self) -> list[str]:
        found: list[str] = []
        for candidate in sorted(self.root.rglob("*")):
            relative = candidate.relative_to(self.root)
            if any(part in SKIP_DIRECTORY_NAMES for part in relative.parts):
                continue
            if candidate.is_symlink():
                raise ManifestError(f"refusing to hash through a symlink: {relative.as_posix()}")
            if candidate.is_file():
                found.append(check_manifest_safe_path(relative.as_posix()))
        return sorted(found)

    def read(self, path: str) -> bytes:
        target = self.root / check_manifest_safe_path(path)
        if target.is_symlink() or not target.is_file():
            raise ManifestError(f"no readable artifact at {path}")
        return target.read_bytes()


class GitSource(Source):
    """Enumerate committed bytes under a path prefix at an immutable commit."""

    kind = "git"

    def __init__(self, repo: Path, commit: str, prefix: str) -> None:
        self.repo = Path(repo)
        self.commit = commit
        self.prefix = prefix.rstrip("/")
        self.locator = f"git:{commit}:{self.prefix}"

    def _git(self, *arguments: str) -> bytes:
        try:
            completed = subprocess.run(
                ("git", *arguments), cwd=self.repo, check=True, capture_output=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ManifestError(f"git {' '.join(arguments)} failed: {exc}") from exc
        return completed.stdout

    def paths(self) -> list[str]:
        listing = self._git("ls-tree", "-r", "--name-only", "-z", self.commit, "--", self.prefix)
        prefix = f"{self.prefix}/"
        found: list[str] = []
        for item in listing.split(b"\0"):
            if not item:
                continue
            full = item.decode("utf-8")
            if not full.startswith(prefix):
                raise ManifestError(f"git listed {full!r} outside prefix {self.prefix!r}")
            found.append(check_manifest_safe_path(full[len(prefix):]))
        return sorted(found)

    def read(self, path: str) -> bytes:
        safe = check_manifest_safe_path(path)
        return self._git("cat-file", "blob", f"{self.commit}:{self.prefix}/{safe}")


def build_source(args: argparse.Namespace) -> Source:
    if args.dir is not None:
        return DirectorySource(Path(args.dir))
    if args.git_commit is None or args.git_prefix is None:
        raise ManifestError("choose --dir or both --git-commit and --git-prefix")
    return GitSource(Path(args.repo), args.git_commit, args.git_prefix)


def generate(source: Source) -> str:
    lines = [HEADER, f"SOURCE {source.kind} {source.locator}"]
    total_bytes = 0
    paths = source.paths()
    for path in paths:
        payload = source.read(path)
        total_bytes += len(payload)
        lines.append(SEPARATOR.join((sha256_bytes(payload), str(len(payload)), path)))
    lines.append(f"TOTAL {len(paths)} {total_bytes}")
    return "\n".join(lines) + "\n"


def parse(text: str) -> tuple[dict[str, tuple[str, int]], tuple[int, int], list[str]]:
    """Parse a manifest into entries, its trailer and any structural findings."""
    findings: list[str] = []
    entries: dict[str, tuple[str, int]] = {}
    trailer: tuple[int, int] | None = None
    lines = text.splitlines()
    if not lines or lines[0] != HEADER:
        findings.append(f"BAD_HEADER expected={HEADER}")
        return entries, (0, 0), findings
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        if line.startswith("SOURCE "):
            continue
        if line.startswith("TOTAL "):
            fields = line.split()
            if len(fields) != 3 or not fields[1].isdigit() or not fields[2].isdigit():
                findings.append(f"MALFORMED_LINE line={number} value={line!r}")
                continue
            if trailer is not None:
                findings.append(f"DUPLICATE_TRAILER line={number}")
            trailer = (int(fields[1]), int(fields[2]))
            continue
        fields = line.split(SEPARATOR)
        if len(fields) != 3:
            findings.append(f"MALFORMED_LINE line={number} value={line!r}")
            continue
        digest, size, path = fields
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            findings.append(f"MALFORMED_LINE line={number} reason=sha256 value={digest!r}")
            continue
        if not size.isdigit():
            findings.append(f"MALFORMED_LINE line={number} reason=bytes value={size!r}")
            continue
        try:
            check_manifest_safe_path(path)
        except ManifestError as exc:
            findings.append(f"UNSAFE_PATH line={number} reason={exc}")
            continue
        if path in entries:
            findings.append(f"DUPLICATE_ENTRY path={path}")
            continue
        entries[path] = (digest, int(size))
    if trailer is None:
        findings.append("MISSING_TRAILER")
        trailer = (0, 0)
    return entries, trailer, findings


def verify(source: Source, text: str) -> list[str]:
    """Return every reason the manifest fails to cover the source exactly."""
    entries, trailer, findings = parse(text)
    if findings and any(item.startswith("BAD_HEADER") for item in findings):
        return findings
    present = source.paths()
    for path in present:
        if path not in entries:
            findings.append(f"UNCOVERED_FILE path={path}")
            continue
        expected_digest, expected_bytes = entries[path]
        payload = source.read(path)
        measured_digest = sha256_bytes(payload)
        if measured_digest != expected_digest:
            findings.append(
                f"HASH_MISMATCH path={path} manifest={expected_digest} measured={measured_digest}"
            )
        if len(payload) != expected_bytes:
            findings.append(
                f"BYTE_MISMATCH path={path} manifest={expected_bytes} measured={len(payload)}"
            )
    for path in sorted(set(entries) - set(present)):
        findings.append(f"MISSING_FILE path={path}")
    claimed_count, claimed_bytes = trailer
    if claimed_count != len(entries):
        findings.append(f"TRAILER_COUNT_MISMATCH claimed={claimed_count} entries={len(entries)}")
    entry_bytes = sum(size for _, size in entries.values())
    if claimed_bytes != entry_bytes:
        findings.append(f"TRAILER_BYTES_MISMATCH claimed={claimed_bytes} entries={entry_bytes}")
    if not entries and not present:
        findings.append("EMPTY_MANIFEST no artifacts covered")
    return findings


def as_json(source: Source, text: str) -> str:
    entries, trailer, _ = parse(text)
    document = {
        "manifest_format": HEADER,
        "source_kind": source.kind,
        "source_locator": source.locator,
        "artifact_count": trailer[0],
        "total_bytes": trailer[1],
        "artifacts": [
            {"path": path, "sha256": digest, "bytes": size}
            for path, (digest, size) in sorted(entries.items())
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", help="enumerate the working tree below this directory")
    parser.add_argument("--repo", default=".", help="repository root for a git source")
    parser.add_argument("--git-commit", help="immutable commit for a git source")
    parser.add_argument("--git-prefix", help="path prefix inside the commit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generator = subparsers.add_parser("generate", help="write a manifest for a source")
    add_source_arguments(generator)
    generator.add_argument("--out", help="write the manifest here instead of stdout")
    generator.add_argument("--json", action="store_true", help="also print a JSON projection")
    verifier = subparsers.add_parser("verify", help="verify a manifest against a source")
    add_source_arguments(verifier)
    verifier.add_argument("--manifest", required=True, help="manifest document to verify")
    args = parser.parse_args(argv)

    try:
        source = build_source(args)
        if args.command == "generate":
            text = generate(source)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            if args.json:
                sys.stdout.write(as_json(source, text))
            return 0
        text = Path(args.manifest).read_text(encoding="utf-8")
        findings = verify(source, text)
    except (ManifestError, OSError, UnicodeDecodeError) as exc:
        print(f"PO03_MANIFEST_ERROR: {exc}", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            print(f"PO03_MANIFEST_VIOLATION: {finding}", file=sys.stderr)
        return 1
    entries, trailer, _ = parse(text)
    print(f"PO03_MANIFEST_PASS artifacts={trailer[0]} bytes={trailer[1]} source={source.locator}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
