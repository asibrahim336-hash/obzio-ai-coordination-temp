# BOUNDARIES — repository-engineering

**MACHINE** = code refuses it, with a named test. **BEHAVIOURAL_ONLY** = prose
only; nothing here detects a violation.

## Permitted acts

| Act | Bound |
|---|---|
| Query the remote for its default branch | Read-only |
| Create a branch from that base | Name must not be a protected ref |
| Write files and commit on that branch | Paths must be relative and contain no `..` |
| Open a pull request | Head = created branch, base = queried default |
| Read any ref back to verify | Read from the REMOTE, never the working tree |

## Prohibited acts

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| P1 | Advancing past `INDEPENDENT_ACCEPTANCE` alone | **MACHINE** | Spine gate. Test: `test_producer_cannot_self_advance` |
| P2 | Self-review | **MACHINE** | `SelfAcceptanceError`. Test: `test_self_review_machine_refused` |
| P3 | Operating without a credential | **MACHINE** | `Transport.__init__` raises `AuthError`. Test: `test_no_credential_refused` |
| P4 | Writing to a protected ref | **MACHINE** | `_guard_ref` raises `ProtectedRefError`; `CHK-RE-03`. Test: `test_protected_ref_write_refused` |
| P5 | Branching onto the base branch itself | **MACHINE** | `engine.execute` raises; `CHK-RE-03`. Test: `test_branch_equals_base_refused` |
| P6 | Reporting an unverified write as done | **MACHINE** | `CHK-RE-01`. Test: `test_injected_readback_mismatch_blocks_progress` |
| P7 | Writing a file and not reading it back | **MACHINE** | `CHK-RE-02`. Test: `test_unverified_file_caught` |
| P8 | Opening a PR against the wrong base | **MACHINE** | `CHK-RE-04`. Test: `test_pr_base_mismatch_caught` |
| P9 | Merging its own PR | **MACHINE** | `CHK-RE-05`. Test: `test_self_merge_caught` |
| P10 | Leaking a token into an artefact | **MACHINE** | `CHK-RE-06` regex scan + `Credential.redacted()`. Tests: `test_credential_never_serialised`, `test_leaked_token_detected` |
| P11 | Force-pushing | **MACHINE (by construction)** | No transport method accepts a force flag; `git push --force` is unreachable through the API. `CHK-RE-07` audits the flag. Test: `test_force_push_not_reachable` |
| P12 | Escaping the repo with `../` paths | **MACHINE** | Admission guard. Test: `test_path_traversal_refused` |
| P13 | Opening an empty PR | **MACHINE** | `engine.execute` raises. Test: `test_empty_pr_refused` |
| P14 | Reading back from the local working tree instead of the remote | **MACHINE (by construction)** | `LocalGitTransport.get_file` runs `git show` in the **remote** dir. Test: `test_readback_reads_remote_not_worktree` |
| P15 | Rewriting history (rebase, amend, reset) | **BEHAVIOURAL_ONLY** | The transport exposes no such method, but the process can shell out to `git` directly. Nothing here detects that |
| P16 | Deleting a branch or a repo | **BEHAVIOURAL_ONLY** | Not exposed by the transport; not prevented at the OS level |
| P17 | Writing content that is malicious but well-formed | **BEHAVIOURAL_ONLY** | Checks verify that bytes arrived intact, never what the bytes mean |
| P18 | Trusting `GitHubTransport` | **BEHAVIOURAL_ONLY / UNPROVEN** | See below |
| P19 | Monkeypatching the spine in-process | **BEHAVIOURAL_ONLY** | Needs a process boundary |

## Journal durability

`journal.json` is flushed after **every** transition and on every guard
refusal, not only at `COMPLETE`. A run that aborts mid-lifecycle therefore
still leaves a readable record of how far it got and why it stopped — which is
what `continuity-recovery` reads. This is a spine property
(`obzio_spine/machine.py`), shared by all five packs.


## Commit-first acceptance (supersedes identity-only acceptance)

The earlier design proved the acceptor was a **different identity** and that
its token bound this exact artefact set. It did not prove the acceptor formed
an **independent judgement**. An acceptor handed the workdir, reading the
artefacts and then deciding, is *anchored* to the thing it is judging.
Unforgeable and unanchored are different properties; the old gate had the
first and implied the second.

