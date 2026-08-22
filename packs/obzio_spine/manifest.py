"""MANIFEST.json generation and verification.

The manifest is not documentation. It is a tamper-evidence record: byte count
plus sha256 for every file in the pack, excluding the manifest itself (which
cannot contain its own hash)."""

import json
import os

from .artefacts import sha256_file

MANIFEST_NAME = "MANIFEST.json"
EXCLUDE_DIRS = {"__pycache__", ".git", "runs", ".pytest_cache"}


def pack_files(root: str):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for fn in sorted(filenames):
            if fn == MANIFEST_NAME:
                continue
            if fn.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, fn)
            out.append(os.path.relpath(full, root))
    return sorted(out)


def build(root: str, pack_name: str, spine_dir: str = None) -> dict:
    entries = {}
    for rel in pack_files(root):
        full = os.path.join(root, rel)
        entries[rel] = {
            "bytes": os.path.getsize(full),
            "sha256": sha256_file(full),
        }
    m = {
        "pack": pack_name,
        "manifest_version": "obzio.manifest.v2",
        "file_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries.values()),
        "files": entries,
    }
    # A pack does not run without the shared spine. A manifest that omits its
    # only dependency is not a tamper-evidence record, it is a partial one.
    if spine_dir and os.path.isdir(spine_dir):
        req = {}
        for rel in pack_files(spine_dir):
            full = os.path.join(spine_dir, rel)
            req[rel] = {"bytes": os.path.getsize(full),
                        "sha256": sha256_file(full)}
        m["requires"] = {
            "spine_dir": os.path.basename(os.path.abspath(spine_dir)),
            "file_count": len(req),
            "total_bytes": sum(e["bytes"] for e in req.values()),
            "files": req,
        }
    return m


def write(root: str, pack_name: str, spine_dir: str = None) -> dict:
    m = build(root, pack_name, spine_dir)
    path = os.path.join(root, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, sort_keys=True)
        f.write("\n")
    return m


def verify(root: str):
    """Returns (ok, problems). Detects modified, missing, and untracked files."""
    path = os.path.join(root, MANIFEST_NAME)
    if not os.path.exists(path):
        return False, [f"{MANIFEST_NAME} missing"]
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    problems = []
    recorded = set(m["files"])
    actual = set(pack_files(root))
    for rel in sorted(recorded - actual):
        problems.append(f"missing: {rel}")
    for rel in sorted(actual - recorded):
        problems.append(f"untracked: {rel}")
    for rel in sorted(recorded & actual):
        full = os.path.join(root, rel)
        if os.path.getsize(full) != m["files"][rel]["bytes"]:
            problems.append(f"byte-count mismatch: {rel}")
        elif sha256_file(full) != m["files"][rel]["sha256"]:
            problems.append(f"sha256 mismatch: {rel}")

    # Verify the declared spine dependency too.
    req = m.get("requires")
    if req:
        spine_root = os.path.join(os.path.dirname(os.path.abspath(root)),
                                  req["spine_dir"])
        if not os.path.isdir(spine_root):
            problems.append(f"required spine dir missing: {req['spine_dir']}")
        else:
            for rel, meta in sorted(req["files"].items()):
                full = os.path.join(spine_root, rel)
                if not os.path.exists(full):
                    problems.append(f"spine file missing: {rel}")
                elif os.path.getsize(full) != meta["bytes"]:
                    problems.append(f"spine byte-count mismatch: {rel}")
                elif sha256_file(full) != meta["sha256"]:
                    problems.append(f"spine sha256 mismatch: {rel}")
    return (not problems), problems
