#!/usr/bin/env python3
"""Content manifest for the PO-03 subtree.

Writes a deterministic `path<TAB>sha256` line for every git-tracked file under
`workstreams/po03/`, sorted by path.  `--verify` recomputes the manifest and
exits non-zero with a unified diff when the committed file no longer describes
the tree, so a clean clone can check provenance without third-party packages.

Exit codes: 0 success, 1 manifest mismatch, 2 environment or input error.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SUBTREE = "workstreams/po03"
MANIFEST_RELATIVE_PATH = f"{SUBTREE}/MANIFEST.sha256"
EXCLUDED_DIRECTORY_NAMES = frozenset({"__pycache__"})

GIT_MODE_SYMLINK = "120000"
GIT_MODE_GITLINK = "160000"
REJECTED_GIT_MODES = {
    GIT_MODE_SYMLINK: "symlink can resolve outside the subtree",
    GIT_MODE_GITLINK: "gitlink content is not carried by this repository",
}

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

READ_CHUNK_BYTES = 1 << 20


class ManifestError(Exception):
    pass


def is_excluded(relative_path: str) -> bool:
    if relative_path == MANIFEST_RELATIVE_PATH:
        return True
    return any(part in EXCLUDED_DIRECTORY_NAMES for part in relative_path.split("/"))


def tracked_entries(root: Path) -> list[tuple[str, str]]:
    git = shutil.which("git")
    if git is None:
        raise ManifestError("git is required to enumerate tracked files")
    try:
        completed = subprocess.run(
            [git, "-C", str(root), "ls-files", "-s", "-z", "--", SUBTREE],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ManifestError(f"git ls-files failed: {exc.stderr.strip()}") from exc
    entries: list[tuple[str, str]] = []
    for record in completed.stdout.split("\x00"):
        if not record:
            continue
        metadata, _, relative_path = record.partition("\t")
        fields = metadata.split()
        if not relative_path or not fields:
            raise ManifestError(f"unparsable git ls-files record: {record!r}")
        entries.append((fields[0], relative_path))
    return entries


def tracked_files(root: Path) -> list[str]:
    included = [
        (mode, relative_path)
        for mode, relative_path in tracked_entries(root)
        if not is_excluded(relative_path)
    ]
    rejected = [
        f"{relative_path} (mode {mode}: {REJECTED_GIT_MODES[mode]})"
        for mode, relative_path in included
        if mode in REJECTED_GIT_MODES
    ]
    if rejected:
        raise ManifestError(
            "refusing to manifest non-regular tracked entries: " + ", ".join(sorted(rejected))
        )
    return sorted(relative_path for _, relative_path in included)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def manifest_text(root: Path, relative_paths: list[str]) -> str:
    lines = []
    for relative_path in sorted(relative_paths):
        target = root / relative_path
        if target.is_symlink():
            raise ManifestError(f"refusing to hash a symlink: {relative_path}")
        if not target.is_file():
            raise ManifestError(f"tracked file is missing from the worktree: {relative_path}")
        lines.append(f"{relative_path}\t{sha256_file(target)}")
    return "".join(f"{line}\n" for line in lines)


def build(root: Path) -> str:
    return manifest_text(root, tracked_files(root))


def write(root: Path) -> tuple[str, int]:
    text = build(root)
    target = root / MANIFEST_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text, len(text.splitlines())


def verify(root: Path) -> tuple[bool, str]:
    computed = build(root)
    target = root / MANIFEST_RELATIVE_PATH
    if not target.exists():
        return False, f"missing manifest: {MANIFEST_RELATIVE_PATH}"
    committed = target.read_text(encoding="utf-8")
    if committed == computed:
        return True, ""
    diff = difflib.unified_diff(
        committed.splitlines(keepends=True),
        computed.splitlines(keepends=True),
        fromfile=f"committed:{MANIFEST_RELATIVE_PATH}",
        tofile="recomputed",
    )
    return False, "".join(diff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--verify",
        action="store_true",
        help="recompute and compare against the committed manifest instead of writing it",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository root to operate on",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        if args.verify:
            ok, detail = verify(root)
            if ok:
                lines = (root / MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8").splitlines()
                print(f"MANIFEST VERIFY: PASS {len(lines)} entries")
                return EXIT_OK
            print("MANIFEST VERIFY: FAIL")
            print(detail, end="" if detail.endswith("\n") else "\n")
            return EXIT_MISMATCH
        text, count = write(root)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        print(f"MANIFEST WRITE: {count} entries -> {MANIFEST_RELATIVE_PATH}")
        print(f"MANIFEST SELF SHA256: {digest}")
        return EXIT_OK
    except ManifestError as exc:
        print(f"MANIFEST ERROR: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
