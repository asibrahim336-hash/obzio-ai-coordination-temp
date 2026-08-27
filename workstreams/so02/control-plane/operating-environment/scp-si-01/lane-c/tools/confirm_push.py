#!/usr/bin/env python3
"""Confirm the remote holds the bytes the manifest hashes.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/confirm_push.py \
        --repo-root . --ref cursor/scp-c-authorship-sidecar-696d

`READ-BACK.json` states its own limitation plainly: it proves the bytes in this
working tree hash and parse, and it does not prove the remote holds them. This
closes that gap. It re-fetches the ref, reads every manifest entry out of the
fetched commit with `git cat-file` rather than off local disk, and compares.

`git push` can exit 0 without moving the ref, so the SHA is taken from
`git ls-remote` — the remote's own answer — and not from the local branch.

## The regress, and where it stops

A confirmation records the SHA of a commit, so it cannot live inside that commit.
Nothing can: a file cannot carry the hash of a commit that does not exist until
the file does. So the receipt written here confirms the *previous* commit, and
the manifest stage is then re-run so that the manifest of the commit carrying
this receipt closes over it too — which keeps `MANIFEST.json` the single declared
exclusion rather than growing a second one.

That leaves exactly one commit unconfirmed by a committed artifact: the last.
`--no-write` runs the same check on it and reports the verdict without writing
anything, so the regress terminates in the lane's return rather than in an
artifact pretending to contain its own future.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402

MANIFEST_REL = "receipts/so02/2026-08-27/scp-c/MANIFEST.json"
OUT_REL = "receipts/so02/2026-08-27/scp-c/PUSH-CONFIRMATION.json"


def git(args: list[str], repo_root: str) -> tuple[int, bytes]:
    proc = subprocess.run(["git", "-C", repo_root] + args,
                          capture_output=True)
    return proc.returncode, proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--integration-ref",
                        default="cursor/operating-environment-return-20260822-v001")
    parser.add_argument("--no-write", action="store_true",
                        help="check and report without writing the receipt; used for the "
                             "last commit, whose confirmation cannot be inside itself")
    args = parser.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest, problems = A.read_back_and_parse(os.path.join(repo_root, MANIFEST_REL))
    if manifest is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1

    code, out = git(["ls-remote", "origin", f"refs/heads/{args.ref}"], repo_root)
    if code != 0:
        print("FAIL ls-remote failed; the push cannot be confirmed and an unconfirmed "
              "push is not a push")
        return 1
    text = out.decode("utf-8", "replace").strip()
    remote_sha = text.split()[0] if text else None
    if remote_sha is None:
        print(f"FAIL NOT_FOUND origin/{args.ref} — git ls-remote returned empty. "
              "git push can exit 0 without moving the ref; this is that case.")
        return 1

    git(["fetch", "origin", args.ref], repo_root)

    findings: list[str] = []
    checked = 0
    for entry in manifest.get("entries", []):
        rel = entry.get("path")
        code, blob = git(["cat-file", "blob", f"{remote_sha}:{rel}"], repo_root)
        if code != 0:
            findings.append(f"ABSENT_ON_REMOTE {rel}")
            continue
        checked += 1
        if A.sha256_bytes(blob) != entry.get("sha256"):
            findings.append(f"HASH_MISMATCH_ON_REMOTE {rel}")
        if len(blob) != entry.get("size_bytes"):
            findings.append(f"SIZE_MISMATCH_ON_REMOTE {rel}")

    # The manifest excludes itself, so confirm it separately or its own arrival
    # on the remote goes unchecked.
    code, blob = git(["cat-file", "blob", f"{remote_sha}:{MANIFEST_REL}"], repo_root)
    manifest_on_remote = None
    if code != 0:
        findings.append(f"ABSENT_ON_REMOTE {MANIFEST_REL}")
    else:
        manifest_on_remote = A.sha256_bytes(blob)
        try:
            reparsed = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(f"UNPARSABLE_ON_REMOTE {MANIFEST_REL}: {exc}")
        else:
            if A.bundle_sha256(reparsed.get("entries", [])) != reparsed.get("bundle_sha256"):
                findings.append(f"BUNDLE_MISMATCH_ON_REMOTE {MANIFEST_REL}")

    code, out = git(["rev-parse", f"origin/{args.integration_ref}"], repo_root)
    integration_sha = out.decode().strip() if code == 0 else None

    receipt = {
        "receipt_id": "SCP-C-PUSH-CONFIRMATION-20260827-v001",
        "lane": "SCP-SI-01 lane C",
        "generated_at": now,
        "evidence_label": "DIRECTLY_REPRODUCED",
        "ref": args.ref,
        "pushed_sha": remote_sha,
        "pushed_sha_source": (
            "git ls-remote origin refs/heads/" + args.ref + " — the remote's own answer. "
            "Not the local branch tip, because git push can exit 0 without moving the ref."
        ),
        "integration_ref": args.integration_ref,
        "integration_sha_at_confirmation": integration_sha,
        "confirms_manifest": {
            "path": MANIFEST_REL,
            "bundle_sha256": manifest.get("bundle_sha256"),
            "entry_count": manifest.get("entry_count"),
            "sha256_on_remote": manifest_on_remote,
        },
        "method": (
            "Every manifest entry is read out of the pushed commit with git cat-file and "
            "hashed, rather than read off local disk. READ-BACK.json proves the working "
            "tree; this proves the remote. MANIFEST.json excludes itself from its own "
            "entries, so it is fetched and re-verified separately, including recomputing "
            "its bundle_sha256 from the pushed bytes."
        ),
        "entries_confirmed_on_remote": checked,
        "findings": findings,
        "verdict": "REMOTE_HOLDS_THE_DECLARED_BYTES" if not findings else "PUSH_UNCONFIRMED",
        "outside_manifest_closure": (
            "This receipt records the SHA of the commit that contains MANIFEST.json, so it "
            "cannot be inside that commit and is therefore not one of the manifest's "
            "entries. The exclusion is structural rather than chosen: a file cannot carry "
            "the hash of a commit that does not exist until the file does. It is stated "
            "here rather than left to be noticed, and the bundle_sha256 it confirms is "
            "named above so a reader can tell which manifest it refers to."
        ),
        "decision_changed": [],
    }

    if not args.no_write:
        path = os.path.join(repo_root, OUT_REL)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    for f in findings:
        print(f"FAIL {f}")
    print(f"pushed_sha    = {remote_sha}")
    print(f"entries       = {checked}/{len(manifest.get('entries', []))} confirmed on remote")
    print(f"bundle_sha256 = {manifest.get('bundle_sha256')}")
    print(f"verdict       = {receipt['verdict']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
