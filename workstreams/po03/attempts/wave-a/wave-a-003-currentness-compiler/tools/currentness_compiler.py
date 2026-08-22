#!/usr/bin/env python3
"""Pointer-driven currentness compiler for the Obzio instruction estate.

The compiler answers one falsifiable question: starting from a declared
entrypoint at one immutable commit, which repository objects are current
launch surfaces, and does any superseded object reach a current launch
surface?

Every byte is read through ``git cat-file`` at a pinned commit, so the result
depends on immutable history rather than on a warm working tree. Supersession
is only accepted from anchored declarations (a ``superseded*`` pointer key, a
``standing`` value that *starts* with the superseded prefix, an explicit spec
entry, or a disposition row). Unanchored substring matches are reported as
near misses instead of being treated as supersession, because current Obzio
standings legitimately mention superseded predecessors inside their own value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any, Iterable

COMPILER_VERSION = "PO03-CURRENTNESS-COMPILER-v1"
SPEC_VERSION = "PO03-CURRENTNESS-SPEC-v1"
BACKTICKED = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
TABLE_ROW = re.compile(r"^\|(?P<cells>.*)\|\s*$")
PATHLIKE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/\-]*$")
GENERIC_LOCATOR_KEYS = frozenset({"path", "paths", "uri", "url", "file", "files", "target", "location"})
DEFAULT_ROUTING_ROLES = ("entrypoint_order", "resolve_in_order")

CLASS_CURRENT = "CURRENT_LAUNCH_SURFACE"
CLASS_EVIDENCE = "IMMUTABLE_EVIDENCE"
CLASS_SUPERSEDED = "RETAINED_SUPERSEDED_EVIDENCE"

GATE_PASS = "PASS"
GATE_FAIL = "FAIL"

EXIT_PASS = 0
EXIT_USAGE = 2
EXIT_GATE_FAIL = 3


class CompilerError(ValueError):
    """Raised when the compiler cannot read a pinned source or a valid spec."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git(repository: str, *arguments: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", repository, *arguments),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise CompilerError(
            f"git {' '.join(arguments)} failed: {result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


def resolve_commit(repository: str, revision: str) -> str:
    return _git(repository, "rev-parse", f"{revision}^{{commit}}").decode("ascii").strip()


def tracked_paths(repository: str, commit: str) -> set[str]:
    listing = _git(repository, "ls-tree", "-r", "-z", "--name-only", commit)
    return {name for name in listing.decode("utf-8").split("\0") if name}


def read_blob(repository: str, commit: str, path: str) -> bytes:
    return _git(repository, "cat-file", "blob", f"{commit}:{path}")


def load_spec(repository: str, commit: str, spec_path: str) -> tuple[dict[str, Any], str]:
    """Read the compilation spec from the pinned commit, never the worktree."""
    payload = read_blob(repository, commit, spec_path)
    try:
        spec = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompilerError(f"spec is not immutable UTF-8 JSON at {commit}:{spec_path}") from exc
    if not isinstance(spec, dict) or spec.get("spec_version") != SPEC_VERSION:
        raise CompilerError(f"spec must be a {SPEC_VERSION} object")
    for field in (
        "entrypoint",
        "entrypoint_section",
        "superseded_key_pattern",
        "superseded_standing_prefix",
        "lineage_key_pattern",
        "absence_evidence_key_pattern",
    ):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise CompilerError(f"spec field must be a non-empty string: {field}")
    for field in ("single_valued_roles", "evidence_roles", "disposition_documents", "explicit_superseded"):
        if not isinstance(spec.get(field, []), list):
            raise CompilerError(f"spec field must be a list: {field}")
    depth = spec.get("max_depth", 8)
    if not isinstance(depth, int) or depth < 1:
        raise CompilerError("spec max_depth must be a positive integer")
    return spec, sha256_bytes(payload)


def _normalize_candidate(value: str) -> str | None:
    candidate = value.strip().strip("`").rstrip("/")
    if not candidate or not PATHLIKE.fullmatch(candidate):
        return None
    posix = PurePosixPath(candidate)
    if posix.is_absolute() or ".." in posix.parts or posix.as_posix() != candidate:
        return None
    return candidate


def entrypoint_references(text: str, section_title: str) -> list[str]:
    """Extract ordered backticked repository references from one section."""
    references: list[str] = []
    inside = False
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading is not None:
            inside = heading.group("title").strip().lower() == section_title.strip().lower()
            continue
        if not inside:
            continue
        for token in BACKTICKED.findall(line):
            candidate = _normalize_candidate(token)
            if candidate is not None and candidate not in references:
                references.append(candidate)
    return references


def _role_of(key_path: tuple[str, ...]) -> str:
    """Name the pointer role, skipping generic locator keys.

    Obzio pointers wrap their target in a locator object, so the literal leaf
    key is usually ``path``. The role that carries routing meaning is the
    enclosing pointer key, for example ``selected_pointer`` or
    ``superseded_pointer``.
    """
    named = [key for key in key_path if not key.startswith("[")]
    for key in reversed(named):
        if key not in GENERIC_LOCATOR_KEYS:
            return key
    return named[-1] if named else "root"


def looks_like_repository_file(candidate: str) -> bool:
    """Judge whether an untracked string was meant to name a repository file.

    Only values that carry a directory separator and a short file extension are
    treated as broken references, so prose, identifiers and bare directory
    names are not reported as missing objects.
    """
    if "/" not in candidate:
        return False
    suffix = PurePosixPath(candidate).suffix
    return bool(re.fullmatch(r"\.[A-Za-z0-9]{2,5}", suffix))


def json_references(document: Any, tracked: set[str]) -> list[dict[str, Any]]:
    """Walk one pointer document and yield every tracked-path reference.

    ``standing`` is read from the object that also carries the reference, so a
    pointer's declared standing travels with the edge instead of being guessed
    from a filename.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any, key_path: tuple[str, ...], standing: str | None) -> None:
        if isinstance(node, dict):
            local_standing = node.get("standing") if isinstance(node.get("standing"), str) else standing
            for key in sorted(node):
                walk(node[key], key_path + (key,), local_standing)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, key_path + (f"[{index}]",), standing)
        elif isinstance(node, str):
            candidate = _normalize_candidate(node)
            if candidate is None:
                return
            if candidate in tracked or looks_like_repository_file(candidate):
                found.append(
                    {
                        "target": candidate,
                        "key_path": "/".join(key_path),
                        "role": _role_of(key_path),
                        "standing": standing,
                        "present": candidate in tracked,
                    }
                )

    walk(document, (), None)
    return found


def disposition_rows(text: str) -> list[dict[str, Any]]:
    """Parse a disposition table into path-resolved and unresolved rows."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = TABLE_ROW.match(line.strip())
        if match is None:
            continue
        cells = [cell.strip() for cell in match.group("cells").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":", " "}:
            continue
        if cells[0].lower().startswith("object"):
            continue
        paths = [
            candidate
            for candidate in (_normalize_candidate(token) for token in BACKTICKED.findall(cells[0]))
            if candidate is not None
        ]
        rows.append({"object": cells[0], "disposition": cells[1], "paths": paths})
    return rows


def _superseded_declarations(
    repository: str,
    commit: str,
    spec: dict[str, Any],
    tracked: set[str],
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Collect anchored supersession declarations from spec and disposition rows."""
    declarations: dict[str, list[str]] = {}
    unresolved: list[dict[str, Any]] = []
    prefix = spec["superseded_standing_prefix"].upper()
    for path in spec.get("explicit_superseded", []):
        candidate = _normalize_candidate(path) if isinstance(path, str) else None
        if candidate is not None:
            declarations.setdefault(candidate, []).append("spec:explicit_superseded")
    for document in spec.get("disposition_documents", []):
        if not isinstance(document, str) or document not in tracked:
            unresolved.append({"document": document, "reason": "DISPOSITION_DOCUMENT_ABSENT_AT_COMMIT"})
            continue
        text = read_blob(repository, commit, document).decode("utf-8", "replace")
        for row in disposition_rows(text):
            if not row["disposition"].upper().startswith(prefix):
                continue
            if not row["paths"]:
                unresolved.append(
                    {
                        "document": document,
                        "object": row["object"],
                        "disposition": row["disposition"],
                        "reason": "SUPERSEDED_ROW_NAMES_NO_REPOSITORY_PATH",
                    }
                )
                continue
            for path in row["paths"]:
                declarations.setdefault(path, []).append(f"disposition:{document}")
    return declarations, unresolved


def compile_currentness(
    *,
    repository: str,
    revision: str,
    spec_path: str,
) -> dict[str, Any]:
    """Compile the current source set from one immutable commit."""
    commit = resolve_commit(repository, revision)
    spec, spec_sha256 = load_spec(repository, commit, spec_path)
    tracked = tracked_paths(repository, commit)
    entrypoint = spec["entrypoint"]
    if entrypoint not in tracked:
        raise CompilerError(f"entrypoint is absent at the pinned commit: {entrypoint}")

    superseded_key = re.compile(spec["superseded_key_pattern"], re.IGNORECASE)
    lineage_key = re.compile(spec["lineage_key_pattern"], re.IGNORECASE)
    absence_key = re.compile(spec["absence_evidence_key_pattern"], re.IGNORECASE)
    standing_prefix = spec["superseded_standing_prefix"].upper()
    single_valued = set(spec.get("single_valued_roles", []))
    evidence_roles = set(spec.get("evidence_roles", []))
    routing_roles = single_valued | set(spec.get("routing_roles", DEFAULT_ROUTING_ROLES))
    max_depth = int(spec.get("max_depth", 8))

    declared_superseded, unresolved_disposition = _superseded_declarations(
        repository, commit, spec, tracked
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    declared_absent: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []
    self_describing: list[dict[str, Any]] = []
    back_references: list[dict[str, Any]] = []
    lineage_references: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    role_targets: dict[str, set[str]] = {}

    def ensure_node(path: str, depth: int) -> dict[str, Any]:
        node = nodes.get(path)
        if node is None:
            payload = read_blob(repository, commit, path)
            node = {
                "path": path,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "depth": depth,
                "roles": [],
                "referenced_by": [],
                "supersession_signals": [],
                "classification": None,
            }
            nodes[path] = node
        node["depth"] = min(node["depth"], depth)
        return node

    def note_supersession(path: str, signal: str) -> None:
        node = nodes[path]
        if signal not in node["supersession_signals"]:
            node["supersession_signals"].append(signal)

    entrypoint_text = read_blob(repository, commit, entrypoint).decode("utf-8", "replace")
    root_node = ensure_node(entrypoint, 0)
    root_node["roles"].append("entrypoint")
    for signal in declared_superseded.get(entrypoint, []):
        note_supersession(entrypoint, signal)

    frontier: list[tuple[str, int, tuple[str, ...]]] = []
    for order, reference in enumerate(entrypoint_references(entrypoint_text, spec["entrypoint_section"])):
        if reference not in tracked:
            missing.append(
                {
                    "target": reference,
                    "referenced_by": entrypoint,
                    "role": "entrypoint_order",
                    "key_path": f"entrypoint_order/[{order}]",
                }
            )
            continue
        node = ensure_node(reference, 1)
        if "entrypoint_order" not in node["roles"]:
            node["roles"].append("entrypoint_order")
        node["referenced_by"].append(entrypoint)
        edges.append(
            {
                "source": entrypoint,
                "target": reference,
                "role": "entrypoint_order",
                "key_path": f"entrypoint_order/[{order}]",
                "standing": None,
            }
        )
        for signal in declared_superseded.get(reference, []):
            note_supersession(reference, signal)
        frontier.append((reference, 1, (entrypoint,)))

    visited: set[str] = set()
    while frontier:
        path, depth, lineage = frontier.pop(0)
        if path in visited:
            continue
        visited.add(path)
        node = nodes[path]
        if node["supersession_signals"]:
            # Superseded objects stay evidence; their subtree is not expanded
            # into launch surfaces.
            continue
        if depth >= max_depth or not path.endswith(".json"):
            continue
        payload = read_blob(repository, commit, path)
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for reference in json_references(document, tracked):
            target = reference["target"]
            role = reference["role"]
            standing = reference["standing"]
            if not reference["present"]:
                record = {
                    "target": target,
                    "referenced_by": path,
                    "role": role,
                    "key_path": reference["key_path"],
                }
                # A role that declares an absence preserves an evidential
                # defect; only an active role naming an absent object is a
                # broken reference.
                sink = declared_absent if absence_key.match(role) else missing
                if record not in sink:
                    sink.append(record)
                continue
            is_superseded_key = bool(superseded_key.match(role))
            is_lineage_key = not is_superseded_key and bool(lineage_key.match(role))
            standing_upper = standing.upper() if isinstance(standing, str) else ""
            is_superseded_standing = standing_upper.startswith(standing_prefix)
            if (
                standing_upper
                and not is_superseded_standing
                and standing_prefix in standing_upper
            ):
                near_miss = {
                    "target": target,
                    "role": role,
                    "standing": standing,
                    "referenced_by": path,
                    "reason": "STANDING_MENTIONS_SUPERSESSION_WITHOUT_DECLARING_IT",
                }
                if near_miss not in near_misses:
                    near_misses.append(near_miss)
            target_node = ensure_node(target, depth + 1)
            if role not in target_node["roles"]:
                target_node["roles"].append(role)
            if path not in target_node["referenced_by"]:
                target_node["referenced_by"].append(path)
            edges.append(
                {
                    "source": path,
                    "target": target,
                    "role": role,
                    "key_path": reference["key_path"],
                    "standing": standing,
                }
            )
            if is_superseded_key:
                note_supersession(target, f"pointer_key:{role}")
            if is_superseded_standing:
                note_supersession(target, "standing_prefix")
            for signal in declared_superseded.get(target, []):
                note_supersession(target, signal)
            if is_lineage_key:
                record = {
                    "target": target,
                    "role": role,
                    "referenced_by": path,
                    "key_path": reference["key_path"],
                    "standing": standing,
                }
                if record not in lineage_references:
                    lineage_references.append(record)
            if role in single_valued and not nodes[target]["supersession_signals"]:
                role_targets.setdefault(role, set()).add(target)
            if target == path:
                # A manifest that names its own path is provenance, not a loop.
                record = {"object": path, "role": role, "key_path": reference["key_path"]}
                if record not in self_describing:
                    self_describing.append(record)
                continue
            if target in lineage:
                record = {
                    "target": target,
                    "referenced_by": path,
                    "role": role,
                    "key_path": reference["key_path"],
                    "lineage": list(lineage),
                }
                if role in routing_roles:
                    violation = {"violation": "ROUTING_POINTER_CYCLE", **record}
                    if violation not in violations:
                        violations.append(violation)
                elif record not in back_references:
                    back_references.append(record)
                continue
            if (
                not is_superseded_key
                and not is_superseded_standing
                and not is_lineage_key
                and role not in evidence_roles
            ):
                frontier.append((target, depth + 1, lineage + (path,)))

    for path, node in nodes.items():
        if node["supersession_signals"]:
            node["classification"] = CLASS_SUPERSEDED
        elif node["roles"] and set(node["roles"]) <= evidence_roles:
            node["classification"] = CLASS_EVIDENCE
        else:
            node["classification"] = CLASS_CURRENT

    for path, node in sorted(nodes.items()):
        if node["classification"] != CLASS_SUPERSEDED:
            continue
        active_roles = sorted(
            {
                edge["role"]
                for edge in edges
                if edge["target"] == path
                and not superseded_key.match(edge["role"])
                and not lineage_key.match(edge["role"])
                and not (
                    isinstance(edge["standing"], str)
                    and edge["standing"].upper().startswith(standing_prefix)
                )
            }
        )
        if active_roles:
            violations.append(
                {
                    "violation": "SUPERSEDED_OBJECT_REACHED_BY_ACTIVE_ROLE",
                    "target": path,
                    "active_roles": active_roles,
                    "supersession_signals": node["supersession_signals"],
                }
            )

    for role, targets in sorted(role_targets.items()):
        if len(targets) > 1:
            violations.append(
                {
                    "violation": "AMBIGUOUS_SINGLE_VALUED_ROLE",
                    "role": role,
                    "targets": sorted(targets),
                }
            )

    for reference in missing:
        violations.append({"violation": "MISSING_REFERENCED_OBJECT", **reference})

    current = sorted(path for path, node in nodes.items() if node["classification"] == CLASS_CURRENT)
    evidence = sorted(path for path, node in nodes.items() if node["classification"] == CLASS_EVIDENCE)
    retained = sorted(path for path, node in nodes.items() if node["classification"] == CLASS_SUPERSEDED)

    report = {
        "compiler_version": COMPILER_VERSION,
        "spec_version": SPEC_VERSION,
        "spec_path": spec_path,
        "spec_sha256": spec_sha256,
        "spec_id": spec.get("spec_id"),
        "commit": commit,
        "entrypoint": entrypoint,
        "entrypoint_sha256": nodes[entrypoint]["sha256"],
        "gate": GATE_FAIL if violations else GATE_PASS,
        "violations": sorted(violations, key=canonical_json),
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "current_launch_surfaces": len(current),
            "immutable_evidence": len(evidence),
            "retained_superseded_evidence": len(retained),
            "missing_references": len(missing),
            "declared_absent_objects": len(declared_absent),
            "substring_near_misses": len(near_misses),
            "self_describing_references": len(self_describing),
            "non_routing_back_references": len(back_references),
            "lineage_references": len(lineage_references),
            "unresolved_disposition_rows": len(unresolved_disposition),
        },
        "current_source_set": current,
        "immutable_evidence_set": evidence,
        "retained_superseded_set": retained,
        "missing_references": sorted(missing, key=canonical_json),
        "declared_absent_objects": sorted(declared_absent, key=canonical_json),
        "substring_near_misses": sorted(near_misses, key=canonical_json),
        "self_describing_references": sorted(self_describing, key=canonical_json),
        "non_routing_back_references": sorted(back_references, key=canonical_json),
        "lineage_references": sorted(lineage_references, key=canonical_json),
        "unresolved_disposition_rows": sorted(unresolved_disposition, key=canonical_json),
        "nodes": [nodes[path] for path in sorted(nodes)],
        "edges": sorted(edges, key=canonical_json),
        "decision_changed": [],
    }
    report["determinism_digest"] = sha256_bytes(canonical_json({k: v for k, v in report.items() if k != "determinism_digest"}))
    return report


def _format_violations(violations: Iterable[dict[str, Any]]) -> str:
    return "\n".join(f"  - {json.dumps(item, sort_keys=True)}" for item in violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile the current Obzio source set from a pinned commit.")
    parser.add_argument("--repository", default=".")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument(
        "--spec",
        default="workstreams/po03/attempts/wave-a/wave-a-003-currentness-compiler/fixtures/spec/currentness.spec.json",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = compile_currentness(
            repository=arguments.repository,
            revision=arguments.commit,
            spec_path=arguments.spec,
        )
    except CompilerError as exc:
        print(f"CURRENTNESS_COMPILER_ERROR {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload = canonical_json(report)
    if arguments.out:
        with open(arguments.out, "wb") as handle:
            handle.write(payload)
    if not arguments.quiet:
        print(
            f"CURRENTNESS_{report['gate']} commit={report['commit'][:12]} "
            f"current={report['counts']['current_launch_surfaces']} "
            f"evidence={report['counts']['immutable_evidence']} "
            f"superseded={report['counts']['retained_superseded_evidence']} "
            f"near_misses={report['counts']['substring_near_misses']} "
            f"digest={report['determinism_digest'][:12]}"
        )
        if report["violations"]:
            print(_format_violations(report["violations"]))
    return EXIT_PASS if report["gate"] == GATE_PASS else EXIT_GATE_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
