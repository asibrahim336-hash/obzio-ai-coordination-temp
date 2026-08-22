#!/usr/bin/env python3
"""Attack the PO-03 manifest pipeline with manifests that omit a real file.

The hypothesis under attack is that a manifest omitting a real file must fail
verification rather than report success.  An omission is the hardest manifest
corruption to catch, because the manifest that results can be flawless on its own
terms: delete an entry, decrement the count, subtract the bytes, and every
internal cross-check still agrees.  Only a verifier that treats the repository
rather than the manifest as authoritative can see what is missing.  A checker
that recomputes totals from the entries it was handed will pass such a manifest
forever.

Three real components are attacked, and they fail differently.

The live emitter, `workstreams/po03/tools/emit_result.py`, is attacked at
generation time.  It selects artifacts by excluding the basenames `manifest.json`
and `result.json` at any depth, so a payload committed at
`<slot>/nested/manifest.json` is real, durable and never counted.  This fixture
commits exactly that and reads what the emitter produced.

The unit 029 auditor, `coverage_assert.py`, is attacked at verification time with
a family of mutated manifests, including one whose arithmetic is perfectly
self-consistent.  It enumerates the commit, so it is expected to refuse.

The unit 025 verifier, `manifest_tool.py verify`, is attacked the same way in its
own text format, including a manifest whose `TOTAL` trailer was adjusted to match
the entries left behind.

Two omissions survive every existing verifier, and both are generation-time or
frame-of-reference gaps rather than verification failures.  For those this fixture
also runs `residual_coverage.py`, shipped alongside it in this subtree, which
enumerates a slot at the branch tip and subtracts every claim any manifest in it
ever made.  Scenarios naming that tool are the demonstration that the gaps the
fixture found are closable, not a restatement that they exist.

Every attack declares the exit code it expects and the fixture compares that
against what actually happened, so a verifier that stops rejecting turns this
fixture red.  Controls that must pass are run alongside the attacks: without
them, "everything was refused" could just mean the verifier refuses everything,
which would make the whole exercise vacuous.

Exit codes: 0 every scenario behaved as declared, 1 a scenario diverged,
2 the fixture could not be set up.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
ATTEMPTS = REPO_ROOT / "workstreams" / "po03" / "attempts"
EMITTER = REPO_ROOT / "workstreams" / "po03" / "tools" / "emit_result.py"
VALIDATOR = REPO_ROOT / "workstreams" / "po03" / "tools" / "validate_contracts.py"
COVERAGE_ASSERT = ATTEMPTS / "po03-wa-b2e7-029-hash-coverage-completeness" / "coverage_assert.py"
MANIFEST_TOOL = ATTEMPTS / "po03-wa-b2e7-025-manifest-generator-verifier" / "manifest_tool.py"

TASK = "po03-omission-probe"
SLOT = f"workstreams/po03/attempts/{TASK}"


class FixtureError(Exception):
    """Raised when the fixture cannot establish the conditions it needs."""


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FixtureError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Scenario:
    """One attack or control, with the exit code it declares in advance."""

    def __init__(
        self,
        name: str,
        target: str,
        expected_exit: int,
        actual_exit: int,
        marker: str,
        observed: str,
        gap: bool = False,
    ) -> None:
        self.name = name
        self.target = target
        self.expected_exit = expected_exit
        self.actual_exit = actual_exit
        self.marker = marker
        self.observed = observed
        self.gap = gap

    @property
    def as_declared(self) -> bool:
        return self.actual_exit == self.expected_exit

    def as_dict(self) -> dict:
        return {
            "scenario": self.name,
            "target": self.target,
            "expected_exit": self.expected_exit,
            "actual_exit": self.actual_exit,
            "as_declared": self.as_declared,
            "marker": self.marker,
            "observed": self.observed,
            "known_gap": self.gap,
        }


def run(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"})
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=environment)


class Scratch:
    """A minimal PO-03 repository holding the real tools under attack.

    The tools are copied from this repository so the fixture measures the live
    implementations, not a paraphrase of them.  Nothing here touches the real
    worktree: the capsule this fixture needs is synthetic and exists only inside
    the scratch tree, because `workstreams/po03/control/**` is immutable.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.slot = root / SLOT
        self._build()

    def git(self, *arguments: str) -> str:
        completed = run(("git", *arguments), self.root)
        if completed.returncode != 0:
            raise FixtureError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout

    def _build(self) -> None:
        tools = self.root / "workstreams" / "po03" / "tools"
        tools.mkdir(parents=True)
        for source in (EMITTER, VALIDATOR):
            if not source.is_file():
                raise FixtureError(f"missing real tool to attack: {source}")
            shutil.copy2(source, tools / source.name)

        capsule = self.root / "workstreams" / "po03" / "control" / "tasks" / TASK
        capsule.mkdir(parents=True)
        (capsule / "input.json").write_text(
            json.dumps(
                {
                    "falsifiable_hypothesis": (
                        "A manifest that omits a real file must fail verification "
                        "rather than report success."
                    ),
                    "ownership": {"result_slot": SLOT},
                    "source_hashes": {"acceptance_contract_sha256": "0" * 64},
                    "transaction": {
                        "attempt_number": 1,
                        "idempotency_key": f"probe:{TASK}:attempt-1",
                        "lease_id": f"lease-{TASK}-1",
                        "fence_token": 1,
                    },
                }
            ),
            encoding="utf-8",
        )

        self.slot.mkdir(parents=True)
        (self.slot / "component.py").write_text("print('payload one')\n", encoding="utf-8")
        (self.slot / "evidence.txt").write_text("payload two, longer body\n", encoding="utf-8")
        (self.slot / "FINDINGS.md").write_text("# probe\n\npayload three\n", encoding="utf-8")

        self.git("init", "--quiet", "--initial-branch", "main", ".")
        self.git("config", "user.email", "fixture@po03.invalid")
        self.git("config", "user.name", "PO-03 omission fixture")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "probe artifacts")
        self.artifact_commit = self.git("rev-parse", "HEAD").strip()

    def emit(self, verdict: str = "PASS") -> subprocess.CompletedProcess:
        return run(
            (
                sys.executable, "-I", "workstreams/po03/tools/emit_result.py",
                "--repo-root", ".", "--task-id", TASK,
                "--artifact-commit", self.artifact_commit,
                "--result-branch", "main", "--worker-id", f"{TASK}-producer",
                "--provider-run-id", "NOT_SUPPORTED", "--exact-model", "fixture",
                "--verdict", verdict, "--evidence", "omission fixture probe",
                "--limitation", "synthetic scratch repository",
            ),
            self.root,
        )

    def committed_slot_files(self, commit: str | None = None) -> list[str]:
        listing = self.git(
            "ls-tree", "-r", "--name-only", "-z", commit or self.artifact_commit, "--", SLOT
        )
        return sorted(item for item in listing.split("\0") if item)


