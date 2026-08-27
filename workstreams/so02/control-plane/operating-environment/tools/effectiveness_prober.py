#!/usr/bin/env python3
"""A reusable effectiveness prober, generalised from `.cursor/hooks/probe_hook_firing.py`.

## The class this exists to make detectable by construction

`INSTALLED_NOT_EFFECTIVE` — FOUNDER_AUTHORED, named in writing 2026-08-27
(SCP-SI-01 baseline). Three defects in this estate turned out to be one
class: a control passed its own check while measuring or guarding the wrong
thing.

    * git authorship mistaken for founder authorship (a commit header is
      identical for every commit an assistant lane makes on the founder's
      behalf; `write_declaration.py` names this the FB-11 mis-certification).
    * manifest closure mistaken for parse validity (a truncated JSON file can
      still hash-match its manifest entry; `evidence_integrity.py`'s
      docstring names this live).
    * hooks installed mistaken for hooks firing (`probe_hook_firing.py`,
      DIRECTLY_REPRODUCED 2026-08-27: two commands the guard refuses by hand
      both executed unrefused through the agent shell tool).

`probe_hook_firing.py` is the correct template for making the third instance
detectable rather than merely documented: it arms, has the operator run
inert commands through the real execution path, then checks whether the
control's own audit trail actually observed them. This module generalises
that template so any control can ship a probe proving it fires in the
topology it actually runs in — not the topology its author imagined.

## Two hard requirements, load-bearing

1. **A probe must be inert.** It may never perform the destructive act the
   control exists to prevent. A probe for a force-push guard that force-pushes
   is not a probe; it is the incident. Every probe function in this module is
   built to run against disposable, throwaway state — a temp directory, a
   local bare repo that is never `origin`, a synthetic declaration — and
   never against this repository's own history or its real remote.
2. **A control that cannot be probed is not a control.** `UNPROBEABLE` is a
   first-class verdict, not a fallback for "I didn't get to it." A control
   is reported `UNPROBEABLE` when no inert experiment exists that would
   distinguish "fires" from "does not fire" from where this code runs — most
   sharply, an ambient IDE/platform hook, which can only be armed and checked
   by an actual agent tool call going through the real execution path; a
   `subprocess.run` inside this file could never trigger it, and pretending
   otherwise would just be a second copy of the defect this module exists to
   catch (`INSTALLED_NOT_EFFECTIVE`, this time about the prober itself).

## What this module is not

It is not a control registry. `CONTROLS` below is a plain list describing
which controls THIS sweep covers and how each is probed; it is not, and does
not attempt to be, a replacement for `control-plane.json`, the write-scope
config, or any other state file. Removing this file changes nothing about
what any control does — it only removes the ability to demonstrate, on
demand, whether each one currently does it.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT_DEFAULT = TOOLS_DIR.parents[4]  # tools -> operating-environment -> control-plane -> so02 -> workstreams -> repo root

DIRECTLY_REPRODUCED = "DIRECTLY_REPRODUCED"
DOCUMENTED = "DOCUMENTED"
HYPOTHESIS = "HYPOTHESIS"

EFFECTIVE = "EFFECTIVE"
INSTALLED_NOT_EFFECTIVE = "INSTALLED_NOT_EFFECTIVE"
UNPROBEABLE = "UNPROBEABLE"
NOT_INSTALLED = "NOT_INSTALLED"

_VERDICTS = frozenset({EFFECTIVE, INSTALLED_NOT_EFFECTIVE, UNPROBEABLE, NOT_INSTALLED})


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


class ControlNotEffectiveError(Exception):
    """Raised by `assert_effective` when a control's verdict is not EFFECTIVE.

    Existing to be raised, not to be caught silently: code that wants to lean
    on a control's effectiveness calls `assert_effective` and lets this
    propagate. Catching it and treating the control as effective anyway would
    be, again, this lane's own defect class."""


