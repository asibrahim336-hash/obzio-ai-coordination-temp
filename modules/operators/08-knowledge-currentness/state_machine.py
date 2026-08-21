"""
Pack 08 - knowledge-currentness
Detect drift between a pinned expectation and live state.

THE DEFECT THIS PACK IS BUILT AGAINST (observed in this operation)
------------------------------------------------------------------
A drift row read MATCH while the underlying file had changed.

That is not one bug, it is a family, and this pack blocks the whole family:

  (a) the row was carried forward from an earlier run and never re-derived
  (b) the "live" side came from a cache that outlived the change
  (c) the comparator short-circuited on mtime/size and never hashed content
  (d) a row was constructed directly with verdict=MATCH by code that had no
      evidence at all

The structural answer: A VERDICT IS NOT A FIELD YOU SET. It is minted, with a
MAC, by the auditor that performed the read, keyed to THIS run's nonce, and
re-verified at report time against the evidence registry of THIS run.

  * Evidence is only constructible by LiveReader.read(), which always reads
    every byte and always hashes - there is no mtime path and no cache        (c)
  * The reader stamps run_id + run_nonce into every Evidence                  (a)(b)
  * DriftRow carries an auth MAC over (run_nonce, evidence_id, verdict);
    a row minted by another run, or by nobody, fails verification             (a)(d)
  * report() re-checks every MATCH row against the live registry, and
    re-checks staleness at REPORT time, not at compare time

A MATCH that nothing re-derived this run cannot be printed. It raises.
"""
from __future__ import annotations

import enum
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import _spine
from _spine import (
    AcceptanceGate, AcceptanceOutcome, CheckReport, CommitFirstAcceptor,
    Objective, Phase, Run, canon, sha256_bytes, write_json,
)

PACK = "08-knowledge-currentness"

DEFAULT_MAX_STALENESS_S = 60.0


class Verdict(str, enum.Enum):
    MATCH = "MATCH"
    DRIFT = "DRIFT"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"      # never an assertion of health


class ReportStatus(str, enum.Enum):
    CURRENT = "CURRENT"
    DRIFT = "DRIFT"
    DEGRADED = "DEGRADED"      # evidence went stale before publication
    INCOMPLETE = "INCOMPLETE"  # a pin was never compared this run


class CurrentnessError(Exception):
    pass


class UnbackedVerdictRefused(CurrentnessError):
    """A MATCH with no fresh, this-run evidence behind it. THE defect."""


class StaleEvidenceRefused(CurrentnessError):
    pass


class NoComparisonPerformed(CurrentnessError):
    pass


class TargetMissing(CurrentnessError):
    """The pinned path is gone. Carries the evidence record of the attempt -
    a read that found nothing is still a read that happened this run."""

    def __init__(self, msg: str, evidence: "Evidence"):
        super().__init__(msg)
        self.evidence = evidence


# --------------------------------------------------------------------------
# Pins
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PinnedExpectation:
    key: str
    path: str
    pinned_digest: str
    pinned_bytes: int
    pinned_at: float
    pinned_by: str

    def to_dict(self):
        return asdict(self)


class Pinboard:
    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)
        self.pins: Dict[str, PinnedExpectation] = {}
        if self.path.exists():
            for k, v in _spine.read_json(self.path).get("pins", {}).items():
                self.pins[k] = PinnedExpectation(**v)

    def pin(self, key: str, target: os.PathLike | str, by: str) -> PinnedExpectation:
        data = Path(target).read_bytes()
        p = PinnedExpectation(key=key, path=str(target),
                              pinned_digest=sha256_bytes(data),
                              pinned_bytes=len(data), pinned_at=time.time(),
                              pinned_by=by)
        self.pins[key] = p
        self.save()
        return p

    def save(self) -> None:
        write_json(self.path, {"pins": {k: v.to_dict() for k, v in self.pins.items()}})


# --------------------------------------------------------------------------
# Evidence - the only currency this pack accepts
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    path: str
    run_id: str
    run_nonce: str
    read_seq: int
    wall_read_at: float
    mono_read_at: float
    byte_len: int
    digest: Optional[str]
    reader: str
    full_read: bool
    outcome: str          # READ | MISSING - an attempted read is still evidence

    def to_dict(self):
        return asdict(self)


