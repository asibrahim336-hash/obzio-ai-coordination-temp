#!/usr/bin/env python3
"""Symlink-aware write guard for a PO-03 owned subtree.

PO03-WA-033 answers containment lexically, on path strings.  That is not
enough on a real filesystem: a lexically owned path such as
``route-05/PO03-WA-034/out/note.txt`` can land anywhere on disk if any
component of it is a symlink.  This guard therefore resolves the write
target physically before admitting it.

Resolution strategy (the final component may legitimately not exist yet):

1. Reject the request lexically first, so a path that is not even nominally
   owned never reaches the filesystem.
2. Walk the ancestor chain from the owned root down to the deepest existing
   ancestor, resolving each component.  A symlinked *directory* component is
   the classic bypass and is caught here.
3. Resolve the deepest existing ancestor with ``os.path.realpath`` and
   require the result to stay inside the physically resolved owned root.
4. If the final component itself exists and is a symlink, resolve it and
   require its target to stay inside the owned root.  A dangling symlink is
   rejected: its target does not exist, so containment cannot be asserted.
5. Symlink cycles surface as ``ELOOP``/non-terminating resolution and are
   reported as their own verdict rather than as a generic error.

The owned root itself is resolved once, so a guard rooted on a symlinked
directory still compares like with like.

Exit codes: 0 admissible, 1 at least one rejection, 2 usage error.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import Iterable


VERDICT_ALLOWED = "ALLOWED"
VERDICT_REJECTED_OUTSIDE_ROOT_LEXICAL = "REJECTED_OUTSIDE_ROOT_LEXICAL"
VERDICT_REJECTED_SYMLINK_ESCAPE = "REJECTED_SYMLINK_ESCAPE"
VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE = "REJECTED_ANCESTOR_SYMLINK_ESCAPE"
VERDICT_REJECTED_DANGLING_SYMLINK = "REJECTED_DANGLING_SYMLINK"
VERDICT_REJECTED_SYMLINK_LOOP = "REJECTED_SYMLINK_LOOP"

MAX_LINK_DEPTH = 40


@dataclass(frozen=True)
class WriteDecision:
    requested_path: str
    resolved_path: str | None
    verdict: str
    reason: str
    symlink_components: tuple[str, ...] = ()

    def allowed(self) -> bool:
        return self.verdict == VERDICT_ALLOWED


class SymlinkResolutionGuard:
    def __init__(self, owned_root: str) -> None:
        absolute_root = os.path.abspath(owned_root)
        if not os.path.isdir(absolute_root):
            raise ValueError(f"owned root is not an existing directory: {owned_root}")
        # Resolve once so a guard rooted on a symlinked directory is still sound.
        self._root = os.path.realpath(absolute_root)

    @property
    def root(self) -> str:
        return self._root

    def _contains(self, resolved: str) -> bool:
        return resolved == self._root or resolved.startswith(self._root + os.sep)

    def _resolve_chain(self, path: str) -> str:
        """Resolve ``path`` one link at a time so loops are detectable."""
        seen = 0
        current = path
        while os.path.islink(current):
            seen += 1
            if seen > MAX_LINK_DEPTH:
                raise OSError(errno.ELOOP, "too many levels of symbolic links", current)
            target = os.readlink(current)
            current = target if os.path.isabs(target) else os.path.join(os.path.dirname(current), target)
            current = os.path.normpath(current)
        return current

    def evaluate(self, requested_path: str) -> WriteDecision:
        candidate = os.path.normpath(os.path.join(self._root, requested_path))

        # Step 1 - lexical gate before touching the filesystem.
        if not (candidate == self._root or candidate.startswith(self._root + os.sep)):
            return WriteDecision(
                requested_path,
                None,
                VERDICT_REJECTED_OUTSIDE_ROOT_LEXICAL,
                "path leaves the owned root before any filesystem access",
            )

        # Step 2 - inspect every component under the root for symlinks.
        symlinked: list[str] = []
        relative = os.path.relpath(candidate, self._root)
        parts = [] if relative == "." else relative.split(os.sep)
        walked = self._root
        for index, part in enumerate(parts):
            walked = os.path.join(walked, part)
            is_final = index == len(parts) - 1
            if not os.path.lexists(walked):
                # Nothing further exists; the deepest existing ancestor governs.
                break
            if os.path.islink(walked):
                symlinked.append(os.path.relpath(walked, self._root))
                try:
                    resolved_link = self._resolve_chain(walked)
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        return WriteDecision(
                            requested_path,
                            None,
                            VERDICT_REJECTED_SYMLINK_LOOP,
                            f"symlink loop at {os.path.relpath(walked, self._root)}",
                            tuple(symlinked),
                        )
                    raise
                if not os.path.exists(resolved_link):
                    return WriteDecision(
                        requested_path,
                        None,
                        VERDICT_REJECTED_DANGLING_SYMLINK,
                        f"dangling symlink at {os.path.relpath(walked, self._root)}; containment unprovable",
                        tuple(symlinked),
                    )
                real_link = os.path.realpath(walked)
                if not self._contains(real_link):
                    verdict = (
                        VERDICT_REJECTED_SYMLINK_ESCAPE
                        if is_final
                        else VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE
                    )
                    return WriteDecision(
                        requested_path,
                        real_link,
                        verdict,
                        f"symlink component {os.path.relpath(walked, self._root)!r} resolves outside the owned root",
                        tuple(symlinked),
                    )

        # Step 3 - deepest existing ancestor must physically live under the root.
        probe = candidate
        while not os.path.lexists(probe) and probe != self._root:
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        try:
            resolved_ancestor = os.path.realpath(probe)
        except OSError as exc:  # pragma: no cover - defensive
            if exc.errno == errno.ELOOP:
                return WriteDecision(
                    requested_path, None, VERDICT_REJECTED_SYMLINK_LOOP, str(exc), tuple(symlinked)
                )
            raise
        if not self._contains(resolved_ancestor):
            return WriteDecision(
                requested_path,
                resolved_ancestor,
                VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE,
                "deepest existing ancestor resolves outside the owned root",
                tuple(symlinked),
            )

        remainder = os.path.relpath(candidate, probe)
        resolved = resolved_ancestor if remainder == "." else os.path.normpath(
            os.path.join(resolved_ancestor, remainder)
        )
        if not self._contains(resolved):
            return WriteDecision(
                requested_path,
                resolved,
                VERDICT_REJECTED_SYMLINK_ESCAPE,
                "resolved target lies outside the owned root",
                tuple(symlinked),
            )
        return WriteDecision(
            requested_path,
            resolved,
            VERDICT_ALLOWED,
            "resolved target is physically inside the owned root",
            tuple(symlinked),
        )

    def open_for_write(self, requested_path: str, data: bytes) -> str:
        """Write only after the guard admits the physically resolved target."""
        decision = self.evaluate(requested_path)
        if not decision.allowed():
            raise PermissionError(f"{decision.verdict}: {decision.reason}")
        assert decision.resolved_path is not None
        os.makedirs(os.path.dirname(decision.resolved_path), exist_ok=True)
        # O_NOFOLLOW closes the residual window on the final component.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(decision.resolved_path, flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return decision.resolved_path


def build_report(guard: SymlinkResolutionGuard, paths: Iterable[str]) -> dict:
    decisions = [guard.evaluate(path) for path in paths]
    rejections = [d for d in decisions if not d.allowed()]
    return {
        "component": "symlink_resolution_guard",
        "owned_root": guard.root,
        "evaluated": len(decisions),
        "allowed": len(decisions) - len(rejections),
        "rejected": len(rejections),
        "admissible": not rejections,
        "decisions": [{**asdict(d), "symlink_components": list(d.symlink_components)} for d in decisions],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject writes that escape an owned subtree via symlinks.")
    parser.add_argument("--owned-root", required=True)
    parser.add_argument("paths", nargs="+", help="paths relative to the owned root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        guard = SymlinkResolutionGuard(args.owned_root)
    except ValueError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2
    report = build_report(guard, args.paths)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for decision in report["decisions"]:
            marker = "ok  " if decision["verdict"] == VERDICT_ALLOWED else "FAIL"
            print(f"{marker} {decision['verdict']:<38} {decision['requested_path']}  ({decision['reason']})")
    return 0 if report["admissible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