@dataclass
class ProbeResult:
    control_id: str
    verdict: str
    evidence_label: str
    method: str
    detail: str
    armed_at: str | None = None
    checked_at: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICTS:
            raise ValueError(f"unknown verdict {self.verdict!r}")
        if self.evidence_label not in (DIRECTLY_REPRODUCED, DOCUMENTED, HYPOTHESIS):
            raise ValueError(f"unknown evidence label {self.evidence_label!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "verdict": self.verdict,
            "evidence_label": self.evidence_label,
            "method": self.method,
            "detail": self.detail,
            "armed_at": self.armed_at,
            "checked_at": self.checked_at,
            "evidence": self.evidence,
        }


def classify(
    control_id: str,
    *,
    installed: bool,
    probe_ran: bool,
    fired: bool | None,
    method: str,
    detail: str,
    evidence_label: str = DIRECTLY_REPRODUCED,
    armed_at: str | None = None,
    checked_at: str | None = None,
    evidence: dict[str, Any] | None = None,
    unprobeable_reason: str | None = None,
) -> ProbeResult:
    """The one place that decides EFFECTIVE / INSTALLED_NOT_EFFECTIVE / UNPROBEABLE.

    Deliberately conservative: EFFECTIVE requires `installed and probe_ran and
    fired is True`. There is no path from "no probe ran" to EFFECTIVE — that
    is exactly the shortcut ("config says enforcing, so it must be") that
    produced the ambient-hook defect this whole module exists to catch.
    """
    if not installed:
        return ProbeResult(control_id, NOT_INSTALLED, evidence_label, method,
                           detail or "the control is not present in this checkout",
                           armed_at, checked_at, evidence or {})
    if not probe_ran or fired is None:
        return ProbeResult(
            control_id, UNPROBEABLE, evidence_label, method,
            detail or (unprobeable_reason or "no inert probe exists that can distinguish "
                       "firing from not firing for this control from here"),
            armed_at, checked_at, evidence or {},
        )
    if fired:
        return ProbeResult(control_id, EFFECTIVE, evidence_label, method, detail,
                           armed_at, checked_at, evidence or {})
    return ProbeResult(control_id, INSTALLED_NOT_EFFECTIVE, evidence_label, method, detail,
                       armed_at, checked_at, evidence or {})


def assert_effective(result: ProbeResult) -> None:
    """Raise unless `result.verdict == EFFECTIVE`. Never silently downgrades a claim to a pass."""
    if result.verdict != EFFECTIVE:
        raise ControlNotEffectiveError(
            f"{result.control_id} is {result.verdict}, not EFFECTIVE: {result.detail} "
            f"(evidence: {result.evidence_label}, method: {result.method})"
        )


# ---------------------------------------------------------------------------
# Per-control probes. Each is inert: disposable fixtures only, never this
# repository's own history and never its real `origin`.
# ---------------------------------------------------------------------------


