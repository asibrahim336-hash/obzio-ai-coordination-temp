#!/usr/bin/env python3
"""Rename admissibility guard: both endpoints of a rename are checked.

A rename is two path facts wearing one entry in a changeset.  A guard that
inspects only the destination admits ``control/outbox.jsonl -> route-05/x``
(capture of unowned evidence); a guard that inspects only the source admits
``route-05/x -> control/outbox.jsonl`` (escape into a shared path).  Both
are ownership violations, and this component classifies them separately
because they have different remedies.

Admissibility matrix, given an ownership predicate over paths:

    source owned, destination owned      -> ALLOWED
    source owned, destination not owned  -> REJECTED_DESTINATION_NOT_OWNED
    source not owned, destination owned  -> REJECTED_SOURCE_NOT_OWNED
    neither owned                        -> REJECTED_BOTH_ENDPOINTS_NOT_OWNED

Two further facts are surfaced rather than silently folded into the matrix:

* A rename whose source is owned and whose destination is not is also an
  *evidence removal* from the owned subtree, flagged as
  ``evidence_leaves_subtree`` so a reviewer sees the deletion semantics.
* A case-only rename (``A.md -> a.md``) is flagged ``case_only`` because it
  is a no-op on case-insensitive filesystems and needs a two-step rename.

The parsers accept the two NUL-delimited git spellings that actually carry
rename records, so the guard can be fed real repository output rather than
hand-written fixtures:

* ``git diff --name-status -z``   -> ``Rnnn\\0old\\0new\\0``
* ``git status --porcelain=v1 -z`` -> ``R  \\0new\\0old\\0`` (index order)

Exit codes: 0 all renames admissible, 1 at least one rejection, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from dataclasses import dataclass, asdict, field
from typing import Callable, Iterable, Sequence


VERDICT_ALLOWED = "ALLOWED"
VERDICT_REJECTED_SOURCE_NOT_OWNED = "REJECTED_SOURCE_NOT_OWNED"
VERDICT_REJECTED_DESTINATION_NOT_OWNED = "REJECTED_DESTINATION_NOT_OWNED"
VERDICT_REJECTED_BOTH_ENDPOINTS_NOT_OWNED = "REJECTED_BOTH_ENDPOINTS_NOT_OWNED"


class RenameParseError(ValueError):
    """Raised when a rename record cannot be parsed unambiguously."""


@dataclass(frozen=True)
class RenameRecord:
    source: str
    destination: str
    similarity: int | None = None


@dataclass(frozen=True)
class RenameDecision:
    source: str
    destination: str
    source_owned: bool
    destination_owned: bool
    verdict: str
    reason: str
    flags: tuple[str, ...] = field(default=())

    def allowed(self) -> bool:
        return self.verdict == VERDICT_ALLOWED


def _normalise(path: str) -> str:
    return posixpath.normpath(path.strip().replace("\\", "/"))


def subtree_ownership(owned_prefixes: Sequence[str]) -> Callable[[str], bool]:
    """Build an ownership predicate from directory prefixes."""
    normalised: list[str] = []
    for prefix in owned_prefixes:
        entry = prefix.strip().replace("\\", "/")
        if entry.endswith("/**"):
            entry = entry[: -len("/**")]
        entry = posixpath.normpath(entry)
        if entry in {".", "", ".."} or entry.startswith("../"):
            raise ValueError(f"unusable owned prefix: {prefix!r}")
        normalised.append(entry)

    def owns(path: str) -> bool:
        candidate = _normalise(path)
        if candidate.startswith("../") or candidate == "..":
            return False
        return any(candidate == entry or candidate.startswith(entry + "/") for entry in normalised)

    return owns


class RenameGuard:
    def __init__(self, owns: Callable[[str], bool]) -> None:
        self._owns = owns

    def evaluate(self, record: RenameRecord) -> RenameDecision:
        source = _normalise(record.source)
        destination = _normalise(record.destination)
        source_owned = self._owns(source)
        destination_owned = self._owns(destination)

        flags: list[str] = []
        if source != destination and source.lower() == destination.lower():
            flags.append("case_only")
        if source == destination:
            flags.append("no_op")

        if source_owned and destination_owned:
            verdict = VERDICT_ALLOWED
            reason = "both endpoints are inside the owned subtree"
        elif source_owned and not destination_owned:
            verdict = VERDICT_REJECTED_DESTINATION_NOT_OWNED
            reason = "rename would move an owned artifact out of the owned subtree"
            flags.append("evidence_leaves_subtree")
        elif not source_owned and destination_owned:
            verdict = VERDICT_REJECTED_SOURCE_NOT_OWNED
            reason = "rename would capture an unowned path into the owned subtree"
            flags.append("unowned_source_removed")
        else:
            verdict = VERDICT_REJECTED_BOTH_ENDPOINTS_NOT_OWNED
            reason = "neither endpoint is inside the owned subtree"

        return RenameDecision(
            source, destination, source_owned, destination_owned, verdict, reason, tuple(flags)
        )

    def evaluate_all(self, records: Iterable[RenameRecord]) -> list[RenameDecision]:
        return [self.evaluate(record) for record in records]


def parse_diff_name_status_z(payload: str) -> list[RenameRecord]:
    """Parse ``git diff --name-status -z`` output, keeping only rename/copy records."""
    fields = [f for f in payload.split("\x00")]
    if fields and fields[-1] == "":
        fields.pop()
    records: list[RenameRecord] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        if not status:
            index += 1
            continue
        code = status[0]
        if code in {"R", "C"}:
            if index + 2 >= len(fields):
                raise RenameParseError(f"truncated rename record at field {index}: {status!r}")
            similarity = int(status[1:]) if status[1:].isdigit() else None
            records.append(RenameRecord(fields[index + 1], fields[index + 2], similarity))
            index += 3
        else:
            if index + 1 >= len(fields):
                raise RenameParseError(f"truncated status record at field {index}: {status!r}")
            index += 2
    return records


def parse_status_porcelain_z(payload: str) -> list[RenameRecord]:
    """Parse ``git status --porcelain=v1 -z``; rename entries list new then old."""
    fields = [f for f in payload.split("\x00")]
    if fields and fields[-1] == "":
        fields.pop()
    records: list[RenameRecord] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        if len(entry) < 4:
            raise RenameParseError(f"malformed porcelain entry: {entry!r}")
        xy, new_path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            if index + 1 >= len(fields):
                raise RenameParseError(f"rename entry without source path: {entry!r}")
            records.append(RenameRecord(fields[index + 1], new_path, None))
            index += 2
        else:
            index += 1
    return records


def build_report(guard: RenameGuard, records: Iterable[RenameRecord]) -> dict:
    decisions = guard.evaluate_all(records)
    rejections = [d for d in decisions if not d.allowed()]
    return {
        "component": "rename_guard",
        "evaluated": len(decisions),
        "allowed": len(decisions) - len(rejections),
        "rejected": len(rejections),
        "admissible": not rejections,
        "decisions": [{**asdict(d), "flags": list(d.flags)} for d in decisions],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check both endpoints of every rename against ownership.")
    parser.add_argument("--owned-prefix", action="append", required=True)
    parser.add_argument(
        "--format",
        choices=("diff-name-status-z", "status-porcelain-z"),
        default="diff-name-status-z",
    )
    parser.add_argument("--input", default="-", help="file containing the NUL-delimited payload, or '-'")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        owns = subtree_ownership(args.owned_prefix)
    except (OSError, ValueError) as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        parse = (
            parse_diff_name_status_z if args.format == "diff-name-status-z" else parse_status_porcelain_z
        )
        records = parse(payload)
    except RenameParseError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    report = build_report(RenameGuard(owns), records)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for decision in report["decisions"]:
            marker = "ok  " if decision["verdict"] == VERDICT_ALLOWED else "FAIL"
            print(
                f"{marker} {decision['verdict']:<38} {decision['source']} -> {decision['destination']}"
                f"  ({decision['reason']})"
            )
        print(f"summary: evaluated={report['evaluated']} rejected={report['rejected']}")
    return 0 if report["admissible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