def emitter_scenarios(holder: Path) -> list[Scenario]:
    """Attack the live emitter at generation time."""
    scenarios: list[Scenario] = []

    # A payload whose basename collides with a generated document name.  The
    # emitter's exclusion is by basename at any depth, so these bytes are real,
    # committed and uncounted.
    scratch = Scratch(holder / "emitter-nested")
    nested = scratch.slot / "nested"
    nested.mkdir()
    (nested / "manifest.json").write_text('{"smuggled": "real payload one"}\n', encoding="utf-8")
    (nested / "result.json").write_text('{"smuggled": "real payload two"}\n', encoding="utf-8")
    scratch.git("add", "-A")
    scratch.git("commit", "--quiet", "-m", "smuggled payloads")
    scratch.artifact_commit = scratch.git("rev-parse", "HEAD").strip()

    completed = scratch.emit()
    real = [path for path in scratch.committed_slot_files()
            if path not in (f"{SLOT}/manifest.json", f"{SLOT}/result.json")]
    if completed.returncode == 0:
        manifest = json.loads((scratch.slot / "manifest.json").read_text(encoding="utf-8"))
        covered = {f"{SLOT}/{entry['logical_name']}" for entry in manifest["artifacts"]}
        omitted = sorted(set(real) - covered)
    else:
        omitted = []
    scenarios.append(
        Scenario(
            name="emitter-omits-payload-named-like-a-generated-document",
            target="emit_result.py (generation)",
            # The emitter is expected to succeed here, and that success is the
            # finding: it reported RESULT_COMMITTED over files it never counted.
            expected_exit=0,
            actual_exit=completed.returncode,
            marker="omitted=" + ",".join(Path(path).name for path in omitted) if omitted else "none",
            observed=(
                f"committed {len(real)} real files under the slot, manifest covered "
                f"{len(real) - len(omitted)}, omitted {len(omitted)}: "
                + ", ".join(path[len(SLOT) + 1:] for path in omitted)
            ) if omitted else "no omission reproduced",
            gap=bool(omitted),
        )
    )

    # The same commit, handed to the independent auditor.  The generator's
    # omission has to be caught by something, and this is that something.
    audit = run(
        (
            sys.executable, "-I", str(COVERAGE_ASSERT), "--repo-root", ".",
            "--commit", "HEAD", "--task-id", TASK,
        ),
        scratch.root,
    ) if _commit_documents(scratch) else None
    if audit is not None:
        uncovered = audit.stdout.count("UNCOVERED_FILE") + audit.stderr.count("UNCOVERED_FILE")
        scenarios.append(
            Scenario(
                name="auditor-catches-the-emitter-omission",
                target="coverage_assert.py (verification)",
                expected_exit=1,
                actual_exit=audit.returncode,
                marker=f"UNCOVERED_FILE x{uncovered}",
                observed=(
                    f"the auditor reported {uncovered} uncovered file(s) the emitter "
                    "had reported success over"
                ),
            )
        )
        residual = run(
            (
                sys.executable, "-I", str(UNIT_ROOT / "residual_coverage.py"),
                "--repo-root", ".", "--commit", "HEAD", "--slot", SLOT,
            ),
            scratch.root,
        )
        scenarios.append(
            Scenario(
                name="residual-check-catches-the-smuggled-payloads",
                target="residual_coverage.py (verification)",
                expected_exit=1,
                actual_exit=residual.returncode,
                marker=f"RESIDUAL_FILE x{residual.stderr.count('RESIDUAL_FILE')}",
                observed=(
                    "the residual check reports the basename-collided payloads as bytes "
                    "no manifest ever claimed"
                ),
            )
        )

    # An empty file is a different failure mode and the emitter should refuse it
    # outright rather than omit it.
    empty = Scratch(holder / "emitter-empty")
    (empty.slot / "hollow.txt").write_text("", encoding="utf-8")
    empty.git("add", "-A")
    empty.git("commit", "--quiet", "-m", "empty artifact")
    empty.artifact_commit = empty.git("rev-parse", "HEAD").strip()
    completed = empty.emit()
    scenarios.append(
        Scenario(
            name="emitter-refuses-an-empty-artifact",
            target="emit_result.py (generation)",
            expected_exit=1,
            actual_exit=completed.returncode,
            marker="refusing to count empty artifact"
            if "refusing to count empty artifact" in completed.stderr else "absent",
            observed=completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "",
        )
    )

    # A slot holding nothing at all must not produce a manifest claiming zero
    # artifacts; an empty manifest is the degenerate omission.
    hollow = Scratch(holder / "emitter-hollow")
    for existing in hollow.slot.iterdir():
        existing.unlink()
    hollow.git("add", "-A")
    hollow.git("commit", "--quiet", "-m", "empty slot")
    hollow.artifact_commit = hollow.git("rev-parse", "HEAD").strip()
    completed = hollow.emit()
    scenarios.append(
        Scenario(
            name="emitter-refuses-a-slot-with-no-artifacts",
            target="emit_result.py (generation)",
            expected_exit=1,
            actual_exit=completed.returncode,
            marker="contains no artifacts"
            if "contains no artifacts" in completed.stderr else "absent",
            observed=completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "",
        )
    )
    return scenarios