def probe_write_admission_gate(repo_root: Path) -> ProbeResult:
    """Does write_admission.py actually refuse a bad declaration and admit a good one?

    Inert: every declaration here targets a scratch ref name that names
    nothing on any real remote, and `write_admission.admit()` never runs git
    push itself — it only evaluates and, for reversibility, rehearses a
    rollback against a disposable fixture remote that reversal_rehearsal.py
    builds and tears down internally.
    """
    wa = _load("write_admission_probe", TOOLS_DIR / "write_admission.py")
    control_id = "WRITE-ADMISSION-GATE (write_admission.py)"

    if not (TOOLS_DIR / "write_admission.py").is_file():
        return classify(control_id, installed=False, probe_ran=False, fired=None,
                        method="file existence", detail="write_admission.py absent")

    bad_report = wa.admit({}, repo_root, rehearse_reversal=False, check_ref_movement=False)
    refused_bad = not bad_report["admitted"] and bad_report["verdict"] == wa.REFUSED

    good_declaration = {
        "declaration_version": "1.0",
        "declared_by": "effectiveness_prober",
        "declared_at": _now(),
        "target": {"ref": "scratch/effectiveness-prober-probe",
                   "paths": ["nonexistent/probe/path.txt"], "operation": "COMMIT_AND_PUSH"},
        "reason": {"code": "PUBLISH_LANE_DELIVERABLE", "statement": (
            "Inert probe declaration for scratch/effectiveness-prober-probe, used only to "
            "verify write_admission.py actually admits a well-formed write; nothing is pushed."),
                   "lane_id": "PROBE", "commission_id": "PROBE"},
        "reversal": {"method": "DELETE_CREATED_REF", "created_ref": "scratch/effectiveness-prober-probe",
                     "custody_ref": "custody/probe", "command": ["git", "push", "origin", "--delete",
                                                                   "scratch/effectiveness-prober-probe"]},
        "concurrency": {"observed_at": _now(), "agents": []},
    }
    good_report = wa.admit(good_declaration, repo_root, rehearse_reversal=True, check_ref_movement=False)
    admitted_good = good_report["admitted"] and good_report["verdict"] == wa.ADMITTED

    fired = refused_bad and admitted_good
    detail = (
        f"empty declaration -> {bad_report['verdict']} (expected {wa.REFUSED}); "
        f"well-formed declaration -> {good_report['verdict']} (expected {wa.ADMITTED})"
    )
    return classify(
        control_id, installed=True, probe_ran=True, fired=fired,
        method="admit({}) expected to refuse; admit(well-formed declaration) expected to admit, "
               "against a scratch ref that addresses no real remote branch",
        detail=detail,
        evidence={"bad_declaration_verdict": bad_report["verdict"],
                  "good_declaration_verdict": good_report["verdict"],
                  "good_declaration_gates": [g["gate"] for g in good_report["gates"] if g["passed"]]},
    )


def probe_evidence_integrity_validity(repo_root: Path) -> ProbeResult:
    """Does verify_artifact_validity catch a hash-bound-but-unparseable artifact?

    Inert: reads two files this call writes itself into a temp directory
    under the system tempdir, never anything committed in the repository.
    """
    ei = _load("evidence_integrity_probe", TOOLS_DIR / "evidence_integrity.py")
    control_id = "EVIDENCE-INTEGRITY VALIDITY CHECK (evidence_integrity.verify_artifact_validity)"

    with tempfile.TemporaryDirectory(prefix="ei-validity-probe-") as workdir:
        root = Path(workdir)
        valid = root / "valid.json"
        valid.write_text(json.dumps({"ok": True}), encoding="utf-8")
        truncated = root / "truncated.json"
        # Deliberately cut off mid-object: the bytes are exactly what a hash
        # would bind, and they still do not parse. This is the live defect
        # evidence_integrity.py's own docstring names: "a lane published a
        # truncated JSON file whose digest matched its manifest exactly."
        truncated.write_bytes(b'{"entries": [{"path": "x", "sha256": "ab')

        errors_valid = ei.verify_artifact_validity(["valid.json"], root)
        errors_truncated = ei.verify_artifact_validity(["truncated.json"], root)

        caught_truncated = bool(errors_truncated) and any(
            "does not parse" in e for e in errors_truncated)
        passed_valid = not errors_valid
        fired = caught_truncated and passed_valid

        return classify(
            control_id, installed=True, probe_ran=True, fired=fired,
            method="verify_artifact_validity against a well-formed JSON file (expect no findings) "
                   "and a byte-truncated one (expect a validity finding), both hash-bindable, "
                   "in a disposable temp directory",
            detail=f"valid.json errors={errors_valid!r}; truncated.json errors={errors_truncated!r}",
            evidence={"errors_on_truncated": errors_truncated, "errors_on_valid": errors_valid},
        )


