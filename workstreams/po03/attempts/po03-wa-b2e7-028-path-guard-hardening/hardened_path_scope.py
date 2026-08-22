#!/usr/bin/env python3
"""A hardened changed-path scope guard for PO-03.

The guard in `workstreams/po03/tools/check_path_scope.py` already refuses every
name-only evasion this unit tried: `..` traversal, absolute paths, backslashes,
NUL, unicode confusables, case variants, trailing-dot directory components and
single-dot components.  Three real gaps were found and are closed here.

1. `RENAME_SOURCE_OUT_OF_SCOPE`.  `git diff --name-only` reports only the
   post-image of a rename, so `git mv state/X workstreams/po03/Y` deletes a file
   outside the allowlist while the guard sees one in-allowlist path and passes.
   This guard reads `git diff --raw`, which carries both images, and judges both.

2. `SYMLINK_TARGET_OUT_OF_SCOPE`.  The legacy guard inspects names only, so an
   in-allowlist path added with mode 120000 pointing at `../../state` passes.
   A symlink is a durable handle out of the allowlist, so this guard reads the
   link body and judges the resolved target.

3. `WORKFLOW_GLOB_MISMATCH`.  The commissioned allowlist is the glob
   `.github/workflows/po03-*.yml`, but the legacy guard implements it as a
   prefix test plus a suffix test, which also admits nested paths such as
   `.github/workflows/po03-a/b.yml`.  This guard matches the glob per path
   segment, so a wildcard cannot cross a directory boundary.

Two further deliberate narrowings are applied and are narrowings, not fixes to
an escape: trailing dot or space components are refused because they collide
with a different path on Windows, and non-ASCII paths are refused because
homoglyphs and NFC/NFD duplicates make review and case-insensitive filesystems
unreliable.  Both are recorded as policy choices in FINDINGS.md.

Exit codes: 0 in scope, 1 violation, 2 error.  Every judgement is fail-closed:
anything unparseable is a violation, never a pass.
"""

from __future__ import annotations

import argparse
import fnmatch
import posixpath
import subprocess
import sys
import unicodedata
from pathlib import PurePosixPath

ALLOW_PREFIXES = ("workstreams/po03/", "receipts/po03/")
ALLOW_GLOBS = (".github/workflows/po03-*.yml",)

REGULAR_FILE_MODES = frozenset({"100644", "100755"})
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
ABSENT_MODE = "000000"

# C0 and C1 controls plus the format characters that let a path display as
# something other than what it is.
FORBIDDEN_CODEPOINTS = frozenset(
    [chr(value) for value in range(0x00, 0x20)]
    + [chr(0x7F)]
    + [chr(value) for value in range(0x80, 0xA0)]
    + [
        "\u00ad",  # soft hyphen
        "\u200b", "\u200c", "\u200d",  # zero-width space, non-joiner, joiner
        "\u200e", "\u200f",  # left-to-right and right-to-left marks
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # bidi embedding and override
        "\u2066", "\u2067", "\u2068", "\u2069",  # bidi isolates
        "\ufeff",  # byte order mark
    ]
)


class ScopeError(Exception):
    """Raised when a path cannot be canonicalised, which is itself a refusal."""


class ChangedEntry:
    """One record from `git diff --raw`, carrying both images of a rename."""

    def __init__(
        self,
        status: str,
        path: str,
        source_path: str | None = None,
        src_mode: str = ABSENT_MODE,
        dst_mode: str = ABSENT_MODE,
        dst_sha: str = "",
    ) -> None:
        self.status = status
        self.path = path
        self.source_path = source_path
        self.src_mode = src_mode
        self.dst_mode = dst_mode
        self.dst_sha = dst_sha

    def __repr__(self) -> str:
        return (
            f"ChangedEntry(status={self.status!r}, path={self.path!r}, "
            f"source_path={self.source_path!r}, dst_mode={self.dst_mode!r})"
        )

    @property
    def paths(self) -> list[tuple[str, str]]:
        """Every path this entry mutates, labelled by which image it is.

        A rename removes its pre-image, so both images are mutations.  A copy
        leaves its source untouched, so only the destination is judged;
        duplicating readable bytes into the allowlist is not an escape.
        """
        images = [("post", self.path)]
        if self.source_path is not None and self.status.startswith("R"):
            images.insert(0, ("pre", self.source_path))
        return images