def _commit_documents(scratch: Scratch) -> bool:
    """Commit the emitted manifest and result so an auditor can read them."""
    if not (scratch.slot / "manifest.json").is_file():
        return False
    scratch.git("add", "-A")
    scratch.git("commit", "--quiet", "-m", "probe result")
    return True


def auditor_scenarios(holder: Path) -> list[Scenario]:
    """Attack the unit 029 auditor with manifests that omit a real file."""
    coverage = load(COVERAGE_ASSERT, "po03_coverage_assert_under_attack")
    scratch = Scratch(holder / "auditor")
    if scratch.emit().returncode != 0:
        raise FixtureError("could not emit a baseline manifest to attack")
    _commit_documents(scratch)

    raw = (scratch.slot / "manifest.json").read_bytes()
    baseline = json.loads(raw)
    result = json.loads((scratch.slot / "result.json").read_text(encoding="utf-8"))
    repository = coverage.Repository(scratch.root)

    def audit(manifest: dict, documents_result: dict | None = result) -> tuple[int, list[str]]:
        body = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        _, errors = coverage.audit_documents(repository, SLOT, manifest, body, documents_result)
        return (1 if errors else 0), errors

    scenarios: list[Scenario] = []

    exit_code, errors = audit(copy.deepcopy(baseline))
    scenarios.append(
        Scenario(
            "control-complete-manifest", "coverage_assert.py (verification)", 0, exit_code,
            "no errors" if not errors else errors[0],
            f"the untouched manifest covers all {baseline['artifact_count']} artifacts",
        )
    )

    stale = copy.deepcopy(baseline)
    dropped = stale["artifacts"].pop(0)
    exit_code, errors = audit(stale)
    scenarios.append(
        Scenario(
            "entry-omitted-totals-left-stale", "coverage_assert.py (verification)", 1, exit_code,
            _first_marker(errors), f"dropped {dropped['logical_name']}, left the totals untouched",
        )
    )

    counted = copy.deepcopy(baseline)
    dropped = counted["artifacts"].pop(0)
    counted["artifact_count"] -= 1
    exit_code, errors = audit(counted)
    scenarios.append(
        Scenario(
            "entry-omitted-count-adjusted", "coverage_assert.py (verification)", 1, exit_code,
            _first_marker(errors),
            f"dropped {dropped['logical_name']} and decremented artifact_count",
        )
    )

    # The strongest attack: nothing inside this manifest disagrees with anything
    # else inside it.  Only enumeration of the commit can catch it.
    consistent = copy.deepcopy(baseline)
    dropped = consistent["artifacts"].pop(0)
    consistent["artifact_count"] -= 1
    consistent["total_bytes"] -= dropped["bytes"]
    exit_code, errors = audit(consistent)
    scenarios.append(
        Scenario(
            "entry-omitted-manifest-fully-self-consistent",
            "coverage_assert.py (verification)", 1, exit_code, _first_marker(errors),
            f"dropped {dropped['logical_name']}, decremented the count and subtracted its "
            f"{dropped['bytes']} bytes so the manifest agrees with itself",
        )
    )

    emptied = copy.deepcopy(baseline)
    emptied["artifacts"] = []
    emptied["artifact_count"] = 0
    emptied["total_bytes"] = 0
    exit_code, errors = audit(emptied)
    scenarios.append(
        Scenario(
            "every-entry-omitted", "coverage_assert.py (verification)", 1, exit_code,
            _first_marker(errors), "a self-consistent manifest claiming the slot holds nothing",
        )
    )

    # A file that appeared after the manifest was written is the accidental form
    # of the same omission, and per-manifest auditing cannot see it.  The
    # manifest names an earlier artifact commit and remains entirely faithful to
    # it, so the auditor passing here is correct about the question it asks and
    # is still a coverage gap at the level of the slot.
    late = scratch.slot / "late_arrival.txt"
    late.write_text("committed after the manifest was generated\n", encoding="utf-8")
    scratch.git("add", "-A")
    scratch.git("commit", "--quiet", "-m", "late artifact")
    late_repository = coverage.Repository(scratch.root)
    _, errors = coverage.audit_documents(
        late_repository, SLOT, copy.deepcopy(baseline), raw, result
    )
    scenarios.append(
        Scenario(
            "artifact-committed-after-the-manifest-escapes-per-manifest-audit",
            "coverage_assert.py (verification)", 0, 1 if errors else 0, _first_marker(errors),
            "a real file added to the slot after the artifact commit is invisible to an "
            "auditor that enumerates the commit the manifest names",
            gap=not errors,
        )
    )

    # The residual check shipped by this unit asks the other question: what does
    # the slot hold now that no manifest ever claimed?
    residual = run(
        (
            sys.executable, "-I", str(UNIT_ROOT / "residual_coverage.py"),
            "--repo-root", ".", "--commit", "HEAD", "--slot", SLOT,
        ),
        scratch.root,
    )
    scenarios.append(
        Scenario(
            "residual-check-catches-the-late-artifact",
            "residual_coverage.py (verification)", 1, residual.returncode,
            "RESIDUAL_FILE" if "RESIDUAL_FILE" in residual.stderr else "absent",
            "enumerating the slot at the branch tip and subtracting every manifest claim "
            "surfaces the late file the per-manifest audit could not see",
        )
    )
    return scenarios


