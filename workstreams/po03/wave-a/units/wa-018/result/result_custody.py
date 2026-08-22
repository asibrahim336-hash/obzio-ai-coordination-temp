#!/usr/bin/env python3
"""Deterministic artifact manifest and immutable remote readback for WA-018.

Two subcommands:

  manifest  Build artifact-manifest.json over the owned result slot with complete
            SHA-256 and byte accounting, sorted by path so the manifest is a
            function of content alone.

  readback  Fetch the pushed branch into a throwaway repository and verify every
            manifest entry against the immutable commit by SHA-256 and byte
            count, then report changed paths against the producer source base.

The readback deliberately runs in a fresh clone with --no-hardlinks so a warm
object store cannot satisfy a read that the remote could not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-018/"
SLOT = OWNED_PREFIX + "result/"
MANIFEST_NAME = "artifact-manifest.json"
RETURN_NAME = "ready-to-commit.json"
MANIFEST_VERSION = "OBZIO-WA-018-ARTIFACT-MANIFEST-v1"
SOURCE_BASE = "48ac81e2580c6efefae8de39dc6b484b57e5c881"

MEDIA_TYPES = {
    ".py": "text/x-python; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

# The manifest is the payload inventory. The manifest cannot contain its own
# digest, and the return envelope carries the manifest digest, so neither is a
# payload entry. Both are accounted for separately in the return envelope.
SELF_EXCLUDED = {MANIFEST_NAME, RETURN_NAME}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True)


def _git_bytes(cwd: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(cwd), *args])


def _media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def _artifact_id(name: str) -> str:
    stem = name.replace(".", "-").replace("_", "-").lower()
    return f"art-po03-wa-018-{stem}"


def _payload_paths() -> list[Path]:
    return sorted(
        path
        for path in HERE.iterdir()
        if path.is_file() and path.name not in SELF_EXCLUDED
    )


def build_manifest() -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    total = 0
    for path in _payload_paths():
        data = path.read_bytes()
        total += len(data)
        artifacts.append(
            {
                "artifact_id": _artifact_id(path.name),
                "logical_name": path.name,
                "path": SLOT + path.name,
                "sha256": _sha(data),
                "bytes": len(data),
                "media_type": _media_type(path),
            }
        )
    return {
        "manifest_version": MANIFEST_VERSION,
        "task_id": "PO03-WA-018",
        "attempt_id": "PO03-WA-018-A02",
        "result_slot": SLOT,
        "owned_subtree": OWNED_PREFIX,
        "producer_source_base_commit": SOURCE_BASE,
        "hash_algorithm": "sha256",
        "ordering": "ascending by path, so the manifest is a function of content alone",
        "self_excluded": sorted(SELF_EXCLUDED),
        "self_excluded_reason": (
            "A manifest cannot contain its own digest, and the return envelope "
            "carries the manifest digest. Both are accounted for separately in "
            "ready-to-commit.json."
        ),
        "artifact_count": len(artifacts),
        "total_bytes": total,
        "artifacts": artifacts,
    }


def _write_json(path: Path, value: Any) -> bytes:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(data)
    return data


def readback(branch: str, commit: str, remote: str) -> dict[str, Any]:
    manifest = json.loads((HERE / MANIFEST_NAME).read_bytes())
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="wa018-readback-") as scratch:
        work = Path(scratch) / "fresh"
        subprocess.check_call(
            ["git", "clone", "--no-hardlinks", "--quiet", remote, str(work)]
        )
        _git(work, "fetch", "--quiet", "origin", f"refs/heads/{branch}")
        resolved = _git(work, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        tip = _git(work, "rev-parse", f"refs/remotes/origin/{branch}").strip()
        # A fresh clone lands on the default branch, where the owned subtree does
        # not exist, so the working tree is moved to the immutable commit before
        # the clean-clone suite is run from it.
        _git(work, "checkout", "--quiet", "--detach", resolved)

        for entry in manifest["artifacts"]:
            data = _git_bytes(work, "show", "--no-textconv", f"{resolved}:{entry['path']}")
            checks.append(
                {
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "bytes": entry["bytes"],
                    "observed_sha256": _sha(data),
                    "observed_bytes": len(data),
                    "matches": _sha(data) == entry["sha256"]
                    and len(data) == entry["bytes"],
                }
            )

        manifest_data = _git_bytes(
            work, "show", "--no-textconv", f"{resolved}:{SLOT}{MANIFEST_NAME}"
        )
        checks.append(
            {
                "path": SLOT + MANIFEST_NAME,
                "sha256": _sha(manifest_data),
                "bytes": len(manifest_data),
                "observed_sha256": _sha(manifest_data),
                "observed_bytes": len(manifest_data),
                "matches": _sha(manifest_data)
                == _sha((HERE / MANIFEST_NAME).read_bytes()),
                "note": "manifest verified as present and hashed at the immutable commit",
            }
        )

        changed = [
            line
            for line in _git(
                work, "diff", "--name-only", f"{SOURCE_BASE}..{resolved}"
            ).splitlines()
            if line.strip()
        ]
        out_of_scope = [path for path in changed if not path.startswith(OWNED_PREFIX)]

        clean_suite = subprocess.run(
            [
                "python3",
                "-m",
                "unittest",
                "discover",
                "-s",
                ".",
                "-p",
                "test_*.py",
            ],
            cwd=work / SLOT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        suite_lines = clean_suite.stderr.strip().splitlines()

    return {
        "protocol_version": "OBZIO-WA-018-READBACK-v1",
        "method": (
            "Fresh no-hardlink clone of the remote into a throwaway directory, "
            "forced ref fetch, then git show --no-textconv <immutable-commit>:<path> "
            "with SHA-256 and byte comparison for every manifest entry."
        ),
        "remote_ref": f"refs/heads/{branch}",
        "commit": resolved,
        "remote_tip_at_readback": tip,
        "base_commit": SOURCE_BASE,
        "artifact_count": len(checks),
        "all_match": all(check["matches"] for check in checks),
        "changed_path_count": len(changed),
        "out_of_scope_changed_path_count": len(out_of_scope),
        "out_of_scope_changed_paths": out_of_scope,
        "clean_clone_suite": {
            "command": "python3 -m unittest discover -s . -p 'test_*.py'",
            "cwd": SLOT,
            "environment": "PATH restricted to /usr/bin:/bin, no inherited environment",
            "exit_code": clean_suite.returncode,
            "state": "PASS" if clean_suite.returncode == 0 else "FAIL",
            "summary": suite_lines[-1] if suite_lines else "",
            "tests_run": next(
                (
                    int(line.split()[1])
                    for line in suite_lines
                    if line.startswith("Ran ")
                ),
                None,
            ),
        },
        "checks": checks,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest")
    read = sub.add_parser("readback")
    read.add_argument("--branch", required=True)
    read.add_argument("--commit", required=True)
    read.add_argument(
        "--remote", default="https://github.com/asibrahim336-hash/obzio-ai-coordination-temp"
    )
    read.add_argument("--out", default="-")
    args = parser.parse_args()

    if args.command == "manifest":
        manifest = build_manifest()
        data = _write_json(HERE / MANIFEST_NAME, manifest)
        print(
            json.dumps(
                {
                    "manifest_path": SLOT + MANIFEST_NAME,
                    "manifest_sha256": _sha(data),
                    "manifest_bytes": len(data),
                    "artifact_count": manifest["artifact_count"],
                    "total_bytes": manifest["total_bytes"],
                },
                sort_keys=True,
            )
        )
        return 0

    report = readback(args.branch, args.commit, args.remote)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        print(text, end="")
    else:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
