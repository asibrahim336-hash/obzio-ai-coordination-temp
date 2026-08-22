#!/usr/bin/env python3
"""Dependency-free currentness compiler and fail-closed admission gate for OE-L4.

`currentctl` compiles what is *actually* current in this repository from git
evidence, and refuses to answer when the repository holds competing claims. It
exists because the recurring failure in this estate is not too much work; it is
work whose currentness, differentiation, admission state and provenance cannot
be resolved without the founder acting as the correction mechanism.

Design rules, all load-bearing:

* Claims never advance state. Only evidence of a declared class does.
* Evidence classes that measure volume or transport - a pull request, a branch,
  a ZIP, a file count, an agent existing, an acknowledgement, a provider
  `completed` - are recorded but can never lift a subject above PROPOSED.
* When two live refs disagree about the same logical pointer, resolution fails
  closed rather than guessing a winner.
* Every assertion emitted carries provenance labelled DIRECTLY_REPRODUCED,
  DOCUMENTED or HYPOTHESIS.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

TOOL_ID = "L4-CURRENTCTL"
TOOL_VERSION = "20260822-v001"
LANE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
LEDGER_DIR = LANE_ROOT / "ledger"

DIRECTLY_REPRODUCED = "DIRECTLY_REPRODUCED"
DOCUMENTED = "DOCUMENTED"
HYPOTHESIS = "HYPOTHESIS"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OID_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_TOKEN_RE = re.compile(r"v(\d{3})")

ERROR = "ERROR"
WARNING = "WARNING"


# --------------------------------------------------------------------------
# provenance and findings
# --------------------------------------------------------------------------


def provenance(label: str, **fields: Any) -> dict[str, Any]:
    """Build a provenance record. `label` must be one of the three evidence labels."""
    if label not in (DIRECTLY_REPRODUCED, DOCUMENTED, HYPOTHESIS):
        raise ValueError(f"unknown evidence label: {label}")
    record: dict[str, Any] = {"label": label}
    record.update(fields)
    return record


class Finding:
    """One fail-closed detection with the evidence that produced it."""

    __slots__ = ("code", "severity", "subject", "detail", "evidence")

    def __init__(self, code: str, severity: str, subject: str, detail: str,
                 evidence: dict[str, Any] | None = None) -> None:
        self.code = code
        self.severity = severity
        self.subject = subject
        self.detail = detail
        self.evidence = evidence or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "detail": self.detail,
            "evidence": self.evidence,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Finding {self.code} {self.severity} {self.subject}>"


def urn(kind: str, name: str) -> str:
    """Stable address for anything this tool asserts about."""
    return f"urn:obzio:l4:{kind}:{name}"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


# --------------------------------------------------------------------------
# git evidence layer
# --------------------------------------------------------------------------


class GitEvidence:
    """Reads the repository through git plumbing.

    The runner is injectable so tests can drive the compiler from fixtures
    without a network or a populated object store.
    """

    REF_FORMAT = "%(refname:short)\t%(objectname)\t%(committerdate:unix)\t%(committerdate:iso8601)\t%(contents:subject)"

    def __init__(self, root: Path, runner: Callable[[Sequence[str]], str] | None = None) -> None:
        self.root = root
        self._runner = runner or self._default_runner
        self._commands: list[list[str]] = []

    def _default_runner(self, args: Sequence[str]) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout

    def run(self, *args: str) -> str:
        self._commands.append(["git", "-C", str(self.root), *args])
        return self._runner(args)

    @property
    def commands(self) -> list[list[str]]:
        return list(self._commands)

    def remote_refs(self) -> list[dict[str, Any]]:
        """Every remote branch with head, time and subject. Excludes origin/HEAD."""
        refs: list[dict[str, Any]] = []
        for line in self.run("for-each-ref", "--format=" + self.REF_FORMAT, "refs/remotes/origin").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            while len(parts) < 5:
                parts.append("")
            short, oid, unix, iso, subject = parts[:5]
            if short == "origin" or not short.startswith("origin/"):
                continue
            refs.append({
                "branch": short[len("origin/"):],
                "head": oid,
                "committed_unix": int(unix) if unix.isdigit() else 0,
                "committed_at": iso,
                "subject": subject,
            })
        refs.sort(key=lambda item: item["branch"])
        return refs

    def commit_parents(self) -> list[tuple[str, list[str]]]:
        """Whole-DAG parent listing in topological order (children before parents)."""
        rows: list[tuple[str, list[str]]] = []
        for line in self.run("rev-list", "--topo-order", "--all", "--parents").splitlines():
            bits = line.split()
            if bits:
                rows.append((bits[0], bits[1:]))
        return rows

    def object_id(self, ref: str, path: str) -> str | None:
        """Blob id of `path` on `ref`, or None when the path is absent there."""
        out = self.run("rev-parse", f"{ref}:{path}").strip()
        return out if OID_RE.fullmatch(out) else None

    def tree_paths(self, ref: str) -> list[str]:
        return [line for line in self.run("ls-tree", "-r", "--name-only", ref).splitlines() if line]

    def count(self, revspec: str) -> int:
        out = self.run("rev-list", "--count", revspec).strip()
        return int(out) if out.isdigit() else 0

    def path_ever_added(self, pattern: str) -> list[str]:
        """Commits on any ref that ever added a path matching `pattern`."""
        out = self.run("log", "--all", "--format=%H", "--diff-filter=A", "--", pattern)
        return [line for line in out.splitlines() if OID_RE.fullmatch(line.strip())]


# --------------------------------------------------------------------------
# ref graph compilation
# --------------------------------------------------------------------------

REF_ACTIVE = "ACTIVE"
REF_SUPERSEDED = "SUPERSEDED"
REF_MERGED = "MERGED"
REF_ORPHANED = "ORPHANED"
REF_ABANDONED = "ABANDONED"

REF_ROLE_WORK = "WORK"
REF_ROLE_LEASE = "LEASE_TOKEN"
REF_ROLE_CANARY = "CANARY_TOKEN"

LEASE_FILES = {"claim.json"}
CANARY_FILES = {"canary.json"}


def compile_ref_graph(git: GitEvidence, live_branches: Iterable[str],
                      trunk: str = "main") -> dict[str, Any]:
    """Compile the containment DAG over remote branch heads.

    Classification is derived, never declared:

    MERGED      head is an ancestor of the trunk head.
    SUPERSEDED  head is an ancestor of some other live-lineage branch head.
    ORPHANED    head shares no ancestry with the trunk at all.
    ACTIVE      an unmerged tip that is a declared live branch.
    ABANDONED   an unmerged tip that nothing points at.
    """
    refs = git.remote_refs()
    live = set(live_branches)
    index = {ref["branch"]: position for position, ref in enumerate(refs)}
    heads = {ref["branch"]: ref["head"] for ref in refs}

    mask: dict[str, int] = defaultdict(int)
    for ref in refs:
        mask[ref["head"]] |= 1 << index[ref["branch"]]
    for commit, parents in git.commit_parents():
        bits = mask.get(commit, 0)
        if not bits:
            continue
        for parent in parents:
            mask[parent] |= bits

    trunk_head = heads.get(trunk)
    by_head: dict[str, list[str]] = defaultdict(list)
    for ref in refs:
        by_head[ref["head"]].append(ref["branch"])

    nodes: dict[str, dict[str, Any]] = {}
    for ref in refs:
        branch = ref["branch"]
        bits = mask[ref["head"]]
        descendants = sorted(
            other["branch"] for other in refs
            if (bits >> index[other["branch"]]) & 1 and other["branch"] != branch
        )
        merged = trunk in descendants
        contained_by_live = sorted(name for name in descendants if name != trunk)
        paths = git.tree_paths(f"origin/{branch}")
        role = REF_ROLE_WORK
        if len(paths) == 1 and paths[0] in LEASE_FILES:
            role = REF_ROLE_LEASE
        elif len(paths) == 1 and paths[0] in CANARY_FILES:
            role = REF_ROLE_CANARY
        disjoint = trunk_head is not None and branch != trunk and not (
            _shares_ancestry(git, mask, index, branch, trunk)
        )

        if branch == trunk:
            classification = REF_ACTIVE
        elif merged:
            classification = REF_MERGED
        elif disjoint:
            classification = REF_ORPHANED
        elif contained_by_live:
            classification = REF_SUPERSEDED
        elif branch in live:
            classification = REF_ACTIVE
        else:
            classification = REF_ABANDONED

        nodes[branch] = {
            "urn": urn("branch", branch),
            "branch": branch,
            "head": ref["head"],
            "committed_at": ref["committed_at"],
            "committed_unix": ref["committed_unix"],
            "subject": ref["subject"],
            "tracked_paths": len(paths),
            "ref_role": role,
            "classification": classification,
            "merged_into_trunk": merged,
            "shares_ancestry_with_trunk": not disjoint,
            "contained_by": contained_by_live,
            "identical_head_with": sorted(name for name in by_head[ref["head"]] if name != branch),
            "declared_live": branch in live,
            "provenance": provenance(
                DIRECTLY_REPRODUCED,
                method="git for-each-ref + git rev-list --topo-order --all --parents",
                head=ref["head"],
            ),
        }

    return {
        "trunk": trunk,
        "trunk_head": trunk_head,
        "ref_count": len(refs),
        "nodes": nodes,
    }


def _shares_ancestry(git: GitEvidence, mask: dict[str, int], index: dict[str, int],
                     branch: str, trunk: str) -> bool:
    """True when branch and trunk have at least one common ancestor commit."""
    branch_bit = 1 << index[branch]
    trunk_bit = 1 << index[trunk]
    both = branch_bit | trunk_bit
    for commit, bits in mask.items():
        if bits & both == both:
            return True
    return False


# --------------------------------------------------------------------------
# currentness scopes
# --------------------------------------------------------------------------


def compile_currentness(git: GitEvidence, scopes: list[dict[str, Any]],
                        live_branches: Sequence[str]) -> dict[str, Any]:
    """Resolve every declared logical pointer scope across every live branch.

    A scope is a *logical* identity - "the operator-system pointer" - realised
    by one or more concrete paths. When live refs hold different bytes for the
    same scope and no supersession edge is declared, the scope is UNRESOLVABLE
    and every consumer must fail closed.
    """
    resolved: dict[str, Any] = {}
    for scope in scopes:
        scope_id = scope["scope_id"]
        paths = scope.get("paths", [])
        supersession = scope.get("supersedes", {})
        variants: dict[str, dict[str, Any]] = {}
        absent: list[str] = []
        for branch in live_branches:
            found = None
            for path in paths:
                oid = git.object_id(f"origin/{branch}", path)
                if oid:
                    found = (path, oid)
                    break
            if found is None:
                absent.append(branch)
                continue
            path, oid = found
            entry = variants.setdefault(oid, {"blob": oid, "path": path, "branches": []})
            entry["branches"].append(branch)

        winners = [oid for oid in variants if oid not in supersession]
        state = "RESOLVED"
        if not variants:
            state = "ABSENT"
        elif len(winners) > 1:
            state = "UNRESOLVABLE_COMPETING_CLAIMS"
        elif len(variants) > 1:
            state = "RESOLVED_BY_DECLARED_SUPERSESSION"

        resolved[scope_id] = {
            "urn": urn("scope", scope_id),
            "scope_id": scope_id,
            "description": scope.get("description", ""),
            "paths": paths,
            "state": state,
            "variant_count": len(variants),
            "variants": sorted(
                ({"blob": v["blob"], "path": v["path"], "branches": sorted(v["branches"])}
                 for v in variants.values()),
                key=lambda item: (-len(item["branches"]), item["blob"]),
            ),
            "absent_on": sorted(absent),
            "resolved_blob": winners[0] if state.startswith("RESOLVED") and winners else None,
            "provenance": provenance(
                DIRECTLY_REPRODUCED,
                method="git rev-parse <ref>:<path> across the declared live branch set",
                live_branches=list(live_branches),
            ),
        }
    return resolved


# --------------------------------------------------------------------------
# version lineage
# --------------------------------------------------------------------------


def compile_version_lineage(git: GitEvidence, ref: str = "HEAD") -> dict[str, Any]:
    """Group versioned artifacts into families and find the breaks in each chain.

    A family is the filename with its `vNNN` token removed. A break is either a
    numeric gap inside the observed range, or a version referenced in committed
    text for which no artifact was ever added on any ref.
    """
    families: dict[str, dict[str, Any]] = {}
    for path in git.tree_paths(ref):
        name = Path(path).name
        match = VERSION_TOKEN_RE.search(name)
        if not match:
            continue
        family_key = str(Path(path).parent / VERSION_TOKEN_RE.sub("vNNN", name))
        family = families.setdefault(family_key, {"family": family_key, "versions": {}})
        family["versions"][int(match.group(1))] = path

    lineage: dict[str, Any] = {}
    for family_key, family in sorted(families.items()):
        numbers = sorted(family["versions"])
        gaps = [n for n in range(numbers[0], numbers[-1] + 1) if n not in family["versions"]]
        chain = [
            {"version": n, "path": family["versions"][n],
             "supersedes": family["versions"].get(n - 1)}
            for n in numbers
        ]
        lineage[family_key] = {
            "urn": urn("lineage", family_key),
            "family": family_key,
            "observed_versions": numbers,
            "internal_gaps": gaps,
            "chain": chain,
            "provenance": provenance(
                DIRECTLY_REPRODUCED,
                method=f"git ls-tree -r --name-only {ref} grouped by vNNN token",
            ),
        }
    return lineage


def detect_phantom_versions(git: GitEvidence, root: Path,
                            tokens: list[dict[str, Any]]) -> list[Finding]:
    """A version referenced in committed text but never added on any ref."""
    findings: list[Finding] = []
    for token in tokens:
        label = token["token"]
        pattern = token["path_glob"]
        commits = git.path_ever_added(pattern)
        references = token.get("referenced_by", [])
        if commits:
            continue
        findings.append(Finding(
            code="LINEAGE_PHANTOM_VERSION",
            severity=ERROR,
            subject=urn("version", label),
            detail=(
                f"{label} is referenced by {len(references)} committed artifact(s) but no commit on "
                f"any ref ever added a path matching {pattern!r}. The lineage claims a predecessor "
                f"that the canonical store has never held."
            ),
            evidence={
                "path_glob": pattern,
                "commits_adding_path": commits,
                "referenced_by": references,
                "provenance": provenance(
                    DIRECTLY_REPRODUCED,
                    method=f"git log --all --diff-filter=A -- {pattern}",
                    result="no commits",
                ),
            },
        ))
    return findings


# --------------------------------------------------------------------------
# admission ladder
# --------------------------------------------------------------------------


class AdmissionLadder:
    """Decides whether declared evidence can carry a subject to a claimed state."""

    def __init__(self, contract: dict[str, Any]) -> None:
        self.contract = contract
        self.order = list(contract["ladder"])
        self.requirements = contract["state_requirements"]
        self.admissible = set(contract["admissible_evidence_classes"])
        self.non_admissible = set(contract["non_admissible_evidence_classes"])
        self.ceiling = contract.get("non_admissible_ceiling", self.order[0])
        self.monotonic = contract.get("monotonic", True)

    def rank(self, state: str) -> int:
        if state not in self.order:
            raise ValueError(f"unknown admission state: {state}")
        return self.order.index(state)

    def classify_evidence(self, entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
        admissible: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        for entry in entries:
            entry_class = entry.get("evidence_class")
            if entry_class in self.non_admissible:
                rejected.append(entry)
            elif entry_class in self.admissible:
                admissible.append(entry)
            else:
                unknown.append(entry)
        return {"admissible": admissible, "rejected": rejected, "unknown": unknown}

    def _satisfied(self, state: str, present: set[str]) -> bool:
        requirement = self.requirements[state]
        all_of = set(requirement.get("requires_all_of", []))
        any_of = set(requirement.get("requires_any_of", []))
        if all_of and not all_of.issubset(present):
            return False
        if any_of and not (any_of & present):
            return False
        return True

    def highest_supported(self, entries: Sequence[dict[str, Any]]) -> str:
        """The highest state the supplied evidence actually supports.

        The ladder is monotonic, so the walk stops at the first unsatisfied rung
        even when a higher rung's own requirements happen to be met. Evidence for
        a later stage does not backfill an earlier one.
        """
        classified = self.classify_evidence(entries)
        present = {entry["evidence_class"] for entry in classified["admissible"]}
        supported = self.order[0]
        for state in self.order:
            if not self._satisfied(state, present):
                break
            supported = state
        if not classified["admissible"]:
            return self.order[0] if not classified["rejected"] else self.ceiling
        return supported

    def skipped_foundations(self, entries: Sequence[dict[str, Any]]) -> list[str]:
        """States whose own requirements are met but which sit above a broken rung."""
        classified = self.classify_evidence(entries)
        present = {entry["evidence_class"] for entry in classified["admissible"]}
        broken = None
        skipped: list[str] = []
        for state in self.order:
            if not self._satisfied(state, present):
                if broken is None:
                    broken = state
                continue
            if broken is not None:
                skipped.append(state)
        return skipped

    def evaluate(self, subject: str, claimed_state: str,
                 entries: Sequence[dict[str, Any]]) -> tuple[str, list[Finding]]:
        """Return (admitted_state, findings). Admitted never exceeds supported."""
        findings: list[Finding] = []
        classified = self.classify_evidence(entries)
        supported = self.highest_supported(entries)

        for entry in classified["unknown"]:
            findings.append(Finding(
                code="EVIDENCE_CLASS_UNKNOWN",
                severity=ERROR,
                subject=urn("workstream", subject),
                detail=(
                    f"evidence class {entry.get('evidence_class')!r} is in neither the admissible "
                    "nor the non-admissible register; an unclassified class cannot be silently trusted"
                ),
                evidence={"entry": entry},
            ))

        skipped = self.skipped_foundations(entries)
        if skipped:
            findings.append(Finding(
                code="LADDER_FOUNDATION_MISSING",
                severity=ERROR,
                subject=urn("workstream", subject),
                detail=(
                    f"evidence satisfies {', '.join(skipped)} while an earlier rung is unsatisfied; "
                    f"the subject is held at {supported} because a later stage cannot backfill an "
                    "earlier one"
                ),
                evidence={"satisfied_above_break": skipped, "held_at": supported},
            ))

        if self.rank(claimed_state) > self.rank(supported):
            blocking = sorted({entry["evidence_class"] for entry in classified["rejected"]})
            findings.append(Finding(
                code="ADMISSION_OVERCLAIM",
                severity=ERROR,
                subject=urn("workstream", subject),
                detail=(
                    f"claimed {claimed_state} but the supplied evidence supports only {supported}"
                    + (f"; non-admissible evidence offered: {', '.join(blocking)}" if blocking else "")
                ),
                evidence={
                    "claimed_state": claimed_state,
                    "supported_state": supported,
                    "required": self.requirements[claimed_state],
                    "admissible_classes_present": sorted(
                        {entry["evidence_class"] for entry in classified["admissible"]}
                    ),
                    "non_admissible_offered": blocking,
                },
            ))

        for entry in classified["rejected"]:
            findings.append(Finding(
                code="NON_ADMISSIBLE_EVIDENCE_OFFERED",
                severity=WARNING,
                subject=urn("workstream", subject),
                detail=(
                    f"{entry['evidence_class']} offered as support for {claimed_state}: "
                    f"{self.contract['non_admissible_evidence_classes'][entry['evidence_class']]}"
                ),
                evidence={"entry": entry, "ceiling": self.ceiling},
            ))

        admitted = supported if self.rank(supported) < self.rank(claimed_state) else claimed_state
        return admitted, findings


DISPLAY_ALIAS_LOCATORS = {
    "current_project_conversation",
    "current-founder-appointment",
    "current conversation",
    "this chat",
    "the current thread",
    "current project",
}


def check_reproducibility(root: Path, subject: str,
                          entries: Sequence[dict[str, Any]],
                          contract: dict[str, Any],
                          git: GitEvidence | None = None) -> list[Finding]:
    """Every evidence entry must resolve to an artifact or a re-runnable command."""
    findings: list[Finding] = []
    rule = contract["reproducibility_rule"]
    artifact_classes = set(rule["artifact_classes"])
    command_classes = set(rule["command_classes"])
    for entry in entries:
        entry_class = entry.get("evidence_class")
        locator = entry.get("locator")
        if isinstance(locator, str) and locator.strip().lower() in DISPLAY_ALIAS_LOCATORS:
            findings.append(Finding(
                code="ALIAS_USED_AS_LOCATOR",
                severity=ERROR,
                subject=urn("workstream", subject),
                detail=(
                    f"{entry_class} carries {locator!r}, a display or session alias. An alias resolves "
                    "to whatever the reader is looking at, so it cannot address the evidence later"
                ),
                evidence={"entry": entry},
            ))
        if entry_class == "REMOTE_READBACK_HASH" and git is not None:
            stale = _readback_staleness(git, entry)
            if stale:
                findings.append(Finding(
                    code="STALE_REMOTE_READBACK",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=(
                        f"read-back pinned to {entry['readback_commit'][:12]} on "
                        f"{entry['readback_ref']}, which is now {stale['commits_behind']} commits behind "
                        f"head {stale['current_head'][:12]}; a read-back that no longer matches the ref "
                        "records a moment, not current state"
                    ),
                    evidence={"entry": entry, **stale,
                              "provenance": provenance(DIRECTLY_REPRODUCED,
                                                       method="git rev-list --count <recorded>..<ref>")},
                ))
        if entry_class in artifact_classes:
            path = entry.get("artifact_path")
            digest = entry.get("sha256")
            if not path or not digest:
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{entry_class} without both artifact_path and sha256",
                    evidence={"entry": entry},
                ))
                continue
            if not SHA256_RE.fullmatch(str(digest)):
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{entry_class} carries a malformed sha256 {digest!r}",
                    evidence={"entry": entry},
                ))
                continue
            target = root / path
            if not target.is_file():
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{entry_class} names {path} which does not exist in the working tree",
                    evidence={"entry": entry},
                ))
                continue
            actual = sha256_bytes(target.read_bytes())
            if actual != digest:
                findings.append(Finding(
                    code="EVIDENCE_HASH_MISMATCH",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{path} hashes to {actual}, evidence claims {digest}",
                    evidence={"entry": entry, "actual_sha256": actual,
                              "provenance": provenance(DIRECTLY_REPRODUCED,
                                                       method="sha256 of working-tree bytes")},
                ))
        elif entry_class in command_classes:
            if not entry.get("argv"):
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{entry_class} without an argv a third party could re-run",
                    evidence={"entry": entry},
                ))
        elif entry_class in ("LAUNCH_RECEIPT_WITH_LOCATOR", "OBSERVED_OUTPUT_WITH_LOCATOR"):
            if not locator:
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=f"{entry_class} without a stable locator is an unaddressable claim",
                    evidence={"entry": entry},
                ))
        elif entry_class == "INDEPENDENT_EVALUATION":
            if not entry.get("evaluator_identity"):
                findings.append(Finding(
                    code="UNBACKED_EVIDENCE_CLAIM",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail="INDEPENDENT_EVALUATION without a named evaluator identity",
                    evidence={"entry": entry},
                ))
            elif entry.get("evaluator_identity") == entry.get("producer_identity"):
                findings.append(Finding(
                    code="SELF_ACCEPTANCE",
                    severity=ERROR,
                    subject=urn("workstream", subject),
                    detail=(
                        f"evaluator {entry['evaluator_identity']} is the producer; "
                        "a producer test is not independent acceptance"
                    ),
                    evidence={"entry": entry},
                ))
    return findings


def _readback_staleness(git: GitEvidence, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return staleness detail when a recorded read-back is no longer the ref head."""
    ref = entry.get("readback_ref")
    recorded = entry.get("readback_commit")
    if not ref or not recorded:
        return None
    current = git.run("rev-parse", f"origin/{ref}").strip()
    if not OID_RE.fullmatch(current) or current == recorded:
        return None
    behind = git.count(f"{recorded}..origin/{ref}")
    return {"current_head": current, "recorded_commit": recorded, "commits_behind": behind}