def probe_evidence_integrity_readback(repo_root: Path) -> ProbeResult:
    """Does verify_readback_truth recompute against the remote rather than trust the record?

    Inert: builds its own disposable bare repository under the system
    tempdir and clones from THAT local path, never from `origin` and never
    touching this repository's own remote-tracking refs.
    """
    ei = _load("evidence_integrity_readback_probe", TOOLS_DIR / "evidence_integrity.py")
    control_id = "EVIDENCE-INTEGRITY READBACK CHECK (evidence_integrity.verify_readback_truth)"

    with tempfile.TemporaryDirectory(prefix="ei-readback-probe-") as workdir:
        root = Path(workdir)
        bare = root / "disposable-remote.git"
        work = root / "work"
        for args in (["init", "--quiet", "--bare", str(bare)],):
            subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)],
                       cwd=root, capture_output=True, text=True, timeout=30)
        for key, value in (("user.email", "probe@obzio.invalid"), ("user.name", "Probe"),
                           ("commit.gpgsign", "false")):
            subprocess.run(["git", "config", key, value], cwd=work, capture_output=True, text=True)
        (work / "probe.txt").write_bytes(b"probe content\n")
        subprocess.run(["git", "add", "-A"], cwd=work, capture_output=True, text=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "probe commit"], cwd=work,
                       capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=work,
                       capture_output=True, text=True)
        subprocess.run(["git", "push", "--quiet", "origin", "main"], cwd=work,
                       capture_output=True, text=True)
        commit = subprocess.run(["git", "rev-parse", "main"], cwd=work, capture_output=True,
                                text=True, timeout=30).stdout.strip()
        blob_sha256 = hashlib.sha256((work / "probe.txt").read_bytes()).hexdigest()

        genuine = {
            "immutable_commit": commit,
            "transports": ["git", "github-api"],
            "comparisons": [{"path": "probe.txt", "remote_git_sha256": blob_sha256,
                             "identical_git_transport": True}],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }
        forged = {
            "immutable_commit": "0" * 40,
            "transports": ["git", "github-api"],
            "comparisons": [{"path": "probe.txt", "remote_git_sha256": "f" * 64,
                             "identical_git_transport": True}],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }

        errors_genuine = ei.verify_readback_truth(genuine, str(bare), root)
        errors_forged = ei.verify_readback_truth(forged, str(bare), root)

        fired = (not errors_genuine) and bool(errors_forged)
        return classify(
            control_id, installed=True, probe_ran=True, fired=fired,
            method="verify_readback_truth against a genuine record (git-clone-recomputed hash "
                   "match, expect no findings) and a forged record naming commit 0*40 (expect a "
                   "rejection), both against a disposable local bare remote",
            detail=f"genuine errors={errors_genuine!r}; forged errors={errors_forged!r}",
            evidence={"errors_on_genuine": errors_genuine, "errors_on_forged": errors_forged},
        )


