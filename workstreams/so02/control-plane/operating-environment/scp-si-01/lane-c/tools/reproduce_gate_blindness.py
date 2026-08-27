#!/usr/bin/env python3
"""Reproduce the one defect this lane found in the gate it was told to invoke.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/reproduce_gate_blindness.py \
        --repo-root .

Exit 0 means the defect still reproduces and this lane's own check still catches
it. Exit 1 means one of the two stopped being true, which is worth knowing
either way.

## The claim

`write_admission`'s evidence gate cannot tell a true `MANIFEST_CLOSURE` record
from a stale or invented one, because
`evidence_integrity.verify_manifest_closure` asks only whether every
`present_paths` entry is covered and whether `bundle_sha256` binds the entry
list. Neither question opens a declared file. So a declaration asserting hashes
for bytes that do not exist is admitted.

This is not a hypothetical. Lane C's first declaration went stale exactly this
way: the slice was rebuilt against a newer integration head, six deliverable
files changed, and the declaration still carried the old hashes. Nothing in the
gate would have said so.

## What this script does

It takes the lane's real declaration, replaces one entry's `sha256` with a
well-formed hash of text that is not in the file, recomputes `bundle_sha256` so
the record stays internally consistent — which is what a stale declaration looks
like, since `build_declaration.py` computes the bundle from whatever entries it
has — and then puts that record through both checks:

* the estate's evidence gate, called directly rather than modelled;
* this lane's `verify_declaration_evidence.verify`, on the same record.

Only the evidence gate is exercised. The other three gates are not implicated
and are not touched, because a reproduction that fails a gate for an unrelated
reason has demonstrated nothing.

## The correction, stated plainly

This is a gap in a control, not a reason to distrust the control. The three
other gates do recompute against the world: the concurrency gate re-runs
`git ls-remote`, and the reversibility gate re-executes the rollback against a
real disposable remote. `EARNED` is the right class for the finding and the
right response is the extra check, which is why this lane added one rather than
routing around the gate.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402
import verify_declaration_evidence as V  # noqa: E402
from build_declaration import DECLARATION_REL  # noqa: E402

ESTATE_TOOLS = os.path.join("workstreams", "so02", "control-plane",
                            "operating-environment", "tools")


def load_gate(repo_root: str):
    """Import the estate's live gate. Never a local copy of it."""
    import importlib.util

    tools_dir = os.path.join(repo_root, ESTATE_TOOLS)
    sys.path.insert(0, tools_dir)
    path = os.path.join(tools_dir, "write_admission.py")
    spec = importlib.util.spec_from_file_location("write_admission_live", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)

    declaration, problems = A.read_back_and_parse(
        os.path.join(repo_root, DECLARATION_REL))
    if declaration is None:
        print(f"FAIL the lane's declaration is unparsable: {problems}")
        return 1

    honest_errors = V.verify(repo_root, copy.deepcopy(declaration))
    if honest_errors:
        print("FAIL the lane's real declaration is already failing its own check, so this "
              "reproduction cannot isolate the gate's blindness:")
        for e in honest_errors:
            print(f"     {e}")
        return 1

    stale = copy.deepcopy(declaration)
    record = stale["evidence"]["record"]
    victim = record["entries"][0]
    real_sha = victim["sha256"]
    victim["sha256"] = A.sha256_text(
        "bytes that are not in that file, hashed so the field stays well formed")
    # A stale declaration is internally consistent. It has to be: the bundle is
    # computed from the entries it holds, whatever they say.
    record["bundle_sha256"] = A.bundle_sha256(record["entries"])

    gate = load_gate(repo_root)
    verdict = gate.check_evidence_gate(stale, Path(repo_root))
    caught_by_gate = not verdict["passed"]
    lane_errors = V.verify(repo_root, copy.deepcopy(stale))
    caught_here = any(e.startswith("HASH_MISMATCH") for e in lane_errors)

    print(f"tampered entry     {victim['path']}")
    print(f"  real sha256      {real_sha}")
    print(f"  declared sha256  {victim['sha256']}")
    print()
    print("estate evidence gate  evidence_integrity.verify_manifest_closure")
    print(f"  verdict            {verdict['verdict']}")
    print(f"  passed             {verdict['passed']}")
    for f in verdict["findings"]:
        print(f"  finding            {f}")
    print()
    print("this lane's check     verify_declaration_evidence.verify")
    print(f"  findings           {len(lane_errors)}")
    for e in lane_errors:
        print(f"  finding            {e}")
    print()
    print(f"gate_admits_a_false_hash = {not caught_by_gate}")
    print(f"lane_check_catches_it    = {caught_here}")

    if caught_by_gate:
        print("\nNOT_REPRODUCED: the gate refused a false hash. The gap this lane reported "
              "has been closed upstream and verify_declaration_evidence.py is now redundant "
              "for this case; say so rather than keeping a stale finding alive.")
        return 1
    if not caught_here:
        print("\nFAIL: the gate is blind and this lane's own check did not catch it either, "
              "which is worse than the defect it was written for.")
        return 1
    print("\nREPRODUCED: a false hash is admitted by the gate and caught here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
