#!/usr/bin/env python3
"""Executable proof that the three hooks in this directory do what they claim.

This estate's sixth recurring failure is a lesson written down without the
mechanism that makes it not recur. A hook is only a mechanism if it fires, so
this file exists so that the claim "the guard refuses X" is never a sentence in
a document — it is a case in a table that either passes or fails right now.

Run it from the repository root:

    python3 .cursor/hooks/verify_hooks.py

It builds throwaway git repositories under a temporary directory, feeds each
hook synthetic stdin matching the documented hook contract, and compares the
observed decision with the expected one. It writes nothing outside the
temporary directory and exits non-zero if any case fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
GUARD = HOOK_DIR / "guard_write_scope.py"
GATE = HOOK_DIR / "gate_claim_state.py"
LEDGER = HOOK_DIR / "ledger_subagent.py"
REAL_WRITE_SCOPE = HOOK_DIR.parent / "write-scope.json"

results: list[tuple[bool, str, str]] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout.strip()


def new_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "verify@example.invalid")
    git(repo, "config", "user.name", "verify")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    # `git init` picks the branch name from the host's init.defaultBranch, so
    # never assume it is `main`; name it explicitly.
    git(repo, "branch", "-M", "main")
    return repo


def install_write_scope(repo: Path, currentness_exit: int = 0, **overrides) -> None:
    """Install the REAL write-scope.json, with only the currentness command stubbed.

    Testing against a hand-written config would prove the harness works and
    nothing about the config that actually ships, so the protected branch globs
    and refusal patterns exercised here are the shipped ones.
    """
    config = json.loads(REAL_WRITE_SCOPE.read_text(encoding="utf-8"))
    stub = repo / "currentness_stub.py"
    stub.write_text(f"import sys\nprint('stub currentness output')\nsys.exit({currentness_exit})\n",
                    encoding="utf-8")
    config["currentness_command"] = ["python3", "currentness_stub.py"]
    config.update(overrides)
    cfg_dir = repo / ".cursor"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "write-scope.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def run_guard(repo: Path, command: str, raw_stdin: str | None = None) -> dict:
    payload = raw_stdin if raw_stdin is not None else json.dumps(
        {"command": command, "cwd": str(repo)}
    )
    r = subprocess.run([sys.executable, str(GUARD)], cwd=repo, input=payload,
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"permission": f"UNPARSEABLE(exit={r.returncode}) {r.stdout[:120]} {r.stderr[:200]}"}


def expect_guard(repo: Path, command: str, expected: str, name: str,
                 raw_stdin: str | None = None) -> None:
    out = run_guard(repo, command, raw_stdin)
    got = out.get("permission")
    record(got == expected, name, f"expected {expected}, got {got}")


# --------------------------------------------------------------------------
# guard_write_scope.py
# --------------------------------------------------------------------------
def verify_guard(root: Path) -> None:
    print("\nguard_write_scope.py — beforeShellExecution")

    repo = new_repo(root, "guard-lane")
    install_write_scope(repo)
    git(repo, "checkout", "-q", "-b", "cursor/oe-l1-cursor-baseline-696d")

    print(" benign commands are not touched")
    expect_guard(repo, "git status --short", "allow", "allows git status")
    expect_guard(repo, "gh pr list --limit 5", "allow", "allows gh pr list (read)")
    expect_guard(repo, "ls -la && python3 -c 'print(1)'", "allow", "allows unrelated shell")
    expect_guard(repo, "git push -u origin cursor/oe-l1-cursor-baseline-696d", "allow",
                 "allows push to own lane branch")
    expect_guard(repo, "git commit -m 'work'", "allow", "allows commit on lane branch")

    print(" protected branches are refused on push")
    for branch in ["main", "so02/strategic-control-plane-migration-20260822-v001",
                   "soo/whatever", "packs/bundle-1", "cursor/po03-something",
                   "cursor/so02-cur-orch-qual-01",
                   "cursor/operating-environment-return-20260822-v001",
                   "po03/anything", "cursor/setup-dev-environment-abc"]:
        expect_guard(repo, f"git push origin {branch}", "deny", f"denies push to {branch}")

    print(" refspec forms resolve to the destination branch")
    expect_guard(repo, "git push origin HEAD:main", "deny", "resolves SRC:DST refspec")
    expect_guard(repo, "git push origin cursor/x:refs/heads/main", "deny",
                 "strips refs/heads/ from destination")
    expect_guard(repo, "git push origin +main", "deny", "handles the + force-refspec prefix")

    print(" protected branches are refused on commit, and bare push follows HEAD")
    protected = new_repo(root, "guard-protected")
    install_write_scope(protected)
    git(protected, "checkout", "-q", "-b", "so02/strategic-control-plane-migration-20260822-v001")
    expect_guard(protected, "git commit -m 'x'", "deny", "denies commit while HEAD is protected")
    expect_guard(protected, "git push", "deny", "bare push targets the current branch")

    print(" named command refusals")
    expect_guard(repo, "gh pr create --title x --body y", "deny", "denies gh pr create")
    expect_guard(repo, "gh pr merge 7 --squash", "deny", "denies gh pr merge")
    expect_guard(repo, "gh issue create --title x", "deny", "denies gh issue create")
    expect_guard(repo, "gh api -X POST /repos/o/r/issues", "deny", "denies gh api -X POST")
    expect_guard(repo, "gh api --method PATCH /repos/o/r/pulls/7", "deny",
                 "denies the --method spelling of the same write")
    expect_guard(repo, "gh api -X delete /repos/o/r/git/refs/heads/x", "deny",
                 "denies a lowercase verb")
    expect_guard(repo, "gh api /repos/o/r/issues", "allow", "allows gh api GET")
    expect_guard(repo, "gh api -X GET /rate_limit", "allow", "allows an explicit -X GET")
    expect_guard(repo, "git push --force origin cursor/oe-l1-cursor-baseline-696d", "deny",
                 "denies --force")
    expect_guard(repo, "git push -f origin cursor/oe-l1-cursor-baseline-696d", "deny",
                 "denies the -f short form")
    expect_guard(repo, "git push --force-with-lease origin cursor/oe-l1-cursor-baseline-696d",
                 "allow", "allows --force-with-lease")
    expect_guard(repo, "git rebase -i HEAD~3", "deny", "denies rebase")
    expect_guard(repo, "git filter-branch --tree-filter true HEAD", "deny", "denies filter-branch")
    expect_guard(repo, "git reset --hard HEAD~1", "deny", "denies reset --hard")
    expect_guard(repo, "git commit --amend -m x", "deny", "denies commit --amend")

    print(" currentness must hold before a commit may exist")
    failing = new_repo(root, "guard-currentness")
    install_write_scope(failing, currentness_exit=1)
    git(failing, "checkout", "-q", "-b", "cursor/lane-696d")
    out = run_guard(failing, "git commit -m 'work'")
    record(out.get("permission") == "deny", "denies commit when currentness check fails",
           f"got {out.get('permission')}")
    record("stub currentness output" in out.get("agent_message", ""),
           "quotes the failing check's own output back to the agent")
    expect_guard(failing, "git status", "allow", "a failing check does not block non-commits")

    print(" detached HEAD and stale-ref push (the reproduced collision)")
    det = new_repo(root, "guard-detached")
    install_write_scope(det)
    git(det, "checkout", "-q", "-b", "cursor/lane-696d")
    base = git(det, "rev-parse", "HEAD")
    git(det, "checkout", "-q", "--detach", base)
    (det / "a.txt").write_text("a\n", encoding="utf-8")
    git(det, "add", "-A")
    git(det, "commit", "-q", "-m", "work on detached head")
    expect_guard(det, "git commit -m 'more work'", "deny", "denies commit on a detached HEAD")
    expect_guard(det, "git push -u origin cursor/lane-696d", "deny",
                 "denies pushing the lane ref left behind at base")
    record(git(det, "rev-parse", "cursor/lane-696d") == base,
           "the reproduced condition is real: the branch ref is still at base")

    print(" the stale-ref rule fires with HEAD attached, and spares divergent branches")
    att = new_repo(root, "guard-attached")
    install_write_scope(att)
    git(att, "checkout", "-q", "-b", "cursor/lane-696d")
    behind = git(att, "rev-parse", "HEAD")
    git(att, "branch", "cursor/stale-696d", behind)
    (att / "b.txt").write_text("b\n", encoding="utf-8")
    git(att, "add", "-A")
    git(att, "commit", "-q", "-m", "ahead")
    expect_guard(att, "git push origin cursor/stale-696d", "deny",
                 "denies pushing a ref strictly behind HEAD on the same lineage")
    git(att, "checkout", "-q", "-b", "cursor/divergent-696d", behind)
    (att / "c.txt").write_text("c\n", encoding="utf-8")
    git(att, "add", "-A")
    git(att, "commit", "-q", "-m", "divergent")
    git(att, "checkout", "-q", "cursor/lane-696d")
    expect_guard(att, "git push origin cursor/divergent-696d", "allow",
                 "allows pushing a genuinely divergent branch")
    expect_guard(att, "git push origin cursor/nonexistent-696d", "allow",
                 "allows pushing a branch that does not exist locally yet")

    print(" the rules are configurable, and the guard fails open")
    optout = new_repo(root, "guard-optout")
    install_write_scope(optout, refuse_detached_head=False, refuse_stale_ref_push=False)
    git(optout, "checkout", "-q", "-b", "cursor/lane-696d")
    git(optout, "checkout", "-q", "--detach", git(optout, "rev-parse", "HEAD"))
    expect_guard(optout, "git commit -m x", "allow", "honours refuse_detached_head:false")

    expect_guard(repo, "git push origin main", "allow", "fails open on malformed stdin",
                 raw_stdin="not json at all")
    naked = new_repo(root, "guard-noconfig")
    expect_guard(naked, "git push origin main", "allow", "fails open when write-scope.json is absent")

    audit = repo / ".cursor/.run/write-scope-audit.jsonl"
    record(audit.is_file() and audit.read_text(encoding="utf-8").count("\n") > 10,
           "writes an append-only audit line per decision")


# --------------------------------------------------------------------------
# gate_claim_state.py
# --------------------------------------------------------------------------
def run_gate(repo: Path, status: str = "completed") -> dict:
    r = subprocess.run([sys.executable, str(GATE)], cwd=repo,
                       input=json.dumps({"status": status, "loop_count": 0}),
                       capture_output=True, text=True, timeout=60)
    if not r.stdout.strip():
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_unparseable": r.stdout[:200]}


def verify_gate(root: Path) -> None:
    print("\ngate_claim_state.py — stop")

    clean = new_repo(root, "gate-clean")
    record(run_gate(clean) == {}, "stays silent when the turn changed nothing")

    aborted = new_repo(root, "gate-aborted")
    (aborted / "claim.md").write_text("This work is COMPLETED.\n", encoding="utf-8")
    record(run_gate(aborted, status="aborted") == {}, "stays silent when the turn did not complete")

    bare = new_repo(root, "gate-bare-claim")
    (bare / "claim.md").write_text("The lane is COMPLETED and ready.\n", encoding="utf-8")
    out = run_gate(bare)
    record("followup_message" in out, "fires on COMPLETED with no receipt manifest")
    record("bundle_sha256" in out.get("followup_message", ""),
           "names the specific evidence a COMPLETED claim requires")

    ok = new_repo(root, "gate-with-receipt")
    (ok / "claim.md").write_text("The lane is COMPLETED.\n", encoding="utf-8")
    (ok / "MANIFEST.json").write_text(
        json.dumps({"entries": [], "entry_count": 0, "bundle_sha256": "0" * 64}), encoding="utf-8")
    record(run_gate(ok) == {}, "stays silent when COMPLETED is backed by a manifest")

    qual = new_repo(root, "gate-qualified")
    (qual / "state.json").write_text(json.dumps({"terminal_state": "QUALIFIED"}), encoding="utf-8")
    record("followup_message" in run_gate(qual), "fires on QUALIFIED with no receipt manifest")

    selfacc = new_repo(root, "gate-self-accept")
    (selfacc / "MANIFEST.json").write_text(
        json.dumps({"bundle_sha256": "0" * 64}), encoding="utf-8")
    (selfacc / "acc.json").write_text(
        json.dumps({"state": "ACCEPTED", "acceptor": "this same run"}), encoding="utf-8")
    out = run_gate(selfacc)
    record("followup_message" in out, "fires when a run records its own acceptance")
    record("REQUESTED_NOT_GRANTED" in out.get("followup_message", ""),
           "names the state a self-acceptance actually sits in")

    nullacc = new_repo(root, "gate-null-acceptor")
    (nullacc / "MANIFEST.json").write_text(
        json.dumps({"bundle_sha256": "0" * 64}), encoding="utf-8")
    (nullacc / "acc.json").write_text(
        json.dumps({"state": "ACCEPTED", "acceptor": None}), encoding="utf-8")
    record(run_gate(nullacc) == {}, "accepts a null acceptor as an honest not-yet-accepted")

    proj = new_repo(root, "gate-projection")
    (proj / "report.md").write_text(
        "The pull request was opened, so the migration is complete.\n", encoding="utf-8")
    out = run_gate(proj)
    record("followup_message" in out, "fires when a pull request is described as completion")
    record("projection" in out.get("followup_message", "").lower(),
           "explains that a pull request is a projection")

    binary = new_repo(root, "gate-binary-only")
    (binary / "blob.bin").write_bytes(b"\x00\x01COMPLETED\x02")
    record(run_gate(binary) == {}, "ignores non-text artifacts")


# --------------------------------------------------------------------------
# ledger_subagent.py
# --------------------------------------------------------------------------
def verify_ledger(root: Path) -> None:
    print("\nledger_subagent.py — subagentStart / subagentStop")

    repo = new_repo(root, "ledger")
    git(repo, "checkout", "-q", "-b", "cursor/lane-696d")
    env = dict(os.environ, CURSOR_AGENT_SOCKET="/nonexistent/socket.sock")

    def run(args: list[str], payload: str) -> int:
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=repo, input=payload,
                              capture_output=True, text=True, timeout=60, env=env).returncode

    rc = run([], json.dumps({"subagent_type": "lane-oe-l1", "subagent_id": "sa-1",
                             "conversation_id": "conv-9"}))
    record(rc == 0, "subagentStart exits 0")
    rc = run(["--stop"], json.dumps({"subagent_type": "lane-oe-l1", "subagent_id": "sa-1",
                                     "status": "completed"}))
    record(rc == 0, "subagentStop exits 0")
    record(run([], "}{ not json") == 0, "tolerates malformed stdin")

    ledger = repo / ".cursor/.run/subagent-ledger.jsonl"
    lines = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
    record(len(lines) == 3, "appends one line per lifecycle event", f"got {len(lines)}")
    record([l["phase"] for l in lines] == ["start", "stop", "start"], "records the phase")
    record(lines[0]["subagent_type"] == "lane-oe-l1" and lines[0]["subagent_id"] == "sa-1",
           "records the only identity a subagent exposes")
    record(lines[0]["checked_out_branch"] == "cursor/lane-696d",
           "records which branch the subagent was actually on")
    record(lines[0]["turn_source"] == "unavailable",
           "marks turn metadata unavailable rather than inventing a value",
           f"got {lines[0]['turn_source']}")

    boot_dir = repo / ".cursor/.run"
    (boot_dir / "runtime-binding.json").write_text(
        json.dumps({"agent_id": "bc-boot", "turn_id": "turn-boot", "turn_model": "model-boot"}),
        encoding="utf-8")
    run([], json.dumps({"subagent_type": "lane-oe-l2"}))
    last = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    record(last["turn_source"] == "boot_snapshot" and last["turn_id"] == "turn-boot",
           "falls back to the boot snapshot and says so", f"got {last['turn_source']}")

    # The metadata service answers a missing leaf with a JSON error body, not
    # with empty output. Recording that body as a value is how a vanished field
    # becomes a confident wrong answer, so absence must survive round-tripping.
    fake_bin = repo / "fakebin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text(
        '#!/bin/sh\necho \'{"error":"not found"}\'\n', encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)
    subprocess.run([sys.executable, str(LEDGER)], cwd=repo,
                   input=json.dumps({"subagent_type": "lane-oe-l3"}),
                   capture_output=True, text=True, timeout=60,
                   env=dict(env, PATH=f"{fake_bin}:{env['PATH']}"))
    last = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    record('"error"' not in json.dumps(last),
           "treats a 404 error body as absence, never as a value")


def main() -> int:
    for path in (GUARD, GATE, LEDGER, REAL_WRITE_SCOPE):
        if not path.is_file():
            print(f"missing: {path}")
            return 2

    root = Path(tempfile.mkdtemp(prefix="verify-hooks-"))
    try:
        verify_guard(root)
        verify_gate(root)
        verify_ledger(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    failed = [name for ok, name, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases passed")
    if failed:
        print("failed:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
