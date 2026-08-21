#!/usr/bin/env python3
"""repository-engineering pack tests.

These run against a REAL git repository created in a temp dir: a real bare
remote, a real clone, real commits, real pushes, and a read-back that shells
out to `git show` against the remote.

INJECTED FAILURE: a transport that corrupts one file in flight. The read-back
digest mismatch must block the run.
"""

import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine import acceptance as acc
from obzio_spine import expectation as exp
from obzio_spine.machine import OperatorMachine, GuardFailure, TransitionError
from obzio_spine.states import State
from obzio_spine.tinytest import (Suite, expect_raises, assert_eq,
                                  assert_true, assert_in, assert_no_import)
from obzio_spine.artefacts import read_json, write_json
from obzio_spine import manifest

import engine
import transport as T
from checks import run_checks
from state_machine import build_machine, make_acceptor, PACK
import oracle

S = Suite(PACK)
TMP = tempfile.mkdtemp(prefix="re-")

FILES = {
    "docs/decision.md": b"# Decision\n\nWe ship the pack.\n",
    "src/handler.py": b"def handle(x):\n    return x + 1\n",
}
CRED = T.Credential("repo-op-01", "ghp_" + "a" * 36)


def _run(*a, cwd=None):
    r = subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr}")
    return r.stdout.strip()


def make_repo(name, default_branch="main"):
    """A real bare remote plus a real working clone with one commit on it."""
    base = os.path.join(TMP, name)
    remote = os.path.join(base, "remote.git")
    work = os.path.join(base, "work")
    os.makedirs(base, exist_ok=True)
    _run("init", "--bare", f"--initial-branch={default_branch}", remote)
    _run("clone", remote, work)
    _run("config", "user.email", "op@obzio.test", cwd=work)
    _run("config", "user.name", "Obzio Operator", cwd=work)
    with open(os.path.join(work, "README.md"), "w") as f:
        f.write("# base\n")
    _run("add", "README.md", cwd=work)
    _run("commit", "-m", "base", cwd=work)
    _run("push", "origin", default_branch, cwd=work)
    return work, remote


def transport(name):
    work, remote = make_repo(name)
    return T.LocalGitTransport(CRED, work, remote)


def fresh(n):
    d = os.path.join(TMP, "runs", n)
    os.makedirs(d, exist_ok=True)
    return d


def reviewer():
    return acc.ReviewerKeypair.generate("reviewer-repo-01")


def drive(name, tp=None, files=None, branch="obzio/feature-x", steps=6,
          producer="repo-op-01", base="main"):
    """Commit-first: expected read-back digests committed before the branch
    is cut."""
    tp = tp or transport(name + "-repo")
    kp = reviewer()
    fs = files if files is not None else FILES
    ac = make_acceptor("reviewer-repo-01", branch, fs, base, "Add decision record")
    m = build_machine(fresh(name), producer, kp.commitments(), tp, branch, fs,
                      "Add decision record", "Body of the PR", acceptor=ac)
    for _ in range(steps):
        m.advance()
    return m, kp, tp, ac


def accept_bit(m, kp, ac, bit=True):
    return exp.AcceptanceReturn(
        accept=bit,
        acceptance_reveal=kp.issue(m.current_run_digest(),
                                   acc.ACCEPT if bit else acc.REJECT),
        expectation_reveal=ac.reveal())


# ------------------------------------------------------------------ happy path

@S.test
def test_full_lifecycle_against_real_git():
    """Branch, write, PR, read-back verify against a real git remote."""
    m, kp, tp, ac = drive("happy")
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)
    rb = read_json(os.path.join(m.run_dir, "readback_verification.json"))
    assert_eq(rb["all_verified"], True)
    assert_eq(rb["checked"], 2)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["verdict"], "ACCEPT")


