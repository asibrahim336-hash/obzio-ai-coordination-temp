#!/usr/bin/env python3
"""Build the sanitized adversarial pack fixture used to qualify the reproducer.

The fixture is a throwaway local repository containing synthetic packs whose
shape mirrors the real corpus (two manifest dialects, a shared spine, an
aggregate manifest) while carrying no PO-01 bytes at all.  Every defect is
injected deliberately from ``fixtures/adversarial-fixture-spec.json``, so the
expected discrepancy set is known before the reproducer runs and a false
negative is a test failure rather than a judgement call.

The generator is the adversary: it writes manifests that *disagree* with the
blobs it commits.  A reproducer that trusted the manifests, or that skipped the
content-addressed relocation lookup, would report a clean corpus and fail here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


SPEC_PATH = Path(__file__).resolve().parent / "fixtures" / "adversarial-fixture-spec.json"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "--no-pager", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _synthetic_body(pack: str, name: str, filler: int) -> bytes:
    """Deterministic sanitized content; no PO-01 bytes and no secrets."""
    header = f"# sanitized fixture content for {pack}/{name}\n"
    body = "".join(f"line {index:04d} of synthetic pack payload\n" for index in range(filler))
    return (header + body).encode("utf-8")


def _digest_entry(payload: bytes) -> dict[str, Any]:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def load_spec(spec_path: Path = SPEC_PATH) -> dict[str, Any]:
    return json.loads(spec_path.read_text(encoding="utf-8"))


def build(target: Path, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Materialise the fixture repository and return its pinned commit facts."""
    spec = spec or load_spec()
    target = Path(target)
    pack_root = spec["pack_root"]
    root = target / pack_root
    root.mkdir(parents=True, exist_ok=True)

    _git(target, "init", "--quiet", "--initial-branch=fixture")
    _git(target, "config", "user.email", "fixture@obzio.invalid")
    _git(target, "config", "user.name", "PO03 WA-006 fixture builder")

    shared_payload = _synthetic_body("_shared", "_spine.py", spec["shared_spine"]["filler_lines"])
    shared_entry = _digest_entry(shared_payload)
    shared_published_path = spec["shared_spine"]["published_at"]
    (target / shared_published_path).parent.mkdir(parents=True, exist_ok=True)
    (target / shared_published_path).write_bytes(shared_payload)

    aggregate_packs: dict[str, Any] = {}
    for pack in spec["packs"]:
        pack_name = pack["name"]
        pack_dir = root / pack_name
        pack_dir.mkdir(parents=True, exist_ok=True)

        claims: dict[str, dict[str, Any]] = {}
        for member in pack["files"]:
            name = member["name"]
            if member.get("content") == "SHARED_SPINE":
                payload = shared_payload
            else:
                payload = _synthetic_body(pack_name, name, member.get("filler_lines", 4))
            entry = _digest_entry(payload)

            # Adversarial injections: the manifest claim is written first, then
            # the committed bytes are deliberately withheld or altered.
            if member.get("inject") == "OMIT_FROM_TREE":
                pass
            elif member.get("inject") == "ALTER_BYTES_AFTER_CLAIM":
                (pack_dir / name).write_bytes(payload + b"# adversarial trailing mutation\n")
            else:
                (pack_dir / name).write_bytes(payload)

            if member.get("inject") == "OVERSTATE_BYTES":
                entry = {**entry, "bytes": entry["bytes"] + member["overstate_by"]}
            if member.get("inject") == "WRONG_DIGEST":
                entry = {**entry, "sha256": hashlib.sha256(b"unrelated-" + payload).hexdigest()}
            claims[name] = entry

        pack_injects = pack.get("injects", [])
        enumerated_bytes = sum(entry["bytes"] for entry in claims.values())
        file_count = len(claims)
        if "UNDERSTATE_FILE_COUNT" in pack_injects:
            file_count -= pack["understate_by"]
        total_bytes = enumerated_bytes
        if "WRONG_TOTAL_BYTES" in pack_injects:
            total_bytes += pack["total_bytes_delta"]

        if pack["dialect"] == "v2_object":
            manifest: dict[str, Any] = {
                "file_count": file_count,
                "files": {name: claims[name] for name in sorted(claims)},
                "manifest_version": "obzio.manifest.v2",
                "pack": pack_name,
                "total_bytes": total_bytes,
            }
        elif pack["dialect"] == "array_path":
            manifest = {
                "excluded": ["MANIFEST.json"],
                "excluded_reason": "MANIFEST.json cannot contain its own digest",
                "file_count": file_count,
                "files": [
                    {"bytes": claims[name]["bytes"], "path": name, "sha256": claims[name]["sha256"]}
                    for name in sorted(claims)
                ],
                "hash_algorithm": "sha256",
                "pack": pack_name,
                "total_bytes": total_bytes,
            }
        else:
            raise ValueError(f"unknown fixture dialect: {pack['dialect']}")

        if "NON_PORTABLE_PACK_ROOT" in pack_injects:
            manifest["build_root"] = pack["non_portable_value"]

        (pack_dir / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if pack.get("aggregate_covered", True):
            aggregate_packs[pack_name] = {
                "file_count": file_count,
                "total_bytes": total_bytes,
                "verifies": True,
            }

    aggregate = {
        "manifest_version": "obzio.manifest.v2",
        "packs": dict(sorted(aggregate_packs.items())),
        "root": spec["aggregate"]["non_portable_root"],
        "shared_spine": {shared_published_path.split("/", 1)[-1]: shared_entry},
        "totals": {"pack_count": len(aggregate_packs)},
    }
    (root / "MANIFEST.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    _git(target, "add", "--all")
    _git(target, "commit", "--quiet", "-m", "sanitized adversarial pack fixture")
    commit = _git(target, "rev-parse", "HEAD").strip()
    return {
        "repo": str(target),
        "commit": commit,
        "pack_root": pack_root,
        "shared_spine_sha256": shared_entry["sha256"],
        "expected_discrepancy_kind_counts": spec["expected_discrepancy_kind_counts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True, help="empty directory for the fixture repo")
    args = parser.parse_args(argv)
    facts = build(args.target)
    print(json.dumps(facts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