def normalize(path: str) -> str:
    """Return the path unchanged, or raise if it is not a canonical safe path."""
    if not path:
        raise ScopeError("empty path")
    if "\\" in path:
        raise ScopeError(f"backslash in path: {path!r}")
    for character in path:
        if character in FORBIDDEN_CODEPOINTS:
            raise ScopeError(f"control or bidi codepoint U+{ord(character):04X} in path: {path!r}")
    try:
        path.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ScopeError(f"non-ASCII path refused by policy: {path!r}") from exc
    if unicodedata.normalize("NFKC", path) != path:
        raise ScopeError(f"path is not NFKC-normalised: {path!r}")
    value = PurePosixPath(path)
    if value.is_absolute():
        raise ScopeError(f"absolute path: {path!r}")
    if str(value) != path:
        raise ScopeError(f"non-canonical path spelling: {path!r}")
    for component in value.parts:
        if component in {"", ".", ".."}:
            raise ScopeError(f"traversal or empty component in path: {path!r}")
        if component != component.strip() or component.endswith("."):
            raise ScopeError(f"trailing dot or space component refused: {path!r}")
    return path


def matches_glob(path: str, pattern: str) -> bool:
    """Match a glob segment by segment so a wildcard cannot cross a `/`."""
    path_segments = path.split("/")
    pattern_segments = pattern.split("/")
    if len(path_segments) != len(pattern_segments):
        return False
    return all(
        fnmatch.fnmatchcase(segment, expected)
        for segment, expected in zip(path_segments, pattern_segments)
    )


def is_allowed(path: str) -> bool:
    """True only for a canonical path inside the commissioned allowlist."""
    path = normalize(path)
    if any(path.startswith(prefix) for prefix in ALLOW_PREFIXES):
        return True
    return any(matches_glob(path, pattern) for pattern in ALLOW_GLOBS)


def classify(path: str) -> str | None:
    """Return a violation code for a path, or None when it is in scope."""
    try:
        if is_allowed(path):
            return None
    except ScopeError as exc:
        return f"NONCANONICAL_PATH {path!r}: {exc}"
    if path.startswith(".github/workflows/po03-") and path.endswith(".yml"):
        return (
            f"WORKFLOW_GLOB_MISMATCH {path}: matches the legacy prefix and suffix test but not "
            f"the commissioned glob {ALLOW_GLOBS[0]}"
        )
    return f"OUT_OF_SCOPE {path}"