@S.test
def test_commits_really_landed_on_the_remote():
    """Independent of our artefacts: ask git directly what is on the remote."""
    m, kp, tp, ac = drive("landed")
    out = subprocess.run(["git", "show", "obzio/feature-x:docs/decision.md"],
                         cwd=tp.remote, capture_output=True)
    assert_eq(out.returncode, 0, "file must exist on the remote branch")
    assert_eq(out.stdout, FILES["docs/decision.md"],
              "remote bytes must equal what we intended to write")
    branches = subprocess.run(["git", "branch", "--list"], cwd=tp.remote,
                              capture_output=True, text=True).stdout
    assert_in("obzio/feature-x", branches)


@S.test
def test_readback_reads_remote_not_worktree():
    """P14: corrupting the LOCAL worktree must not change the read-back."""
    m, kp, tp, ac = drive("remote-read")
    local = os.path.join(tp.work, "docs/decision.md")
    with open(local, "wb") as f:
        f.write(b"LOCAL CORRUPTION")
    got = tp.get_file("obzio/feature-x", "docs/decision.md")
    assert_eq(got, FILES["docs/decision.md"],
              "read-back must come from the remote, not the working tree")


@S.test
def test_base_branch_is_queried_not_assumed():
    """The base comes from the remote's real HEAD, not a hardcoded 'main'."""
    m, kp, tp, ac = drive("base")
    br = read_json(os.path.join(m.run_dir, "branch_record.json"))
    assert_eq(br["base"], "main")
    assert_true(br["base_sha"], "base sha must be recorded")
    events = [e for e in m.journal if e["event"] == "STATE_RECOVERED"]
    assert_eq(events[0]["detail"]["base_branch"], "main")


# ------------------------------------------------- INJECTED FAILURE + RECOVERY

class CorruptingTransport(T.LocalGitTransport):
    """Injected fault: silently flips one byte on read-back for one path.

    This models the realistic failure -- encoding mangling, a proxy rewriting
    content, a stale CDN -- where the write 'succeeds' and the bytes are wrong.
    """
    corrupt_path = "src/handler.py"

    def get_file(self, ref, path):
        data = super().get_file(ref, path)
        if path == self.corrupt_path:
            return data.replace(b"x + 1", b"x + 2")
        return data


@S.test
def test_injected_readback_mismatch_blocks_progress():
    """INJECTED FAILURE: read-back returns different bytes. Run must stop."""
    work, remote = make_repo("corrupt-repo")
    tp = CorruptingTransport(CRED, work, remote)
    kp = reviewer()
    d = fresh("corrupt")
    m = build_machine(d, "repo-op-01", kp.commitments(), tp, "obzio/feature-x",
                      FILES, "Add decision record", "Body",
                      acceptor=make_acceptor("reviewer-repo-01", "obzio/feature-x",
                                             FILES, "main", "Add decision record"))
    for _ in range(4):
        m.advance()
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT)

    err = expect_raises(GuardFailure, m.advance)
    assert_in("MACHINE_CHECKS_PASSED", str(err))
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT, "must not have moved")

    msgs = " ".join(f.message for f in m.check_report.failures)
    assert_in("CHK-RE-01", " ".join(f.check for f in m.check_report.failures))
    assert_in("src/handler.py", msgs)
    assert_in("read back", msgs)

    # The artefact itself must record the mismatch, not just the exception.
    rb = read_json(os.path.join(d, "readback_verification.json"))
    assert_eq(rb["all_verified"], False)
    bad = [x for x in rb["results"] if not x["match"]]
    assert_eq(len(bad), 1)
    assert_eq(bad[0]["path"], "src/handler.py")
    assert_true(bad[0]["observed_sha256"] != bad[0]["intended_sha256"])


@S.test
def test_recovery_with_honest_transport():
    """RECOVERY: the same write through an uncorrupted transport completes."""
    m, kp, tp, ac = drive("recovered")
    assert_true(m.check_report.passed, "checks must pass on an honest transport")
    rb = read_json(os.path.join(m.run_dir, "readback_verification.json"))
    assert_eq(rb["all_verified"], True)
    assert_true(all(x["match"] for x in rb["results"]))
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


