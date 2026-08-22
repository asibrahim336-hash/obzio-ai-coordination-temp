#!/usr/bin/env python3
"""build-manifest.py — OE-W3-CREDENTIAL-ESTATE

Builds the delivery manifest and, separately, the remote read-back record.

Closure rule. The manifest covers EVERY file this lane wrote, in both of its
namespaces, including the read-back record. The single exception is
MANIFEST.json itself, which cannot contain its own SHA-256 without the value
changing as it is written. That exclusion is declared in the manifest as an
explicit field rather than left for a reader to infer — an independent
acceptor has already refused a bundle for omitting a read-back record from its
own manifest, and a later lane repeated it.

bundle_sha256 is defined exactly as the delivery contract specifies:

    sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")))

Subcommands:
    readback <ref>        verify the remote holds byte-identical content, write
                          REMOTE-READBACK.json
    readback-check <ref>  the same verification, writing nothing — used for the
                          final pass that also covers MANIFEST.json and the
                          read-back record, which is what terminates the chain
    manifest              build MANIFEST.json over every file including the above
    verify                recompute and compare, for an acceptor
"""

from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
NAMESPACES = [
    "workstreams/so02/control-plane/operating-environment/w3-credential-estate",
    "receipts/so02/2026-08-22/oe-w3-credential-estate",
]
MANIFEST_PATH = "receipts/so02/2026-08-22/oe-w3-credential-estate/MANIFEST.json"
READBACK_PATH = "receipts/so02/2026-08-22/oe-w3-credential-estate/REMOTE-READBACK.json"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bundle_files(include_manifest: bool = False) -> list[str]:
    """Every file this lane wrote, as repo-relative POSIX paths, sorted."""
    out: list[str] = []
    for ns in NAMESPACES:
        root = REPO / ns
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel == MANIFEST_PATH and not include_manifest:
                continue
            out.append(rel)
    return sorted(out)


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def cmd_readback(ref: str, write: bool = True) -> int:
    """Verify the REMOTE holds byte-identical content, by reading its objects.

    This is a read-back by recomputation, not a trust assertion: every file is
    re-hashed from the blob git fetched back from the remote, and compared
    against the working tree. A push that silently no-ops on a stale ref
    fails here.

    With write=False nothing is written. That mode exists so the final
    read-back — the one that also covers MANIFEST.json and the read-back
    record itself — can run after the last push without creating a new file
    that would need a further manifest, which is what would otherwise make
    the chain non-terminating.
    """
    print(f"read-back against remote ref: {ref}")
    git("fetch", "origin", ref.split("/", 1)[-1] if ref.startswith("origin/") else ref)
    remote_sha = git("rev-parse", ref).strip()
    local_sha = git("rev-parse", "HEAD").strip()
    print(f"  remote commit: {remote_sha}")
    print(f"  local  commit: {local_sha}")

    entries, mismatches, missing = [], [], []
    for rel in bundle_files(include_manifest=True):
        local_path = REPO / rel
        if not local_path.exists():
            continue
        local_digest = sha256_file(local_path)
        try:
            blob = subprocess.run(
                ["git", "-C", str(REPO), "cat-file", "blob", f"{remote_sha}:{rel}"],
                capture_output=True, check=True,
            ).stdout
        except subprocess.CalledProcessError:
            missing.append(rel)
            continue
        remote_digest = hashlib.sha256(blob).hexdigest()
        match = remote_digest == local_digest
        if not match:
            mismatches.append(rel)
        entries.append({
            "path": rel,
            "local_sha256": local_digest,
            "remote_sha256": remote_digest,
            "match": match,
        })

    verified = not mismatches and not missing
    record = {
        "record_id": "OE-W3-REMOTE-READBACK-20260822",
        "lane": "OE-W3-CREDENTIAL-ESTATE",
        "method": (
            "For each file, the blob was read back from the fetched remote commit with "
            "`git cat-file blob <remote_sha>:<path>` and re-hashed, then compared against the "
            "working tree. This is verification by recomputation from remote objects, not an "
            "assertion that the push succeeded."
        ),
        "why_this_check_exists": (
            "`git push` can print 'Everything up-to-date' and exit 0 against a stale ref, so "
            "exit status is not evidence of publication. Only a read-back of remote objects is."
        ),
        "remote_ref": ref,
        "remote_commit_sha": remote_sha,
        "local_commit_sha": local_sha,
        "commits_equal": remote_sha == local_sha,
        "files_checked": len(entries),
        "files_missing_on_remote": missing,
        "files_with_digest_mismatch": mismatches,
        "verified": verified,
        "scope_note": (
            "This record covers every bundle file present on the remote at the commit named "
            "above. MANIFEST.json and this record are themselves written afterwards and "
            "published in the following commit; an acceptor confirms those two with "
            "`build-manifest.py verify` plus `git ls-remote`, which is the terminating step "
            "of the chain."
        ),
        "entries": entries,
    }
    if write:
        (REPO / READBACK_PATH).write_text(json.dumps(record, indent=2, sort_keys=False) + "\n")
    print(f"  files checked: {len(entries)}; mismatches: {len(mismatches)}; missing: {len(missing)}")
    if missing:
        for m in missing:
            print(f"    MISSING ON REMOTE: {m}")
    print(f"  verified: {verified}")
    print(f"  wrote {READBACK_PATH}" if write else "  (check mode — nothing written)")
    return 0 if verified else 1