def _first_marker(errors: list[str]) -> str:
    return errors[0].split(" ")[0] if errors else "no errors"


def manifest_tool_scenarios(holder: Path) -> list[Scenario]:
    """Attack the unit 025 verifier in its own text format."""
    source = holder / "manifest-tool" / "src"
    source.mkdir(parents=True)
    (source / "a.txt").write_text("alpha payload\n", encoding="utf-8")
    (source / "b.txt").write_text("beta payload, longer\n", encoding="utf-8")
    (source / "c.txt").write_text("gamma payload\n", encoding="utf-8")

    generated = holder / "manifest-tool" / "manifest.txt"
    completed = run(
        (
            sys.executable, "-I", str(MANIFEST_TOOL), "generate",
            "--dir", str(source), "--out", str(generated),
        ),
        holder,
    )
    if completed.returncode != 0:
        raise FixtureError(f"could not generate a manifest to attack: {completed.stderr.strip()}")
    baseline = generated.read_text(encoding="utf-8")

    def verify(text: str, name: str) -> subprocess.CompletedProcess:
        candidate = holder / "manifest-tool" / f"{name}.txt"
        candidate.write_text(text, encoding="utf-8")
        return run(
            (
                sys.executable, "-I", str(MANIFEST_TOOL), "verify",
                "--dir", str(source), "--manifest", str(candidate),
            ),
            holder,
        )

    lines = baseline.splitlines()
    entries = [line for line in lines if line and not line.startswith(("PO03-", "SOURCE", "TOTAL"))]
    if len(entries) != 3:
        raise FixtureError(f"expected 3 manifest entries, parsed {len(entries)}")

    scenarios: list[Scenario] = []

    completed = verify(baseline, "control")
    scenarios.append(
        Scenario(
            "control-generated-manifest-verifies", "manifest_tool.py verify", 0,
            completed.returncode, _tool_marker(completed),
            "the manifest as generated verifies against its source",
        )
    )

    stale = "\n".join(line for line in lines if line != entries[0]) + "\n"
    completed = verify(stale, "stale")
    scenarios.append(
        Scenario(
            "line-omitted-trailer-left-stale", "manifest_tool.py verify", 1,
            completed.returncode, _tool_marker(completed),
            "removed one entry and left TOTAL claiming three",
        )
    )

    # Adjust TOTAL to match the two entries that remain, so the document is
    # internally coherent and only the source contradicts it.
    dropped_bytes = int(entries[0].split()[1])
    total = next(line for line in lines if line.startswith("TOTAL"))
    fields = total.split()
    adjusted_total = f"TOTAL {int(fields[1]) - 1} {int(fields[2]) - dropped_bytes}"
    adjusted = "\n".join(
        adjusted_total if line.startswith("TOTAL") else line
        for line in lines if line != entries[0]
    ) + "\n"
    completed = verify(adjusted, "adjusted")
    scenarios.append(
        Scenario(
            "line-omitted-trailer-adjusted-to-match", "manifest_tool.py verify", 1,
            completed.returncode, _tool_marker(completed),
            f"removed one entry and rewrote the trailer to '{adjusted_total}', so the "
            "manifest is internally consistent",
        )
    )

    emptied = "\n".join(
        ["TOTAL 0 0" if line.startswith("TOTAL") else line
         for line in lines if line not in entries]
    ) + "\n"
    completed = verify(emptied, "emptied")
    scenarios.append(
        Scenario(
            "every-line-omitted", "manifest_tool.py verify", 1, completed.returncode,
            _tool_marker(completed), "a coherent manifest claiming the source is empty",
        )
    )
    return scenarios


