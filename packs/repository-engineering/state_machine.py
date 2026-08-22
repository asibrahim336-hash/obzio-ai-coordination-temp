"""repository-engineering state machine."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine.machine import OperatorMachine
from obzio_spine.states import State
from obzio_spine.artefacts import write_json

import engine
import oracle
from transport import TransportError, AuthError
from checks import run_checks, REQUIRED_ARTEFACTS

PACK = "repository-engineering"


def make_acceptor(reviewer_id, branch, files, base, pr_title):
    """Pre-commitment from the intended bytes. Contacts no repository.

    The expected read-back digest is sha256 of what the caller intends to
    write -- an arithmetic fact fixed before any branch exists."""
    from obzio_spine.expectation import Acceptor
    return Acceptor(reviewer_id,
                    oracle.derive_expectation(branch, files, base, pr_title),
                    oracle.inputs_digest(branch, files, base, pr_title))


def build_machine(run_dir, producer_id, commitments, tp, branch, files,
                  pr_title, pr_body, base=None, acceptor=None):
    m = OperatorMachine(PACK, run_dir, producer_id, commitments,
                        artefact_names=REQUIRED_ARTEFACTS)
    m.set_expectation_extractor(lambda mm: oracle.extract_actual(mm.run_dir))
    if acceptor is not None:
        m.register_expectation(acceptor.commitment())
    m._tp = tp
    m._plan = {"branch": branch, "files": files, "pr_title": pr_title,
               "pr_body": pr_body, "base": base}

    @m.guard(State.CURRENT_STATE_RECOVERED)
    def _recover(mm, **kw):
        # Recovering repo state means asking the REMOTE what the base branch
        # is, not assuming "main". An operator that assumes the default branch
        # will eventually open a PR against the wrong base.
        base_now = mm._plan["base"] or mm._tp.default_branch()
        mm._plan["base"] = base_now
        mm._record("STATE_RECOVERED",
                   {"base_branch": base_now, "protected": list(mm._tp.protected)})
        return True

    @m.guard(State.INPUT_ADMITTED)
    def _admit(mm, **kw):
        p = mm._plan
        if not p["files"]:
            raise ValueError("no files to write")
        for path, content in p["files"].items():
            if not isinstance(content, (bytes, bytearray)):
                raise TypeError(f"{path}: content must be bytes, got {type(content).__name__}")
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"unsafe repository path {path!r}")
        if p["branch"] in mm._tp.protected:
            raise ValueError(f"refusing to target protected ref {p['branch']!r}")
        if not p["pr_title"].strip():
            raise ValueError("PR must have a title")
        mm._record("INPUT_ADMITTED",
                   {"branch": p["branch"], "files": sorted(p["files"])})
        return True

    @m.guard(State.ACTION_EXECUTED)
    def _execute(mm, **kw):
        p = mm._plan
        out = engine.execute(mm._tp, p["branch"], p["files"],
                             p["pr_title"], p["pr_body"], base=p["base"])
        for name in ("branch_record", "commit_record", "pr_record",
                     "readback_verification"):
            path = os.path.join(mm.run_dir, f"{name}.json")
            write_json(path, out[name])
            mm.declare_artefact(name, path)
        write_json(os.path.join(mm.run_dir, "audit.json"), out["_audit"])
        mm._record("ACTION_EXECUTED", {
            "branch": p["branch"], "files": out["commit_record"]["file_count"],
            "pr": out["pr_record"]["number"],
            "verified": out["readback_verification"]["all_verified"]})
        return True

    @m.guard(State.REQUIRED_ARTEFACTS_PRESENT)
    def _present(mm, **kw):
        missing = [a for a in REQUIRED_ARTEFACTS
                   if not os.path.exists(os.path.join(mm.run_dir, a))]
        if missing:
            raise FileNotFoundError(f"required artefacts absent: {missing}")
        return True

    @m.guard(State.MACHINE_CHECKS_PASSED)
    def _checks(mm, **kw):
        rep = run_checks(mm.run_dir)
        mm.check_report = rep
        write_json(os.path.join(mm.run_dir, "check_report.json"), rep.to_json())
        mm._record("CHECKS_RUN", {"passed": rep.passed, "failures": len(rep.failures)})
        return rep.passed

    @m.guard(State.INDEPENDENT_ACCEPTANCE)
    def _submit(mm, **kw):
        mm._record("SUBMITTED_FOR_REVIEW", {"run_digest": mm.current_run_digest()})
        return True

    @m.guard(State.RETURN_STATE_WRITTEN)
    def _write_return(mm, **kw):
        mm.write_return_state(State.RETURN_STATE_WRITTEN)
        mm.flush_journal()
        return True

    @m.guard(State.COMPLETE)
    def _complete(mm, **kw):
        mm.write_return_state(State.COMPLETE)
        mm.flush_journal()
        return True

    return m
