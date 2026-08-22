#!/usr/bin/env python3
"""Provenance lineage for generated artifacts: source, tool, config, parents.

A generated artifact is only reproducible if four things are pinned at the
moment of generation:

    source        the input bytes it was derived from (path + SHA-256)
    tool          the program that derived it, pinned by the SHA-256 of the
                  tool's own source, not merely by a version string
    configuration the parameters that steered the tool, canonicalised so
                  that key order and whitespace cannot change the digest
    parents       the record ids of the artifacts this one was built on

Each record seals those four facts into an ``attestation_sha256`` computed
over a canonical JSON serialization.  Verification re-derives the digest and
re-hashes every referenced file, so any of the following is caught:

    SOURCE_DRIFT          a recorded source file changed after recording
    OUTPUT_DRIFT          the generated artifact changed after recording
    TOOL_DRIFT            the tool's source changed after recording
    CONFIG_TAMPERED       config bytes no longer hash to the recorded digest
    ATTESTATION_MISMATCH  a field was edited without resealing the record
    BROKEN_LINEAGE        a declared parent is absent from the ledger
    CYCLE_DETECTED        parent edges form a cycle
    MISSING_FILE          a recorded path no longer exists

Canonicalisation uses sorted keys, no insignificant whitespace and UTF-8
without ASCII escaping, so two semantically identical configurations always
produce the same digest and a reordered one is not treated as a change.

Exit codes: 0 lineage intact, 1 findings present, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable


SOURCE_DRIFT = "SOURCE_DRIFT"
OUTPUT_DRIFT = "OUTPUT_DRIFT"
TOOL_DRIFT = "TOOL_DRIFT"
CONFIG_TAMPERED = "CONFIG_TAMPERED"
ATTESTATION_MISMATCH = "ATTESTATION_MISMATCH"
BROKEN_LINEAGE = "BROKEN_LINEAGE"
CYCLE_DETECTED = "CYCLE_DETECTED"
MISSING_FILE = "MISSING_FILE"
UNRECORDED_SOURCE = "UNRECORDED_SOURCE"


class LineageError(ValueError):
    """Raised when a lineage ledger cannot be interpreted."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileRef:
    path: str
    sha256: str
    bytes: int

    @classmethod
    def of(cls, root: Path, relative: str) -> "FileRef":
        absolute = root / relative
        return cls(relative, sha256_file(absolute), absolute.stat().st_size)


@dataclass(frozen=True)
class ToolRef:
    name: str
    version: str
    source_path: str
    source_sha256: str

    @classmethod
    def of(cls, root: Path, name: str, version: str, relative: str) -> "ToolRef":
        return cls(name, version, relative, sha256_file(root / relative))


@dataclass
class LineageRecord:
    record_id: str
    output: FileRef
    sources: list[FileRef]
    tool: ToolRef
    configuration: dict[str, Any]
    parents: list[str] = field(default_factory=list)
    recorded_at: str | None = None
    attestation_sha256: str = ""

    def sealed_payload(self) -> dict[str, Any]:
        """The exact subset of the record that the attestation covers."""
        return {
            "record_id": self.record_id,
            "output": asdict(self.output),
            "sources": [asdict(s) for s in sorted(self.sources, key=lambda s: s.path)],
            "tool": asdict(self.tool),
            "configuration_sha256": sha256_bytes(canonical_json(self.configuration)),
            "parents": sorted(self.parents),
        }

    def seal(self) -> "LineageRecord":
        self.attestation_sha256 = sha256_bytes(canonical_json(self.sealed_payload()))
        return self

    def to_dict(self) -> dict[str, Any]:
        document = self.sealed_payload()
        document["configuration"] = self.configuration
        document["recorded_at"] = self.recorded_at
        document["attestation_sha256"] = self.attestation_sha256
        return document

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "LineageRecord":
        try:
            record = cls(
                record_id=document["record_id"],
                output=FileRef(**document["output"]),
                sources=[FileRef(**s) for s in document["sources"]],
                tool=ToolRef(**document["tool"]),
                configuration=document["configuration"],
                parents=list(document.get("parents", [])),
                recorded_at=document.get("recorded_at"),
                attestation_sha256=document.get("attestation_sha256", ""),
            )
        except (KeyError, TypeError) as exc:
            raise LineageError(f"unusable lineage record: {exc}") from exc
        # The recorded configuration digest is part of the seal; if the record
        # carries one that disagrees with the configuration body, keep both so
        # verification can report CONFIG_TAMPERED rather than silently reseal.
        record._declared_configuration_sha256 = document.get("configuration_sha256")  # type: ignore[attr-defined]
        return record


@dataclass(frozen=True)
class Finding:
    record_id: str
    finding: str
    detail: str


