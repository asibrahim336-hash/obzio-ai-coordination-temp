"""PO03-WA-056 — a corrupted manifest can never produce a PASS.

Frozen hypothesis: adversarial corrupt manifests never produce a false PASS.

The commission makes the manifest load-bearing: hashes and byte counts are
verified, another process reads every artifact back by immutable SHA, and only
then may a result advance. Every one of those guarantees rests on the manifest
being an honest description of the tree. So the interesting question is not
"does the verifier accept a good manifest" but "which corruptions can slip past
it".

This module pairs a strict verifier with an adversarial corruption generator.
The generator mutates a known-good manifest in each way an attacker or a buggy
writer plausibly would — truncation, hash and byte-count swaps, duplicate
entries, path traversal, absolute paths, symlink escape, Unicode and case-fold
path aliasing, unlisted files, non-hex digests — and the test suite asserts that
every single corruption is rejected.

Standard library only. No writes outside a caller-supplied directory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_VERSION = "PO03-WA-056-MANIFEST-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Verdict:
    passed: bool
    failures: list = field(default_factory=list)
    checked: int = 0

    def fail(self, code: str, detail: str) -> None:
        self.passed = False
        self.failures.append({"code": code, "detail": detail})

    @property
    def codes(self) -> set:
        return {f["code"] for f in self.failures}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_files(root: Path) -> list:
    out = []
    for base, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            path = Path(base) / name
            if path.name == "manifest.json" and path.parent == root:
                continue
            out.append(path)
    return sorted(out)


def build_manifest(root: Path) -> dict:
    entries = []
    for path in _tree_files(root):
        rel = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "manifest_version": MANIFEST_VERSION,
        "artifact_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "artifacts": entries,
    }


def _safe_relative(root: Path, rel: str):
    """Resolve a manifest path, refusing traversal, absolutes and symlink escape."""
    if rel != rel.strip() or not rel:
        return None, "PATH_WHITESPACE"
    if rel.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", rel):
        return None, "PATH_ABSOLUTE"
    if "\\" in rel:
        return None, "PATH_BACKSLASH"
    raw_segments = rel.split("/")
    if any(segment == ".." for segment in raw_segments):
        return None, "PATH_TRAVERSAL"
    # pathlib silently folds "./" and empty segments away, so compare the raw
    # string against its canonical form before letting pathlib touch it.
    if raw_segments != [s for s in raw_segments if s not in (".", "")]:
        return None, "PATH_NOT_CANONICAL"
    candidate = root / rel
    if candidate.is_symlink():
        return None, "PATH_SYMLINK"
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return None, "PATH_UNRESOLVABLE"
    if not str(resolved).startswith(str(root.resolve()) + os.sep) and resolved != root.resolve():
        return None, "PATH_ESCAPES_ROOT"
    return candidate, ""


def verify(root: Path, manifest: dict) -> Verdict:
    """Verify a manifest against the tree. Any inconsistency is a FAIL."""
    verdict = Verdict(True)
    root = Path(root)

    if not isinstance(manifest, dict):
        verdict.fail("MANIFEST_SHAPE", "manifest is not an object")
        return verdict
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        verdict.fail("MANIFEST_VERSION", f"unexpected version {manifest.get('manifest_version')!r}")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        verdict.fail("EMPTY_MANIFEST", "manifest declares no artifacts")
        return verdict

    declared_count = manifest.get("artifact_count")
    if declared_count != len(entries):
        verdict.fail(
            "COUNT_MISMATCH", f"artifact_count={declared_count} but {len(entries)} entries present"
        )

    seen_exact, seen_folded, matched = set(), {}, set()
    running_bytes = 0

    for entry in entries:
        if not isinstance(entry, dict):
            verdict.fail("ENTRY_SHAPE", f"entry is not an object: {entry!r}")
            continue
        rel, digest, size = entry.get("path"), entry.get("sha256"), entry.get("bytes")
        if not isinstance(rel, str):
            verdict.fail("ENTRY_PATH_MISSING", f"entry has no usable path: {entry!r}")
            continue
        if rel in seen_exact:
            verdict.fail("DUPLICATE_ENTRY", f"{rel} listed more than once")
            continue
        seen_exact.add(rel)

        folded = unicodedata.normalize("NFC", rel).casefold()
        if folded in seen_folded and seen_folded[folded] != rel:
            verdict.fail(
                "PATH_ALIAS",
                f"{rel!r} aliases {seen_folded[folded]!r} under Unicode/case normalisation",
            )
            continue
        seen_folded[folded] = rel

        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            verdict.fail("DIGEST_MALFORMED", f"{rel}: sha256={digest!r}")
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            verdict.fail("BYTES_MALFORMED", f"{rel}: bytes={size!r}")
            continue

        target, path_code = _safe_relative(root, rel)
        if target is None:
            verdict.fail(path_code, f"{rel} is not a safe in-tree path")
            continue
        if not target.exists() or not target.is_file():
            verdict.fail("ARTIFACT_MISSING", f"{rel} is manifested but absent")
            continue

        actual_digest = sha256_file(target)
        actual_bytes = target.stat().st_size
        if actual_digest != digest:
            verdict.fail("DIGEST_MISMATCH", f"{rel}: manifest={digest} actual={actual_digest}")
        if actual_bytes != size:
            verdict.fail("BYTES_MISMATCH", f"{rel}: manifest={size} actual={actual_bytes}")

        matched.add(target.resolve())
        running_bytes += actual_bytes
        verdict.checked += 1

    unlisted = sorted(
        p.relative_to(root).as_posix() for p in _tree_files(root) if p.resolve() not in matched
    )
    if unlisted:
        verdict.fail("UNLISTED_ARTIFACT", f"present but not manifested: {unlisted}")

    declared_total = manifest.get("total_bytes")
    if isinstance(declared_total, int) and declared_total != running_bytes and verdict.checked:
        verdict.fail(
            "TOTAL_BYTES_MISMATCH", f"total_bytes={declared_total} but {running_bytes} verified"
        )
    return verdict


# --------------------------------------------------------------------------- #
# Adversarial corruption generator
# --------------------------------------------------------------------------- #


def _c(manifest: dict) -> dict:
    return copy.deepcopy(manifest)


def corruptions(manifest: dict, root: Path) -> list:
    """Yield (name, corrupt_manifest, expected_failure_code) triples."""
    out = []

    m = _c(manifest)
    m["artifacts"] = m["artifacts"][:-1]
    m["artifact_count"] = len(m["artifacts"])
    m["total_bytes"] = sum(e["bytes"] for e in m["artifacts"])
    out.append(("truncated_entry_list", m, "UNLISTED_ARTIFACT"))

    m = _c(manifest)
    m["artifacts"][0]["sha256"] = "0" * 64
    out.append(("digest_zeroed", m, "DIGEST_MISMATCH"))

    m = _c(manifest)
    if len(m["artifacts"]) > 1:
        m["artifacts"][0]["sha256"], m["artifacts"][1]["sha256"] = (
            m["artifacts"][1]["sha256"],
            m["artifacts"][0]["sha256"],
        )
        out.append(("digests_swapped", m, "DIGEST_MISMATCH"))

    m = _c(manifest)
    m["artifacts"][0]["sha256"] = m["artifacts"][0]["sha256"].upper()
    out.append(("digest_uppercased", m, "DIGEST_MALFORMED"))

    m = _c(manifest)
    m["artifacts"][0]["sha256"] = "z" * 64
    out.append(("digest_non_hex", m, "DIGEST_MALFORMED"))

    m = _c(manifest)
    m["artifacts"][0]["sha256"] = m["artifacts"][0]["sha256"][:32]
    out.append(("digest_short", m, "DIGEST_MALFORMED"))

    m = _c(manifest)
    del m["artifacts"][0]["sha256"]
    out.append(("digest_absent", m, "DIGEST_MALFORMED"))

    m = _c(manifest)
    m["artifacts"][0]["bytes"] += 1
    m["total_bytes"] += 1
    out.append(("bytes_inflated", m, "BYTES_MISMATCH"))

    m = _c(manifest)
    m["artifacts"][0]["bytes"] = -1
    out.append(("bytes_negative", m, "BYTES_MALFORMED"))

    m = _c(manifest)
    m["artifacts"][0]["bytes"] = str(m["artifacts"][0]["bytes"])
    out.append(("bytes_stringified", m, "BYTES_MALFORMED"))

    m = _c(manifest)
    m["artifacts"].append(_c(m["artifacts"][0]))
    m["artifact_count"] = len(m["artifacts"])
    out.append(("duplicate_entry", m, "DUPLICATE_ENTRY"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "../escaped.txt"
    out.append(("path_traversal", m, "PATH_TRAVERSAL"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "/etc/hostname"
    out.append(("path_absolute", m, "PATH_ABSOLUTE"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "sub\\component.py"
    out.append(("path_backslash", m, "PATH_BACKSLASH"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "./" + m["artifacts"][0]["path"]
    out.append(("path_dot_prefix", m, "PATH_NOT_CANONICAL"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = " " + m["artifacts"][0]["path"]
    out.append(("path_leading_space", m, "PATH_WHITESPACE"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "sub//" + Path(m["artifacts"][0]["path"]).name
    out.append(("path_double_slash", m, "PATH_NOT_CANONICAL"))

    m = _c(manifest)
    original = m["artifacts"][0]["path"]
    alias = _c(m["artifacts"][0])
    alias["path"] = original.upper()
    m["artifacts"].append(alias)
    m["artifact_count"] = len(m["artifacts"])
    out.append(("path_case_alias", m, "PATH_ALIAS"))

    m = _c(manifest)
    m["artifacts"][0]["path"] = "definitely-not-here.txt"
    out.append(("artifact_missing", m, "ARTIFACT_MISSING"))

    m = _c(manifest)
    m["artifacts"] = []
    m["artifact_count"] = 0
    out.append(("empty_artifact_list", m, "EMPTY_MANIFEST"))

    m = _c(manifest)
    m["artifact_count"] = len(m["artifacts"]) + 7
    out.append(("count_inflated", m, "COUNT_MISMATCH"))

    m = _c(manifest)
    m["total_bytes"] = m["total_bytes"] + 1000
    out.append(("total_bytes_inflated", m, "TOTAL_BYTES_MISMATCH"))

    m = _c(manifest)
    m["manifest_version"] = "PO03-TOTALLY-FINE-v9"
    out.append(("version_forged", m, "MANIFEST_VERSION"))

    m = _c(manifest)
    m["artifacts"][0] = "component.py"
    out.append(("entry_not_an_object", m, "ENTRY_SHAPE"))

    m = _c(manifest)
    del m["artifacts"][0]["path"]
    out.append(("path_absent", m, "ENTRY_PATH_MISSING"))

    return out
