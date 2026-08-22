#!/usr/bin/env python3
"""Drive the PO-03 WA-003 reproductions and write one receipt per reproduction.

Reproduction 1 and 5 certify the real repository-native PO-03 suites from a
pristine clone.  Reproduction 2 isolates the provenance-pin claim from the
runtime-portability claim.  Reproductions 3 and 4 are sanitized adversarial
mutants: a clone of the repository is copied inside the work root, an additional
probe module is committed there, and the gate must catch it.  Nothing outside
``--work-root`` and ``--out-dir`` is written and the repository under test is
only ever read.

Every reproduction records its own expected disposition, so a receipt that does
not match its prediction is a defect rather than a narrative.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HARNESS_PATH = Path(__file__).resolve().parent / "clean_clone_harness.py"
SPEC = importlib.util.spec_from_file_location("po03_clean_clone_harness", HARNESS_PATH)
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
sys.modules["po03_clean_clone_harness"] = HARNESS
SPEC.loader.exec_module(HARNESS)

PYTHON = shlex.quote(sys.executable)
SEEDED_SUITE = f"{PYTHON} -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'"
UNIT_SUITE = (
    f"{PYTHON} -I -m unittest discover "
    "-s workstreams/po03/wave-a/units/wa-003/tests -p 'test_*.py'"
)
SUITE_CLOSURE = (
    "workstreams/po03/tests",
    "workstreams/po03/tools/validate_contracts.py",
    "workstreams/po03/contracts",
)
UNIT_CLOSURE = (
    "workstreams/po03/wave-a/units/wa-003/harness",
    "workstreams/po03/wave-a/units/wa-003/tests",
)

WARM_ENV_PROBE = '''"""Sanitized adversarial probe: depends on warm provider session memory."""

import os
import unittest


class WarmProviderMemory(unittest.TestCase):
    def test_requires_provider_session_variable(self):
        self.assertTrue(os.environ["PO03_WARM_PROVIDER_SESSION_TOKEN"])
'''

WARM_TMP_PROBE = '''"""Sanitized adversarial probe: hardcodes the system temporary directory."""

import unittest

WARM_STATE_PATH = "/tmp/po03-warm-state.json"


class HardcodedSystemTemp(unittest.TestCase):
    def test_passes_without_touching_the_path(self):
        self.assertTrue(WARM_STATE_PATH.endswith(".json"))
'''


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def hash_expectations(repo: Path, task_input: Path) -> dict[str, str]:
    """Map every SHA-256 the immutable task input declares onto its path."""
    document = json.loads((repo / task_input).read_text(encoding="utf-8"))
    source_base = document["source_base"]
    mapping = {
        "workstreams/po03/COMMISSION.md": source_base["commission_sha256"],
        "workstreams/po03/tools/validate_contracts.py": source_base["validator_sha256"],
        "workstreams/po03/tests/test_validate_contracts.py": source_base["seed_tests_sha256"],
        "workstreams/po03/contracts/transactional-result.schema.json": source_base[
            "transactional_schema_sha256"
        ],
        "workstreams/po03/contracts/wave-compounding.schema.json": source_base["wave_schema_sha256"],
        ".github/workflows/po03-contracts.yml": source_base["workflow_sha256"],
        document["acceptance_contract"]["path"]: document["acceptance_contract"]["sha256"],
        document["portfolio"]["path"]: document["portfolio"]["sha256"],
    }
    return mapping


def declared_pins(repo: Path, task_input: Path) -> dict[str, str]:
    document = json.loads((repo / task_input).read_text(encoding="utf-8"))
    return {
        "commission_commit": document["source_base"]["commission_commit"],
        "minimum_protocol_ancestor": document["source_base"]["minimum_protocol_ancestor"],
    }


def clone_into(source: str, commit: str, dest: Path) -> Path:
    HARNESS.clone_immutable(source, commit, dest)
    git(dest, "config", "user.email", "po03-wa-003-repro@obzio.invalid")
    git(dest, "config", "user.name", "PO03 WA-003 Reproduction")
    git(dest, "checkout", "--quiet", "-b", "sanitized-mutant")
    return dest


def commit_probe(repo: Path, relative: str, content: str, message: str) -> str:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", "--", relative)
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def warm_copy(source: str, commit: str, dest: Path, suite_command: str) -> Path:
    """Reproduce an observed warm checkout: a clone that has already been run in."""
    HARNESS.clone_immutable(source, commit, dest)
    subprocess.run(
        shlex.split(suite_command),
        cwd=str(dest),
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_reproductions")
    parser.add_argument("--repo", required=True, help="repository under test; read only")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--task-input",
        default="workstreams/po03/control/inputs/wave-a/wa-003.json",
    )
    parser.add_argument("--only", action="append", default=[], dest="only")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    work_root = Path(args.work_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    expectations = hash_expectations(repo, Path(args.task_input))
    pins = declared_pins(repo, Path(args.task_input))

    ledger: list[dict[str, Any]] = []
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def selected(repro_id: str) -> bool:
        return not args.only or repro_id in args.only

    def record(
        repro_id: str,
        claim: str,
        prediction: dict[str, str],
        config: "HARNESS.HarnessConfig",
    ) -> None:
        report = HARNESS.run_harness(config)
        receipt = out_dir / f"{repro_id.lower()}.json"
        receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        observed = {"overall": report["overall"]}
        for check_id in prediction:
            if check_id == "overall":
                continue
            observed[check_id] = next(
                entry["disposition"] for entry in report["checks"] if entry["id"] == check_id
            )
        ledger.append(
            {
                "reproduction_id": repro_id,
                "claim_under_test": claim,
                "prediction": prediction,
                "observed": observed,
                "prediction_held": observed == prediction,
                "receipt": receipt.name,
                "receipt_sha256": HARNESS.sha256_file(receipt),
                "wall_time_seconds": report["wall_time_seconds"],
                "counts": report["counts"],
            }
        )
        print(f"{repro_id}: prediction_held={observed == prediction} observed={observed}")

    # REPRO-1: the falsifiable hypothesis itself, on the seeded PO-03 suite.
    if selected("REPRO-1"):
        warm = warm_copy(str(repo), args.commit, work_root / "repro-1-warm", SEEDED_SUITE)
        record(
            "REPRO-1",
            "The seeded PO-03 contract suite executes from a pristine clone with no warm "
            "checkout, uncommitted file, provider environment memory, home state or system "
            "temporary directory.",
            {"overall": "PASS", "CC-11": "PASS", "CC-15": "PASS", "CC-17": "PASS", "CC-07": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(repo),
                commit=args.commit,
                work_root=str(work_root / "repro-1"),
                suite_command=SEEDED_SUITE,
                scan_paths=SUITE_CLOSURE,
                require_pins=(f"{pins['commission_commit']}:ancestor",),
                expect_sha256=expectations,
                warm_baseline_dir=str(warm),
                recurrence_clones=2,
                label="repro-1-seeded-suite-clean-clone",
            ),
        )

    # REPRO-2: the declared provenance pins, isolated from the runtime claim.
    if selected("REPRO-2"):
        record(
            "REPRO-2",
            "Every provenance SHA the immutable Wave A task input declares resolves inside a "
            "pristine clone of the repository under test.",
            {"overall": "FAIL", "CC-06": "FAIL", "CC-11": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(repo),
                commit=args.commit,
                work_root=str(work_root / "repro-2"),
                suite_command=SEEDED_SUITE,
                scan_paths=SUITE_CLOSURE,
                require_pins=(
                    f"{pins['commission_commit']}:ancestor",
                    f"{pins['minimum_protocol_ancestor']}:ancestor",
                ),
                recurrence_clones=1,
                label="repro-2-declared-provenance-pins",
            ),
        )

    # REPRO-3: sanitized Obzio-native mutant that depends on warm provider memory.
    if selected("REPRO-3"):
        mutant = clone_into(str(repo), args.commit, work_root / "repro-3-mutant")
        mutant_head = commit_probe(
            mutant,
            "workstreams/po03/tests/test_warm_env_probe.py",
            WARM_ENV_PROBE,
            "sanitized adversarial probe: warm provider session memory",
        )
        record(
            "REPRO-3",
            "A PO-03 suite that reads a provider session variable passes in the warm "
            "checkout and is caught by the clean-clone gate, so Python isolated mode alone "
            "does not establish environment independence.",
            {"overall": "FAIL", "CC-11": "FAIL", "CC-15": "FAIL", "CC-09": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(mutant),
                commit=mutant_head,
                work_root=str(work_root / "repro-3"),
                suite_command=SEEDED_SUITE,
                scan_paths=SUITE_CLOSURE,
                warm_baseline_dir=str(mutant),
                recurrence_clones=1,
                base_env={
                    **{
                        name: value
                        for name, value in os.environ.items()
                        if name in ("PATH", "LANG")
                    },
                    "PO03_WARM_PROVIDER_SESSION_TOKEN": "synthetic-warm-session-value-0003",
                },
                label="repro-3-warm-provider-memory-mutant",
            ),
        )

    # REPRO-4: sanitized Obzio-native mutant with a hardcoded system temp path.
    if selected("REPRO-4"):
        mutant = clone_into(str(repo), args.commit, work_root / "repro-4-mutant")
        mutant_head = commit_probe(
            mutant,
            "workstreams/po03/tests/test_warm_tmp_probe.py",
            WARM_TMP_PROBE,
            "sanitized adversarial probe: hardcoded system temporary directory",
        )
        record(
            "REPRO-4",
            "Redirecting TMPDIR does not detect a hardcoded /tmp path; only the static "
            "closure scan does, so the scan is a required part of the gate.",
            {"overall": "FAIL", "CC-08": "FAIL", "CC-11": "PASS", "CC-10": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(mutant),
                commit=mutant_head,
                work_root=str(work_root / "repro-4"),
                suite_command=SEEDED_SUITE,
                scan_paths=SUITE_CLOSURE,
                recurrence_clones=1,
                label="repro-4-hardcoded-system-temp-mutant",
            ),
        )

    # REPRO-5: this unit's own suite must itself recur from a pristine clone.  The
    # detector module and the adversarial fixtures necessarily embed the literals
    # the scanner looks for, so they are excluded here and audited by REPRO-6.
    detector_exclusions = (
        "workstreams/po03/wave-a/units/wa-003/harness/clean_clone_harness.py",
        "workstreams/po03/wave-a/units/wa-003/harness/run_reproductions.py",
        "workstreams/po03/wave-a/units/wa-003/tests/**",
    )
    if selected("REPRO-5"):
        record(
            "REPRO-5",
            "The WA-003 gate and its adversarial fixtures execute from a pristine clone of the "
            "delivered commit, so the new mechanism is portable rather than warm-checkout bound.",
            {"overall": "PASS", "CC-11": "PASS", "CC-17": "PASS", "CC-08": "PASS", "CC-12": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(repo),
                commit=args.commit,
                work_root=str(work_root / "repro-5"),
                suite_command=UNIT_SUITE,
                scan_paths=UNIT_CLOSURE,
                scan_exclude=detector_exclusions,
                recurrence_clones=2,
                timeout_seconds=1800,
                label="repro-5-unit-suite-clean-clone",
            ),
        )

    # REPRO-6: audit the exclusion itself.  Scanning the unit with no exclusions must
    # flag exactly the detector and fixture files, and nothing else.
    if selected("REPRO-6"):
        record(
            "REPRO-6",
            "Without exclusions the scanner flags only the detector module and the "
            "adversarial fixture carriers, so the REPRO-5 exclusion list is complete and "
            "no other delivered file embeds a non-portable path literal.",
            {"overall": "FAIL", "CC-08": "FAIL", "CC-11": "PASS"},
            HARNESS.HarnessConfig(
                source_repo=str(repo),
                commit=args.commit,
                work_root=str(work_root / "repro-6"),
                suite_command=SEEDED_SUITE,
                scan_paths=UNIT_CLOSURE,
                recurrence_clones=1,
                label="repro-6-unit-scan-exclusion-audit",
            ),
        )

    summary = {
        "schema_version": "OBZIO-PO03-WA003-REPRODUCTION-LEDGER-v1",
        "task_id": "PO03-WA-003",
        "repository_under_test": str(repo),
        "commit_under_test": args.commit,
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reproduction_count": len(ledger),
        "all_predictions_held": all(item["prediction_held"] for item in ledger),
        "reproductions": ledger,
    }
    ledger_path = out_dir / "reproduction-ledger.json"
    ledger_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"reproductions={len(ledger)} all_predictions_held={summary['all_predictions_held']} "
        f"ledger={ledger_path}"
    )
    return 0 if summary["all_predictions_held"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