def resolve_symlink(link_path: str, target: str) -> str:
    """Resolve a symlink body against the directory holding the link."""
    if target.startswith("/"):
        raise ScopeError(f"absolute symlink target: {target!r}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link_path), target))
    if resolved == ".." or resolved.startswith("../"):
        raise ScopeError(f"symlink target escapes the repository: {target!r}")
    return resolved


def evaluate(entries: list[ChangedEntry], read_blob=None) -> list[str]:
    """Judge every image of every changed entry and return all violations."""
    violations: list[str] = []
    for entry in entries:
        for image, path in entry.paths:
            finding = classify(path)
            if finding is None:
                continue
            if image == "pre" and entry.source_path is not None:
                violations.append(
                    f"RENAME_SOURCE_OUT_OF_SCOPE {entry.source_path} -> {entry.path} "
                    f"(status={entry.status}): {finding}"
                )
            else:
                violations.append(f"{finding} (status={entry.status})")

        if entry.dst_mode == GITLINK_MODE:
            violations.append(
                f"GITLINK_NOT_ALLOWED {entry.path}: a submodule pointer is not a PO-03 artifact"
            )
            continue
        if entry.dst_mode not in REGULAR_FILE_MODES | {SYMLINK_MODE, ABSENT_MODE}:
            violations.append(f"UNEXPECTED_MODE {entry.path}: mode={entry.dst_mode}")
            continue
        if entry.dst_mode != SYMLINK_MODE:
            continue
        if read_blob is None:
            violations.append(
                f"SYMLINK_UNVERIFIABLE {entry.path}: a symlink was added or changed but its "
                f"target could not be read, so it cannot be cleared"
            )
            continue
        try:
            target = read_blob(entry.dst_sha).decode("utf-8")
            resolved = resolve_symlink(entry.path, target)
        except (ScopeError, OSError, UnicodeDecodeError) as exc:
            violations.append(f"SYMLINK_TARGET_REFUSED {entry.path}: {exc}")
            continue
        target_finding = classify(resolved)
        if target_finding is not None:
            violations.append(
                f"SYMLINK_TARGET_OUT_OF_SCOPE {entry.path} -> {target} "
                f"(resolves to {resolved}): {target_finding}"
            )
    return sorted(set(violations))


def parse_raw(payload: bytes) -> list[ChangedEntry]:
    """Parse `git diff --raw -z --no-abbrev` output into changed entries."""
    fields = payload.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    entries: list[ChangedEntry] = []
    index = 0
    while index < len(fields):
        header = fields[index].decode("utf-8", errors="surrogateescape")
        index += 1
        if not header.startswith(":"):
            raise ScopeError(f"unexpected git diff --raw header: {header!r}")
        parts = header[1:].split()
        if len(parts) != 5:
            raise ScopeError(f"unexpected git diff --raw header fields: {header!r}")
        src_mode, dst_mode, _src_sha, dst_sha, status = parts
        if index >= len(fields):
            raise ScopeError(f"git diff --raw record {header!r} has no path")
        first = fields[index].decode("utf-8", errors="surrogateescape")
        index += 1
        source_path = None
        path = first
        if status[0] in {"R", "C"}:
            if index >= len(fields):
                raise ScopeError(f"rename record {header!r} has no destination path")
            source_path = first
            path = fields[index].decode("utf-8", errors="surrogateescape")
            index += 1
        entries.append(
            ChangedEntry(
                status=status,
                path=path,
                source_path=source_path,
                src_mode=src_mode,
                dst_mode=dst_mode,
                dst_sha=dst_sha,
            )
        )
    return entries


def git(repo: str, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ("git", *arguments), cwd=repo, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScopeError(f"git {' '.join(arguments)} failed: {exc}") from exc


def changed_entries(repo: str, base: str, head: str) -> list[ChangedEntry]:
    # -M is explicit so the judgement does not depend on the repository's
    # diff.renames configuration, and both images of a rename are judged either
    # way: with detection on the pre-image comes from the R record, with it off
    # the same path arrives as its own D record.
    payload = git(
        repo, "diff", "--raw", "-z", "--no-abbrev", "-M",
        "--diff-filter=ACMRDTUXB", f"{base}...{head}",
    )
    return parse_raw(payload)


def blob_reader(repo: str):
    def read(object_id: str) -> bytes:
        return git(repo, "cat-file", "blob", object_id)

    return read


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--path", action="append", dest="paths",
        help="judge this path by name only; repeatable, for synthetic checks",
    )
    args = parser.parse_args(argv)
    try:
        if args.paths is not None:
            entries = [ChangedEntry(status="A", path=path) for path in args.paths]
            violations = evaluate(entries)
            examined = len(entries)
        else:
            if not args.base:
                print("PO03_HARDENED_SCOPE_ERROR: --base is required without --path", file=sys.stderr)
                return 2
            entries = changed_entries(args.repo, args.base, args.head)
            violations = evaluate(entries, blob_reader(args.repo))
            examined = sum(len(entry.paths) for entry in entries)
    except ScopeError as exc:
        print(f"PO03_HARDENED_SCOPE_ERROR: {exc}", file=sys.stderr)
        return 2
    if violations:
        for violation in violations:
            print(f"PO03_HARDENED_SCOPE_VIOLATION: {violation}", file=sys.stderr)
        return 1
    print(f"PO03_HARDENED_SCOPE_PASS images={examined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
