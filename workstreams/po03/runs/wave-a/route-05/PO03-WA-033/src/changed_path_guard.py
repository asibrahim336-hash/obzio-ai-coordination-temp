#!/usr/bin/env python3
"""Changed-path guard for PO-03 route-scoped write allowlists.

The guard answers one question for a candidate changeset: is every changed
path contained in the declared write allowlist?  It is deliberately lexical
and repository-relative so it can run in a clean runtime before any commit,
with no third-party packages and no network.

Containment rules enforced here:

* Allowlist entries are directory prefixes (``a/b/``) or exact file paths.
  A directory prefix matches a path only at a path-component boundary, so
  ``runs/route-05/`` never matches ``runs/route-050/x``.
* Paths are normalised (``./`` collapsed, redundant separators removed)
  before comparison, so cosmetic spellings cannot smuggle a write past a
  prefix comparison.
* Absolute paths, Windows-style drive/UNC spellings, NUL bytes, and any
  path that escapes the repository root via ``..`` are rejected outright
  rather than normalised into something that happens to match. Escaping is
  a distinct verdict from "not in the allowlist" because the two failures
  have different operator remedies.
* An empty allowlist rejects everything; that is the fail-closed default.

Exit codes: 0 all paths admissible, 1 at least one rejection, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from dataclasses import dataclass, asdict
from typing import Iterable


VERDICT_ALLOWED = "ALLOWED"
VERDICT_REJECTED_NOT_IN_ALLOWLIST = "REJECTED_NOT_IN_ALLOWLIST"
VERDICT_REJECTED_ESCAPES_ROOT = "REJECTED_ESCAPES_ROOT"
VERDICT_REJECTED_ABSOLUTE = "REJECTED_ABSOLUTE_PATH"
VERDICT_REJECTED_MALFORMED = "REJECTED_MALFORMED_PATH"

REJECTING_VERDICTS = frozenset(
    {
        VERDICT_REJECTED_NOT_IN_ALLOWLIST,
        VERDICT_REJECTED_ESCAPES_ROOT,
        VERDICT_REJECTED_ABSOLUTE,
        VERDICT_REJECTED_MALFORMED,
    }
)


class AllowlistError(ValueError):
    """Raised when an allowlist entry is itself unusable."""


@dataclass(frozen=True)
class PathDecision:
    raw_path: str
    normalised_path: str | None
    verdict: str
    matched_rule: str | None
    reason: str

    def allowed(self) -> bool:
        return self.verdict == VERDICT_ALLOWED


def normalise_repo_path(raw: str) -> tuple[str | None, str, str]:
    """Return ``(normalised, verdict, reason)`` for one repository-relative path."""
    if raw is None or not raw.strip():
        return None, VERDICT_REJECTED_MALFORMED, "empty path"
    if "\x00" in raw:
        return None, VERDICT_REJECTED_MALFORMED, "NUL byte in path"

    candidate = raw.strip().replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("//"):
        return None, VERDICT_REJECTED_ABSOLUTE, "absolute POSIX path"
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        return None, VERDICT_REJECTED_ABSOLUTE, "drive-qualified path"

    normalised = posixpath.normpath(candidate)
    if normalised == "." or normalised == "":
        return None, VERDICT_REJECTED_MALFORMED, "path resolves to repository root"
    if normalised == ".." or normalised.startswith("../"):
        return None, VERDICT_REJECTED_ESCAPES_ROOT, "path escapes repository root"
    return normalised, VERDICT_ALLOWED, "normalised"


def normalise_allowlist_entry(raw: str) -> tuple[str, bool]:
    """Return ``(normalised_entry, is_directory_prefix)``."""
    if raw is None or not raw.strip():
        raise AllowlistError("empty allowlist entry")
    entry = raw.strip().replace("\\", "/")
    if entry.startswith("/"):
        raise AllowlistError(f"allowlist entry must be repository-relative: {raw!r}")
    # A trailing "/" or a trailing "/**" both mean "this directory subtree".
    is_prefix = entry.endswith("/") or entry.endswith("/**")
    if entry.endswith("/**"):
        entry = entry[: -len("/**")]
    normalised = posixpath.normpath(entry)
    if normalised in {".", "", ".."} or normalised.startswith("../"):
        raise AllowlistError(f"allowlist entry escapes repository root: {raw!r}")
    return normalised, is_prefix


def _is_within(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


class ChangedPathGuard:
    def __init__(self, allowlist: Iterable[str]) -> None:
        self._rules: list[tuple[str, bool, str]] = []
        for raw in allowlist:
            normalised, is_prefix = normalise_allowlist_entry(raw)
            self._rules.append((normalised, is_prefix, raw.strip()))

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def evaluate(self, raw_path: str) -> PathDecision:
        normalised, verdict, reason = normalise_repo_path(raw_path)
        if normalised is None:
            return PathDecision(raw_path, None, verdict, None, reason)

        for entry, is_prefix, original in self._rules:
            if is_prefix:
                if _is_within(normalised, entry):
                    return PathDecision(
                        raw_path, normalised, VERDICT_ALLOWED, original, "inside allowlisted subtree"
                    )
            elif normalised == entry:
                return PathDecision(
                    raw_path, normalised, VERDICT_ALLOWED, original, "exact allowlisted path"
                )

        return PathDecision(
            raw_path,
            normalised,
            VERDICT_REJECTED_NOT_IN_ALLOWLIST,
            None,
            "no allowlist rule covers this path",
        )

    def evaluate_all(self, paths: Iterable[str]) -> list[PathDecision]:
        return [self.evaluate(path) for path in paths]


def build_report(guard: ChangedPathGuard, paths: Iterable[str]) -> dict:
    decisions = guard.evaluate_all(paths)
    rejections = [d for d in decisions if not d.allowed()]
    return {
        "component": "changed_path_guard",
        "rule_count": guard.rule_count,
        "evaluated": len(decisions),
        "allowed": len(decisions) - len(rejections),
        "rejected": len(rejections),
        "admissible": not rejections,
        "decisions": [asdict(d) for d in decisions],
    }


def _read_lines(path: str) -> list[str]:
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    return [line for line in (raw.strip() for raw in text.splitlines()) if line and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject changed paths outside a write allowlist.")
    parser.add_argument("--allowlist-file", required=True, help="one allowlist entry per line")
    parser.add_argument("--changed-paths-file", required=True, help="one changed path per line, or '-' for stdin")
    parser.add_argument("--json", action="store_true", help="emit the full decision report as JSON")
    args = parser.parse_args(argv)

    try:
        guard = ChangedPathGuard(_read_lines(args.allowlist_file))
    except (AllowlistError, OSError) as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        paths = _read_lines(args.changed_paths_file)
    except OSError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    report = build_report(guard, paths)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for decision in report["decisions"]:
            marker = "ok  " if decision["verdict"] == VERDICT_ALLOWED else "FAIL"
            print(f"{marker} {decision['verdict']:<32} {decision['raw_path']}  ({decision['reason']})")
        print(
            f"summary: evaluated={report['evaluated']} allowed={report['allowed']} rejected={report['rejected']}"
        )
    return 0 if report["admissible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
