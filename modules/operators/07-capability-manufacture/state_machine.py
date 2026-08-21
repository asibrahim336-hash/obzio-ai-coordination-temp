"""
Pack 07 - capability-manufacture
Commission an external agent platform, then decide whether what came back is
a capability or a story about a capability.

THE FAILURE THIS PACK IS BUILT AGAINST
--------------------------------------
A NARRATIVE RETURN: the vendor delivers a confident README, a STATUS.md
declaring success, a results.json saying {"status":"success","tests_passed":12},
and a module that imports cleanly and does nothing. Every surface signal says
delivered. Nothing runs.

THE RULE THAT PREVENTS IT
-------------------------
Evidence of capability is output WE produced by executing THEIR artefact.
Nothing else counts:
  * undeclared files contribute ZERO material bytes, however many there are
  * a vendor's own success report is never evidence - it is catalogued under
    `self_attestation_ignored` and its bytes are excluded
  * the acceptance spec is pinned and hashed BEFORE the return arrives, so the
    goalposts cannot move to fit what showed up

Verdicts: MATERIAL / PARTIAL / NARRATIVE_RETURN / EMPTY.
Only MATERIAL may advance, and only MATERIAL may leave quarantine.
"""
from __future__ import annotations

import ast
import enum
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _spine
from _spine import (
    AcceptanceGate, AcceptanceOutcome, CheckReport, CommitFirstAcceptor,
    Objective, Phase, Run, sha256_file, sha256_obj, write_json,
)

PACK = "07-capability-manufacture"

PROSE_SUFFIXES = {".md", ".txt", ".rst", ".adoc", ".html"}
MAX_CAPTURE = 16384


class Verdict(str, enum.Enum):
    MATERIAL = "MATERIAL"
    PARTIAL = "PARTIAL"
    NARRATIVE_RETURN = "NARRATIVE_RETURN"
    EMPTY = "EMPTY"


class CommissionError(Exception):
    pass


class SpecMutated(CommissionError):
    pass


class ReturnRejected(CommissionError):
    pass


class QuarantineEscape(CommissionError):
    pass


class PromotionRefused(CommissionError):
    pass


# --------------------------------------------------------------------------
# Completion-claim vocabulary
#
# NOTE ON WEIGHT: these patterns are a REPORTING signal only. They never make
# a return fail on their own - a return with zero claims and zero passing
# probes is still refused. They exist to distinguish NARRATIVE_RETURN (loud
# and empty) from EMPTY (quiet and empty), because those need different
# follow-up with the vendor.
# --------------------------------------------------------------------------
CLAIM_PATTERNS: List[Tuple[str, str]] = [
    (r"\b(?:all|every)\s+(?:the\s+)?(?:tests?|checks?|cases?)\s+(?:now\s+)?(?:pass|passed|passing)\b",
     "all-tests-pass"),
    (r"\bfully\s+(?:implemented|working|functional|complete|tested)\b", "fully-x"),
    (r"\bsuccessfully\s+(?:implemented|completed|delivered|deployed|built|integrated)\b",
     "successfully-x"),
    (r"\bproduction[-\s]ready\b", "production-ready"),
    (r"\b(?:implementation|integration|migration)\s+is\s+complete\b", "is-complete"),
    (r"\bverified\s+(?:working|correct|end[-\s]to[-\s]end)\b", "verified-working"),
    (r"\b100\s*%\s*(?:complete|coverage|passing)\b", "hundred-percent"),
    (r"\bready\s+for\s+(?:production|deployment|use|review)\b", "ready-for-x"),
    (r"\bno\s+(?:known\s+)?(?:issues|bugs|failures)\b", "no-issues"),
]
_COMPILED = [(re.compile(p, re.I), label) for p, label in CLAIM_PATTERNS]

SELF_ATTESTATION_NAMES = re.compile(
    r"^(results?|status|report|summary|outcome|completion)[-_.]?.*\.(json|ya?ml|md|txt)$",
    re.I,
)


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Probe:
    argv: Tuple[str, ...] = ()
    expect_exit: int = 0
    expect_stdout_contains: Tuple[str, ...] = ()
    timeout_s: float = 15.0

    def to_dict(self):
        return {k: list(v) if isinstance(v, tuple) else v
                for k, v in asdict(self).items()}