def probe_lane_guard(repo_root: Path) -> ProbeResult:
    """Does lane_guard.py's detection logic fire, and can it read real remote bytes?

    Inert: `namespace_matches` and `detect_path_collisions` are pure
    functions probed with synthetic fixtures. `verify_reported_head` is
    probed with a read-only `git ls-remote` against this repository's own
    real `origin` — no write, no push, the same command `git fetch` uses
    to discover what exists before deciding anything.
    """
    lg = _load("lane_guard_probe", TOOLS_DIR / "lane_guard.py")
    control_id = "LANE-GUARD (lane_guard.py)"

    owned = ["workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/**"]
    containment_fires = (
        lg.namespace_matches("workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/x.json", owned)
        and not lg.namespace_matches("workstreams/so02/control-plane/operating-environment/scp-si-01/lane-b/x.json", owned)
    )
    collisions = lg.detect_path_collisions([
        {"parent_id": "X", "changed_files": ["shared.json"]},
        {"parent_id": "Y", "changed_files": ["shared.json"]},
    ])
    collision_fires = len(collisions) == 1 and "shared.json" in collisions[0]

    code, out, err = _git(["ls-remote", "--heads", "origin"], cwd=repo_root, timeout=30)
    live_remote_read = code == 0 and bool(out.strip())
    result = lg.verify_reported_head("cursor/branch-that-almost-certainly-does-not-exist-probe",
                                      "a" * 40)
    absence_detection_fires = result["state"] == "REPORTED_BUT_ABSENT" and result["matches"] is False

    fired = containment_fires and collision_fires and live_remote_read and absence_detection_fires
    detail = (
        f"namespace containment fires={containment_fires}; collision detection fires={collision_fires}; "
        f"live read-only ls-remote against origin succeeded={live_remote_read}; "
        f"absent-branch detection fires={absence_detection_fires}. "
        "This probes the MECHANISM: that the script correctly detects what it claims when invoked, "
        "and that it can read real remote bytes. Whether the coordinator actually invokes it at every "
        "integration is a process guarantee, not a code fact — this prober attests to the former from "
        "a DIRECTLY_REPRODUCED probe and defers to the founder's own statement, DOCUMENTED not "
        "independently reproduced by this probe, for the latter: 'The only thing in this estate that "
        "is genuinely enforcing is lane_guard.py at integration time, because it reads remote bytes "
        "and the coordinator runs it.'"
    )
    return classify(
        control_id, installed=True, probe_ran=True, fired=fired,
        method="namespace_matches/detect_path_collisions against synthetic fixtures (inert); "
               "verify_reported_head against a deliberately absent branch name and a read-only "
               "git ls-remote --heads origin (read-only, no write)",
        detail=detail,
        evidence={"containment_fires": containment_fires, "collision_fires": collision_fires,
                  "live_remote_read": live_remote_read, "absence_detection_fires": absence_detection_fires,
                  "invocation_guarantee_evidence_label": DOCUMENTED},
    )


def probe_currentctl(repo_root: Path) -> ProbeResult:
    """Does the currentness compiler actually read live git evidence and produce a real projection?

    Inert: `compile` only reads git refs and JSON ledger files under
    `l4-currentness-recovery/`; it performs no writes and this probe passes
    `--repo-root`/`--ledger-dir` explicitly rather than mutating anything.
    """
    path = repo_root / "workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tools/currentctl.py"
    control_id = "CURRENTNESS COMPILER (currentctl.py)"
    if not path.is_file():
        return classify(control_id, installed=False, probe_ran=False, fired=None,
                        method="file existence", detail="currentctl.py absent")

    ct = _load("currentctl_probe", path)
    ledger_dir = path.parent.parent / "ledger"
    try:
        compiler = ct.Compiler(repo_root=repo_root, ledger_dir=ledger_dir)
        projection = compiler.compile()
    except Exception as exc:  # noqa: BLE001 - a probe failure is evidence, not a crash to hide
        return classify(control_id, installed=True, probe_ran=True, fired=False,
                        method="Compiler(repo_root, ledger_dir).compile() against the real repository",
                        detail=f"compile() raised {exc!r} instead of returning a projection")

    reads_real_git = projection.get("trunk_head") is not None and projection.get("ref_count", 0) > 0
    has_findings_shape = isinstance(projection.get("findings"), list)
    projection_hash_present = bool(projection.get("projection_sha256"))
    fired = reads_real_git and has_findings_shape and projection_hash_present

    return classify(
        control_id, installed=True, probe_ran=True, fired=fired,
        method="compile() against this repository's own real git refs and ledger, read-only",
        detail=(
            f"trunk_head={projection.get('trunk_head')!r} ref_count={projection.get('ref_count')} "
            f"finding_counts={projection.get('finding_counts')} fail_closed={projection.get('fail_closed')}"
        ),
        evidence={"ref_classification_counts": projection.get("ref_classification_counts"),
                  "finding_counts": projection.get("finding_counts"),
                  "fail_closed": projection.get("fail_closed"),
                  "projection_sha256": projection.get("projection_sha256")},
    )


