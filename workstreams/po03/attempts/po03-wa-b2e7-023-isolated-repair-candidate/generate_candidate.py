#!/usr/bin/env python3
"""Generate a frozen regression and isolated integration candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
PACKS = (
    "06-browser-execution",
    "07-capability-manufacture",
    "08-knowledge-currentness",
    "09-infrastructure-operation",
    "10-economics-measurement",
)
HERE = Path(__file__).resolve().parent
ALLOWED_OUTPUT = (HERE / "candidate").resolve()


FROZEN_TEST = '''#!/usr/bin/env python3
"""Frozen regression for the absent declared sibling runtime dependency."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
PACKS = (
    "06-browser-execution",
    "07-capability-manufacture",
    "08-knowledge-currentness",
    "09-infrastructure-operation",
    "10-economics-measurement",
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-root", required=True, type=Path)
    args = parser.parse_args()
    missing = []
    for pack in PACKS:
        manifest = json.loads((args.pack_root / pack / "MANIFEST.json").read_text())
        assert any(row.get("path") == "_spine.py" for row in manifest["files"])
        target = args.pack_root / pack / "_spine.py"
        if not target.is_file():
            missing.append(target.relative_to(args.pack_root).as_posix())
    assert not missing, f"{PINNED} missing declared runtime files: {missing}"
    print(json.dumps({"pinned": PINNED, "missing": missing, "verdict": "PASS"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


REPAIR_CANDIDATE = '''#!/usr/bin/env python3
"""Integration candidate: restore manifest-pinned sibling spine bytes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
EXPECTED_SPINE_SHA256 = "431773539ced6556fdd9a631fc80d42404aa2f30846a1d127826dd099a01f182"
PACKS = (
    "06-browser-execution",
    "07-capability-manufacture",
    "08-knowledge-currentness",
    "09-infrastructure-operation",
    "10-economics-measurement",
)

def repair(pack_root: Path) -> list[str]:
    source = pack_root / "_shared" / "_spine.py"
    body = source.read_bytes()
    observed = hashlib.sha256(body).hexdigest()
    if observed != EXPECTED_SPINE_SHA256:
        raise ValueError(f"shared spine hash mismatch: {observed}")
    written = []
    for pack in PACKS:
        manifest = json.loads((pack_root / pack / "MANIFEST.json").read_text())
        declaration = next(row for row in manifest["files"] if row.get("path") == "_spine.py")
        if declaration["sha256"] != observed or declaration["bytes"] != len(body):
            raise ValueError(f"{pack} declaration does not match shared spine")
        target = pack_root / pack / "_spine.py"
        if not target.exists():
            target.write_bytes(body)
            written.append(target.relative_to(pack_root).as_posix())
    return written

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-root", required=True, type=Path)
    args = parser.parse_args()
    written = repair(args.pack_root)
    print(json.dumps({"pinned": PINNED, "written": written, "verdict": "REPAIR_CANDIDATE_APPLIED_TO_COPY"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def git_blob(repo: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ("git", "cat-file", "blob", f"{PINNED}:{path}"),
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output != ALLOWED_OUTPUT:
        raise SystemExit(f"refusing output outside isolated candidate path: {output}")
    if any("po01" in part.lower() for part in output.parts):
        raise SystemExit(f"refusing PO-01 namespace path: {output}")

    missing = []
    declarations = []
    for pack in PACKS:
        manifest_path = f"packs/{pack}/MANIFEST.json"
        manifest_raw = git_blob(args.repo, manifest_path)
        if manifest_raw is None:
            raise SystemExit(f"missing manifest at {PINNED}:{manifest_path}")
        manifest = json.loads(manifest_raw)
        declaration = next(row for row in manifest["files"] if row.get("path") == "_spine.py")
        target = f"packs/{pack}/_spine.py"
        declarations.append({"manifest": manifest_path, "target": target, **declaration})
        if git_blob(args.repo, target) is None:
            missing.append(target)

    shared = git_blob(args.repo, "packs/_shared/_spine.py")
    if shared is None:
        raise SystemExit("shared spine absent")
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "frozen_test_missing_spine.py": FROZEN_TEST,
        "repair_candidate.py": REPAIR_CANDIDATE,
        "defect.json": json.dumps(
            {
                "defect_version": "PO03-ISOLATED-REPAIR-CANDIDATE-v1",
                "pinned_commit": PINNED,
                "missing_paths": missing,
                "declarations": declarations,
                "shared_spine": {
                    "path": "packs/_shared/_spine.py",
                    "bytes": len(shared),
                    "sha256": hashlib.sha256(shared).hexdigest(),
                },
                "po01_path_writes": [],
                "candidate_scope": "held entirely under this PO-03 unit; never applied to PO-01",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    written = []
    for name, text in files.items():
        target = output / name
        if output not in target.resolve().parents:
            raise SystemExit(f"unsafe output path: {target}")
        target.write_text(text, encoding="utf-8")
        written.append(target.relative_to(HERE).as_posix())
    print(
        json.dumps(
            {
                "pinned_commit": PINNED,
                "missing_count": len(missing),
                "missing_paths": missing,
                "written_paths": written,
                "po01_path_writes": [],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