The acceptor now derives its own expected result from the run's **declared
inputs only**, and hash-commits it **before any artefact exists**. At the gate
it reveals that commitment; the machine compares the producer's artefacts
against it and **divergence defaults to REJECT**, enforced by the machine
rather than by the acceptor's discretion.

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| C1 | Committing an expectation after any artefact exists | **MACHINE** | `OperatorMachine.register_expectation` raises `AnchoringError`. Test: `test_anchored_acceptor_is_refused` |
| C2 | Running at all without a committed expectation | **MACHINE** | `advance()` refuses to leave PREFLIGHT. Test: `test_commit_first_is_mandatory` |
| C3 | Committing twice, or revising after seeing the work | **MACHINE** | `register_expectation` refuses a second commitment |
| C4 | Retrofitting an expectation to match the artefacts | **MACHINE** | SHA-256 commitment over salt+expectation+inputs; `verify_expectation` |
| C5 | Accepting despite divergence from the commitment | **MACHINE** | Machine overrides the ACCEPT bit and forces REJECT. Test: `test_divergence_forces_reject_over_acceptor_bit` |
| C6 | Returning a rationale, diff, or rubric to the producer | **MACHINE (by type)** | `AcceptanceReturn` carries one bit plus reveals; `Reveal.note` was deleted. Divergence detail goes to the acceptor's sink |
| C7 | Deriving the expectation from the producer's own engine | **MACHINE (structural)** | `assert_no_import` parses the oracle's AST. Test: `test_oracle_does_not_import_engine` |
| C8 | Two implementations silently disagreeing | **MACHINE** | Disagreement is divergence, and divergence is REJECT |

### This pack's oracle: `INDEPENDENT_ORACLE` (strongest of the five)

The expected result here is not a judgement at all. If you intend to write
bytes B to path P, the remote must afterwards return bytes hashing to
`sha256(B)`. `oracle.py` computes that with `hashlib` before any branch
exists, importing neither `engine.py` nor `transport.py`.

This is the only pack where the acceptor checks an **externally fixed
arithmetic fact** rather than re-running logic and agreeing with itself.

**Covers:** per-path read-back digests, branch/base separation, PR head and
base, PR unmerged and open, file count.
**Does not cover:** whether the file content is correct, useful or safe;
whether the change should be made at all; server-side branch protection; or
whether a human should approve the PR.

### What commit-first does NOT buy

It defeats **anchoring**. It does not defeat a **shared blind spot**. Both the
oracle and the engine in this pack were written by the same author against the
same specification. They are two implementations, not two adversaries. A
misconception present in the spec is present in both, and they will agree
enthusiastically on the same wrong answer.

`Derivation` states the strength of the claim on every run and it is recorded
in `return_state.acceptance_independence`:

| Value | Meaning |
|---|---|
| `INDEPENDENT_ORACLE` | separately-written code, does not import the engine |
| `PARTIAL_ORACLE` | covers only a subset of the output; the rest is uncommitted |
| `SHARED_ENGINE` | same code — proves reproducibility only, **not** independence |
| `NONE` | no derivable expectation; acceptance is `BEHAVIOURAL_ONLY` |

Genuine independence would require an oracle written by a different party who
had not seen this implementation. Nothing in this repository delivers that,
and no wording here should be read as claiming it.

## Known weaknesses in this pack's controls

1. **`GitHubTransport` is unproven code.** It is the only path that talks to a
   real remote API, and it has never been executed against a live repository
   from this sandbox — there is no token here. The request shapes match the
   documented REST v3 endpoints, but "matches the docs" is not evidence.
   Specifically unverified: the `sha` round-trip on updating an existing file,
   HTTP error mapping, pagination (not implemented — a repo with many refs may
   behave differently), and rate-limit handling (absent entirely). Everything
   the tests prove is proven about `LocalGitTransport` only.
2. **The local transport is not a faithful GitHub model.** Local git has no
   pull requests, so `open_pr` records metadata in memory. It therefore cannot
   catch PR-specific failure modes: merge conflicts, required status checks,
   branch protection rules enforced server-side, review requirements, or a
   base branch that moved between the branch cut and the PR open. `CHK-RE-05`
   checks a field this pack itself wrote — for `LocalGitTransport` that is
   close to self-attestation.
3. **`CHK-RE-06` is a regex, and regexes miss.** It catches common token
   shapes (`ghp_`, `github_pat_`, AWS keys, PEM headers). A token in an
   unlisted format, base64-wrapped, or split across fields passes cleanly.
   It reduces the chance of a leak; it does not prevent one.
4. **Force-push is unreachable, not forbidden.** P11 holds because the
   transport has no force parameter. It is a design property, not a runtime
   check — a future method that accepts `force=True` would silently remove
   the control, and `CHK-RE-07` would only catch it if the flag were recorded
   in the audit trail.
5. **No concurrency safety.** Two operators running this pack against the same
   branch name will collide, and the failure will surface as a git error, not
   as a clear diagnostic.