def cmd_manifest() -> int:
    files = bundle_files(include_manifest=False)
    entries = [
        {
            "path": rel,
            "size_bytes": (REPO / rel).stat().st_size,
            "sha256": sha256_file(REPO / rel),
        }
        for rel in files
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    bundle_sha256 = hashlib.sha256(canonical.encode()).hexdigest()

    manifest = {
        "record_id": "OE-W3-CREDENTIAL-ESTATE-MANIFEST-20260822",
        "lane": "OE-W3-CREDENTIAL-ESTATE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "authority_basis": "FOUNDER-AUTHORITY-DERESTRICTION-20260822T2225Z",
        "branch": "cursor/oe-w3-credential-estate-696d",
        "terminal_state": "READY_TO_COMMIT",
        "namespaces_covered": NAMESPACES,
        "closure": {
            "rule": "Every file this lane wrote, in both namespaces, appears below — including the remote read-back record.",
            "read_back_record_included": READBACK_PATH in files,
            "self_exclusion": MANIFEST_PATH,
            "self_exclusion_reason": "A manifest cannot contain its own SHA-256: writing the value changes the file whose value it is. This is the only omission, and it is declared here rather than left to be inferred.",
            "history": "An independent acceptor refused an earlier bundle in this programme partly for excluding a read-back record from its own manifest, and a later lane repeated it. Hence the explicit assertion above.",
        },
        "bundle_sha256_definition": "sha256 of json.dumps(entries, sort_keys=True, separators=(\",\", \":\"))",
        "bundle_sha256": bundle_sha256,
        "entry_count": len(entries),
        "total_bytes": sum(e["size_bytes"] for e in entries),
        "verification": {
            "recompute": "python3 workstreams/so02/control-plane/operating-environment/w3-credential-estate/tools/build-manifest.py verify",
            "hermetic_recompute": "Run the same command inside a container started with HostConfig.NetworkMode=none via the Docker API on 127.0.0.1:2375. A result obtained with no network and no inherited credential cannot have come from anywhere but the supplied bytes.",
            "credential_gate": "python3 workstreams/so02/control-plane/operating-environment/w3-credential-estate/tools/scan-for-credentials.py <namespaces> — expect CLEAN, exit 0.",
            "publication": "git ls-remote origin refs/heads/cursor/oe-w3-credential-estate-696d",
        },
        "credential_disclosure_statement": "No credential value appears in any file listed below. Names, lengths, prefix classes, redacted forms and SHA-256 digests only. Verified mechanically by scan-for-credentials.py, which refused an earlier draft of this bundle.",
        "entries": entries,
    }
    (REPO / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    print(f"entry_count   : {len(entries)}")
    print(f"total_bytes   : {manifest['total_bytes']}")
    print(f"bundle_sha256 : {bundle_sha256}")
    print(f"read-back record included: {manifest['closure']['read_back_record_included']}")
    print(f"wrote {MANIFEST_PATH}")
    return 0


def cmd_verify() -> int:
    manifest = json.loads((REPO / MANIFEST_PATH).read_text())
    entries = manifest["entries"]
    listed = {e["path"] for e in entries}
    actual = set(bundle_files(include_manifest=False))

    problems: list[str] = []
    for missing in sorted(actual - listed):
        problems.append(f"FILE NOT IN MANIFEST: {missing}")
    for extra in sorted(listed - actual):
        problems.append(f"MANIFEST LISTS A MISSING FILE: {extra}")
    for e in entries:
        p = REPO / e["path"]
        if not p.exists():
            continue
        if (d := sha256_file(p)) != e["sha256"]:
            problems.append(f"DIGEST MISMATCH: {e['path']} expected {e['sha256']} got {d}")
        if (s := p.stat().st_size) != e["size_bytes"]:
            problems.append(f"SIZE MISMATCH: {e['path']} expected {e['size_bytes']} got {s}")

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    recomputed = hashlib.sha256(canonical.encode()).hexdigest()
    if recomputed != manifest["bundle_sha256"]:
        problems.append(f"BUNDLE DIGEST MISMATCH: expected {manifest['bundle_sha256']} got {recomputed}")
    if len(entries) != manifest["entry_count"]:
        problems.append(f"ENTRY COUNT MISMATCH: declared {manifest['entry_count']} actual {len(entries)}")
    if READBACK_PATH not in listed:
        problems.append("CLOSURE FAILURE: the remote read-back record is not in the manifest")

    print(f"files on disk : {len(actual)}")
    print(f"entries listed: {len(entries)}")
    print(f"bundle_sha256 : {recomputed}")
    print(f"read-back record in manifest: {READBACK_PATH in listed}")
    if problems:
        print(f"VERIFY: FAIL — {len(problems)} problem(s)")
        for p in problems:
            print(f"  {p}")
        return 1
    print("VERIFY: PASS — full closure, every digest and size matches")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "manifest"
    DEFAULT_REF = "origin/cursor/oe-w3-credential-estate-696d"
    if cmd == "readback":
        raise SystemExit(cmd_readback(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REF))
    if cmd == "readback-check":
        raise SystemExit(cmd_readback(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REF,
                                      write=False))
    if cmd == "manifest":
        raise SystemExit(cmd_manifest())
    if cmd == "verify":
        raise SystemExit(cmd_verify())
    raise SystemExit(f"unknown subcommand: {cmd}")