# ------------------------------------------------------------------- auth/refs

@S.test
def test_no_credential_refused():
    """P3: a transport cannot be constructed without a credential."""
    expect_raises(T.AuthError, T.LocalGitTransport, None, "/tmp", "/tmp")
    expect_raises(T.AuthError, T.LocalGitTransport,
                  T.Credential("x", ""), "/tmp", "/tmp")


@S.test
def test_protected_ref_write_refused():
    """P4: writing to main is refused by the transport itself."""
    tp = transport("protected-repo")
    expect_raises(T.ProtectedRefError, tp.create_branch, "main")
    expect_raises(T.ProtectedRefError, tp.put_file, "main", "a.txt", b"x", "m")
    err = expect_raises(T.ProtectedRefError, tp.create_branch, "production")
    assert_in("protected ref", str(err))


@S.test
def test_protected_branch_refused_at_admission():
    """The machine refuses a protected target before any git call happens."""
    tp = transport("protected2-repo")
    kp = reviewer()
    m = build_machine(fresh("protected2"), "repo-op-01", kp.commitments(), tp,
                      "main", FILES, "t", "b",
                      acceptor=make_acceptor("reviewer-repo-01", "main", FILES,
                                             "main", "t"))
    m.advance()
    err = expect_raises(GuardFailure, m.advance)
    assert_in("protected ref", str(err))


@S.test
def test_branch_equals_base_refused():
    """P5: branch == base is refused even when the base is NOT protected.

    Isolating this from P4 matters: on a normal repo `main` is both the base
    and a protected ref, so a refusal there proves nothing about which control
    fired. This repo's default branch is `develop`, which is not in the
    protected list, so only the branch-equals-base rule can be responsible."""
    work, remote = make_repo("samebase-repo", default_branch="develop")
    tp = T.LocalGitTransport(CRED, work, remote)
    assert_eq(tp.default_branch(), "develop")
    assert_true("develop" not in tp.protected,
                "the base must be unprotected for this test to isolate P5")
    err = expect_raises(T.ProtectedRefError, engine.execute, tp, "develop",
                        FILES, "t", "b")
    assert_in("is the base branch", str(err))
    # And a normal branch on the same repo still works, proving the refusal
    # was about the collision and not about the repo being broken.
    out = engine.execute(tp, "obzio/ok", FILES, "t", "b")
    assert_eq(out["readback_verification"]["all_verified"], True)
    assert_eq(out["pr_record"]["base"], "develop")


@S.test
def test_path_traversal_refused():
    """P12: paths escaping the repo are refused at admission."""
    tp = transport("traversal-repo")
    kp = reviewer()
    bad = {"../../etc/passwd": b"bad"}
    m = build_machine(fresh("traversal"), "repo-op-01", kp.commitments(), tp,
                      "obzio/x", bad, "t", "b",
                      acceptor=make_acceptor("reviewer-repo-01", "obzio/x", bad,
                                             "main", "t"))
    m.advance()
    err = expect_raises(GuardFailure, m.advance)
    assert_in("unsafe repository path", str(err))


@S.test
def test_empty_pr_refused():
    """P13: an empty change set never opens a PR."""
    tp = transport("emptypr-repo")
    expect_raises(ValueError, engine.execute, tp, "obzio/x", {}, "t", "b")


@S.test
def test_force_push_not_reachable():
    """P11: no transport method exposes a force flag."""
    import inspect
    for name in ("create_branch", "put_file", "get_file", "open_pr"):
        sig = inspect.signature(getattr(T.LocalGitTransport, name))
        assert_true("force" not in sig.parameters,
                    f"{name} must not accept a force parameter")
    src = inspect.getsource(T.LocalGitTransport)
    for banned in ("--force", "-f\"", "push --force", "reset --hard"):
        assert_true(banned not in src, f"transport source contains {banned!r}")