class LineageLedger:
    def __init__(self, records: Iterable[LineageRecord] | None = None) -> None:
        self._records: dict[str, LineageRecord] = {}
        for record in records or ():
            self.add(record)

    def add(self, record: LineageRecord) -> None:
        if record.record_id in self._records:
            raise LineageError(f"duplicate record_id: {record.record_id}")
        self._records[record.record_id] = record

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        return record_id in self._records

    def get(self, record_id: str) -> LineageRecord:
        return self._records[record_id]

    def record_ids(self) -> list[str]:
        return sorted(self._records)

    def ancestry(self, record_id: str) -> list[str]:
        """Return every ancestor id, nearest first; raises on a cycle."""
        seen: list[str] = []
        stack = [(record_id, tuple())]
        while stack:
            current, path = stack.pop()
            if current in path:
                raise LineageError(f"cycle through {current}")
            record = self._records.get(current)
            if record is None:
                continue
            for parent in sorted(record.parents):
                if parent not in seen:
                    seen.append(parent)
                stack.append((parent, path + (current,)))
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_version": "PO03-LINEAGE-v1",
            "records": [self._records[key].to_dict() for key in sorted(self._records)],
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "LineageLedger":
        if not isinstance(document, dict) or not isinstance(document.get("records"), list):
            raise LineageError("ledger must be an object with a records array")
        return cls(LineageRecord.from_dict(entry) for entry in document["records"])


def record_generation(
    root: Path,
    record_id: str,
    output_relative: str,
    source_relatives: Iterable[str],
    tool_name: str,
    tool_version: str,
    tool_relative: str,
    configuration: dict[str, Any],
    parents: Iterable[str] = (),
    recorded_at: str | None = None,
) -> LineageRecord:
    record = LineageRecord(
        record_id=record_id,
        output=FileRef.of(root, output_relative),
        sources=[FileRef.of(root, relative) for relative in source_relatives],
        tool=ToolRef.of(root, tool_name, tool_version, tool_relative),
        configuration=configuration,
        parents=list(parents),
        recorded_at=recorded_at,
    )
    return record.seal()


def verify(ledger: LineageLedger, root: Path, declared_sources: dict[str, list[str]] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for record_id in ledger.record_ids():
        record = ledger.get(record_id)

        declared_config_sha = getattr(record, "_declared_configuration_sha256", None)
        actual_config_sha = sha256_bytes(canonical_json(record.configuration))
        if declared_config_sha is not None and declared_config_sha != actual_config_sha:
            findings.append(
                Finding(record_id, CONFIG_TAMPERED, "configuration body does not match its sealed digest")
            )

        expected = sha256_bytes(canonical_json(record.sealed_payload()))
        if record.attestation_sha256 != expected:
            findings.append(
                Finding(record_id, ATTESTATION_MISMATCH, "record fields were edited without resealing")
            )

        for ref, drift in ((record.output, OUTPUT_DRIFT),) + tuple((s, SOURCE_DRIFT) for s in record.sources):
            absolute = root / ref.path
            if not absolute.is_file():
                findings.append(Finding(record_id, MISSING_FILE, f"{ref.path} is absent"))
                continue
            if sha256_file(absolute) != ref.sha256:
                findings.append(Finding(record_id, drift, f"{ref.path} changed after recording"))

        tool_path = root / record.tool.source_path
        if not tool_path.is_file():
            findings.append(Finding(record_id, MISSING_FILE, f"{record.tool.source_path} is absent"))
        elif sha256_file(tool_path) != record.tool.source_sha256:
            findings.append(Finding(record_id, TOOL_DRIFT, "tool source changed after recording"))

        for parent in sorted(record.parents):
            if parent not in ledger:
                findings.append(Finding(record_id, BROKEN_LINEAGE, f"declared parent {parent} is not in the ledger"))

        try:
            ledger.ancestry(record_id)
        except LineageError as exc:
            findings.append(Finding(record_id, CYCLE_DETECTED, str(exc)))

        if declared_sources and record_id in declared_sources:
            recorded = {s.path for s in record.sources}
            for expected_source in declared_sources[record_id]:
                if expected_source not in recorded:
                    findings.append(
                        Finding(record_id, UNRECORDED_SOURCE, f"{expected_source} was used but not recorded")
                    )
    return findings


def build_report(ledger: LineageLedger, findings: list[Finding]) -> dict:
    return {
        "component": "lineage_recorder",
        "records": len(ledger),
        "findings_count": len(findings),
        "lineage_intact": not findings,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify generated-artifact lineage against the bytes on disk.")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"USAGE_ERROR: root is not a directory: {args.root}", file=sys.stderr)
        return 2
    try:
        ledger = LineageLedger.from_dict(json.loads(args.ledger.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, LineageError) as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    report = build_report(ledger, verify(ledger, args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            print(f"FAIL {finding['finding']:<22} {finding['record_id']}  ({finding['detail']})")
        print(f"summary: records={report['records']} findings={report['findings_count']}")
    return 0 if report["lineage_intact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
