"""Independent acceptance: adversarial review of another operator's output.

This is NOT a checklist walk. The premise is that the subject's own reports
are the least trustworthy thing in the directory, because they are exactly
what a failing operator would edit. So:

  * The subject's check_report.json is treated as a CLAIM, not evidence. The
    reviewer re-runs the subject pack's checks itself and compares.
  * The subject's MANIFEST.json is re-verified against the bytes on disk.
  * The subject's return_state.json is examined for the specific shapes that a
    run which did not really succeed leaves behind.

Every finding carries an evidence pointer -- artefact, locator, observed value
-- so a third party can reproduce it without re-running anything.
"""

import importlib.util
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import List

from fence import SubjectHandle

ACCEPT = "ACCEPT"
REJECT = "REJECT"


@dataclass
class Evidence:
    artefact: str
    locator: str
    observed: str

    def to_json(self):
        return asdict(self)


@dataclass
class Finding:
    id: str
    probe: str
    severity: str            # BLOCKING | ADVISORY
    summary: str
    evidence: List[Evidence] = field(default_factory=list)

    def to_json(self):
        d = asdict(self)
        d["evidence"] = [e.to_json() for e in self.evidence]
        return d


class Review:
    def __init__(self, handle: "SubjectHandle", subject_pack_dir: str = None):
        self.h = handle
        self.subject_pack_dir = subject_pack_dir
        self.findings: List[Finding] = []
        self._n = 0
        self.probes_run: List[str] = []

    def _add(self, probe, severity, summary, evidence):
        self._n += 1
        self.findings.append(Finding(f"F-{self._n:03d}", probe, severity,
                                     summary, evidence))

    def _probe(self, name):
        self.probes_run.append(name)

    # ------------------------------------------------------------- probes

    def probe_required_artefacts(self, required):
        """P-01: the artefacts the subject was required to produce exist."""
        self._probe("P-01_required_artefacts")
        for rel in required:
            if not self.h.exists(rel):
                self._add("P-01_required_artefacts", "BLOCKING",
                          f"required artefact {rel} is absent",
                          [Evidence(rel, "<file>", "MISSING")])
            elif os.path.getsize(os.path.join(self.h.root, rel)) == 0:
                self._add("P-01_required_artefacts", "BLOCKING",
                          f"required artefact {rel} is empty",
                          [Evidence(rel, "<file>", "0 bytes")])

    def probe_return_state(self):
        """P-02: the run's own claim of completion is internally coherent."""
        self._probe("P-02_return_state")
        if not self.h.exists("return_state.json"):
            self._add("P-02_return_state", "BLOCKING",
                      "no return_state.json: the run left no durable claim",
                      [Evidence("return_state.json", "<file>", "MISSING")])
            return
        rs = self.h.read_json("return_state.json")
        if rs.get("final_state") != "COMPLETE":
            self._add("P-02_return_state", "BLOCKING",
                      f"run did not complete (final_state="
                      f"{rs.get('final_state')!r})",
                      [Evidence("return_state.json", "final_state",
                                str(rs.get("final_state")))])
        if rs.get("verdict") != ACCEPT:
            self._add("P-02_return_state", "BLOCKING",
                      f"run carries verdict {rs.get('verdict')!r}",
                      [Evidence("return_state.json", "verdict",
                                str(rs.get("verdict")))])
        if not rs.get("accepted_run_digest"):
            self._add("P-02_return_state", "BLOCKING",
                      "run claims completion with no accepted_run_digest: "
                      "nothing binds the acceptance to these artefacts",
                      [Evidence("return_state.json", "accepted_run_digest",
                                "null")])
        # The subject's own producer must not have been its own reviewer.
        if rs.get("producer_id") and rs.get("producer_id") == rs.get("reviewer_id"):
            self._add("P-02_return_state", "BLOCKING",
                      f"subject self-reviewed: producer and reviewer are both "
                      f"{rs.get('producer_id')!r}",
                      [Evidence("return_state.json", "producer_id/reviewer_id",
                                str(rs.get("producer_id")))])

    def probe_check_report_not_vacuous(self):
        """P-03: a passing check report that ran no checks proves nothing."""
        self._probe("P-03_check_report")
        if not self.h.exists("check_report.json"):
            self._add("P-03_check_report", "BLOCKING",
                      "no check_report.json", 
                      [Evidence("check_report.json", "<file>", "MISSING")])
            return
        cr = self.h.read_json("check_report.json")
        if cr.get("passed") and cr.get("failure_count", 0) > 0:
            self._add("P-03_check_report", "BLOCKING",
                      "check report claims passed=true while reporting failures",
                      [Evidence("check_report.json", "passed/failure_count",
                                f"{cr.get('passed')}/{cr.get('failure_count')}")])
        declared = len(cr.get("findings", []))
        actual_fails = len([f for f in cr.get("findings", [])
                            if f.get("severity") == "FAIL"])
        if actual_fails != cr.get("failure_count", actual_fails):
            self._add("P-03_check_report", "BLOCKING",
                      f"failure_count ({cr.get('failure_count')}) disagrees with "
                      f"the findings list ({actual_fails} FAIL entries)",
                      [Evidence("check_report.json", "failure_count",
                                str(cr.get("failure_count")))])

    def probe_recompute_checks(self):
        """P-04: RE-RUN the subject's own checks. Do not trust its report.

        This is the probe that distinguishes review from proofreading. The
        subject's check_report.json is a file the subject wrote; a failing
        operator edits exactly that file."""
        self._probe("P-04_recomputed_checks")
        if not self.subject_pack_dir:
            self._add("P-04_recomputed_checks", "ADVISORY",
                      "no pack directory supplied; checks could not be recomputed "
                      "and the subject's own report is unverified",
                      [Evidence("check_report.json", "<recompute>", "SKIPPED")])
            return
        checks_py = os.path.join(self.subject_pack_dir, "checks.py")
        if not os.path.exists(checks_py):
            self._add("P-04_recomputed_checks", "ADVISORY",
                      f"subject pack has no checks.py at {checks_py}",
                      [Evidence("checks.py", "<file>", "MISSING")])
            return
        spec = importlib.util.spec_from_file_location(
            "subject_checks_" + str(abs(hash(checks_py))), checks_py)
        mod = importlib.util.module_from_spec(spec)
        saved = list(sys.path)
        try:
            sys.path.insert(0, self.subject_pack_dir)
            spec.loader.exec_module(mod)
            recomputed = mod.run_checks(self.h.root)
        except Exception as e:
            self._add("P-04_recomputed_checks", "BLOCKING",
                      f"recomputing the subject's checks raised {type(e).__name__}: {e}",
                      [Evidence("checks.py", "run_checks", repr(e)[:180])])
            return
        finally:
            sys.path[:] = saved

        self.recomputed = recomputed
        if not recomputed.passed:
            for f in recomputed.failures:
                self._add("P-04_recomputed_checks", "BLOCKING",
                          f"recomputed check failed: {f.check}: {f.message}",
                          [Evidence("<recomputed>", f.check, f.message[:200])])

        if self.h.exists("check_report.json"):
            claimed = self.h.read_json("check_report.json").get("passed")
            if claimed is True and not recomputed.passed:
                self._add("P-04_recomputed_checks", "BLOCKING",
                          "subject's check_report claims PASS but recomputation "
                          "FAILS: the report does not describe these artefacts",
                          [Evidence("check_report.json", "passed", "true"),
                           Evidence("<recomputed>", "passed", "false")])

    def probe_manifest(self):
        """P-05: the subject's manifest matches the bytes actually present."""
        self._probe("P-05_manifest")
        if not self.subject_pack_dir:
            return
        from obzio_spine import manifest
        ok, problems = manifest.verify(self.subject_pack_dir)
        if not ok:
            for p in problems[:20]:
                self._add("P-05_manifest", "BLOCKING",
                          f"pack manifest does not match disk: {p}",
                          [Evidence("MANIFEST.json", "verify", p)])

    def probe_journal_continuity(self):
        """P-06: the journal is an unbroken, ordered record."""
        self._probe("P-06_journal")
        if not self.h.exists("journal.json"):
            self._add("P-06_journal", "ADVISORY", "no journal.json present",
                      [Evidence("journal.json", "<file>", "MISSING")])
            return
        j = self.h.read_json("journal.json")
        seqs = [e.get("seq") for e in j]
        if seqs != list(range(len(j))):
            self._add("P-06_journal", "BLOCKING",
                      "journal sequence numbers are not contiguous from zero: "
                      "entries were removed or reordered",
                      [Evidence("journal.json", "seq", str(seqs[:12]))])
        transitions = [e for e in j if e.get("event") == "TRANSITION"]
        if not transitions:
            self._add("P-06_journal", "BLOCKING", "journal records no transitions",
                      [Evidence("journal.json", "event=TRANSITION", "0")])
        if not any(e.get("event") == "ACCEPTANCE_VERIFIED" for e in j):
            self._add("P-06_journal", "BLOCKING",
                      "journal contains no ACCEPTANCE_VERIFIED event: the run "
                      "never crossed an independent acceptance gate",
                      [Evidence("journal.json", "event=ACCEPTANCE_VERIFIED",
                                "absent")])

    def probe_digest_binding(self):
        """P-07: the accepted digest actually binds the artefacts present."""
        self._probe("P-07_digest_binding")
        if not self.h.exists("return_state.json"):
            return
        rs = self.h.read_json("return_state.json")
        claimed = rs.get("accepted_run_digest")
        arts = rs.get("artefacts") or {}
        if not claimed or not arts:
            return
        from obzio_spine.artefacts import run_digest
        paths = [os.path.join(self.h.root, v) for v in arts.values()]
        if not all(os.path.exists(p) for p in paths):
            self._add("P-07_digest_binding", "BLOCKING",
                      "return_state names artefacts that are not on disk",
                      [Evidence("return_state.json", "artefacts", str(arts))])
            return
        actual = run_digest(paths)
        if actual != claimed:
            self._add("P-07_digest_binding", "BLOCKING",
                      f"accepted_run_digest {claimed[:16]}... does not match the "
                      f"artefacts present ({actual[:16]}...): they changed after "
                      f"acceptance",
                      [Evidence("return_state.json", "accepted_run_digest",
                                claimed[:32]),
                       Evidence("<recomputed>", "run_digest", actual[:32])])

    # ------------------------------------------------------------- verdict

    def run_all(self, required_artefacts):
        self.probe_required_artefacts(required_artefacts)
        self.probe_return_state()
        self.probe_check_report_not_vacuous()
        self.probe_recompute_checks()
        self.probe_manifest()
        self.probe_journal_continuity()
        self.probe_digest_binding()
        return self.findings

    @property
    def blocking(self):
        return [f for f in self.findings if f.severity == "BLOCKING"]

    def verdict(self):
        """ACCEPT only in the absence of blocking findings.

        There is no 'accept with reservations'. A reviewer that can accept a
        run it has blocking findings on is a reviewer that always accepts."""
        return REJECT if self.blocking else ACCEPT
