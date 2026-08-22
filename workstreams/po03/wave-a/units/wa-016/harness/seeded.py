#!/usr/bin/env python3
"""Loader for the read-only seeded PO-03 controls this unit composes.

The seeded validator, schemas, acceptance contract and frozen task input live
outside this unit's owned subtree.  They are loaded in place and hash-checked
against the digests pinned in the frozen task input, so drift in a control this
unit depends on fails loudly instead of silently changing what "valid" means.
Nothing here writes to those paths.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

UNIT_ROOT = Path(__file__).resolve().parents[1]

# The frozen task input this unit executes.
TASK_INPUT_REL = "workstreams/po03/control/inputs/wave-a/wa-016.json"

SEEDED_RELS = {
    "validator": "workstreams/po03/tools/validate_contracts.py",
    "transactional_schema": "workstreams/po03/contracts/transactional-result.schema.json",
    "wave_schema": "workstreams/po03/contracts/wave-compounding.schema.json",
    "seed_tests": "workstreams/po03/tests/test_validate_contracts.py",
    "commission": "workstreams/po03/COMMISSION.md",
    "workflow": ".github/workflows/po03-contracts.yml",
}

# source_base keys in the frozen input that pin each seeded control's digest.
PINNED_DIGEST_KEYS = {
    "validator": "validator_sha256",
    "transactional_schema": "transactional_schema_sha256",
    "wave_schema": "wave_schema_sha256",
    "seed_tests": "seed_tests_sha256",
    "commission": "commission_sha256",
    "workflow": "workflow_sha256",
}


class SeededControlError(RuntimeError):
    """A read-only seeded control is missing or has drifted from its pin."""


def repository_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up to the seeded control tree."""
    current = (start or UNIT_ROOT).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / SEEDED_RELS["validator"]).exists():
            return candidate
    raise SeededControlError("repository root with seeded PO-03 controls not found")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_input(root: Path | None = None) -> dict[str, Any]:
    base = root or repository_root()
    path = base / TASK_INPUT_REL
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeededControlError(f"frozen task input unreadable at {path}: {exc}") from exc


@dataclass(frozen=True)
class ControlDigest:
    name: str
    relative_path: str
    observed_sha256: str
    pinned_sha256: str | None
    bytes: int

    @property
    def matches_pin(self) -> bool:
        return self.pinned_sha256 is not None and self.observed_sha256 == self.pinned_sha256


def control_digests(root: Path | None = None) -> list[ControlDigest]:
    """Observed vs pinned digest for every seeded control this unit reads."""
    base = root or repository_root()
    pins = task_input(base)["source_base"]
    digests: list[ControlDigest] = []
    for name, rel in sorted(SEEDED_RELS.items()):
        path = base / rel
        if not path.exists():
            raise SeededControlError(f"seeded control missing: {rel}")
        digests.append(
            ControlDigest(
                name=name,
                relative_path=rel,
                observed_sha256=sha256_file(path),
                pinned_sha256=pins.get(PINNED_DIGEST_KEYS[name]),
                bytes=path.stat().st_size,
            )
        )
    return digests


_VALIDATOR: ModuleType | None = None


def load_validator(root: Path | None = None, *, require_pin: bool = True) -> ModuleType:
    """Import the seeded validator in place, refusing a drifted control.

    The module is loaded from its read-only path rather than copied, so this
    harness always tests the control that actually gates the repository.
    """
    global _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR
    base = root or repository_root()
    path = base / SEEDED_RELS["validator"]
    observed = sha256_file(path)
    pinned = task_input(base)["source_base"][PINNED_DIGEST_KEYS["validator"]]
    if require_pin and observed != pinned:
        raise SeededControlError(
            f"seeded validator drifted: observed {observed} != pinned {pinned}"
        )
    spec = importlib.util.spec_from_file_location("po03_seeded_validate_contracts", path)
    if spec is None or spec.loader is None:
        raise SeededControlError(f"cannot load seeded validator from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _VALIDATOR = module
    return module


def acceptance_contract(root: Path | None = None) -> tuple[dict[str, Any], str]:
    """The frozen acceptance contract and its observed digest."""
    base = root or repository_root()
    rel = task_input(base)["acceptance_contract"]["path"]
    path = base / rel
    return json.loads(path.read_text(encoding="utf-8")), sha256_file(path)
