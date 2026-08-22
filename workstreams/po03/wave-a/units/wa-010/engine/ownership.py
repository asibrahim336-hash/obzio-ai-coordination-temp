#!/usr/bin/env python3
"""Changed-path ownership enforcement for PO-03 subordinate writers.

Hypothesis H-PO03-WA-010 states that ownership grants plus deny globs can
prevent overlapping subordinate writes *before* commit.  This module is the
executable form of that claim.  It answers two separate questions:

1. Static overlap: can two ownership grants ever name the same path?  This is
   decided from the patterns alone by :mod:`gitglob`, so a colliding pair of
   grants is reported before any subordinate has written a byte.
2. Per-change admission: is this specific writer allowed to add, modify, delete
   or rename this specific path?  A deny glob outranks an ownership grant, a
   rename is checked on both sides, and a writer holding a stale fence token is
   refused even when the path is inside its own subtree.

The module has no third-party dependencies and no network or filesystem
side-effects beyond reading the documents it is given, so it runs in a clean
clone and inside CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gitglob import (  # type: ignore[no-redef]
        GlobSyntaxError,
        PathGlob,
        PathSyntaxError,
        compile_globs,
        first_match,
        is_nfc,
        normalize_path,
    )
else:  # pragma: no cover - package-relative import is not used by the tests
    from .gitglob import (
        GlobSyntaxError,
        PathGlob,
        PathSyntaxError,
        compile_globs,
        first_match,
        is_nfc,
        normalize_path,
    )


ALLOW = "ALLOW"
DENY = "DENY"

REASON_ALLOWED = "ALLOWED"
REASON_MALFORMED_PATH = "DENY_MALFORMED_PATH"
REASON_PROHIBITED_PATH = "DENY_PROHIBITED_PATH"
REASON_READ_ONLY_PATH = "DENY_READ_ONLY_PATH"
REASON_FOREIGN_OWNER = "DENY_FOREIGN_OWNER"
REASON_UNOWNED_PATH = "DENY_UNOWNED_PATH"
REASON_RENAME_SOURCE_NOT_OWNED = "DENY_RENAME_SOURCE_NOT_OWNED"
REASON_RENAME_TARGET_NOT_OWNED = "DENY_RENAME_TARGET_NOT_OWNED"
REASON_DELETE_NOT_OWNED = "DENY_DELETE_NOT_OWNED"
REASON_STALE_FENCE = "DENY_STALE_FENCE"
REASON_FENCE_AHEAD = "DENY_FENCE_AHEAD_OF_REGISTRY"
REASON_UNKNOWN_WRITER = "DENY_UNKNOWN_WRITER"
REASON_SHARED_WORKTREE = "DENY_SHARED_WORKTREE"
REASON_UNKNOWN_STATUS = "DENY_UNKNOWN_STATUS"
REASON_MISSING_RENAME_SOURCE = "DENY_MISSING_RENAME_SOURCE"

ADD = "ADD"
MODIFY = "MODIFY"
DELETE = "DELETE"
RENAME = "RENAME"
COPY = "COPY"
TYPECHANGE = "TYPECHANGE"

# git --name-status letters.  'U' (unmerged) and 'X' (unknown) are deliberately
# absent: a writer must not commit an unresolved or unclassified change.
_GIT_STATUS_LETTERS = {
    "A": ADD,
    "M": MODIFY,
    "D": DELETE,
    "R": RENAME,
    "C": COPY,
    "T": TYPECHANGE,
}

# Paths that no writer may ever touch, independently of the ownership document.
IMPLICIT_DENY_GLOBS = (
    ".git/**",
    "**/.git/**",
    "**/.gitmodules",
)

_ISOLATION_REQUIRED_WRITE_MODES = frozenset(
    {"BEST_OF_N_ISOLATED_WORKTREE_ONLY", "ISOLATED_BRANCH_ONLY"}
)


class OwnershipDocumentError(ValueError):
    """Raised when an ownership document cannot be interpreted."""


@dataclass(frozen=True)
class Change:
    """One changed path as reported by git, normalised to a write intent."""

    status: str
    path: str | None
    old_path: str | None = None
    similarity: int | None = None

    @property
    def target(self) -> str | None:
        """Path created or rewritten by this change."""
        if self.status in (ADD, MODIFY, TYPECHANGE, RENAME, COPY):
            return self.path
        return None

    @property
    def source(self) -> str | None:
        """Path removed by this change."""
        if self.status == DELETE:
            return self.path
        if self.status == RENAME:
            return self.old_path
        return None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "path": self.path}
        if self.old_path is not None:
            payload["old_path"] = self.old_path
        if self.similarity is not None:
            payload["similarity"] = self.similarity
        return payload


@dataclass(frozen=True)
class Owner:
    owner_id: str
    task_id: str
    role: str
    fence_token: int
    write_mode: str
    owned_globs: tuple[PathGlob, ...]
    read_only_globs: tuple[PathGlob, ...] = ()
    attempt_id: str | None = None

    def owns(self, segments: tuple[str, ...]) -> PathGlob | None:
        return first_match(self.owned_globs, segments)


@dataclass(frozen=True)
class Decision:
    change: Change
    side: str
    path: str | None
    decision: str
    reason: str
    detail: str
    matched_glob: str | None = None
    conflicting_owner: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "change": self.change.to_dict(),
            "side": self.side,
            "path": self.path,
            "decision": self.decision,
            "reason": self.reason,
            "detail": self.detail,
            "matched_glob": self.matched_glob,
            "conflicting_owner": self.conflicting_owner,
        }


@dataclass
class EnforcementReport:
    owner_id: str
    declared_fence: int | None
    isolated_worktree: bool
    decisions: list[Decision] = field(default_factory=list)

    @property
    def denials(self) -> list[Decision]:
        return [decision for decision in self.decisions if not decision.allowed]

    @property
    def blocked(self) -> bool:
        return bool(self.denials)

    @property
    def outcome(self) -> str:
        return "BLOCKED" if self.blocked else "ADMITTED"

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.reason] = counts.get(decision.reason, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "declared_fence": self.declared_fence,
            "isolated_worktree": self.isolated_worktree,
            "outcome": self.outcome,
            "checked_sides": len(self.decisions),
            "denied_sides": len(self.denials),
            "reason_counts": self.reason_counts(),
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str
    detail: str
    left_owner: str | None = None
    left_glob: str | None = None
    right_owner: str | None = None
    right_glob: str | None = None
    witness_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "left_owner": self.left_owner,
            "left_glob": self.left_glob,
            "right_owner": self.right_owner,
            "right_glob": self.right_glob,
            "witness_path": self.witness_path,
        }


class OwnershipEngine:
    """Decides static grant overlap and per-change write admission."""

    def __init__(
        self,
        owners: Sequence[Owner],
        deny_globs: Sequence[PathGlob] = (),
        *,
        include_implicit_deny: bool = True,
        source_document: str | None = None,
    ) -> None:
        seen: set[str] = set()
        for owner in owners:
            if owner.owner_id in seen:
                raise OwnershipDocumentError(f"duplicate owner id {owner.owner_id!r}")
            seen.add(owner.owner_id)
        self.owners = tuple(owners)
        self.declared_deny_globs = tuple(deny_globs)
        self.implicit_deny_globs = (
            compile_globs(IMPLICIT_DENY_GLOBS) if include_implicit_deny else ()
        )
        self.deny_globs = self.declared_deny_globs + self.implicit_deny_globs
        self.source_document = source_document
        self.task_input_lease_id: str | None = None
        self.task_input_write_globs: tuple[PathGlob, ...] | None = None
        self._by_id = {owner.owner_id: owner for owner in self.owners}

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_ownership_document(
        cls, document: dict[str, Any], *, source_document: str | None = None
    ) -> "OwnershipEngine":
        if not isinstance(document, dict):
            raise OwnershipDocumentError("ownership document root must be an object")
        owners: list[Owner] = []
        controller = document.get("controller")
        if isinstance(controller, dict):
            owners.append(
                Owner(
                    owner_id=str(controller.get("branch") or "controller"),
                    task_id=str(controller.get("run_id") or "controller"),
                    role="controller",
                    fence_token=int(controller.get("fence_token", 1)),
                    write_mode=str(controller.get("write_mode", "SHARED_CONTROLLER")),
                    owned_globs=compile_globs(_glob_list(controller, "owned_globs")),
                )
            )
        subordinates = document.get("subordinate_owners", [])
        if not isinstance(subordinates, list):
            raise OwnershipDocumentError("subordinate_owners must be an array")
        for index, entry in enumerate(subordinates):
            if not isinstance(entry, dict):
                raise OwnershipDocumentError(f"subordinate_owners[{index}] must be an object")
            owner_id = entry.get("lease_id")
            if not isinstance(owner_id, str) or not owner_id.strip():
                raise OwnershipDocumentError(
                    f"subordinate_owners[{index}].lease_id must be a non-empty string"
                )
            fence = entry.get("fence_token")
            if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
                raise OwnershipDocumentError(
                    f"subordinate_owners[{index}].fence_token must be an integer >= 1"
                )
            owners.append(
                Owner(
                    owner_id=owner_id,
                    task_id=str(entry.get("task_id") or owner_id),
                    role="subordinate",
                    fence_token=fence,
                    write_mode=str(entry.get("write_mode", "")),
                    owned_globs=compile_globs(_glob_list(entry, "owned_globs")),
                    attempt_id=entry.get("attempt_id"),
                )
            )
        deny = compile_globs(_glob_list(document, "global_deny_globs", required=False))
        return cls(owners, deny, source_document=source_document)

    @classmethod
    def from_task_input(
        cls, document: dict[str, Any], *, source_document: str | None = None
    ) -> "OwnershipEngine":
        """Build the single-writer view an immutable Wave A task input describes."""
        if not isinstance(document, dict):
            raise OwnershipDocumentError("task input root must be an object")
        ownership = document.get("ownership")
        attempt = document.get("attempt")
        if not isinstance(ownership, dict) or not isinstance(attempt, dict):
            raise OwnershipDocumentError("task input requires 'ownership' and 'attempt' objects")
        lease_id = attempt.get("lease_id")
        fence = attempt.get("fence_token")
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise OwnershipDocumentError("attempt.lease_id must be a non-empty string")
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
            raise OwnershipDocumentError("attempt.fence_token must be an integer >= 1")
        owner = Owner(
            owner_id=lease_id,
            task_id=str(document.get("task_id") or lease_id),
            role="subordinate",
            fence_token=fence,
            write_mode="BEST_OF_N_ISOLATED_WORKTREE_ONLY",
            owned_globs=compile_globs(_glob_list(ownership, "allowed_write_globs")),
            read_only_globs=compile_globs(
                _glob_list(ownership, "read_only_globs", required=False)
            ),
            attempt_id=attempt.get("attempt_id"),
        )
        deny = compile_globs(_glob_list(ownership, "prohibited_globs", required=False))
        return cls([owner], deny, source_document=source_document)

    @classmethod
    def from_registry_and_task_input(
        cls,
        registry: dict[str, Any],
        task_input: dict[str, Any],
        *,
        source_document: str | None = None,
    ) -> "OwnershipEngine":
        """Compose the view a subordinate is actually gated by.

        The controller registry supplies every owner and the deny list; the
        immutable task input supplies the writer's read-only list and its own
        prohibited list.  Both are enforced, and the deny lists are unioned so
        neither document can quietly widen the other.
        """
        base = cls.from_ownership_document(registry, source_document=source_document)
        ownership = task_input.get("ownership")
        attempt = task_input.get("attempt")
        if not isinstance(ownership, dict) or not isinstance(attempt, dict):
            raise OwnershipDocumentError("task input requires 'ownership' and 'attempt' objects")
        lease_id = attempt.get("lease_id")
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise OwnershipDocumentError("attempt.lease_id must be a non-empty string")
        read_only = compile_globs(_glob_list(ownership, "read_only_globs", required=False))
        owners: list[Owner] = []
        matched = False
        for owner in base.owners:
            if owner.owner_id == lease_id:
                matched = True
                owners.append(
                    Owner(
                        owner_id=owner.owner_id,
                        task_id=owner.task_id,
                        role=owner.role,
                        fence_token=owner.fence_token,
                        write_mode=owner.write_mode,
                        owned_globs=owner.owned_globs,
                        read_only_globs=read_only,
                        attempt_id=owner.attempt_id,
                    )
                )
            else:
                owners.append(owner)
        if not matched:
            raise OwnershipDocumentError(
                f"registry has no grant for the task input's lease {lease_id!r}"
            )
        prohibited = compile_globs(_glob_list(ownership, "prohibited_globs", required=False))
        deny = list(base.declared_deny_globs)
        for glob in prohibited:
            if glob not in deny:
                deny.append(glob)
        engine = cls(owners, deny, source_document=source_document)
        engine.task_input_lease_id = lease_id
        engine.task_input_write_globs = compile_globs(
            _glob_list(ownership, "allowed_write_globs")
        )
        return engine

    @classmethod
    def from_path(cls, path: Path, *, kind: str = "ownership") -> "OwnershipEngine":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if kind == "ownership":
            return cls.from_ownership_document(document, source_document=str(path))
        if kind == "task-input":
            return cls.from_task_input(document, source_document=str(path))
        raise OwnershipDocumentError(f"unknown document kind {kind!r}")

    def detect_grant_divergence(self) -> list[Finding]:
        """Report a registry grant that disagrees with the immutable task input.

        The registry and the task input are written at different times by
        different actors.  If they disagree about what a writer owns, the writer
        has no single authoritative grant and must not proceed.
        """
        lease_id = getattr(self, "task_input_lease_id", None)
        declared = getattr(self, "task_input_write_globs", None)
        if lease_id is None or declared is None:
            return []
        owner = self._by_id.get(lease_id)
        if owner is None:  # pragma: no cover - construction already rejects this
            return []
        registry_patterns = sorted(glob.pattern for glob in owner.owned_globs)
        input_patterns = sorted(glob.pattern for glob in declared)
        if registry_patterns == input_patterns:
            return []
        return [
            Finding(
                kind="GRANT_DIVERGENCE",
                severity="ERROR",
                detail=(
                    f"registry grants {registry_patterns} to {lease_id!r} but the immutable task "
                    f"input declares {input_patterns}"
                ),
                left_owner=lease_id,
                left_glob=",".join(registry_patterns),
                right_owner="__task_input__",
                right_glob=",".join(input_patterns),
            )
        ]

    # ------------------------------------------------------------ static checks

    def find_owners(self, segments: tuple[str, ...]) -> list[tuple[Owner, PathGlob]]:
        found: list[tuple[Owner, PathGlob]] = []
        for owner in self.owners:
            glob = owner.owns(segments)
            if glob is not None:
                found.append((owner, glob))
        return found

    def detect_grant_overlaps(self) -> list[Finding]:
        """Report every pair of owners whose grants can name the same path."""
        findings: list[Finding] = []
        for left_index in range(len(self.owners)):
            for right_index in range(left_index + 1, len(self.owners)):
                left = self.owners[left_index]
                right = self.owners[right_index]
                for left_glob in left.owned_globs:
                    for right_glob in right.owned_globs:
                        witness = left_glob.intersection_witness(right_glob)
                        if witness is None:
                            continue
                        findings.append(
                            Finding(
                                kind="OWNERSHIP_OVERLAP",
                                severity="ERROR",
                                detail=(
                                    f"grants of {left.owner_id!r} and {right.owner_id!r} both "
                                    f"admit {witness!r}"
                                ),
                                left_owner=left.owner_id,
                                left_glob=left_glob.pattern,
                                right_owner=right.owner_id,
                                right_glob=right_glob.pattern,
                                witness_path=witness,
                            )
                        )
        return findings

    def detect_self_overlaps(self) -> list[Finding]:
        """Report redundant grants inside one owner: a symptom of a drifting registry."""
        findings: list[Finding] = []
        for owner in self.owners:
            globs = owner.owned_globs
            for left_index in range(len(globs)):
                for right_index in range(left_index + 1, len(globs)):
                    witness = globs[left_index].intersection_witness(globs[right_index])
                    if witness is None:
                        continue
                    findings.append(
                        Finding(
                            kind="REDUNDANT_SELF_GRANT",
                            severity="ADVISORY",
                            detail=(
                                f"{owner.owner_id!r} holds two grants that both admit {witness!r}"
                            ),
                            left_owner=owner.owner_id,
                            left_glob=globs[left_index].pattern,
                            right_owner=owner.owner_id,
                            right_glob=globs[right_index].pattern,
                            witness_path=witness,
                        )
                    )
        return findings

    def detect_shadowed_grants(self) -> list[Finding]:
        """Report grants that a deny glob partly cancels.

        The deny always wins at admission time, so this is an advisory about a
        contradictory registry rather than a blocking defect.
        """
        findings: list[Finding] = []
        for owner in self.owners:
            for owned in owner.owned_globs:
                for deny in self.deny_globs:
                    witness = owned.intersection_witness(deny)
                    if witness is None:
                        continue
                    findings.append(
                        Finding(
                            kind="DENY_SHADOWED_GRANT",
                            severity="ADVISORY",
                            detail=(
                                f"grant {owned.pattern!r} of {owner.owner_id!r} overlaps deny "
                                f"{deny.pattern!r} at {witness!r}; the deny wins"
                            ),
                            left_owner=owner.owner_id,
                            left_glob=owned.pattern,
                            right_owner="__deny__",
                            right_glob=deny.pattern,
                            witness_path=witness,
                        )
                    )
        return findings

    def detect_case_insensitive_collisions(self) -> list[Finding]:
        """Report grants that only stay disjoint on a case-sensitive filesystem.

        macOS and Windows checkouts fold case, so two grants that differ only in
        case become one directory there.  Case folding a pattern can perturb
        character classes, so this check is advisory.
        """
        findings: list[Finding] = []
        for left_index in range(len(self.owners)):
            for right_index in range(left_index + 1, len(self.owners)):
                left = self.owners[left_index]
                right = self.owners[right_index]
                for left_glob in left.owned_globs:
                    for right_glob in right.owned_globs:
                        if left_glob.intersection_witness(right_glob) is not None:
                            continue
                        try:
                            folded_left = PathGlob(left_glob.pattern.casefold())
                            folded_right = PathGlob(right_glob.pattern.casefold())
                        except GlobSyntaxError:
                            continue
                        witness = folded_left.intersection_witness(folded_right)
                        if witness is None:
                            continue
                        findings.append(
                            Finding(
                                kind="CASE_INSENSITIVE_COLLISION",
                                severity="ADVISORY",
                                detail=(
                                    f"grants of {left.owner_id!r} and {right.owner_id!r} are "
                                    f"disjoint only while the filesystem preserves case "
                                    f"({witness!r})"
                                ),
                                left_owner=left.owner_id,
                                left_glob=left_glob.pattern,
                                right_owner=right.owner_id,
                                right_glob=right_glob.pattern,
                                witness_path=witness,
                            )
                        )
        return findings

    def detect_non_nfc_patterns(self) -> list[Finding]:
        findings: list[Finding] = []
        for owner in self.owners:
            for glob in owner.owned_globs:
                if is_nfc(glob.pattern):
                    continue
                findings.append(
                    Finding(
                        kind="NON_NFC_GRANT",
                        severity="ADVISORY",
                        detail=(
                            f"grant {glob.pattern!r} of {owner.owner_id!r} is not NFC-normalised "
                            f"and may not match a checkout that normalises differently"
                        ),
                        left_owner=owner.owner_id,
                        left_glob=glob.pattern,
                    )
                )
        return findings

    def audit(self) -> list[Finding]:
        return (
            self.detect_grant_overlaps()
            + self.detect_grant_divergence()
            + self.detect_self_overlaps()
            + self.detect_shadowed_grants()
            + self.detect_case_insensitive_collisions()
            + self.detect_non_nfc_patterns()
        )

    def blocking_findings(self) -> list[Finding]:
        return [finding for finding in self.audit() if finding.severity == "ERROR"]

    # -------------------------------------------------------- change admission

    def check_changes(
        self,
        owner_id: str,
        changes: Iterable[Change],
        *,
        declared_fence: int | None = None,
        isolated_worktree: bool = True,
    ) -> EnforcementReport:
        report = EnforcementReport(
            owner_id=owner_id,
            declared_fence=declared_fence,
            isolated_worktree=isolated_worktree,
        )
        owner = self._by_id.get(owner_id)
        changes = list(changes)
        if owner is None:
            for change in changes:
                report.decisions.append(
                    Decision(
                        change=change,
                        side="writer",
                        path=change.path,
                        decision=DENY,
                        reason=REASON_UNKNOWN_WRITER,
                        detail=f"no ownership grant is registered for writer {owner_id!r}",
                    )
                )
            if not changes:
                report.decisions.append(
                    Decision(
                        change=Change(status=MODIFY, path=None),
                        side="writer",
                        path=None,
                        decision=DENY,
                        reason=REASON_UNKNOWN_WRITER,
                        detail=f"no ownership grant is registered for writer {owner_id!r}",
                    )
                )
            return report

        fence_denial = self._check_fence(owner, declared_fence)
        worktree_denial = self._check_worktree(owner, isolated_worktree)
        for change in changes:
            if fence_denial is not None:
                report.decisions.append(
                    Decision(
                        change=change,
                        side="writer",
                        path=change.path,
                        decision=DENY,
                        reason=fence_denial[0],
                        detail=fence_denial[1],
                    )
                )
                continue
            if worktree_denial is not None:
                report.decisions.append(
                    Decision(
                        change=change,
                        side="writer",
                        path=change.path,
                        decision=DENY,
                        reason=worktree_denial[0],
                        detail=worktree_denial[1],
                    )
                )
                continue
            report.decisions.extend(self._check_change(owner, change))
        return report

    def _check_fence(
        self, owner: Owner, declared_fence: int | None
    ) -> tuple[str, str] | None:
        if declared_fence is None:
            return None
        if not isinstance(declared_fence, int) or isinstance(declared_fence, bool):
            return (REASON_STALE_FENCE, "declared fence token is not an integer")
        if declared_fence < owner.fence_token:
            return (
                REASON_STALE_FENCE,
                f"writer presented fence {declared_fence} but ownership of "
                f"{owner.owner_id!r} has advanced to {owner.fence_token}",
            )
        if declared_fence > owner.fence_token:
            return (
                REASON_FENCE_AHEAD,
                f"writer presented fence {declared_fence} ahead of registered "
                f"{owner.fence_token} for {owner.owner_id!r}; the registry is stale",
            )
        return None

    def _check_worktree(
        self, owner: Owner, isolated_worktree: bool
    ) -> tuple[str, str] | None:
        if isolated_worktree:
            return None
        if owner.write_mode in _ISOLATION_REQUIRED_WRITE_MODES:
            return (
                REASON_SHARED_WORKTREE,
                f"write_mode {owner.write_mode} forbids writing from a shared worktree",
            )
        return None

    def _check_change(self, owner: Owner, change: Change) -> list[Decision]:
        if change.status not in _GIT_STATUS_LETTERS.values():
            return [
                Decision(
                    change=change,
                    side="writer",
                    path=change.path,
                    decision=DENY,
                    reason=REASON_UNKNOWN_STATUS,
                    detail=f"unsupported change status {change.status!r}",
                )
            ]
        if change.status == RENAME and not change.old_path:
            return [
                Decision(
                    change=change,
                    side="source",
                    path=None,
                    decision=DENY,
                    reason=REASON_MISSING_RENAME_SOURCE,
                    detail="a rename must report the path it moved away from",
                )
            ]

        decisions: list[Decision] = []
        source = change.source
        if source is not None:
            decisions.append(self._check_side(owner, change, "source", source))
        target = change.target
        if target is not None:
            decisions.append(self._check_side(owner, change, "target", target))
        if not decisions:
            decisions.append(
                Decision(
                    change=change,
                    side="target" if change.status != DELETE else "source",
                    path=change.path,
                    decision=DENY,
                    reason=REASON_MALFORMED_PATH,
                    detail=(
                        f"a change of status {change.status!r} must name the path it writes, "
                        f"but the path is {change.path!r}"
                    ),
                )
            )
        return decisions

    def _check_side(self, owner: Owner, change: Change, side: str, raw_path: str) -> Decision:
        try:
            segments = normalize_path(raw_path)
        except PathSyntaxError as exc:
            return Decision(
                change=change,
                side=side,
                path=raw_path,
                decision=DENY,
                reason=REASON_MALFORMED_PATH,
                detail=str(exc),
            )

        deny_hit = first_match(self.deny_globs, segments)
        if deny_hit is not None:
            return Decision(
                change=change,
                side=side,
                path=raw_path,
                decision=DENY,
                reason=REASON_PROHIBITED_PATH,
                detail=f"path is denied to every writer by {deny_hit.pattern!r}",
                matched_glob=deny_hit.pattern,
            )

        read_only_hit = first_match(owner.read_only_globs, segments)
        owned = owner.owns(segments)
        if read_only_hit is not None and owned is None:
            return Decision(
                change=change,
                side=side,
                path=raw_path,
                decision=DENY,
                reason=REASON_READ_ONLY_PATH,
                detail=f"path is read-only for {owner.owner_id!r} by {read_only_hit.pattern!r}",
                matched_glob=read_only_hit.pattern,
            )

        if owned is None:
            others = [
                (other, glob)
                for other, glob in self.find_owners(segments)
                if other.owner_id != owner.owner_id
            ]
            if others:
                other, other_glob = others[0]
                return Decision(
                    change=change,
                    side=side,
                    path=raw_path,
                    decision=DENY,
                    reason=self._not_owned_reason(change, side, REASON_FOREIGN_OWNER),
                    detail=(
                        f"path belongs to {other.owner_id!r} via {other_glob.pattern!r}, "
                        f"not to {owner.owner_id!r}"
                    ),
                    matched_glob=other_glob.pattern,
                    conflicting_owner=other.owner_id,
                )
            return Decision(
                change=change,
                side=side,
                path=raw_path,
                decision=DENY,
                reason=self._not_owned_reason(change, side, REASON_UNOWNED_PATH),
                detail=f"no grant of {owner.owner_id!r} admits this path",
            )

        return Decision(
            change=change,
            side=side,
            path=raw_path,
            decision=ALLOW,
            reason=REASON_ALLOWED,
            detail=f"admitted by grant {owned.pattern!r}",
            matched_glob=owned.pattern,
        )

    @staticmethod
    def _not_owned_reason(change: Change, side: str, fallback: str) -> str:
        if change.status == RENAME:
            return (
                REASON_RENAME_SOURCE_NOT_OWNED
                if side == "source"
                else REASON_RENAME_TARGET_NOT_OWNED
            )
        if change.status == DELETE:
            return REASON_DELETE_NOT_OWNED
        return fallback

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_document": self.source_document,
            "owner_count": len(self.owners),
            "declared_deny_globs": [glob.pattern for glob in self.declared_deny_globs],
            "implicit_deny_globs": [glob.pattern for glob in self.implicit_deny_globs],
            "owners": [
                {
                    "owner_id": owner.owner_id,
                    "task_id": owner.task_id,
                    "role": owner.role,
                    "fence_token": owner.fence_token,
                    "write_mode": owner.write_mode,
                    "attempt_id": owner.attempt_id,
                    "owned_globs": [glob.pattern for glob in owner.owned_globs],
                    "read_only_globs": [glob.pattern for glob in owner.read_only_globs],
                }
                for owner in self.owners
            ],
        }


def _glob_list(document: dict[str, Any], key: str, *, required: bool = True) -> list[str]:
    value = document.get(key)
    if value is None:
        if required:
            raise OwnershipDocumentError(f"{key} is required")
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OwnershipDocumentError(f"{key} must be an array of strings")
    if required and not value:
        raise OwnershipDocumentError(f"{key} must not be empty")
    return list(value)


# ------------------------------------------------------------------ git parsing


def parse_name_status_z(payload: bytes) -> list[Change]:
    """Parse ``git diff --name-status -z`` output.

    ``-z`` is mandatory rather than convenient: without it git quotes and escapes
    unusual paths, and a quoted path silently fails to match a glob.
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    fields = payload.split(b"\x00")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        raw_status = fields[index].decode("utf-8", errors="surrogateescape")
        index += 1
        if not raw_status:
            continue
        letter = raw_status[0]
        similarity: int | None = None
        if len(raw_status) > 1 and raw_status[1:].isdigit():
            similarity = int(raw_status[1:])
        status = _GIT_STATUS_LETTERS.get(letter)
        if status is None:
            raise ValueError(f"unsupported git status field {raw_status!r}")
        needed = 2 if status in (RENAME, COPY) else 1
        if index + needed > len(fields):
            raise ValueError(f"truncated git status record for {raw_status!r}")
        if needed == 2:
            old_path = fields[index].decode("utf-8", errors="surrogateescape")
            new_path = fields[index + 1].decode("utf-8", errors="surrogateescape")
            changes.append(
                Change(status=status, path=new_path, old_path=old_path, similarity=similarity)
            )
            index += 2
        else:
            path = fields[index].decode("utf-8", errors="surrogateescape")
            changes.append(Change(status=status, path=path, similarity=similarity))
            index += 1
    return changes


