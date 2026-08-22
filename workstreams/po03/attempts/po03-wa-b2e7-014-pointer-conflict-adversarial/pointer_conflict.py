#!/usr/bin/env python3
"""Detect conflicting and dangling "current pointer" claims instead of last-writer-wins.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-014-pointer-conflict-adversarial):
    Two pointers claiming currentness for the same function is a
    detectable conflict rather than a silent last-writer-wins.

This module is intentionally self-contained (it does not import unit
po03-wa-b2e7-009's compiler) so it can be evaluated independently. It
implements two resolution strategies over a set of candidate JSON
documents, each representing one "pointer" file:

  - `naive_current_candidates`: an UNSAFE heuristic that treats any
    candidate whose `status` field contains a needle like "CURRENT" as a
    current claim. This is deliberately naive so its failure mode can be
    measured against real data.
  - `resolve_authoritative`: a SAFE resolver that requires exactly one
    candidate to carry a specific marker field/value (e.g.
    `alias_id == "OBZIO-ACTIVE-CONTROL-POINTER-CURRENT"`). Zero matches
    or more than one match both raise `PointerConflictError` -- the
    resolver refuses to emit a route rather than guessing (e.g. via
    last-writer-wins on file mtime or lexicographic filename order).
  - `resolve_target_exists`: verifies a resolved candidate's referenced
    target path actually exists; a missing target (dangling pointer)
    also raises `PointerConflictError`.
  - `compare_fields`: raises `PointerConflictError` if two documents that
    are both supposed to describe "the same current state" disagree on
    any of a named set of fields (models the real
    ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json vs
    ACTIVE_INSTRUCTION_STACK.json five-key consistency check).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class PointerConflictError(Exception):
    """Raised when currentness cannot be safely resolved: refuse, don't guess."""


def load_candidates(paths: list[Path]) -> list[dict[str, Any]]:
    candidates = []
    for path in paths:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PointerConflictError(f"unreadable/invalid candidate {path}: {exc}") from exc
        candidates.append({"path": str(path), "doc": doc})
    return candidates


def naive_current_candidates(candidates: list[dict[str, Any]], needle: str = "CURRENT") -> list[dict[str, Any]]:
    """UNSAFE by design: string-matches the `status` field. Used only to
    measure how badly a naive filename/status heuristic fails on real
    data; never used as the actual resolution path."""
    return [c for c in candidates if needle in str(c["doc"].get("status", ""))]


def resolve_authoritative(
    candidates: list[dict[str, Any]],
    marker_field: str = "alias_id",
    marker_value: str = "",
) -> dict[str, Any]:
    matches = [c for c in candidates if c["doc"].get(marker_field) == marker_value]
    if len(matches) == 0:
        raise PointerConflictError(
            f"no candidate carries {marker_field}={marker_value!r}: nothing to route to (refuse, do not guess)"
        )
    if len(matches) > 1:
        conflicting = [c["path"] for c in matches]
        raise PointerConflictError(
            f"{len(matches)} candidates carry {marker_field}={marker_value!r}: conflict, refuse to pick one: {conflicting}"
        )
    return matches[0]


def _dig(doc: Any, dotted_path: str) -> Any:
    node = doc
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve_target_exists(repo_root: Path, candidate: dict[str, Any], target_field_path: str) -> str:
    target = _dig(candidate["doc"], target_field_path)
    if not isinstance(target, str):
        raise PointerConflictError(
            f"{candidate['path']}: field {target_field_path!r} does not name a target path (dangling)"
        )
    if not (Path(repo_root) / target).is_file():
        raise PointerConflictError(f"{candidate['path']}: target {target!r} does not exist on disk (dangling pointer)")
    return target


def compare_fields(doc_a: dict[str, Any], doc_b: dict[str, Any], fields: list[str], label_a: str, label_b: str) -> None:
    mismatches = [f for f in fields if doc_a.get(f) != doc_b.get(f)]
    if mismatches:
        raise PointerConflictError(
            f"{label_a} and {label_b} disagree on {mismatches}: "
            f"{[(f, doc_a.get(f), doc_b.get(f)) for f in mismatches]}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--candidate", action="append", dest="candidates", required=True)
    parser.add_argument("--marker-field", default="alias_id")
    parser.add_argument("--marker-value", default="")
    parser.add_argument("--target-field-path", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    try:
        candidates = load_candidates([repo_root / c for c in args.candidates])
        winner = resolve_authoritative(candidates, args.marker_field, args.marker_value)
        result: dict[str, Any] = {"status": "RESOLVED", "winner": winner["path"]}
        if args.target_field_path:
            result["target"] = resolve_target_exists(repo_root, winner, args.target_field_path)
    except PointerConflictError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