def reproduce_commands(root: Path, ledger: dict[str, Any]) -> list[Finding]:
    """Actually re-run every REPRODUCIBLE_COMMAND and compare the exit code."""
    findings: list[Finding] = []
    for workstream in ledger.get("workstreams", []):
        for entry in workstream.get("evidence", []):
            if entry.get("evidence_class") != "REPRODUCIBLE_COMMAND":
                continue
            argv = entry.get("argv")
            if not argv:
                continue
            expected = entry.get("expected_exit_code", 0)
            result = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, check=False)
            if result.returncode != expected:
                findings.append(Finding(
                    code="REPRODUCTION_FAILED",
                    severity=ERROR,
                    subject=urn("workstream", workstream["workstream_id"]),
                    detail=(
                        f"{' '.join(argv)} exited {result.returncode}, evidence claims {expected}"
                    ),
                    evidence={
                        "argv": argv,
                        "actual_exit_code": result.returncode,
                        "stdout_tail": result.stdout[-400:],
                        "stderr_tail": result.stderr[-400:],
                        "provenance": provenance(DIRECTLY_REPRODUCED, method="subprocess re-run"),
                    },
                ))
    return findings


# --------------------------------------------------------------------------
# commission differentiation
# --------------------------------------------------------------------------


def check_commission_differentiation(commissions: list[dict[str, Any]],
                                     contract: dict[str, Any]) -> list[Finding]:
    """Two active whole-operation commissions over overlapping scope must differentiate."""
    findings: list[Finding] = []
    markers = [m.lower() for m in contract["differentiation_rule"]["whole_operation_markers"]]

    seen_ids: dict[str, list[str]] = defaultdict(list)
    for commission in commissions:
        seen_ids[commission["commission_id"]].append(commission["path"])
    for commission_id, paths in sorted(seen_ids.items()):
        if len(paths) > 1:
            findings.append(Finding(
                code="COMMISSION_ID_COLLISION",
                severity=ERROR,
                subject=urn("commission", commission_id),
                detail=(
                    f"commission id {commission_id} is claimed by {len(paths)} distinct documents; "
                    "an identifier that resolves to more than one scope is not addressable"
                ),
                evidence={"paths": sorted(paths)},
            ))

    active = [c for c in commissions if c.get("active", True)]
    for position, first in enumerate(active):
        for second in active[position + 1:]:
            if first["commission_id"] == second["commission_id"]:
                continue  # already reported as COMMISSION_ID_COLLISION
            overlap = sorted(set(first.get("namespace", [])) & set(second.get("namespace", [])))
            if not overlap:
                continue
            first_whole = _whole_operation(first, markers)
            second_whole = _whole_operation(second, markers)
            if not (first_whole and second_whole):
                continue
            if second["commission_id"] in first.get("supersedes", []) or \
               first["commission_id"] in second.get("supersedes", []):
                continue
            shared_actor = bool(set(first.get("binds", [])) & set(second.get("binds", [])))
            findings.append(Finding(
                code="UNDIFFERENTIATED_COMMISSION_OVERLAP",
                severity=ERROR,
                subject=urn("commission-pair",
                            "+".join(sorted((first["commission_id"], second["commission_id"])))),
                detail=(
                    f"{first['commission_id']} and {second['commission_id']} both assert "
                    f"whole-operation authority over {', '.join(overlap)} with no supersession edge"
                    + (" and both bind the same runtime actor" if shared_actor else "")
                ),
                evidence={
                    "overlapping_namespace": overlap,
                    "first": {"id": first["commission_id"], "path": first["path"],
                              "markers": first_whole, "binds": first.get("binds", [])},
                    "second": {"id": second["commission_id"], "path": second["path"],
                               "markers": second_whole, "binds": second.get("binds", [])},
                    "provenance": provenance(DOCUMENTED, method="commission register scope comparison"),
                },
            ))
    return findings