class LiveReader:
    """Reads live state. Always every byte, always hashed, never cached,
    never keyed across runs.

    There is deliberately no `if mtime == last_mtime: return cached` path in
    this class. That shortcut is defect (c) and it is why `full_read` is a
    recorded field rather than an assumption."""

    def __init__(self, run_id: str, reader_id: str, log_path: os.PathLike | str):
        self.run_id = run_id
        self.reader_id = reader_id
        self.run_nonce = secrets.token_hex(16)
        self.log_path = Path(log_path)
        self._seq = 0
        self.registry: Dict[str, Evidence] = {}

    def _emit(self, p: Path, data: Optional[bytes]) -> Evidence:
        self._seq += 1
        ev = Evidence(
            evidence_id=secrets.token_hex(12),
            path=str(p),
            run_id=self.run_id,
            run_nonce=self.run_nonce,
            read_seq=self._seq,
            wall_read_at=time.time(),
            mono_read_at=time.monotonic(),
            byte_len=len(data) if data is not None else 0,
            digest=sha256_bytes(data) if data is not None else None,
            reader=self.reader_id,
            full_read=data is not None,
            outcome="READ" if data is not None else "MISSING",
        )
        self.registry[ev.evidence_id] = ev
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return ev

    def read(self, path: os.PathLike | str) -> Evidence:
        p = Path(path)
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            raise TargetMissing(f"pinned path absent: {p}", self._emit(p, None))
        return self._emit(p, data)