def changes_from_document(document: Any) -> list[Change]:
    entries = document.get("changes") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        raise ValueError("changes document must be an array or carry a 'changes' array")
    changes: list[Change] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"changes[{index}] must be an object")
        status = entry.get("status")
        if not isinstance(status, str):
            raise ValueError(f"changes[{index}].status must be a string")
        status = status.upper()
        if status in _GIT_STATUS_LETTERS:
            status = _GIT_STATUS_LETTERS[status]
        changes.append(
            Change(
                status=status,
                path=entry.get("path"),
                old_path=entry.get("old_path"),
                similarity=entry.get("similarity"),
            )
        )
    return changes


def git_changes(repo: Path, *args: str) -> list[Change]:
    completed = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-status", "-z", "-M", *args],
        check=True,
        capture_output=True,
    )
    return parse_name_status_z(completed.stdout)


# --------------------------------------------------------------------- CLI


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(payload: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if out is None:
        sys.stdout.write(text)
    else:
        Path(out).write_text(text, encoding="utf-8")


def _build_engine(args: argparse.Namespace) -> OwnershipEngine:
    task_input = getattr(args, "task_input", None)
    if task_input is not None:
        return OwnershipEngine.from_registry_and_task_input(
            _load_json(args.ownership),
            _load_json(task_input),
            source_document=f"{args.ownership}+{task_input}",
        )
    return OwnershipEngine.from_path(args.ownership, kind=args.kind)


def _cmd_audit(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    findings = engine.audit()
    blocking = [finding for finding in findings if finding.severity == "ERROR"]
    payload = {
        "command": "audit",
        "registry": engine.to_dict(),
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "outcome": "OVERLAP_DETECTED" if blocking else "DISJOINT",
        "findings": [finding.to_dict() for finding in findings],
    }
    _emit(payload, args.out)
    if not args.out:
        return 1 if blocking else 0
    print(f"{payload['outcome']} findings={len(findings)} blocking={len(blocking)}")
    return 1 if blocking else 0


def _cmd_check(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    if args.changes is not None:
        changes = changes_from_document(_load_json(args.changes))
    elif args.staged:
        changes = git_changes(args.repo, "--cached")
    elif args.diff is not None:
        changes = git_changes(args.repo, args.diff)
    else:
        changes = changes_from_document(json.loads(sys.stdin.read()))
    report = engine.check_changes(
        args.owner,
        changes,
        declared_fence=args.fence,
        isolated_worktree=not args.shared_worktree,
    )
    payload = {
        "command": "check",
        "registry_source": engine.source_document,
        "change_count": len(changes),
        "report": report.to_dict(),
    }
    _emit(payload, args.out)
    if args.out:
        print(f"{report.outcome} checked={len(report.decisions)} denied={len(report.denials)}")
    return 1 if report.blocked else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--kind",
        choices=("ownership", "task-input"),
        default="ownership",
        help="interpret the document as the controller registry or one immutable task input",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="detect grant overlap before any write")
    audit.add_argument("ownership", type=Path)
    audit.add_argument("--task-input", type=Path, default=None)
    audit.add_argument("--out", type=Path, default=None)
    audit.set_defaults(func=_cmd_audit)

    check = subparsers.add_parser("check", help="admit or deny a set of changed paths")
    check.add_argument("ownership", type=Path)
    check.add_argument("--task-input", type=Path, default=None)
    check.add_argument("--owner", required=True)
    check.add_argument("--fence", type=int, default=None)
    check.add_argument("--changes", type=Path, default=None)
    check.add_argument("--staged", action="store_true")
    check.add_argument("--diff", default=None, help="git revision range, e.g. BASE..HEAD")
    check.add_argument("--repo", type=Path, default=Path("."))
    check.add_argument("--shared-worktree", action="store_true")
    check.add_argument("--out", type=Path, default=None)
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in ("kind",):
        if not hasattr(args, name):
            setattr(args, name, "ownership")
    try:
        return int(args.func(args))
    except (OwnershipDocumentError, GlobSyntaxError, PathSyntaxError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"IO_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