def _whole_operation(commission: dict[str, Any], markers: Sequence[str]) -> list[str]:
    text = " ".join(commission.get("scope_text", "")).lower() if isinstance(
        commission.get("scope_text"), list) else str(commission.get("scope_text", "")).lower()
    return [marker for marker in markers if marker in text]


def check_commission_resolution(commissions: list[dict[str, Any]],
                                register_ids: set[str]) -> list[Finding]:
    """AGENTS.md rule 8: every active commission must resolve through the register."""
    findings: list[Finding] = []
    for commission in commissions:
        if not commission.get("active", True):
            continue
        if commission["commission_id"] in register_ids:
            continue
        findings.append(Finding(
            code="COMMISSION_UNRESOLVED_IN_REGISTER",
            severity=ERROR,
            subject=urn("commission", commission["commission_id"]),
            detail=(
                f"{commission['commission_id']} is active in {commission['path']} but is absent from "
                "state/operator-system/COMMISSION_REGISTER.jsonl, so it cannot resolve one function, "
                "appointment, authority envelope, runtime binding and return route"
            ),
            evidence={"path": commission["path"], "register_ids": sorted(register_ids)},
        ))
    return findings


# --------------------------------------------------------------------------
# integration state
# --------------------------------------------------------------------------


def check_integration_reality(graph: dict[str, Any], pull_requests: list[dict[str, Any]],
                              ladder: AdmissionLadder) -> list[Finding]:
    """A PR is not integration, and a stack of PRs is a single unlanded chain."""
    findings: list[Finding] = []
    nodes = graph["nodes"]
    open_prs = [pr for pr in pull_requests if pr.get("state") == "OPEN"]

    heads = {pr["headRefName"] for pr in open_prs}
    bases = {pr["baseRefName"] for pr in open_prs}
    stacked = sorted(heads & bases)
    if stacked:
        findings.append(Finding(
            code="STACKED_UNLANDED_PR_CHAIN",
            severity=ERROR,
            subject=urn("integration", "open-pr-stack"),
            detail=(
                f"{len(stacked)} branch(es) are simultaneously the head of one open pull request and "
                f"the base of another: {', '.join(stacked)}. Nothing in the chain can land until the "
                "bottom lands, so every state above it is proposed integration, not integration"
            ),
            evidence={
                "stacked_branches": stacked,
                "open_pr_count": len(open_prs),
                "provenance": provenance(DIRECTLY_REPRODUCED,
                                         method="gh pr list --state all --json headRefName,baseRefName"),
            },
        ))

    for pr in open_prs:
        head = nodes.get(pr["headRefName"])
        if head and head["merged_into_trunk"]:
            continue
        findings.append(Finding(
            code="PR_TREATED_AS_CAPABILITY",
            severity=WARNING,
            subject=urn("pull-request", str(pr["number"])),
            detail=(
                f"PR #{pr['number']} ({pr['headRefName']} -> {pr['baseRefName']}) is open and its head "
                "is not an ancestor of the trunk; PULL_REQUEST_EXISTS cannot lift any subject above "
                f"{ladder.ceiling}"
            ),
            evidence={"number": pr["number"], "head": pr["headRefName"], "base": pr["baseRefName"]},
        ))

    orphaned = sorted(name for name, node in nodes.items() if node["classification"] == REF_ORPHANED)
    if orphaned:
        findings.append(Finding(
            code="ORPHANED_REF_POPULATION",
            severity=WARNING,
            subject=urn("integration", "orphaned-refs"),
            detail=(
                f"{len(orphaned)} remote refs share no ancestry with {graph['trunk']} and therefore "
                "cannot be integrated by any ordinary merge; they are addressable evidence, not lineage"
            ),
            evidence={"count": len(orphaned), "sample": orphaned[:8],
                      "provenance": provenance(DIRECTLY_REPRODUCED,
                                               method="containment DAG over all remote heads")},
        ))

    tokens = sorted(name for name, node in nodes.items()
                    if node["ref_role"] in (REF_ROLE_LEASE, REF_ROLE_CANARY))
    if tokens:
        findings.append(Finding(
            code="COORDINATION_TOKENS_COUNTED_AS_SCALE",
            severity=WARNING,
            subject=urn("integration", "coordination-tokens"),
            detail=(
                f"{len(tokens)} of {graph['ref_count']} remote refs carry a single coordination file "
                "(a lease claim or a route canary) and no work; counting refs as delivered scale "
                "counts mutexes"
            ),
            evidence={"count": len(tokens), "sample": tokens[:8],
                      "provenance": provenance(DIRECTLY_REPRODUCED,
                                               method="git ls-tree -r --name-only per ref")},
        ))
    return findings