# --------------------------------------------------------------- credentials

@S.test
def test_credential_never_serialised():
    """P10: the raw token appears in no artefact."""
    m, kp, tp, ac = drive("cred")
    for fn in os.listdir(m.run_dir):
        raw = open(os.path.join(m.run_dir, fn), encoding="utf-8", errors="replace").read()
        assert_true(CRED.token not in raw, f"raw token leaked into {fn}")
    br = read_json(os.path.join(m.run_dir, "branch_record.json"))
    assert_true("token" not in br["credential"])
    assert_eq(br["credential"]["token_present"], True)
    assert_eq(br["credential"]["principal"], "repo-op-01")


@S.test
def test_credential_repr_is_redacted():
    """Even accidental logging of the object cannot spill the token."""
    c = T.Credential("p", "ghp_secretsecretsecret")
    assert_true("secret" not in repr(c), "repr must redact")
    assert_true("secret" not in str(c), "str must redact")
    assert_true("secret" not in f"{c}", "f-string must redact")


@S.test
def test_leaked_token_detected():
    """P10: if a token DID reach an artefact, CHK-RE-06 catches it."""
    m, kp, tp, ac = drive("leak")
    p = os.path.join(m.run_dir, "branch_record.json")
    br = read_json(p)
    br["credential"]["token"] = "ghp_" + "b" * 36
    write_json(p, br)
    rep = run_checks(m.run_dir)
    assert_true(not rep.passed)
    checks = " ".join(f.check for f in rep.failures)
    assert_in("CHK-RE-06", checks)


# --------------------------------------------------------------- record checks

@S.test
def test_unverified_file_caught():
    """P7: a file written but not read back is caught."""
    m, kp, tp, ac = drive("unverified")
    p = os.path.join(m.run_dir, "readback_verification.json")
    rb = read_json(p)
    rb["results"] = [x for x in rb["results"] if x["path"] != "src/handler.py"]
    rb["checked"] = len(rb["results"])
    write_json(p, rb)
    rep = run_checks(m.run_dir)
    assert_in("CHK-RE-02", " ".join(f.check for f in rep.failures))
    assert_in("never read back", " ".join(f.message for f in rep.failures))


@S.test
def test_pr_base_mismatch_caught():
    """P8: a PR opened against the wrong base is caught."""
    m, kp, tp, ac = drive("prbase")
    p = os.path.join(m.run_dir, "pr_record.json")
    pr = read_json(p)
    pr["base"] = "some-other-branch"
    write_json(p, pr)
    rep = run_checks(m.run_dir)
    assert_in("CHK-RE-04", " ".join(f.check for f in rep.failures))


@S.test
def test_self_merge_caught():
    """P9: a PR recorded as merged is refused."""
    m, kp, tp, ac = drive("merge")
    p = os.path.join(m.run_dir, "pr_record.json")
    pr = read_json(p)
    pr["merged"] = True
    pr["state"] = "closed"
    write_json(p, pr)
    rep = run_checks(m.run_dir)
    assert_in("CHK-RE-05", " ".join(f.check for f in rep.failures))
    assert_in("does not merge", " ".join(f.message for f in rep.failures))


@S.test
def test_commits_landed_on_wrong_branch_caught():
    """A commit record naming a different branch than the one cut is caught."""
    m, kp, tp, ac = drive("wrongbranch")
    p = os.path.join(m.run_dir, "commit_record.json")
    cr = read_json(p)
    cr["branch"] = "obzio/some-other"
    write_json(p, cr)
    rep = run_checks(m.run_dir)
    assert_in("CHK-RE-03", " ".join(f.check for f in rep.failures))


