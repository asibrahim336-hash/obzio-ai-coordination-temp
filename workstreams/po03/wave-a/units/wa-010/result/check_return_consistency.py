#!/usr/bin/env python3
"""Check a WA-010 producer return against itself.

The return document restates several figures that are also carried as structured
fields: the changed-path count, the artifact count and byte total, the number of
paths read back, and the test counts.  Those restatements are prose, so nothing
stops them from surviving a regeneration that moved the underlying number.  That
is exactly what happened twice on this branch, so the drift is checked rather than
proof-read.

Two families of check run:

* Cross-field checks compare structured fields that must agree with each other,
  including the read-back record's manifest path against the manifest path the
  return declares.  A path label that names a file the commit does not carry is a
  defect even when every digest matches.
* Narrative checks require each restated figure to appear literally in the prose
  that restates it.  A stale figure fails because the current value is absent from
  the sentence, not because a heuristic decided the sentence looks wrong.

Usage::

    python3 -I check_return_consistency.py [ready-to-commit.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RESULT_DIR = Path(__file__).resolve().parent
UNIT_PREFIX = "workstreams/po03/wave-a/units/wa-010"

INTEGER = re.compile(r"\d+")


@dataclass(frozen=True)
class Finding:
    check_id: str
    kind: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"check_id": self.check_id, "kind": self.kind, "detail": self.detail}


@dataclass(frozen=True)
class NarrativeRule:
    """Require a figure to appear verbatim in the sentence that restates it."""

    check_id: str
    assertion_contains: str
    figure_name: str
    figure: Callable[[dict[str, Any]], int]


NARRATIVE_RULES: tuple[NarrativeRule, ...] = (
    NarrativeRule(
        check_id="RC-N01",
        assertion_contains="wrote only its declared owned subtree",
        figure_name="payload_commit.base_to_payload_changed_path_count",
        figure=lambda doc: doc["payload_commit"]["base_to_payload_changed_path_count"],
    ),
    NarrativeRule(
        check_id="RC-N02",
        assertion_contains="complete SHA-256 and byte accounting",
        figure_name="artifact_count",
        figure=lambda doc: doc["artifact_count"],
    ),
    NarrativeRule(
        check_id="RC-N03",
        assertion_contains="complete SHA-256 and byte accounting",
        figure_name="total_bytes",
        figure=lambda doc: doc["total_bytes"],
    ),
    NarrativeRule(
        check_id="RC-N04",
        assertion_contains="read back from an immutable remote commit",
        figure_name="readback_verification.verified_paths",
        figure=lambda doc: doc["readback_verification"]["verified_paths"],
    ),
    NarrativeRule(
        check_id="RC-N05",
        assertion_contains="executable component, reproduction, tests and adversarial cases",
        figure_name="tests.focused_tests",
        figure=lambda doc: doc["tests"]["focused_tests"],
    ),
    NarrativeRule(
        check_id="RC-N06",
        assertion_contains="executable component, reproduction, tests and adversarial cases",
        figure_name="tests.adversarial_cases",
        figure=lambda doc: doc["tests"]["adversarial_cases"],
    ),
    NarrativeRule(
        check_id="RC-N07",
        assertion_contains="Exact repository SHAs read are recorded",
        figure_name="source_base.repository_sources_read",
        figure=lambda doc: doc["source_base"]["repository_sources_read"],
    ),
)


def _matching_evidence(document: dict[str, Any], needle: str) -> list[str]:
    return [
        entry["evidence"]
        for entry in document.get("acceptance_self_check", [])
        if needle in entry.get("assertion", "")
    ]


def check_narrative_figures(document: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in NARRATIVE_RULES:
        try:
            expected = int(rule.figure(document))
        except (KeyError, TypeError, ValueError):
            findings.append(
                Finding(
                    rule.check_id,
                    "MISSING_FIGURE",
                    f"{rule.figure_name} is absent or not an integer",
                )
            )
            continue
        sentences = _matching_evidence(document, rule.assertion_contains)
        if not sentences:
            findings.append(
                Finding(
                    rule.check_id,
                    "MISSING_ASSERTION",
                    f"no self-check assertion contains {rule.assertion_contains!r}",
                )
            )
            continue
        found = {int(token) for sentence in sentences for token in INTEGER.findall(sentence)}
        if expected not in found:
            findings.append(
                Finding(
                    rule.check_id,
                    "STALE_NARRATIVE_FIGURE",
                    f"{rule.figure_name} is {expected} but the self-check prose states "
                    f"{sorted(found)}",
                )
            )
    return findings


def check_cross_fields(document: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    def require(check_id: str, condition: bool, detail: str) -> None:
        if not condition:
            findings.append(Finding(check_id, "FIELD_DISAGREEMENT", detail))

    readback = document.get("readback_verification") or {}

    require(
        "RC-X01",
        document.get("terminal_report") == "READY_TO_COMMIT",
        f"terminal_report is {document.get('terminal_report')!r}",
    )
    require(
        "RC-X02",
        document.get("decision_changed") == [],
        f"decision_changed is {document.get('decision_changed')!r}, not []",
    )
    require(
        "RC-X03",
        document.get("manifest_sha256") == readback.get("manifest_sha256"),
        "manifest_sha256 differs from the digest the read-back verified",
    )
    require(
        "RC-X04",
        document.get("manifest_path") == readback.get("manifest_path"),
        f"manifest_path is {document.get('manifest_path')!r} but the read-back record "
        f"names {readback.get('manifest_path')!r}",
    )
    require(
        "RC-X05",
        document.get("artifact_count") == readback.get("artifact_count"),
        "artifact_count differs from the read-back artifact count",
    )
    require(
        "RC-X06",
        document.get("total_bytes") == readback.get("total_bytes"),
        "total_bytes differs from the read-back byte total",
    )
    require(
        "RC-X07",
        len(document.get("changed_files") or [])
        == (document.get("payload_commit") or {}).get("base_to_payload_changed_path_count"),
        "changed_files length differs from base_to_payload_changed_path_count",
    )
    require(
        "RC-X08",
        readback.get("all_match") is True and not readback.get("mismatched_paths"),
        "the read-back record does not report a clean match",
    )

    transactional = document.get("transactional_result") or {}
    txn = transactional.get("result_transaction") or {}
    require(
        "RC-X09",
        txn.get("manifest_sha256") == document.get("manifest_sha256"),
        "the transactional result carries a different manifest digest",
    )
    require(
        "RC-X10",
        len(transactional.get("artifacts") or []) == document.get("artifact_count"),
        "the transactional artifact list length differs from artifact_count",
    )

    stray = [
        entry.get("path")
        for entry in readback.get("checks") or []
        if not str(entry.get("path", "")).startswith(f"{UNIT_PREFIX}/")
    ]
    require("RC-X11", not stray, f"read-back covered paths outside the owned subtree: {stray}")

    declared_manifest = document.get("manifest_path")
    covered = {entry.get("path") for entry in readback.get("checks") or []}
    require(
        "RC-X12",
        declared_manifest in covered,
        f"the declared manifest path {declared_manifest!r} was not itself read back",
    )
    return findings


def check_document(document: dict[str, Any]) -> list[Finding]:
    return check_cross_fields(document) + check_narrative_figures(document)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "document",
        nargs="?",
        type=Path,
        default=RESULT_DIR / "ready-to-commit.json",
    )
    args = parser.parse_args(argv)
    if not args.document.exists():
        print(f"MISSING: {args.document}", file=sys.stderr)
        return 2
    document = json.loads(args.document.read_text(encoding="utf-8"))
    findings = check_document(document)
    print(
        json.dumps(
            {
                "document": str(args.document),
                "outcome": "CONSISTENT" if not findings else "INCONSISTENT",
                "finding_count": len(findings),
                "findings": [finding.as_dict() for finding in findings],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
