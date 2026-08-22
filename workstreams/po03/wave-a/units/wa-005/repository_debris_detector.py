#!/usr/bin/env python3
"""Read-only repository debris and superseded-transport classifier.

The detector consumes an explicit, hash-bound inventory and emits dispositions.
It never deletes, moves, renames, or edits an inventoried artifact.  Ambiguous
metadata, integrity failures, links, and unique bytes all fail closed to a
retention disposition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


INVENTORY_PROTOCOL = "OBZIO-REPOSITORY-DEBRIS-INVENTORY-v1"
DISPOSITION_PROTOCOL = "OBZIO-REPOSITORY-DISPOSITION-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ROLES = {"MATERIAL", "TRANSPORT", "GENERATED_DEBRIS", "EVIDENCE"}
STANDINGS = {"CURRENT", "SUPERSEDED", "UNKNOWN"}
CLASSIFICATIONS = {
    "CURRENT_MATERIAL",
    "SUPERSEDED_TRANSPORT_REDUNDANT",
    "REDUNDANT_DEBRIS",
    "SUPERSEDED_MATERIAL",
    "SUPERSEDED_UNIQUE_EVIDENCE",
    "AMBIGUOUS_REVIEW",
}
DISPOSITIONS = {
    "RETAIN",
    "SUPERSEDE_RETAIN",
    "REVIEW_FOR_REMOVAL",
    "RETAIN_SUPERSEDED",
    "RETAIN_AS_EVIDENCE",
    "RETAIN_PENDING_REVIEW",
}

INVENTORY_KEYS = {"protocol_version", "root", "artifacts"}
ARTIFACT_KEYS = {
    "artifact_id",
    "path",
    "role",
    "standing",
    "expected_sha256",
    "expected_bytes",
    "superseded_by",
    "evidence_claims",
}


class DetectorError(ValueError):
    """An inventory or output violates the detector contract."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DetectorError(f"cannot read {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DetectorError(f"{path}: expected strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DetectorError(f"{path}: root must be a JSON object")
    return value, raw


def _relative_posix(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DetectorError(f"{field}: must be a non-empty string")
    if "\\" in value:
        raise DetectorError(f"{field}: backslashes are not canonical POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise DetectorError(f"{field}: must be a canonical relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise DetectorError(f"{field}: traversal and empty segments are forbidden")
    return value


def _validate_inventory(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if set(doc) != INVENTORY_KEYS:
        missing = sorted(INVENTORY_KEYS - set(doc))
        extra = sorted(set(doc) - INVENTORY_KEYS)
        raise DetectorError(f"inventory keys mismatch missing={missing} extra={extra}")
    if doc["protocol_version"] != INVENTORY_PROTOCOL:
        raise DetectorError("$.protocol_version: unsupported")
    _relative_posix(doc["root"], "$.root")
    artifacts = doc["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise DetectorError("$.artifacts: must be a non-empty array")

    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for index, artifact in enumerate(artifacts):
        prefix = f"$.artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise DetectorError(f"{prefix}: must be an object")
        if set(artifact) != ARTIFACT_KEYS:
            missing = sorted(ARTIFACT_KEYS - set(artifact))
            extra = sorted(set(artifact) - ARTIFACT_KEYS)
            raise DetectorError(f"{prefix}: keys mismatch missing={missing} extra={extra}")
        artifact_id = artifact["artifact_id"]
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise DetectorError(f"{prefix}.artifact_id: must be non-empty")
        if artifact_id in ids:
            raise DetectorError(f"{prefix}.artifact_id: duplicate {artifact_id!r}")
        ids.add(artifact_id)
        artifact_path = _relative_posix(artifact["path"], f"{prefix}.path")
        if artifact_path in paths:
            raise DetectorError(f"{prefix}.path: duplicate {artifact_path!r}")
        paths.add(artifact_path)
        if artifact["role"] not in ROLES:
            raise DetectorError(f"{prefix}.role: unsupported")
        if artifact["standing"] not in STANDINGS:
            raise DetectorError(f"{prefix}.standing: unsupported")
        if not isinstance(artifact["expected_sha256"], str) or not SHA256_RE.fullmatch(
            artifact["expected_sha256"]
        ):
            raise DetectorError(f"{prefix}.expected_sha256: must be lowercase SHA-256")
        if (
            not isinstance(artifact["expected_bytes"], int)
            or isinstance(artifact["expected_bytes"], bool)
            or artifact["expected_bytes"] < 0
        ):
            raise DetectorError(f"{prefix}.expected_bytes: must be an integer >= 0")
        successor = artifact["superseded_by"]
        if successor is not None and (
            not isinstance(successor, str) or not successor.strip()
        ):
            raise DetectorError(f"{prefix}.superseded_by: must be null or non-empty")
        claims = artifact["evidence_claims"]
        if not isinstance(claims, list) or any(
            not isinstance(claim, str) or not claim.strip() for claim in claims
        ):
            raise DetectorError(f"{prefix}.evidence_claims: must contain non-empty strings")
        if len(set(claims)) != len(claims):
            raise DetectorError(f"{prefix}.evidence_claims: duplicate claim")
        normalized.append(dict(artifact))
    return normalized


def _inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _inspect_file(root: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    relative = PurePosixPath(artifact["path"])
    candidate = root.joinpath(*relative.parts)
    result: dict[str, Any] = {
        "status": "MISSING",
        "expected_sha256": artifact["expected_sha256"],
        "actual_sha256": None,
        "expected_bytes": artifact["expected_bytes"],
        "actual_bytes": None,
    }
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
    except OSError:
        result["status"] = "MISSING"
        return result
    if not _inside(resolved_parent, root):
        result["status"] = "PARENT_ESCAPE_REFUSED"
        return result
    checked = resolved_parent / candidate.name
    try:
        mode = checked.lstat().st_mode
    except OSError:
        result["status"] = "MISSING"
        return result
    if stat.S_ISLNK(mode):
        result["status"] = "SYMLINK_REFUSED"
        return result
    if not stat.S_ISREG(mode):
        result["status"] = "NON_REGULAR_REFUSED"
        return result
    try:
        data = checked.read_bytes()
    except OSError:
        result["status"] = "READ_FAILED"
        return result
    result["actual_sha256"] = _sha256_bytes(data)
    result["actual_bytes"] = len(data)
    if (
        result["actual_sha256"] == artifact["expected_sha256"]
        and result["actual_bytes"] == artifact["expected_bytes"]
    ):
        result["status"] = "VERIFIED"
    else:
        result["status"] = "CLAIM_MISMATCH"
    return result


def _relation_errors(artifacts: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    errors: dict[str, list[str]] = defaultdict(list)
    for artifact in artifacts:
        artifact_id = artifact["artifact_id"]
        successor_id = artifact["superseded_by"]
        standing = artifact["standing"]
        if standing == "SUPERSEDED" and successor_id is None:
            errors[artifact_id].append("SUPERSEDED_WITHOUT_SUCCESSOR")
        if standing != "SUPERSEDED" and successor_id is not None:
            errors[artifact_id].append("SUCCESSOR_ON_NON_SUPERSEDED_ARTIFACT")
        if successor_id is None:
            continue
        if successor_id == artifact_id:
            errors[artifact_id].append("SELF_SUPERSESSION")
            continue
        successor = by_id.get(successor_id)
        if successor is None:
            errors[artifact_id].append("SUCCESSOR_NOT_IN_INVENTORY")
        elif successor["standing"] != "CURRENT":
            errors[artifact_id].append("SUCCESSOR_NOT_CURRENT")

    for artifact in artifacts:
        origin = artifact["artifact_id"]
        seen: set[str] = set()
        current = origin
        while current in by_id:
            successor_id = by_id[current]["superseded_by"]
            if successor_id is None or successor_id not in by_id:
                break
            if successor_id == origin or successor_id in seen:
                errors[origin].append("SUPERSESSION_CYCLE")
                break
            seen.add(current)
            current = successor_id
    return errors


def _classify(
    artifact: dict[str, Any],
    integrity: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    inspections: dict[str, dict[str, Any]],
    digest_members: dict[str, list[str]],
    claim_counts: Counter[str],
    relation_errors: list[str],
) -> dict[str, Any]:
    artifact_id = artifact["artifact_id"]
    actual_sha = integrity["actual_sha256"]
    duplicate_ids = (
        sorted(item for item in digest_members.get(actual_sha, []) if item != artifact_id)
        if actual_sha is not None
        else []
    )
    unique_claims = sorted(
        claim for claim in artifact["evidence_claims"] if claim_counts[claim] == 1
    )
    content_unique = integrity["status"] == "VERIFIED" and not duplicate_ids
    rationale: list[str] = []

    classification = "AMBIGUOUS_REVIEW"
    disposition = "RETAIN_PENDING_REVIEW"
    protection_required = True
    removal_eligible = False

    if integrity["status"] != "VERIFIED":
        rationale.append(f"integrity is {integrity['status']}; fail closed")
    elif relation_errors:
        rationale.append("invalid supersession metadata: " + ", ".join(relation_errors))
    elif artifact["standing"] == "UNKNOWN":
        rationale.append("standing is UNKNOWN; explicit disposition requires review")
    elif artifact["standing"] == "CURRENT":
        classification = "CURRENT_MATERIAL"
        disposition = "RETAIN"
        rationale.append("explicit standing is CURRENT")
    else:
        successor_id = artifact["superseded_by"]
        successor_integrity = inspections[successor_id]
        same_as_successor = (
            actual_sha is not None
            and successor_integrity["status"] == "VERIFIED"
            and actual_sha == successor_integrity["actual_sha256"]
        )
        unique_evidence = bool(unique_claims) or content_unique or artifact["role"] == "EVIDENCE"
        if unique_evidence:
            classification = "SUPERSEDED_UNIQUE_EVIDENCE"
            disposition = "RETAIN_AS_EVIDENCE"
            rationale.append("superseded bytes or evidence claims are not fully represented elsewhere")
        elif not same_as_successor:
            classification = "SUPERSEDED_MATERIAL"
            disposition = "RETAIN_SUPERSEDED"
            rationale.append("supersession is valid but successor is not byte-equivalent")
        elif artifact["role"] == "TRANSPORT":
            classification = "SUPERSEDED_TRANSPORT_REDUNDANT"
            disposition = "SUPERSEDE_RETAIN"
            removal_eligible = True
            protection_required = False
            rationale.append("hash-verified transport duplicate has a CURRENT successor")
        elif artifact["role"] == "GENERATED_DEBRIS":
            classification = "REDUNDANT_DEBRIS"
            disposition = "REVIEW_FOR_REMOVAL"
            removal_eligible = True
            protection_required = False
            rationale.append("hash-verified generated duplicate has a CURRENT successor")
        else:
            classification = "SUPERSEDED_MATERIAL"
            disposition = "RETAIN_SUPERSEDED"
            rationale.append("superseded material remains lineage evidence")

    has_unique_evidence = (
        classification == "SUPERSEDED_UNIQUE_EVIDENCE"
        or (
            integrity["status"] == "VERIFIED"
            and (bool(unique_claims) or content_unique)
            and artifact["standing"] != "CURRENT"
        )
    )
    return {
        "artifact_id": artifact_id,
        "path": artifact["path"],
        "role": artifact["role"],
        "standing": artifact["standing"],
        "classification": classification,
        "disposition": disposition,
        "integrity": integrity,
        "content": {
            "duplicate_artifact_ids": duplicate_ids,
            "unique_bytes": content_unique,
        },
        "evidence": {
            "claims": sorted(artifact["evidence_claims"]),
            "unique_claims": unique_claims,
            "has_unique_evidence": has_unique_evidence,
        },
        "supersession": {
            "superseded_by": artifact["superseded_by"],
            "relation_errors": sorted(set(relation_errors)),
        },
        "protection_required": protection_required,
        "removal_eligible_after_review": removal_eligible,
        "rationale": rationale,
    }


def scan_inventory(inventory_path: Path) -> dict[str, Any]:
    inventory_path = inventory_path.resolve(strict=True)
    doc, raw = _read_json_object(inventory_path)
    artifacts = _validate_inventory(doc)
    root_field = PurePosixPath(doc["root"])
    root = inventory_path.parent.joinpath(*root_field.parts).resolve(strict=True)
    if not root.is_dir():
        raise DetectorError("$.root: must resolve to a directory")

    inspections = {
        artifact["artifact_id"]: _inspect_file(root, artifact) for artifact in artifacts
    }
    digest_members: dict[str, list[str]] = defaultdict(list)
    claim_counts: Counter[str] = Counter()
    for artifact in artifacts:
        artifact_id = artifact["artifact_id"]
        inspection = inspections[artifact_id]
        if inspection["status"] == "VERIFIED":
            digest_members[inspection["actual_sha256"]].append(artifact_id)
            claim_counts.update(artifact["evidence_claims"])

    by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    relationship_errors = _relation_errors(artifacts)
    dispositions = [
        _classify(
            artifact,
            inspections[artifact["artifact_id"]],
            by_id,
            inspections,
            digest_members,
            claim_counts,
            relationship_errors[artifact["artifact_id"]],
        )
        for artifact in artifacts
    ]
    counts = Counter(item["classification"] for item in dispositions)
    result = {
        "protocol_version": DISPOSITION_PROTOCOL,
        "inventory_path": inventory_path.name,
        "inventory_sha256": _sha256_bytes(raw),
        "scan_mode": "READ_ONLY",
        "mutation_performed": False,
        "summary": {
            "artifact_count": len(dispositions),
            "classification_counts": dict(sorted(counts.items())),
            "protected_count": sum(
                1 for item in dispositions if item["protection_required"]
            ),
            "removal_candidate_count": sum(
                1 for item in dispositions if item["removal_eligible_after_review"]
            ),
        },
        "dispositions": dispositions,
        "decision_changed": [],
    }
    errors = validate_disposition(result)
    if errors:
        raise DetectorError("internal disposition invariant failed: " + "; ".join(errors))
    return result


def validate_disposition(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "protocol_version",
        "inventory_path",
        "inventory_sha256",
        "scan_mode",
        "mutation_performed",
        "summary",
        "dispositions",
        "decision_changed",
    }
    if set(doc) != required:
        errors.append("$: keys do not match disposition contract")
        return errors
    if doc["protocol_version"] != DISPOSITION_PROTOCOL:
        errors.append("$.protocol_version: unsupported")
    if not isinstance(doc["inventory_sha256"], str) or not SHA256_RE.fullmatch(
        doc["inventory_sha256"]
    ):
        errors.append("$.inventory_sha256: invalid")
    if doc["scan_mode"] != "READ_ONLY" or doc["mutation_performed"] is not False:
        errors.append("$: detector must be read-only")
    if doc["decision_changed"] != []:
        errors.append("$.decision_changed: must be []")
    dispositions = doc["dispositions"]
    if not isinstance(dispositions, list) or not dispositions:
        errors.append("$.dispositions: must be non-empty")
        return errors
    ids: set[str] = set()
    counts: Counter[str] = Counter()
    protected = 0
    removal_candidates = 0
    for index, item in enumerate(dispositions):
        prefix = f"$.dispositions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            errors.append(f"{prefix}.artifact_id: invalid")
        elif artifact_id in ids:
            errors.append(f"{prefix}.artifact_id: duplicate")
        ids.add(artifact_id)
        classification = item.get("classification")
        disposition = item.get("disposition")
        if classification not in CLASSIFICATIONS:
            errors.append(f"{prefix}.classification: invalid")
        else:
            counts[classification] += 1
        if disposition not in DISPOSITIONS:
            errors.append(f"{prefix}.disposition: invalid")
        if disposition == "DELETE":
            errors.append(f"{prefix}.disposition: deletion is forbidden")
        integrity = item.get("integrity")
        evidence = item.get("evidence")
        protection = item.get("protection_required")
        removal = item.get("removal_eligible_after_review")
        if protection is True:
            protected += 1
        if removal is True:
            removal_candidates += 1
        if isinstance(integrity, dict) and integrity.get("status") != "VERIFIED":
            if protection is not True or disposition != "RETAIN_PENDING_REVIEW":
                errors.append(f"{prefix}: unverified artifact must fail closed")
        if isinstance(evidence, dict) and evidence.get("has_unique_evidence") is True:
            if protection is not True or disposition not in {
                "RETAIN_AS_EVIDENCE",
                "RETAIN_PENDING_REVIEW",
            }:
                errors.append(f"{prefix}: unique evidence must be retained")
        if removal is True and classification not in {
            "REDUNDANT_DEBRIS",
            "SUPERSEDED_TRANSPORT_REDUNDANT",
        }:
            errors.append(f"{prefix}: only verified redundant classes may be removal candidates")
    summary = doc["summary"]
    expected_summary = {
        "artifact_count": len(dispositions),
        "classification_counts": dict(sorted(counts.items())),
        "protected_count": protected,
        "removal_candidate_count": removal_candidates,
    }
    if summary != expected_summary:
        errors.append("$.summary: counts do not reconcile")
    return errors


def _write_new(path: Path, data: bytes, protected_root: Path | None = None) -> None:
    parent = path.parent.resolve(strict=True)
    candidate = parent / path.name
    if protected_root is not None and _inside(candidate, protected_root):
        raise DetectorError("output cannot be written inside the inventoried root")
    try:
        with candidate.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise DetectorError(f"refusing to overwrite output: {candidate}") from exc
    except OSError as exc:
        raise DetectorError(f"cannot write output {candidate}: {exc}") from exc


def _inventory_root(inventory_path: Path) -> Path:
    doc, _ = _read_json_object(inventory_path)
    _validate_inventory(doc)
    root_field = PurePosixPath(doc["root"])
    return inventory_path.parent.joinpath(*root_field.parts).resolve(strict=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("inventory", type=Path)
    scan_parser.add_argument("--output", type=Path)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("document", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            result = scan_inventory(args.inventory)
            data = _json_bytes(result)
            if args.output is None:
                sys.stdout.buffer.write(data)
            else:
                _write_new(
                    args.output,
                    data,
                    protected_root=_inventory_root(args.inventory.resolve(strict=True)),
                )
                print(
                    "CLASSIFIED "
                    f"artifacts={result['summary']['artifact_count']} "
                    f"protected={result['summary']['protected_count']} "
                    f"removal_candidates={result['summary']['removal_candidate_count']}"
                )
        else:
            result, _ = _read_json_object(args.document)
            errors = validate_disposition(result)
            if errors:
                for error in errors:
                    print(f"INVALID: {error}")
                return 1
            print(f"VALID disposition sha256={_sha256_bytes(args.document.read_bytes())}")
    except (DetectorError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