def mtime_shortcut_verdict(exp: PinnedExpectation, pinned_mtime: float) -> str:
    """THE DEFECTIVE COMPARATOR, kept for one purpose: to be disagreed with.

    Never call this to decide anything. `DriftAuditor` runs it alongside the
    real comparison purely as a tripwire - when this says MATCH and the real
    comparison says DRIFT, something rewrote content while preserving mtime,
    which is worth knowing about on its own."""
    try:
        return (Verdict.MATCH.value
                if os.stat(exp.path).st_mtime == pinned_mtime
                else Verdict.DRIFT.value)
    except FileNotFoundError:
        return Verdict.MISSING.value


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DriftRow:
    key: str
    path: str
    verdict: str
    pinned_digest: str
    live_digest: Optional[str]
    pinned_bytes: int
    live_bytes: Optional[int]
    evidence_id: Optional[str]
    run_nonce: str
    compared_at: float
    compared_mono: float
    auth: str
    mtime_shortcut_said: Optional[str] = None

    def core(self) -> Dict[str, Any]:
        return {"key": self.key, "path": self.path, "verdict": self.verdict,
                "pinned_digest": self.pinned_digest, "live_digest": self.live_digest,
                "evidence_id": self.evidence_id, "run_nonce": self.run_nonce,
                "compared_at": self.compared_at}

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------------------------
# Auditor
# --------------------------------------------------------------------------
class DriftAuditor:
    def __init__(self, run_id: str, workdir: os.PathLike | str, reader: LiveReader,
                 max_staleness_s: float = DEFAULT_MAX_STALENESS_S):
        self.run_id = run_id
        self.workdir = Path(workdir)
        self.reader = reader
        self.max_staleness_s = float(max_staleness_s)
        self._auth_key = secrets.token_bytes(32)
        self.rows: List[DriftRow] = []
        self.comparisons = 0

    def _auth(self, core: Dict[str, Any]) -> str:
        return hmac.new(self._auth_key, canon(core), hashlib.sha256).hexdigest()

    # -- the ONLY way a verdict comes into existence ----------------------
    def compare(self, exp: PinnedExpectation,
                pinned_mtime: Optional[float] = None) -> DriftRow:
        """Read live state NOW and mint a verdict bound to that read.

        Note the signature: there is no way to hand this method an Evidence
        object. It performs the read itself. That is what makes 'MATCH without
        a fresh comparison' unrepresentable rather than merely discouraged."""
        self.comparisons += 1
        try:
            ev = self.reader.read(exp.path)
        except TargetMissing as miss:
            core = {"key": exp.key, "path": exp.path, "verdict": Verdict.MISSING.value,
                    "pinned_digest": exp.pinned_digest, "live_digest": None,
                    "evidence_id": miss.evidence.evidence_id,
                    "run_nonce": self.reader.run_nonce, "compared_at": time.time()}
            row = DriftRow(**core, pinned_bytes=exp.pinned_bytes, live_bytes=None,
                           compared_mono=miss.evidence.mono_read_at,
                           auth=self._auth(core))
            self.rows.append(row)
            return row

        verdict = (Verdict.MATCH.value if ev.digest == exp.pinned_digest
                   else Verdict.DRIFT.value)
        core = {"key": exp.key, "path": exp.path, "verdict": verdict,
                "pinned_digest": exp.pinned_digest, "live_digest": ev.digest,
                "evidence_id": ev.evidence_id, "run_nonce": self.reader.run_nonce,
                "compared_at": time.time()}
        row = DriftRow(**core, pinned_bytes=exp.pinned_bytes, live_bytes=ev.byte_len,
                       compared_mono=ev.mono_read_at, auth=self._auth(core),
                       mtime_shortcut_said=(mtime_shortcut_verdict(exp, pinned_mtime)
                                            if pinned_mtime is not None else None))
        self.rows.append(row)
        return row

    def admit_row(self, row: DriftRow) -> DriftRow:
        """Accept a row produced elsewhere. Verifies it belongs to this run."""
        self._verify_row(row)
        self.rows.append(row)
        return row

    def _verify_row(self, row: DriftRow) -> None:
        if not hmac.compare_digest(self._auth(row.core()), row.auth):
            raise UnbackedVerdictRefused(
                f"row {row.key!r} carries verdict {row.verdict} with an auth MAC "
                "this auditor did not mint - it was not derived by this run")
        if row.run_nonce != self.reader.run_nonce:
            raise UnbackedVerdictRefused(
                f"row {row.key!r} carries run_nonce {row.run_nonce[:8]}, this run "
                f"is {self.reader.run_nonce[:8]} - carried-forward verdicts are refused")
        if row.verdict == Verdict.MATCH.value:
            if not row.evidence_id or row.evidence_id not in self.reader.registry:
                raise UnbackedVerdictRefused(
                    f"row {row.key!r} asserts MATCH with evidence "
                    f"{row.evidence_id!r} that this run never read")
            ev = self.reader.registry[row.evidence_id]
            if not ev.full_read:
                raise UnbackedVerdictRefused(
                    f"row {row.key!r} asserts MATCH from a partial read")
            if ev.digest != row.live_digest:
                raise UnbackedVerdictRefused(
                    f"row {row.key!r} live_digest does not match its own evidence")

    # -- publication -------------------------------------------------------
    def report(self, pins: Dict[str, PinnedExpectation]) -> Dict[str, Any]:
        if self.comparisons == 0 and not self.rows:
            raise NoComparisonPerformed(
                "refusing to publish a currentness report with zero comparisons")

        now_mono = time.monotonic()
        published: List[Dict[str, Any]] = []
        downgraded: List[Dict[str, Any]] = []

        for row in self.rows:
            self._verify_row(row)          # raises on the observed defect
            d = row.to_dict()
            staleness = round(now_mono - row.compared_mono, 4)
            d["staleness_s_at_publication"] = staleness
            if row.verdict == Verdict.MATCH.value and staleness > self.max_staleness_s:
                d["verdict"] = Verdict.UNKNOWN.value
                d["downgraded_from"] = Verdict.MATCH.value
                d["downgrade_reason"] = (
                    f"evidence {staleness}s old at publication, ceiling "
                    f"{self.max_staleness_s}s")
                downgraded.append({"key": row.key, "staleness_s": staleness})
            published.append(d)

        compared_keys = {r.key for r in self.rows}
        uncompared = sorted(set(pins) - compared_keys)
        counts = {v.value: sum(1 for d in published if d["verdict"] == v.value)
                  for v in Verdict}

        if uncompared:
            status = ReportStatus.INCOMPLETE.value
        elif counts[Verdict.DRIFT.value] or counts[Verdict.MISSING.value]:
            status = ReportStatus.DRIFT.value
        elif downgraded or counts[Verdict.UNKNOWN.value]:
            status = ReportStatus.DEGRADED.value
        else:
            status = ReportStatus.CURRENT.value

        disagreements = [d["key"] for d in published
                         if d.get("mtime_shortcut_said") == Verdict.MATCH.value
                         and d["verdict"] == Verdict.DRIFT.value]

        return {
            "run_id": self.run_id,
            "run_nonce": self.reader.run_nonce,
            "generated_at": time.time(),
            "max_staleness_s": self.max_staleness_s,
            "pins_total": len(pins),
            "comparisons_performed": self.comparisons,
            "reads_performed": len(self.reader.registry),
            "status": status,
            "counts": counts,
            "uncompared_pins": uncompared,
            "downgraded": downgraded,
            "mtime_shortcut_disagreements": disagreements,
            "rows": published,
            "exit_code": 0 if status == ReportStatus.CURRENT.value else 1,
        }


