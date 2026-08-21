"""Deterministic checks for repository-engineering artefacts."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.artefacts import read_json
from obzio_spine.checkkit import CheckReport

REQUIRED_ARTEFACTS = [
    "branch_record.json",
    "commit_record.json",
    "pr_record.json",
    "readback_verification.json",
]

# Patterns that must never appear in an artefact. Credentials leak into audit
# records constantly; this is the cheapest control that actually catches it.
SECRET_PATTERNS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "github token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github fine-grained PAT"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws access key"),
    (re.compile(r'"(?:token|password|secret)"\s*:\s*"[^"]{8,}"', re.I),
     "literal token field"),
]


def run_checks(run_dir: str) -> CheckReport:
    r = CheckReport("repository-engineering")

    missing = [a for a in REQUIRED_ARTEFACTS
               if not os.path.exists(os.path.join(run_dir, a))]
    if missing:
        r.fail("artefacts_present", f"missing artefacts: {missing}", missing=missing)
        return r

    br = read_json(os.path.join(run_dir, "branch_record.json"))
    cr = read_json(os.path.join(run_dir, "commit_record.json"))
    pr = read_json(os.path.join(run_dir, "pr_record.json"))
    rb = read_json(os.path.join(run_dir, "readback_verification.json"))

    # --- CHK-RE-01 read-back proves the write --------------------------
    # The pack's reason to exist. Every file must be re-read from the remote
    # and digest-matched.
    if not rb.get("all_verified"):
        r.fail("CHK-RE-01_readback_verified",
               "read-back did not verify every file", checked=rb.get("checked"))
    for res in rb.get("results", []):
        if not res["match"]:
            r.fail("CHK-RE-01_readback_verified",
                   f"{res['path']}: wrote sha {res['intended_sha256'][:12]} but "
                   f"read back {str(res['observed_sha256'])[:24]}",
                   path=res["path"])

    # --- CHK-RE-02 every written file was read back --------------------
    written = {f["path"] for f in cr.get("files", [])}
    checked = {x["path"] for x in rb.get("results", [])}
    for p in sorted(written - checked):
        r.fail("CHK-RE-02_readback_total",
               f"{p} was written but never read back", path=p)
    for p in sorted(checked - written):
        r.fail("CHK-RE-02_readback_total",
               f"{p} was read back but is not in the commit record", path=p)
    if not written:
        r.fail("CHK-RE-02_readback_total", "commit record contains no files")

    # --- CHK-RE-03 no write to a protected ref -------------------------
    protected = set(br.get("protected_refs", []))
    if br.get("branch") in protected:
        r.fail("CHK-RE-03_protected_ref",
               f"wrote to protected ref {br['branch']!r}", branch=br["branch"])
    if br.get("branch") == br.get("base"):
        r.fail("CHK-RE-03_protected_ref",
               f"work branch equals base branch {br.get('base')!r}")
    if cr.get("branch") != br.get("branch"):
        r.fail("CHK-RE-03_protected_ref",
               f"commits landed on {cr.get('branch')!r}, not the created branch "
               f"{br.get('branch')!r}")

    # --- CHK-RE-04 PR points at the branch we made ---------------------
    if pr.get("head") != br.get("branch"):
        r.fail("CHK-RE-04_pr_targets_branch",
               f"PR head is {pr.get('head')!r} but the created branch was "
               f"{br.get('branch')!r}")
    if pr.get("base") != br.get("base"):
        r.fail("CHK-RE-04_pr_targets_branch",
               f"PR base is {pr.get('base')!r} but the branch was cut from "
               f"{br.get('base')!r}")
    if rb.get("ref") != br.get("branch"):
        r.fail("CHK-RE-04_pr_targets_branch",
               f"read-back checked ref {rb.get('ref')!r}, not the PR head branch")

    # --- CHK-RE-05 the operator did not merge its own PR ---------------
    if pr.get("merged"):
        r.fail("CHK-RE-05_no_self_merge",
               "PR is recorded as merged; this pack proposes, it does not merge")
    if pr.get("state") not in ("open", "OPEN"):
        r.fail("CHK-RE-05_no_self_merge",
               f"PR state is {pr.get('state')!r}, expected open")

    # --- CHK-RE-06 no credential material in any artefact --------------
    for name in REQUIRED_ARTEFACTS + ["audit.json"]:
        p = os.path.join(run_dir, name)
        if not os.path.exists(p):
            continue
        raw = open(p, "r", encoding="utf-8", errors="replace").read()
        for pat, label in SECRET_PATTERNS:
            m = pat.search(raw)
            if m:
                r.fail("CHK-RE-06_no_credential_leak",
                       f"{name} appears to contain a {label}", artefact=name,
                       pattern=label)
    cred = br.get("credential", {})
    if "token" in cred:
        r.fail("CHK-RE-06_no_credential_leak",
               "branch_record.credential carries a raw 'token' field")

    # --- CHK-RE-07 no force push ---------------------------------------
    audit_p = os.path.join(run_dir, "audit.json")
    if os.path.exists(audit_p):
        for call in read_json(audit_p):
            if call.get("force"):
                r.fail("CHK-RE-07_no_force_push",
                       f"force flag set on {call.get('op')}", call=call)
    else:
        r.warn("CHK-RE-07_no_force_push",
               "no audit.json present; force-push absence is unverified")

    # --- CHK-RE-08 commit shas are plausible and distinct --------------
    for f in cr.get("files", []):
        if not re.fullmatch(r"[0-9a-f]{7,64}", str(f.get("commit_sha", ""))):
            r.fail("CHK-RE-08_commit_identified",
                   f"{f['path']} has no valid commit sha "
                   f"({f.get('commit_sha')!r})", path=f["path"])
        if int(f.get("byte_count", -1)) < 0:
            r.fail("CHK-RE-08_commit_identified", f"{f['path']} has no byte count")

    return r


if __name__ == "__main__":
    rep = run_checks(sys.argv[1])
    print(rep.summary())
    for f in rep.findings:
        print(f"  [{f.severity}] {f.check}: {f.message}")
    sys.exit(0 if rep.passed else 1)
