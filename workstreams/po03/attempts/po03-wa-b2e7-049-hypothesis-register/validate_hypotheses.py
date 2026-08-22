#!/usr/bin/env python3
"""Reject malformed, unhashed, or non-falsifiable hypothesis entries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


COMPARATORS = {
    "less_than",
    "less_than_or_equal",
    "greater_than",
    "greater_than_or_equal",
    "equal",
    "not_equal",
}
VAGUE = ("better", "reasonable", "material", "significant", "appropriate")


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def validate_entry(entry: dict[str, object]) -> list[str]:
    errors: list[str] = []
    required = {
        "hypothesis_id",
        "hypothesis",
        "source_identity",
        "source_claim",
        "refutation_condition",
        "preregistered_at",
        "hypothesis_hash",
        "decision_changed",
    }
    missing = required - entry.keys()
    if missing:
        return [f"missing fields: {sorted(missing)}"]
    source = entry["source_identity"]
    if not isinstance(source, dict):
        errors.append("source_identity must be an object")
    else:
        source_required = {
            "publisher",
            "title",
            "url",
            "fetch_status",
            "page_sha256",
            "text",
            "observed_at",
            "relied_text_sha256",
        }
        if source_required - source.keys():
            errors.append("source identity is incomplete")
        elif hashlib.sha256(str(source["text"]).encode()).hexdigest() != source["relied_text_sha256"]:
            errors.append("relied source text hash mismatch")
        if source.get("text") != entry["source_claim"]:
            errors.append("source claim does not equal frozen relied text")
    refutation = entry["refutation_condition"]
    if not isinstance(refutation, dict):
        errors.append("refutation_condition must be an object")
    else:
        if not isinstance(refutation.get("metric"), str) or not refutation["metric"].strip():
            errors.append("refutation metric is required")
        if refutation.get("comparator") not in COMPARATORS:
            errors.append("refutation comparator must be executable")
        threshold = refutation.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            errors.append("numeric refutation threshold is required")
        sample_size = refutation.get("sample_size")
        if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 1:
            errors.append("positive integer sample_size is required")
        reject_when = refutation.get("reject_when")
        if not isinstance(reject_when, str) or not reject_when.strip():
            errors.append("reject_when is required")
        elif any(word in reject_when.lower() for word in VAGUE):
            errors.append("reject_when contains a non-operational vague term")
    if entry["decision_changed"] != []:
        errors.append("decision_changed must remain empty")
    frozen = dict(entry)
    supplied_hash = frozen.pop("hypothesis_hash")
    if hashlib.sha256(canonical(frozen)).hexdigest() != supplied_hash:
        errors.append("hypothesis hash mismatch")
    return errors


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: invalid JSON: {exc}")
            continue
        entries.append(entry)
        errors.extend(f"line {number}: {error}" for error in validate_entry(entry))
    if len(entries) < 12:
        errors.append(f"requires at least 12 hypotheses, got {len(entries)}")
    ids = [entry.get("hypothesis_id") for entry in entries]
    if len(ids) != len(set(ids)):
        errors.append("hypothesis_id values must be unique")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    errors = validate_file(args.ledger)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(f"VALID: {len(args.ledger.read_text(encoding='utf-8').splitlines())} falsifiable hypotheses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
