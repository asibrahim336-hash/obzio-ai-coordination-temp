#!/usr/bin/env python3
"""Qualify bytes independently of a pack's self-reported status."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def qualify(pack_dir: Path, manifest_name: str = "fixture_manifest.json") -> dict[str, Any]:
    manifest = json.loads((pack_dir / manifest_name).read_text(encoding="utf-8"))
    rows = []
    for path, expected in sorted(manifest["files"].items()):
        target = pack_dir / path
        body = target.read_bytes() if target.is_file() else None
        observed_hash = hashlib.sha256(body).hexdigest() if body is not None else None
        observed_bytes = len(body) if body is not None else None
        accepted = (
            body is not None
            and observed_hash == expected.get("sha256")
            and observed_bytes == expected.get("bytes")
        )
        rows.append(
            {
                "path": path,
                "present": body is not None,
                "declared_sha256": expected.get("sha256"),
                "observed_sha256": observed_hash,
                "declared_bytes": expected.get("bytes"),
                "observed_bytes": observed_bytes,
                "accepted": accepted,
            }
        )
    accepted = bool(rows) and all(row["accepted"] for row in rows)
    return {
        "fixture_label": manifest.get("fixture_label"),
        "self_reported_status": manifest.get("self_reported_status"),
        "qualification": "PASS" if accepted else "FAIL",
        "self_report_ignored": True,
        "evidence_table": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.pack_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