def _tool_marker(completed: subprocess.CompletedProcess) -> str:
    stream = completed.stdout + completed.stderr
    for token in ("MANIFEST_VIOLATION", "UNCOVERED", "MISSING", "TRAILER"):
        if token in stream:
            return token
    return "verified" if completed.returncode == 0 else "unlabelled failure"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--scratch", help="build the scratch repositories here instead of a temporary directory"
    )
    args = parser.parse_args(argv)

    holder = Path(args.scratch) if args.scratch else Path(
        tempfile.mkdtemp(prefix="po03-omission-")
    )
    holder.mkdir(parents=True, exist_ok=True)
    try:
        scenarios = (
            emitter_scenarios(holder)
            + auditor_scenarios(holder)
            + manifest_tool_scenarios(holder)
        )
    except (FixtureError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"PO03_OMISSION_ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if not args.scratch:
            shutil.rmtree(holder, ignore_errors=True)

    diverged = [scenario for scenario in scenarios if not scenario.as_declared]
    controls = [scenario for scenario in scenarios if scenario.name.startswith("control-")]
    rejecting = [scenario for scenario in scenarios if scenario.expected_exit != 0]
    gaps = [scenario for scenario in scenarios if scenario.gap]

    stream = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps([scenario.as_dict() for scenario in scenarios], indent=2))
    else:
        for scenario in scenarios:
            print(
                f"{'OK      ' if scenario.as_declared else 'DIVERGED'} {scenario.name} "
                f"target={scenario.target} expected_exit={scenario.expected_exit} "
                f"actual_exit={scenario.actual_exit} marker={scenario.marker}"
            )
            print(f"         {scenario.observed}")

    if not controls:
        print("PO03_OMISSION_ERROR: no control scenario ran, rejection is unmeasured", file=sys.stderr)
        return 2
    if diverged:
        for scenario in diverged:
            print(
                f"PO03_OMISSION_DIVERGENCE: {scenario.name} expected exit "
                f"{scenario.expected_exit}, got {scenario.actual_exit}: {scenario.observed}",
                file=sys.stderr,
            )
        return 1
    for scenario in gaps:
        print(f"KNOWN_GAP: {scenario.name}: {scenario.observed}", file=sys.stderr)
    print(
        f"PO03_OMISSION_PASS scenarios={len(scenarios)} rejecting={len(rejecting)} "
        f"controls={len(controls)} generation_gaps={len(gaps)}",
        file=stream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