@dataclass(frozen=True)
class Deliverable:
    path: str
    kind: str                      # python_module | jsonl | json | text
    must_define: Tuple[str, ...] = ()
    min_bytes: int = 1
    probe: Optional[Probe] = None

    def to_dict(self):
        d = {"path": self.path, "kind": self.kind,
             "must_define": list(self.must_define), "min_bytes": self.min_bytes,
             "probe": self.probe.to_dict() if self.probe else None}
        return d


@dataclass(frozen=True)
class CommissionSpec:
    commission_id: str
    vendor: str
    deliverables: Tuple[Deliverable, ...]
    min_probes_passed: int = 1
    max_prose_ratio: float = 2.0

    def to_dict(self):
        return {
            "commission_id": self.commission_id,
            "vendor": self.vendor,
            "min_probes_passed": self.min_probes_passed,
            "max_prose_ratio": self.max_prose_ratio,
            "deliverables": [d.to_dict() for d in self.deliverables],
        }

    def digest(self) -> str:
        return sha256_obj(self.to_dict())


# --------------------------------------------------------------------------
# Assessment
# --------------------------------------------------------------------------
@dataclass
class ReturnAssessment:
    commission_id: str
    spec_digest: str
    verdict: str = Verdict.EMPTY.value
    material_bytes: int = 0
    prose_bytes: int = 0
    undeclared_bytes: int = 0
    prose_ratio: float = 0.0
    probes_defined: int = 0
    probes_passed: int = 0
    deliverables: List[Dict[str, Any]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    type_failures: List[str] = field(default_factory=list)
    claims_found: List[Dict[str, Any]] = field(default_factory=list)
    self_attestation_ignored: List[Dict[str, Any]] = field(default_factory=list)
    undeclared_files: List[str] = field(default_factory=list)
    return_received_at: float = 0.0
    reasoning: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------------------------
# Validator
# --------------------------------------------------------------------------
class CommissionValidator:
    def __init__(self, quarantine: os.PathLike | str, workdir: os.PathLike | str):
        self.quarantine = Path(quarantine).resolve()
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.probe_log = self.workdir / "probe_log.jsonl"

    # -- audit -----------------------------------------------------------
    def _log(self, row: Dict[str, Any]) -> None:
        with open(self.probe_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **row},
                                sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- containment -----------------------------------------------------
    def _resolve_inside(self, rel: str) -> Path:
        p = (self.quarantine / rel).resolve()
        if not str(p).startswith(str(self.quarantine) + os.sep) and p != self.quarantine:
            raise QuarantineEscape(f"{rel!r} resolves outside quarantine: {p}")
        return p

    # -- type conformance -------------------------------------------------
    @staticmethod
    def _top_level_names(src: str) -> set:
        tree = ast.parse(src)
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        return names

    def _typecheck(self, d: Deliverable, path: Path) -> Tuple[bool, str]:
        try:
            if d.kind == "python_module":
                src = path.read_text(encoding="utf-8", errors="replace")
                names = self._top_level_names(src)          # parse, do not import
                missing = [s for s in d.must_define if s not in names]
                if missing:
                    return False, f"does not define {missing}"
                return True, f"parses; defines {sorted(names)[:6]}"
            if d.kind == "jsonl":
                n = 0
                for i, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    if line.strip():
                        json.loads(line)
                        n += 1
                return (n > 0), f"{n} json lines"
            if d.kind == "json":
                json.loads(path.read_text(encoding="utf-8"))
                return True, "parses as json"
            if d.kind == "text":
                return path.stat().st_size >= d.min_bytes, f"{path.stat().st_size} bytes"
            return False, f"unknown kind {d.kind!r}"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    # -- behavioural probe -------------------------------------------------
    def _run_probe(self, d: Deliverable, path: Path) -> Tuple[bool, Dict[str, Any]]:
        """Execute the vendor's artefact and judge OUR captured output.

        Containment here is partial and deliberately documented as such in
        BOUNDARIES.md control 12: cwd confinement, stripped env, wall-clock
        timeout and output cap - but no seccomp, no namespace, no container."""
        probe = d.probe
        argv = [sys.executable, str(path), *probe.argv]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        t0 = time.time()
        try:
            cp = subprocess.run(argv, cwd=str(self.quarantine), env=env,
                                capture_output=True, text=True,
                                timeout=probe.timeout_s)
            out = cp.stdout[:MAX_CAPTURE]
            err = cp.stderr[:MAX_CAPTURE]
            code = cp.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            out, err, code, timed_out = "", "timeout", -1, True

        reasons = []
        if timed_out:
            reasons.append(f"timed out after {probe.timeout_s}s")
        if code != probe.expect_exit:
            reasons.append(f"exit {code}, expected {probe.expect_exit}")
        for needle in probe.expect_stdout_contains:
            if needle not in out:
                reasons.append(f"stdout missing {needle!r}")
        ok = not reasons
        rec = {"kind": "PROBE", "deliverable": d.path, "argv": argv[1:],
               "exit": code, "expected_exit": probe.expect_exit,
               "duration_s": round(time.time() - t0, 4), "passed": ok,
               "reasons": reasons, "stdout_head": out[:400],
               "stderr_head": err[:400], "inside_quarantine": True}
        self._log(rec)
        return ok, rec

    # -- inventory ---------------------------------------------------------
    def _inventory(self, declared: set) -> Dict[str, Any]:
        prose_bytes = 0
        undeclared_bytes = 0
        undeclared: List[str] = []
        attestations: List[Dict[str, Any]] = []
        claims: List[Dict[str, Any]] = []
        for p in sorted(self.quarantine.rglob("*")):
            if not p.is_file():
                continue
            rel = str(p.relative_to(self.quarantine))
            size = p.stat().st_size
            if p.suffix.lower() in PROSE_SUFFIXES:
                prose_bytes += size
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    text = ""
                for ln, line in enumerate(text.splitlines(), 1):
                    for rx, label in _COMPILED:
                        m = rx.search(line)
                        if m:
                            claims.append({"file": rel, "line": ln,
                                           "label": label,
                                           "text": m.group(0)[:120]})
            if rel not in declared:
                undeclared_bytes += size
                undeclared.append(rel)
                if SELF_ATTESTATION_NAMES.match(p.name):
                    attestations.append({
                        "file": rel, "bytes": size,
                        "why_ignored": "vendor self-report; not evidence of capability",
                        "sha256": sha256_file(p),
                    })
        return {"prose_bytes": prose_bytes, "undeclared_bytes": undeclared_bytes,
                "undeclared_files": undeclared, "claims": claims,
                "self_attestation_ignored": attestations}

    # -- the decision -------------------------------------------------------
    def validate(self, spec: CommissionSpec, pinned_digest: str) -> ReturnAssessment:
        if spec.digest() != pinned_digest:
            raise SpecMutated(
                "acceptance spec differs from the one pinned at commission time "
                f"({spec.digest()[:12]} vs {pinned_digest[:12]}); "
                "goalposts may not move after the return arrives"
            )

        a = ReturnAssessment(commission_id=spec.commission_id,
                             spec_digest=pinned_digest,
                             return_received_at=time.time())
        declared = {d.path for d in spec.deliverables}

        for d in spec.deliverables:
            row: Dict[str, Any] = {"path": d.path, "kind": d.kind,
                                   "present": False, "bytes": 0,
                                   "type_ok": False, "type_detail": "",
                                   "probe_defined": d.probe is not None,
                                   "probe_passed": None, "sha256": None}
            try:
                p = self._resolve_inside(d.path)
            except QuarantineEscape as e:
                row["type_detail"] = str(e)
                a.type_failures.append(f"{d.path}: {e}")
                a.deliverables.append(row)
                continue

            if not p.exists() or p.stat().st_size < d.min_bytes:
                a.missing.append(d.path)
                a.deliverables.append(row)
                continue

            row["present"] = True
            row["bytes"] = p.stat().st_size
            row["sha256"] = sha256_file(p)
            ok, detail = self._typecheck(d, p)
            row["type_ok"], row["type_detail"] = ok, detail
            if not ok:
                a.type_failures.append(f"{d.path}: {detail}")

            if d.probe is not None:
                a.probes_defined += 1
                if ok:
                    passed, _rec = self._run_probe(d, p)
                    row["probe_passed"] = passed
                    if passed:
                        a.probes_passed += 1
                else:
                    row["probe_passed"] = False
                    self._log({"kind": "PROBE_SKIPPED", "deliverable": d.path,
                               "reason": f"type check failed: {detail}",
                               "passed": False})

            # material bytes accrue ONLY for declared, type-conforming files
            if ok:
                a.material_bytes += row["bytes"]
            a.deliverables.append(row)

        inv = self._inventory(declared)
        a.prose_bytes = inv["prose_bytes"]
        a.undeclared_bytes = inv["undeclared_bytes"]
        a.undeclared_files = inv["undeclared_files"]
        a.claims_found = inv["claims"]
        a.self_attestation_ignored = inv["self_attestation_ignored"]
        a.prose_ratio = round(a.prose_bytes / max(a.material_bytes, 1), 3)

        present = [r for r in a.deliverables if r["present"]]
        conforming = [r for r in a.deliverables if r["type_ok"]]
        all_probes_ok = (a.probes_passed == a.probes_defined
                         and a.probes_passed >= spec.min_probes_passed)

        # ORDER MATTERS: a return that is nothing but a success story is a
        # NARRATIVE_RETURN, not an EMPTY one. They need different follow-up.
        if len(conforming) == len(spec.deliverables) and all_probes_ok:
            a.verdict = Verdict.MATERIAL.value
            a.reasoning.append(
                f"all {len(conforming)} deliverables conform; "
                f"{a.probes_passed}/{a.probes_defined} probes passed under our execution")
        elif a.probes_passed < spec.min_probes_passed and (
                a.claims_found
                or (a.material_bytes > 0 and a.prose_ratio > spec.max_prose_ratio)):
            # the ratio arm is gated on material_bytes > 0 on purpose: a return
            # that is one honest note saying "not started" has an unbounded
            # prose ratio but is EMPTY, not narrative. Narrative means a claim
            # of success, or bulk prose wrapped around something that does not
            # run - not the absence of work honestly reported.
            a.verdict = Verdict.NARRATIVE_RETURN.value
            a.reasoning.append(
                f"{a.probes_passed}/{a.probes_defined} probes passed "
                f"(minimum {spec.min_probes_passed}) while the return carries "
                f"{len(a.claims_found)} completion claim(s) and a prose:material "
                f"ratio of {a.prose_ratio}")
            if a.self_attestation_ignored:
                a.reasoning.append(
                    f"{len(a.self_attestation_ignored)} vendor self-report file(s) "
                    "excluded from evidence")
        elif not present:
            a.verdict = Verdict.EMPTY.value
            a.reasoning.append(
                "no declared deliverable is present and nothing was claimed")
        else:
            a.verdict = Verdict.PARTIAL.value
            a.reasoning.append(
                f"{len(conforming)}/{len(spec.deliverables)} conform, "
                f"{a.probes_passed}/{a.probes_defined} probes passed")

        self._log({"kind": "VERDICT", "verdict": a.verdict,
                   "probes_passed": a.probes_passed,
                   "probes_defined": a.probes_defined,
                   "material_bytes": a.material_bytes,
                   "prose_bytes": a.prose_bytes})
        return a


# --------------------------------------------------------------------------
# Pack run
# --------------------------------------------------------------------------
class CapabilityManufactureRun(Run):
    def __init__(self, workdir, producer_id, gate, spec: CommissionSpec,
                 quarantine, **kw):
        super().__init__(PACK, workdir, producer_id, gate,
                         mandate={"commission_id": spec.commission_id,
                                  "vendor": spec.vendor,
                                  "spec_digest": spec.digest()}, **kw)
        self.spec = spec
        self.quarantine = Path(quarantine)
        self.validator: Optional[CommissionValidator] = None
        self.assessment: Optional[ReturnAssessment] = None

    def dispatch(self) -> Path:
        """PREFLIGHT: pin the acceptance spec BEFORE the vendor can see what
        it is graded against, and before anything comes back."""
        self.quarantine.mkdir(parents=True, exist_ok=True)
        p = self.workdir / "commission.json"
        write_json(p, {"spec": self.spec.to_dict(),
                       "spec_digest": self.spec.digest(),
                       "dispatched_at": time.time(),
                       "quarantine": str(self.quarantine),
                       "producer_id": self.producer_id})
        self.advance(Phase.PREFLIGHT, {"spec_digest": self.spec.digest(),
                                       "vendor": self.spec.vendor})
        self.validator = CommissionValidator(self.quarantine, self.workdir)
        return p

    def recover_state(self) -> Dict[str, Any]:
        prior = self.workdir / "assessment.json"
        prev = _spine.read_json(prior) if prior.exists() else None
        self.advance(Phase.CURRENT_STATE_RECOVERED,
                     {"prior_assessment": bool(prev),
                      "prior_verdict": (prev or {}).get("verdict")})
        return {"prior": prev}

    def admit_return(self) -> Dict[str, Any]:
        """INPUT_ADMITTED: record exactly what arrived, byte for byte, before
        any judgement. This inventory is what the audit compares against."""
        files = []
        for p in sorted(self.quarantine.rglob("*")):
            if p.is_file():
                files.append({"path": str(p.relative_to(self.quarantine)),
                              "bytes": p.stat().st_size,
                              "sha256": sha256_file(p)})
        write_json(self.workdir / "return_inventory.json",
                   {"received_at": time.time(), "file_count": len(files),
                    "total_bytes": sum(f["bytes"] for f in files),
                    "files": files})
        self.advance(Phase.INPUT_ADMITTED,
                     {"file_count": len(files),
                      "total_bytes": sum(f["bytes"] for f in files)})
        return {"files": files}

    def validate_return(self) -> ReturnAssessment:
        pinned = _spine.read_json(self.workdir / "commission.json")["spec_digest"]
        a = self.validator.validate(self.spec, pinned)
        self.assessment = a
        write_json(self.workdir / "assessment.json", a.to_dict())
        self.advance(Phase.ACTION_EXECUTED,
                     {"verdict": a.verdict, "probes": f"{a.probes_passed}/{a.probes_defined}"})
        return a

    def artefacts_present(self) -> None:
        if self.assessment is None:
            raise ReturnRejected("no assessment")
        if self.assessment.verdict != Verdict.MATERIAL.value:
            raise ReturnRejected(
                f"verdict is {self.assessment.verdict}; only MATERIAL advances. "
                + " ".join(self.assessment.reasoning)
            )
        import checks
        missing = checks.missing_artefacts(self.workdir)
        if missing:
            raise FileNotFoundError(f"missing artefacts: {missing}")
        self.advance(Phase.REQUIRED_ARTEFACTS_PRESENT,
                     {"artefacts": checks.REQUIRED_ARTEFACTS})

    def machine_checks(self) -> CheckReport:
        import checks
        rep = checks.run_checks(self.workdir)
        write_json(self.workdir / "checks_report.json", rep.to_dict())
        if not rep.ok:
            raise RuntimeError(f"machine checks failed: {rep.failed}")
        self.advance(Phase.MACHINE_CHECKS_PASSED, {"check_digest": rep.digest()})
        return rep

    def promote(self, dest: os.PathLike | str) -> List[str]:
        """Move the capability out of quarantine. Refused unless the run was
        independently accepted - a MATERIAL verdict alone is not enough."""
        if not self.accepted:
            raise PromotionRefused(
                "promotion out of quarantine requires INDEPENDENT_ACCEPTANCE")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        moved = []
        for d in self.spec.deliverables:
            src = self.quarantine / d.path
            tgt = dest / d.path
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            moved.append(d.path)
        write_json(self.workdir / "promotion.json",
                   {"dest": str(dest), "promoted": moved, "at": time.time(),
                    "acceptor_id": self._acceptance.acceptor_id})
        self.note("PROMOTED", {"dest": str(dest), "files": moved})
        return moved

    def finish(self, acceptor: CommitFirstAcceptor,
               objective: Objective) -> Path:
        """Commit-first acceptance. The acceptor executes the vendor artefacts
        itself and commits its own verdict before opening assessment.json."""
        acceptor.precommit(self, objective)
        outcome = acceptor.decide(self)
        self.accept_with(outcome)
        p = self.write_return_state({"verdict": self.assessment.verdict,
                                     "assessment": "assessment.json"})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": p.name})
        self.advance(Phase.COMPLETE, {})
        return p
