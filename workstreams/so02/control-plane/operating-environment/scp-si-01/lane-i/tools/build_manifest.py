#!/usr/bin/env python3
"""Emit (or check) the SCP-SI-01 Lane I receipt manifest.

`bundle_sha256` is the sha256 of the canonical JSON encoding of the entry
list (`json.dumps(entries, sort_keys=True, separators=(",", ":"))`), so a
third party can recompute it from the files alone without trusting this
script's own output.

Closure covers, relative to the repository root:

  * everything under `workstreams/so02/control-plane/operating-environment/
    scp-si-01/lane-i/` (this lane's own namespace) except compiled bytecode
  * everything under `receipts/so02/2026-08-27/scp-i/` except `MANIFEST.json`
    itself (a file cannot contain its own hash) and compiled bytecode
  * this lane's one write declaration
  * the four tooling files this lane added under the shared `tools/`
    directory (named explicitly below, not path-derived, so an unrelated
    future addition to that shared directory by another lane is never
    silently swept into this lane's closure)

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[7]
RECEIPT_DIR = REPO_ROOT / "receipts/so02/2026-08-27/scp-i"
MANIFEST = RECEIPT_DIR / "MANIFEST.json"
WRITE_DECLARATION = (
    REPO_ROOT
    / "workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-I.json"
)
SHARED_TOOLS_DIR = REPO_ROOT / "workstreams/so02/control-plane/operating-environment/tools"
SHARED_TOOLS_FILES = [
    "push_with_admission.py",
    "test_push_with_admission.py",
    "effectiveness_prober.py",
    "test_effectiveness_prober.py",
]

MANIFEST_ID = "SCP-SI-01-LANE-I-MANIFEST-20260827-v001"


def _is_junk(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo")


def _hash_entry(path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def collect_entries() -> list[dict]:
    entries = []

    for path in sorted(LANE_ROOT.rglob("*")):
        if not path.is_file() or _is_junk(path):
            continue
        entries.append(_hash_entry(path))

    if RECEIPT_DIR.exists():
        for path in sorted(RECEIPT_DIR.rglob("*")):
            if not path.is_file() or path == MANIFEST or _is_junk(path):
                continue
            entries.append(_hash_entry(path))

    if WRITE_DECLARATION.is_file():
        entries.append(_hash_entry(WRITE_DECLARATION))

    for name in SHARED_TOOLS_FILES:
        path = SHARED_TOOLS_DIR / name
        if not path.is_file():
            raise SystemExit(f"CLOSURE ERROR: expected shared-tools file missing: {path}")
        entries.append(_hash_entry(path))

    seen = set()
    deduped = []
    for entry in entries:
        if entry["path"] in seen:
            continue
        seen.add(entry["path"])
        deduped.append(entry)
    deduped.sort(key=lambda entry: entry["path"])
    return deduped


def bundle_hash(entries: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build() -> dict:
    entries = collect_entries()
    bundle = bundle_hash(entries)
    manifest = {
        "manifest_id": MANIFEST_ID,
        "lane": "SCP-SI-01-LANE-I",
        "commission_id": "SCP-SI-01",
        "branch": "cursor/scp-i-effective-controls-696d",
        "terminal_state": "READY_TO_COMMIT",
        "closure": {
            "covered": [
                "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/",
                "receipts/so02/2026-08-27/scp-i/",
                str(WRITE_DECLARATION.relative_to(REPO_ROOT)),
                *[f"workstreams/so02/control-plane/operating-environment/tools/{name}"
                  for name in SHARED_TOOLS_FILES],
            ],
            "self_exclusion_rule": (
                "This manifest excludes itself and nothing else in receipts/so02/2026-08-27/scp-i/. "
                "A file cannot contain its own hash, so the exclusion is declared rather than implied."
            ),
            "excluded_by_rule": [
                str(MANIFEST.relative_to(REPO_ROOT)),
            ],
            "also_excluded": (
                "Compiled bytecode (__pycache__, *.pyc, *.pyo) -- regenerated on import, not evidence."
            ),
            "read_back_record_is_covered": (
                "receipts/so02/2026-08-27/scp-i/READ-BACK-20260827-v001.json is a manifest entry, not "
                "an exception, once it exists. It is produced by cloning an already-pushed commit and "
                "is itself included the next time this builder runs, exactly as the OE-W5 precedent "
                "(receipts/so02/2026-08-22/oe-w5-agentic-office/MANIFEST.json) does."
            ),
            "closure_assertion": (
                "entries == every file under the covered namespaces, plus the one write declaration, "
                "plus the four named shared-tools files, minus excluded_by_rule, minus also_excluded"
            ),
            "closure_check": (
                "python3 workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/tools/"
                "build_manifest.py --check receipts/so02/2026-08-27/scp-i/MANIFEST.json"
            ),
        },
        "entry_count": len(entries),
        "bundle_sha256_definition": 'sha256 of json.dumps(entries, sort_keys=True, separators=(",",":"))',
        "bundle_sha256": bundle,
        "entries": entries,
    }
    return manifest


def write_manifest() -> int:
    manifest = build()
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"entry_count   {manifest['entry_count']}")
    print(f"bundle_sha256 {manifest['bundle_sha256']}")
    return 0


def check(manifest_path: Path) -> int:
    """Recompute every entry's hash from disk and every declared JSON's parse,
    and compare against a previously-written manifest. Never trusts the
    manifest's own claims about itself."""
    on_disk = build()
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))

    ok = True
    if recorded.get("entry_count") != on_disk["entry_count"]:
        print(f"MISMATCH entry_count: recorded={recorded.get('entry_count')} "
              f"on_disk={on_disk['entry_count']}")
        ok = False
    if recorded.get("bundle_sha256") != on_disk["bundle_sha256"]:
        print(f"MISMATCH bundle_sha256: recorded={recorded.get('bundle_sha256')} "
              f"on_disk={on_disk['bundle_sha256']}")
        ok = False

    recorded_by_path = {e["path"]: e for e in recorded.get("entries", [])}
    on_disk_by_path = {e["path"]: e for e in on_disk["entries"]}
    for path, expected in recorded_by_path.items():
        actual = on_disk_by_path.get(path)
        if actual is None:
            print(f"MISSING on disk: {path}")
            ok = False
            continue
        if actual["sha256"] != expected["sha256"] or actual["size_bytes"] != expected["size_bytes"]:
            print(f"HASH MISMATCH: {path}")
            ok = False
        if path.endswith(".json"):
            try:
                json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"PARSE FAILURE: {path}: {exc}")
                ok = False
    for path in on_disk_by_path:
        if path not in recorded_by_path:
            print(f"EXTRA on disk, not in manifest: {path}")
            ok = False

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        target = Path(argv[1]) if len(argv) > 1 else MANIFEST
        return check(target)
    return write_manifest()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