# --------------------------------------------------------------------------
# Pack run
# --------------------------------------------------------------------------
class KnowledgeCurrentnessRun(Run):
    def __init__(self, workdir, producer_id, gate, pinboard_path,
                 max_staleness_s=DEFAULT_MAX_STALENESS_S, **kw):
        super().__init__(PACK, workdir, producer_id, gate,
                         mandate={"pinboard": str(pinboard_path),
                                  "max_staleness_s": max_staleness_s}, **kw)
        self.pinboard = Pinboard(pinboard_path)
        self.reader = LiveReader(self.run_id, producer_id,
                                 self.workdir / "evidence_log.jsonl")
        self.auditor = DriftAuditor(self.run_id, self.workdir, self.reader,
                                    max_staleness_s)
        self.report: Optional[Dict[str, Any]] = None

    def preflight(self):
        self.advance(Phase.PREFLIGHT, {"pins": len(self.pinboard.pins),
                                       "run_nonce": self.reader.run_nonce,
                                       "max_staleness_s": self.auditor.max_staleness_s})

    def recover_state(self):
        """Prior reports are read for CONTEXT ONLY. Their verdicts are
        discarded here, loudly and on the record - carrying one forward is
        exactly the defect."""
        prior = self.workdir / "drift_report.json"
        prev = _spine.read_json(prior) if prior.exists() else None
        self.advance(Phase.CURRENT_STATE_RECOVERED, {
            "prior_report": bool(prev),
            "prior_status": (prev or {}).get("status"),
            "prior_verdicts_discarded": len((prev or {}).get("rows", [])),
            "note": "prior verdicts are never reused; every row is re-derived",
        })
        return prev

    def admit_pins(self, keys: Optional[List[str]] = None) -> List[str]:
        keys = sorted(keys if keys is not None else self.pinboard.pins.keys())
        unknown = [k for k in keys if k not in self.pinboard.pins]
        if unknown:
            raise KeyError(f"unpinned keys: {unknown}")
        self._to_audit = keys
        self.advance(Phase.INPUT_ADMITTED, {"keys": keys})
        return keys

    def audit(self, pinned_mtimes: Optional[Dict[str, float]] = None):
        pinned_mtimes = pinned_mtimes or {}
        for k in self._to_audit:
            self.auditor.compare(self.pinboard.pins[k], pinned_mtimes.get(k))
        self.advance(Phase.ACTION_EXECUTED,
                     {"comparisons": self.auditor.comparisons,
                      "reads": len(self.reader.registry)})
        return self.auditor.rows

    def publish(self) -> Dict[str, Any]:
        # The report is scored against the WHOLE pinboard, not against the
        # subset we chose to look at. Auditing 3 of 5 pins and calling the
        # result CURRENT is the same lie as a stale MATCH, one level up.
        self.report = self.auditor.report(self.pinboard.pins)
        write_json(self.workdir / "drift_report.json", self.report)
        import checks
        missing = checks.missing_artefacts(self.workdir)
        if missing:
            raise FileNotFoundError(f"missing artefacts: {missing}")
        self.advance(Phase.REQUIRED_ARTEFACTS_PRESENT,
                     {"status": self.report["status"],
                      "counts": self.report["counts"]})
        return self.report

    def machine_checks(self) -> CheckReport:
        """NOTE: finding drift is a SUCCESSFUL audit. These checks assert the
        audit was performed honestly, not that the world is healthy. The drift
        finding travels in report['status'] and report['exit_code']."""
        import checks
        rep = checks.run_checks(self.workdir)
        write_json(self.workdir / "checks_report.json", rep.to_dict())
        if not rep.ok:
            raise RuntimeError(f"machine checks failed: {rep.failed}")
        self.advance(Phase.MACHINE_CHECKS_PASSED, {"check_digest": rep.digest()})
        return rep

    def finish(self, acceptor: CommitFirstAcceptor,
               objective: Objective) -> Path:
        """Commit-first acceptance. The acceptor derives and hash-commits its
        own per-key verdicts BEFORE the artefact window opens; only then does
        it read drift_report.json. Divergence defaults REJECT."""
        acceptor.precommit(self, objective)
        outcome = acceptor.decide(self)
        self.accept_with(outcome)
        p = self.write_return_state({"status": self.report["status"],
                                     "counts": self.report["counts"],
                                     "report": "drift_report.json"})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": p.name})
        self.advance(Phase.COMPLETE, {})
        return p