# --------------------------------------------------------------------------
# compilation entry point
# --------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
    return rows


class Compiler:
    """Compiles the current-state graph and runs every fail-closed gate."""

    def __init__(self, repo_root: Path = REPO_ROOT, ledger_dir: Path = LEDGER_DIR,
                 git: GitEvidence | None = None) -> None:
        self.repo_root = repo_root
        self.ledger_dir = ledger_dir
        self.git = git or GitEvidence(repo_root)
        self.contract = load_json(ledger_dir / "admission-ladder.json")
        self.scopes = load_json(ledger_dir / "currentness-scopes.json")
        self.ledger = load_json(ledger_dir / "workstream-ledger.json")
        self.ladder = AdmissionLadder(self.contract)

    def compile(self) -> dict[str, Any]:
        live = self.scopes["live_branches"]
        # Lane branches are live addresses declared by the group manifest, but they are not
        # currentness authorities, so they classify refs without competing for pointer scopes.
        addressed = list(live) + list(self.scopes.get("lane_branches", []))
        graph = compile_ref_graph(self.git, addressed, trunk=self.scopes.get("trunk", "main"))
        currentness = compile_currentness(self.git, self.scopes["scopes"], live)
        lineage = compile_version_lineage(self.git, self.scopes.get("lineage_ref", "HEAD"))

        findings: list[Finding] = []
        for scope in currentness.values():
            if scope["state"] == "UNRESOLVABLE_COMPETING_CLAIMS":
                findings.append(Finding(
                    code="COMPETING_CURRENTNESS_CLAIM",
                    severity=ERROR,
                    subject=scope["urn"],
                    detail=(
                        f"{scope['scope_id']} resolves to {scope['variant_count']} distinct blobs across "
                        "the live branch set with no declared supersession; currentness is unresolvable "
                        "and every consumer must fail closed"
                    ),
                    evidence={"variants": scope["variants"], "absent_on": scope["absent_on"],
                              "provenance": scope["provenance"]},
                ))
            elif scope["state"] == "ABSENT" and scope.get("required", True):
                findings.append(Finding(
                    code="CURRENTNESS_SCOPE_ABSENT",
                    severity=WARNING,
                    subject=scope["urn"],
                    detail=f"{scope['scope_id']} is absent on every live branch",
                    evidence={"paths": scope["paths"]},
                ))

        for family in lineage.values():
            if family["internal_gaps"]:
                findings.append(Finding(
                    code="LINEAGE_INTERNAL_GAP",
                    severity=WARNING,
                    subject=family["urn"],
                    detail=(
                        f"{family['family']} observes versions {family['observed_versions']} with "
                        f"{family['internal_gaps']} absent inside the range"
                    ),
                    evidence={"observed": family["observed_versions"], "gaps": family["internal_gaps"]},
                ))

        findings.extend(detect_phantom_versions(self.git, self.repo_root,
                                                self.scopes.get("version_tokens", [])))
        findings.extend(check_commission_differentiation(self.ledger.get("commissions", []),
                                                         self.contract))
        register_ids = {
            row.get("commission_id")
            for row in load_jsonl(self.repo_root / "state/operator-system/COMMISSION_REGISTER.jsonl")
        }
        findings.extend(check_commission_resolution(self.ledger.get("commissions", []), register_ids))
        findings.extend(check_integration_reality(graph, self.ledger.get("pull_requests", []),
                                                  self.ladder))

        workstreams: dict[str, Any] = {}
        for workstream in self.ledger.get("workstreams", []):
            subject = workstream["workstream_id"]
            entries = workstream.get("evidence", [])
            admitted, subject_findings = self.ladder.evaluate(
                subject, workstream["claimed_state"], entries)
            findings.extend(subject_findings)
            findings.extend(check_reproducibility(self.repo_root, subject, entries, self.contract,
                                                  self.git))
            classified = self.ladder.classify_evidence(entries)
            workstreams[subject] = {
                "urn": urn("workstream", subject),
                "workstream_id": subject,
                "name": workstream.get("name", ""),
                "owner": workstream.get("owner", ""),
                "claimed_state": workstream["claimed_state"],
                "admitted_state": admitted,
                "overclaimed": admitted != workstream["claimed_state"],
                "admissible_evidence": [e["evidence_class"] for e in classified["admissible"]],
                "non_admissible_evidence": [e["evidence_class"] for e in classified["rejected"]],
                "evidence": entries,
                "provenance": workstream.get("provenance", provenance(DOCUMENTED, method="lane ledger")),
            }

        projection = {
            "tool": {"id": TOOL_ID, "version": TOOL_VERSION},
            "ledger_revision": self.ledger.get("revision"),
            "trunk": graph["trunk"],
            "trunk_head": graph["trunk_head"],
            "ref_count": graph["ref_count"],
            "ref_classification_counts": _counts(graph["nodes"], "classification"),
            "ref_role_counts": _counts(graph["nodes"], "ref_role"),
            "refs": graph["nodes"],
            "currentness_scopes": currentness,
            "version_lineage": lineage,
            "workstreams": workstreams,
            "admission_counts": _admission_counts(workstreams),
            "findings": [f.as_dict() for f in findings],
            "finding_counts": _finding_counts(findings),
            "fail_closed": any(f.severity == ERROR for f in findings),
        }
        projection["projection_sha256"] = canonical_sha256(
            {k: v for k, v in projection.items() if k != "projection_sha256"})
        return projection

    def resolve(self, scope_id: str) -> tuple[int, str]:
        """Fail-closed pointer resolution for a single scope."""
        live = self.scopes["live_branches"]
        currentness = compile_currentness(self.git, self.scopes["scopes"], live)
        scope = currentness.get(scope_id)
        if scope is None:
            return 2, f"UNKNOWN SCOPE: {scope_id}"
        if scope["state"] == "UNRESOLVABLE_COMPETING_CLAIMS":
            lines = [f"REFUSED: {scope_id} has {scope['variant_count']} competing current claims"]
            for variant in scope["variants"]:
                lines.append(f"  {variant['blob'][:12]}  {variant['path']}  <- {', '.join(variant['branches'])}")
            lines.append("Resolution is withheld until a supersession edge is declared.")
            return 1, "\n".join(lines)
        if scope["state"] == "ABSENT":
            return 1, f"REFUSED: {scope_id} is absent on every live branch"
        return 0, f"RESOLVED: {scope_id} -> {scope['resolved_blob']} ({scope['variants'][0]['path']})"