def ambient_hook_result_from_manual_probe(
    *, armed_at: str, checked_at: str, audit_lines_before: int, audit_lines_after: int,
    control_passed_at_arm: bool, commands_sent_through_shell_tool: list[str],
) -> ProbeResult:
    """Wrap a manually-run `.cursor/hooks/probe_hook_firing.py` cycle as a ProbeResult.

    This function does NOT run the probe. It cannot: the whole point of
    `probe_hook_firing.py` is that only a real agent tool call can trigger a
    beforeShellExecution hook, so the arm/check/observe cycle has to be
    driven by an actual Shell tool invocation outside this module, exactly as
    that script's own usage instructions say. This wrapper exists so the
    manually-observed result can be reported in the same shape as every
    other control's probe result, with the same evidence discipline.
    """
    control_id = "WRITE-SCOPE AMBIENT HOOK (.cursor/hooks/guard_write_scope.py via beforeShellExecution)"
    added = audit_lines_after - audit_lines_before
    fired = added > 0
    detail = (
        f"control (guard_write_scope.py run by hand) passed its own check at arm time: "
        f"{control_passed_at_arm}. {len(commands_sent_through_shell_tool)} inert command(s) sent "
        f"through the agent's real shell tool. Audit log lines {audit_lines_before} -> "
        f"{audit_lines_after} (added {added})."
    )
    return classify(
        control_id, installed=True, probe_ran=True, fired=fired,
        method="probe_hook_firing.py --arm, then inert commands sent through the agent's own "
               "Shell tool (not subprocess-in-process, since only a real tool call can trigger "
               "a beforeShellExecution hook), then --check comparing the guard's own append-only "
               "audit log line count before and after",
        detail=detail, armed_at=armed_at, checked_at=checked_at,
        evidence={"audit_lines_before": audit_lines_before, "audit_lines_after": audit_lines_after,
                  "commands_sent": commands_sent_through_shell_tool,
                  "control_passed_at_arm": control_passed_at_arm},
    )


PROGRAMMATIC_PROBES: dict[str, Callable[[Path], ProbeResult]] = {
    "write_admission_gate": probe_write_admission_gate,
    "evidence_integrity_validity": probe_evidence_integrity_validity,
    "evidence_integrity_readback": probe_evidence_integrity_readback,
    "lane_guard": probe_lane_guard,
    "currentctl": probe_currentctl,
}


def sweep(repo_root: Path = REPO_ROOT_DEFAULT,
         ambient_hook_result: ProbeResult | None = None) -> dict[str, Any]:
    """Run every programmatic probe and fold in the manually-observed ambient-hook result."""
    results: list[ProbeResult] = [probe(repo_root) for probe in PROGRAMMATIC_PROBES.values()]
    if ambient_hook_result is not None:
        results.insert(0, ambient_hook_result)

    counts: dict[str, int] = {}
    for result in results:
        counts[result.verdict] = counts.get(result.verdict, 0) + 1

    return {
        "tool": "effectiveness_prober",
        "generated_at": _now(),
        "controls_probed": len(results),
        "verdict_counts": counts,
        "results": [r.to_dict() for r in results],
        "not_a_control_registry": (
            "This report is the output of one sweep, not a persisted registry. It does not "
            "replace control-plane.json or write-scope.json."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(REPO_ROOT_DEFAULT))
    parser.add_argument("--ambient-hook-probe-json", default=None,
                        help="path to a JSON file with the manually observed ambient-hook probe "
                             "fields (armed_at, checked_at, audit_lines_before, audit_lines_after, "
                             "control_passed_at_arm, commands_sent_through_shell_tool)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    ambient = None
    if args.ambient_hook_probe_json:
        payload = json.loads(Path(args.ambient_hook_probe_json).read_text(encoding="utf-8"))
        accepted = {"armed_at", "checked_at", "audit_lines_before", "audit_lines_after",
                   "control_passed_at_arm", "commands_sent_through_shell_tool"}
        ambient = ambient_hook_result_from_manual_probe(
            **{k: v for k, v in payload.items() if k in accepted})

    report = sweep(Path(args.repo), ambient)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
