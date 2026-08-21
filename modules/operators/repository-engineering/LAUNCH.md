# LAUNCH — repository-engineering

## Entry point

```bash
cd /tmp/packs/repository-engineering
python3 test_pack.py                 # runs against a REAL local git repo
python3 checks.py <run_dir>
```

```python
from transport import Credential, GitHubTransport, LocalGitTransport
from state_machine import build_machine

from state_machine import make_acceptor
from obzio_spine.expectation import AcceptanceReturn

tp = GitHubTransport(Credential("op-01", os.environ["GITHUB_TOKEN"]), "owner", "repo")
files = {"docs/x.md": b"...."}

# COMMIT FIRST: expected read-back digests are sha256 of the intended bytes,
# computed before the branch is cut. No repository is contacted.
acceptor = make_acceptor("reviewer-01", "obzio/feature-x", files, "main", "Add x")

m  = build_machine(run_dir, producer_id, commitments, tp,
                   branch="obzio/feature-x", files=files,
                   pr_title="Add x", pr_body="why", acceptor=acceptor)
for _ in range(6): m.advance()
m.advance(acceptance=AcceptanceReturn(True, acceptance_reveal, acceptor.reveal()))
m.advance()
```

The token is read from the environment by the CALLER and wrapped in
`Credential`. It is never written to an artefact — only
`Credential.redacted()` is, and `CHK-RE-06` scans every artefact for leaked
secret material.

## Acceptance independence: `INDEPENDENT_ORACLE`

Acceptance is **commit-first**. The acceptor derives and hash-commits its own
expected result from the declared inputs *before any artefact exists*; the
machine refuses the commitment if one already does. At the gate the artefacts
are compared against that commitment and **divergence defaults to REJECT**.
The channel back to the producer is **one bit** — no rationale, no diff, no
rubric. See BOUNDARIES.md for exactly what this oracle does and does not
cover.

## Mandate

Operate a git repository through an authenticated API: cut a branch from the
remote's real default, write files, open a pull request, then **read the bytes
back from the remote and digest-match them**.

A write you did not read back is not a write you can report.

## Maximum delegated authority

| Act | Authority |
|---|---|
| Read the remote's default branch and refs | **GRANTED** |
| Create a new non-protected branch | **GRANTED** |
| Write files on that branch and commit | **GRANTED** |
| Open a pull request against the base | **GRANTED** |
| Read any ref back for verification | **GRANTED** |
| Write to `main`/`master`/`release`/`production` | **DENIED** — `ProtectedRefError`, machine-enforced |
| Force-push, rewrite history, delete refs | **DENIED** — not reachable through the transport API at all |
| Merge, approve, or close the PR | **DENIED** — this pack proposes; `CHK-RE-05` |
| Put a token into any artefact | **DENIED** — `CHK-RE-06` |
| Report success on an unverified write | **DENIED** — `CHK-RE-01` |
| Accept its own PR | **DENIED** — machine-enforced at the gate |

## Transport fidelity

| Transport | Status |
|---|---|
| `LocalGitTransport` | **PROVEN** — drives the real `git` binary, exercised by every test |
| `GitHubTransport` | **UNPROVEN** — real urllib REST calls, correct per the documented API, but never executed against a live repo from this sandbox. Verify against a scratch repo before trusting it. |

## Required artefacts

`branch_record.json` · `commit_record.json` · `pr_record.json` ·
`readback_verification.json` — plus `audit.json`, `check_report.json`,
`journal.json`, `return_state.json`.

## Definition of done

`readback_verification.all_verified` is true, the PR is open and unmerged,
no artefact contains credential material, and the reviewer returned ACCEPT.
