#!/usr/bin/env python3
"""Ownership arbiter that makes concurrent-writer collisions loud.

Wave A runs several route workers at once against one repository.  The
protective claim is that their owned subtrees are disjoint, so they cannot
interfere.  This component tests that claim at two moments:

Static, before any write
    ``detect_claim_overlaps`` compares declared prefix claims pairwise.
    Nesting counts as overlap: a claim on ``a/b`` and a claim on ``a/b/c``
    are not disjoint, even though neither string is a prefix of the other in
    the naive sense of equality.

Dynamic, at the moment of writing
    ``ArbitratedWriter.write`` refuses any target outside the writer's own
    claim, and creates the target with ``O_CREAT | O_EXCL``.  Exclusive
    creation is what converts a race into a verdict: the loser of the race
    gets ``FileExistsError``, which is reported as ``COLLISION_DETECTED``
    instead of silently overwriting the winner's bytes.  Default filesystem
    semantics do the opposite - last writer wins, with no signal at all.

Bytes are written to a per-writer temporary file and then linked into place,
so a reader never observes a partially written artifact, and the exclusive
creation and the content commit are the same event.

Exit codes: 0 claims disjoint, 1 overlaps detected, 2 usage error.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import posixpath
import sys
import tempfile
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Sequence


OUTCOME_WRITTEN = "WRITTEN"
OUTCOME_COLLISION = "COLLISION_DETECTED"
OUTCOME_OUT_OF_CLAIM = "REJECTED_OUT_OF_CLAIM"
OUTCOME_UNCLAIMED_WRITER = "REJECTED_UNKNOWN_WRITER"

OVERLAP_IDENTICAL = "IDENTICAL_CLAIM"
OVERLAP_NESTED = "NESTED_CLAIM"


class ArbiterError(ValueError):
    """Raised when claims or writers are configured unusably."""


@dataclass(frozen=True)
class Claim:
    writer_id: str
    prefix: str


@dataclass(frozen=True)
class ClaimOverlap:
    writer_a: str
    writer_b: str
    prefix_a: str
    prefix_b: str
    kind: str
    detail: str


@dataclass(frozen=True)
class WriteOutcome:
    writer_id: str
    path: str
    outcome: str
    detail: str

    def succeeded(self) -> bool:
        return self.outcome == OUTCOME_WRITTEN


def normalise_prefix(prefix: str) -> str:
    entry = prefix.strip().replace("\\", "/")
    if entry.endswith("/**"):
        entry = entry[: -len("/**")]
    normalised = posixpath.normpath(entry)
    if normalised in {".", "", ".."} or normalised.startswith("../") or posixpath.isabs(normalised):
        raise ArbiterError(f"unusable claim prefix: {prefix!r}")
    return normalised


def _covers(prefix: str, path: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def detect_claim_overlaps(claims: Sequence[Claim]) -> list[ClaimOverlap]:
    """Pairwise disjointness check over declared claims."""
    normalised = [(c, normalise_prefix(c.prefix)) for c in claims]
    overlaps: list[ClaimOverlap] = []
    for i in range(len(normalised)):
        for j in range(i + 1, len(normalised)):
            (claim_a, prefix_a), (claim_b, prefix_b) = normalised[i], normalised[j]
            if claim_a.writer_id == claim_b.writer_id:
                continue
            if prefix_a == prefix_b:
                kind, detail = OVERLAP_IDENTICAL, "two writers claim the same subtree"
            elif _covers(prefix_a, prefix_b):
                kind, detail = OVERLAP_NESTED, f"{prefix_b} is nested inside {prefix_a}"
            elif _covers(prefix_b, prefix_a):
                kind, detail = OVERLAP_NESTED, f"{prefix_a} is nested inside {prefix_b}"
            else:
                continue
            overlaps.append(
                ClaimOverlap(claim_a.writer_id, claim_b.writer_id, prefix_a, prefix_b, kind, detail)
            )
    return overlaps


class ArbitratedWriter:
    """Enforces claims at write time and turns races into explicit verdicts."""

    def __init__(self, root: Path, claims: Iterable[Claim], allow_overlapping_claims: bool = False) -> None:
        self._root = Path(root)
        self._claims: dict[str, str] = {}
        claim_list = list(claims)
        overlaps = detect_claim_overlaps(claim_list)
        if overlaps and not allow_overlapping_claims:
            raise ArbiterError(
                "claims are not disjoint: " + "; ".join(f"{o.writer_a}~{o.writer_b}:{o.kind}" for o in overlaps)
            )
        for claim in claim_list:
            if claim.writer_id in self._claims:
                raise ArbiterError(f"writer {claim.writer_id} declared more than one claim")
            self._claims[claim.writer_id] = normalise_prefix(claim.prefix)
        self._lock = threading.Lock()
        self._journal: list[WriteOutcome] = []

    @property
    def journal(self) -> list[WriteOutcome]:
        with self._lock:
            return list(self._journal)

    def _record(self, outcome: WriteOutcome) -> WriteOutcome:
        with self._lock:
            self._journal.append(outcome)
        return outcome

    def write(self, writer_id: str, relative_path: str, payload: bytes) -> WriteOutcome:
        prefix = self._claims.get(writer_id)
        if prefix is None:
            return self._record(
                WriteOutcome(writer_id, relative_path, OUTCOME_UNCLAIMED_WRITER, "writer holds no claim")
            )

        candidate = posixpath.normpath(relative_path.replace("\\", "/"))
        if not _covers(prefix, candidate):
            return self._record(
                WriteOutcome(
                    writer_id, relative_path, OUTCOME_OUT_OF_CLAIM,
                    f"{candidate} is outside claim {prefix}",
                )
            )

        target = self._root / candidate
        target.parent.mkdir(parents=True, exist_ok=True)

        # Stage in a sibling temp file so the exclusive link is the only
        # moment at which the artifact becomes visible.
        fd, staged = tempfile.mkstemp(dir=str(target.parent), prefix=".po03-stage-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            try:
                os.link(staged, target)
            except FileExistsError:
                return self._record(
                    WriteOutcome(
                        writer_id, candidate, OUTCOME_COLLISION,
                        "target already exists; exclusive create refused to overwrite",
                    )
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    return self._record(
                        WriteOutcome(writer_id, candidate, OUTCOME_COLLISION, "exclusive create refused")
                    )
                raise
        finally:
            if os.path.exists(staged):
                os.unlink(staged)

        return self._record(WriteOutcome(writer_id, candidate, OUTCOME_WRITTEN, "exclusive create succeeded"))


def build_report(claims: Sequence[Claim]) -> dict:
    overlaps = detect_claim_overlaps(claims)
    return {
        "component": "disjoint_writer_arbiter",
        "claims": [asdict(c) for c in claims],
        "overlap_count": len(overlaps),
        "disjoint": not overlaps,
        "overlaps": [asdict(o) for o in overlaps],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that declared writer claims are disjoint.")
    parser.add_argument(
        "--claim",
        action="append",
        required=True,
        metavar="WRITER_ID=PREFIX",
        help="repeatable writer claim",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    claims: list[Claim] = []
    for raw in args.claim:
        if "=" not in raw:
            print(f"USAGE_ERROR: claim must be WRITER_ID=PREFIX, got {raw!r}", file=sys.stderr)
            return 2
        writer_id, prefix = raw.split("=", 1)
        claims.append(Claim(writer_id.strip(), prefix.strip()))
    try:
        report = build_report(claims)
    except ArbiterError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for overlap in report["overlaps"]:
            print(
                f"FAIL {overlap['kind']:<18} {overlap['writer_a']} ({overlap['prefix_a']}) "
                f"~ {overlap['writer_b']} ({overlap['prefix_b']}): {overlap['detail']}"
            )
        print(f"summary: claims={len(claims)} overlaps={report['overlap_count']} disjoint={report['disjoint']}")
    return 0 if report["disjoint"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
