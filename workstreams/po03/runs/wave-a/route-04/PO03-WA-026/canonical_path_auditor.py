#!/usr/bin/env python3
"""Canonicalize manifest paths before duplicate and coverage decisions."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


SEPARATOR_ALIASES = {"\\": "/", "\u2044": "/", "\u2215": "/", "\uff0f": "/"}
DRIVE = re.compile(r"^[A-Za-z]:")


class UnsafePath(ValueError):
    pass


def canonicalize(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise UnsafePath("empty_or_nul")
    decoded = unquote(raw, errors="strict")
    normalized = unicodedata.normalize("NFKC", decoded)
    for source, target in SEPARATOR_ALIASES.items():
        normalized = normalized.replace(source, target)
    if normalized.startswith("/") or DRIVE.match(normalized):
        raise UnsafePath("absolute_or_drive_path")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise UnsafePath("repository_escape")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise UnsafePath("empty_after_normalization")
    return "/".join(parts)


def audit_paths(claimed: Iterable[Any], actual: Iterable[Any] | None = None) -> dict[str, Any]:
    defects: list[dict[str, Any]] = []
    canonical_claims: dict[str, str] = {}
    for index, raw in enumerate(claimed):
        try:
            canonical = canonicalize(raw)
        except (UnsafePath, UnicodeError) as error:
            defects.append({"code": "UNSAFE_PATH", "index": index, "path": raw, "reason": str(error)})
            continue
        prior = canonical_claims.get(canonical)
        if prior is not None:
            defects.append(
                {
                    "code": "CANONICAL_ALIAS_DUPLICATE",
                    "canonical": canonical,
                    "first": prior,
                    "duplicate": raw,
                }
            )
        else:
            canonical_claims[canonical] = raw

    omissions: list[str] = []
    undeclared: list[str] = []
    if actual is not None:
        canonical_actual: set[str] = set()
        for index, raw in enumerate(actual):
            try:
                canonical_actual.add(canonicalize(raw))
            except (UnsafePath, UnicodeError) as error:
                defects.append(
                    {"code": "UNSAFE_ACTUAL_PATH", "index": index, "path": raw, "reason": str(error)}
                )
        omissions = sorted(set(canonical_claims) - canonical_actual)
        undeclared = sorted(canonical_actual - set(canonical_claims))
        defects.extend({"code": "MANIFEST_OMISSION", "path": path} for path in omissions)
        defects.extend({"code": "UNDECLARED_PACK_FILE", "path": path} for path in undeclared)

    return {
        "canonical_paths": sorted(canonical_claims),
        "omissions": omissions,
        "undeclared": undeclared,
        "defects": defects,
        "disposition": "PASS" if canonical_claims and not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = audit_paths(entry.get("path") for entry in manifest.get("artifacts", []))
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