def _counts(nodes: dict[str, Any], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        counts[node[key]] += 1
    return dict(sorted(counts.items()))


def _admission_counts(workstreams: dict[str, Any]) -> dict[str, dict[str, int]]:
    claimed: dict[str, int] = defaultdict(int)
    admitted: dict[str, int] = defaultdict(int)
    for workstream in workstreams.values():
        claimed[workstream["claimed_state"]] += 1
        admitted[workstream["admitted_state"]] += 1
    return {"claimed": dict(sorted(claimed.items())), "admitted": dict(sorted(admitted.items()))}


def _finding_counts(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for finding in findings:
        counts[finding.code] += 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def _print_report(projection: dict[str, Any]) -> None:
    print(f"{TOOL_ID} {TOOL_VERSION}")
    print(f"trunk {projection['trunk']} @ {projection['trunk_head']}")
    print(f"refs {projection['ref_count']}  " + "  ".join(
        f"{k}={v}" for k, v in projection["ref_classification_counts"].items()))
    print("ref roles  " + "  ".join(f"{k}={v}" for k, v in projection["ref_role_counts"].items()))
    print("admission claimed  " + "  ".join(
        f"{k}={v}" for k, v in projection["admission_counts"]["claimed"].items()))
    print("admission admitted " + "  ".join(
        f"{k}={v}" for k, v in projection["admission_counts"]["admitted"].items()))
    print()
    for finding in projection["findings"]:
        print(f"{finding['severity']}: [{finding['code']}] {finding['subject']}")
        print(f"    {finding['detail']}")
    print()
    print("findings  " + "  ".join(f"{k}={v}" for k, v in projection["finding_counts"].items()))
    print(f"projection_sha256 {projection['projection_sha256']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="currentctl", description=__doc__.splitlines()[0])
    parser.add_argument("command",
                        choices=("compile", "validate", "project", "resolve", "reproduce"))
    parser.add_argument("--scope", help="scope id for `resolve`")
    parser.add_argument("--out", help="write the projection JSON to this path")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--ledger-dir", default=str(LEDGER_DIR))
    args = parser.parse_args(argv)

    compiler = Compiler(Path(args.repo_root), Path(args.ledger_dir))

    if args.command == "resolve":
        if not args.scope:
            parser.error("resolve requires --scope")
        code, message = compiler.resolve(args.scope)
        print(message)
        return code

    if args.command == "reproduce":
        findings = reproduce_commands(compiler.repo_root, compiler.ledger)
        for finding in findings:
            print(f"FAIL: [{finding.code}] {finding.detail}")
        if findings:
            return 1
        print("PASS: every REPRODUCIBLE_COMMAND re-ran with its claimed exit code")
        return 0

    projection = compiler.compile()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.command == "project":
        print(json.dumps(projection, indent=2, sort_keys=True))
        return 0

    _print_report(projection)

    if args.command == "validate":
        return 1 if projection["fail_closed"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