@S.test
def test_github_transport_is_declared_unproven():
    """The pack must not claim GitHubTransport is verified."""
    b = open(os.path.join(_HERE, "BOUNDARIES.md"), encoding="utf-8").read()
    l = open(os.path.join(_HERE, "LAUNCH.md"), encoding="utf-8").read()
    assert_in("UNPROVEN", b)
    assert_in("UNPROVEN", l)
    assert_true(hasattr(T.GitHubTransport, "open_pr"))
    # It must at least be import-clean and correctly shaped.
    g = T.GitHubTransport(CRED, "owner", "repo")
    assert_eq(g.API, "https://api.github.com")


# ------------------------------------------------------------------- the gate

@S.test
def test_producer_cannot_self_advance():
    """P1: the engineer cannot accept its own PR."""
    m, kp, tp, ac = drive("gate")
    err = expect_raises(acc.AcceptanceError, m.advance)
    assert_in("cannot advance itself", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_self_review_machine_refused():
    """P2: producer and reviewer may not be the same principal."""
    kp = acc.ReviewerKeypair.generate("repo-op-01")
    tp = transport("selfrev-repo")
    expect_raises(acc.SelfAcceptanceError, OperatorMachine,
                  PACK, fresh("selfrev"), "repo-op-01", kp.commitments())


@S.test
def test_forged_acceptance_refused():
    """Forging a reveal requires a SHA-256 preimage."""
    m, kp, tp, ac = drive("forge")
    dg = m.current_run_digest()
    forged = acc.Reveal("reviewer-repo-01", acc.ACCEPT, dg, "guess",
                        acc.bind("guess", dg, acc.ACCEPT))
    expect_raises(acc.AcceptanceError, m.advance,
                  acceptance=exp.AcceptanceReturn(True, forged, ac.reveal()))


@S.test
def test_post_acceptance_tamper_detected():
    """Editing the verification record after sign-off is caught."""
    m, kp, tp, ac = drive("tamper")
    m.advance(acceptance=accept_bit(m, kp, ac))
    p = os.path.join(m.run_dir, "readback_verification.json")
    rb = read_json(p)
    rb["all_verified"] = "definitely"
    write_json(p, rb)
    err = expect_raises(TransitionError, m.advance)
    assert_in("changed after acceptance", str(err))


@S.test
def test_checks_report_missing_artefacts():
    """checks.py on an empty dir fails rather than passing vacuously."""
    rep = run_checks(fresh("emptydir"))
    assert_true(not rep.passed)
    assert_in("missing artefacts", rep.failures[0].message)


# ------------------------------------------------------ commit-first (NEW)

@S.test
def test_anchored_acceptor_is_refused():
    """REQUIRED: an acceptor that has SEEN the records cannot commit."""
    m0, kp0, tp0, ac0 = drive("anchored")
    d = m0.run_dir
    assert_true(os.path.exists(os.path.join(d, "readback_verification.json")))
    kp = reviewer()
    m = OperatorMachine(PACK, d, "repo-op-02", kp.commitments(),
                        artefact_names=["branch_record.json", "commit_record.json",
                                        "pr_record.json",
                                        "readback_verification.json"])
    late = make_acceptor("reviewer-repo-01", "obzio/feature-x", FILES, "main", "t")
    err = expect_raises(exp.AnchoringError, m.register_expectation, late.commitment())
    assert_in("anchored", str(err))


@S.test
def test_commit_first_is_mandatory():
    """No committed expectation means the run cannot leave PREFLIGHT."""
    tp = transport("nocommit-repo")
    kp = reviewer()
    m = build_machine(fresh("nocommit"), "repo-op-01", kp.commitments(), tp,
                      "obzio/x", FILES, "t", "b")
    err = expect_raises(exp.AnchoringError, m.advance)
    assert_in("commit-first is mandatory", str(err))


@S.test
def test_expected_digests_are_arithmetic_not_judgement():
    """The oracle's expectation is sha256 of the intended bytes. Nothing else.

    This is the strongest independence available anywhere in the five packs:
    the expected value is fixed by arithmetic, so the acceptor is not
    re-running the producer's logic and agreeing with itself."""
    e = oracle.derive_expectation("obzio/feature-x", FILES, "main", "t")
    import hashlib
    for path, content in FILES.items():
        assert_eq(e.fields["expected_digests"][path],
                  hashlib.sha256(content).hexdigest())
    assert_eq(e.derivation, exp.Derivation.INDEPENDENT_ORACLE)
    assert_no_import(os.path.join(_HERE, "oracle.py"), ["engine", "transport"])


@S.test
def test_corrupt_readback_diverges_from_precommitment():
    """The corrupting transport now fails against a PRE-COMMITTED digest.

    Previously the corruption was caught by the pack's own checks. Now it is
    caught by an expectation formed before the write happened -- so it holds
    even if the producer's own checks were compromised."""
    work, remote = make_repo("precommit-corrupt-repo")
    tp = CorruptingTransport(CRED, work, remote)
    kp = reviewer()
    ac = make_acceptor("reviewer-repo-01", "obzio/feature-x", FILES, "main",
                       "Add decision record")
    m = build_machine(fresh("precommit-corrupt"), "repo-op-01", kp.commitments(),
                      tp, "obzio/feature-x", FILES, "Add decision record", "Body",
                      acceptor=ac)
    for _ in range(4):
        m.advance()
    # The pack's own checks catch it first, which is correct and unchanged.
    expect_raises(GuardFailure, m.advance)
    # And the pre-committed digest disagrees with what the remote returned.
    actual = oracle.extract_actual(m.run_dir)
    agrees, div = exp.compare(ac.expectation, actual)
    assert_true(not agrees, "the pre-committed digest must disagree")
    fields = {d["field"] for d in div}
    assert_in("expected_digests", fields)
    assert_in("all_readback_verified", fields)


@S.test
def test_divergence_forces_reject_over_acceptor_bit():
    """An ACCEPT bit cannot override a digest that does not match."""
    m, kp, tp, ac = drive("diverge")
    p = os.path.join(m.run_dir, "pr_record.json")
    pr = read_json(p)
    pr["merged"] = True                     # this pack must never merge
    write_json(p, pr)
    err = expect_raises(exp.DivergenceError, m.advance,
                        acceptance=accept_bit(m, kp, ac, bit=True))
    assert_eq(m.verdict, "REJECT")
    ev = [e for e in m.journal if e["event"] == "DIVERGENCE_FORCED_REJECT"][0]
    assert_in("pr_merged", ev["detail"]["divergent_fields"])
    assert_eq(ev["detail"]["acceptor_said"], "ACCEPT")


@S.test
def test_single_bit_channel_carries_no_guidance():
    """The producer learns THAT it failed, never WHAT to change."""
    m, kp, tp, ac = drive("onebit")
    ret = accept_bit(m, kp, ac, bit=False)
    assert_eq(ret.bit(), 0)
    assert_true(not hasattr(ret.acceptance_reveal, "note"))
    logged = ret.to_json()
    assert_eq(sorted(logged), ["accept", "bit", "reviewer_id"])
    err = expect_raises(acc.AcceptanceError, m.advance, acceptance=ret)
    for leak in ("digest", "sha256", "branch", "path", "docs/", "src/"):
        assert_true(leak not in str(err).lower(),
                    f"rejection leaked {leak!r} back to the producer")


@S.test
def test_manifest_verifies_and_detects_tamper():
    """MANIFEST.json detects a modified pack file."""
    ok, problems = manifest.verify(_HERE)
    assert_true(ok, f"manifest should verify clean: {problems}")
    victim = os.path.join(_HERE, "transport.py")
    original = open(victim, "rb").read()
    try:
        with open(victim, "ab") as f:
            f.write(b"\n# tamper\n")
        assert_true(not manifest.verify(_HERE)[0], "tamper must be detected")
    finally:
        with open(victim, "wb") as f:
            f.write(original)
    assert_true(manifest.verify(_HERE)[0], "clean again after restore")


if __name__ == "__main__":
    rc = S.run()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
