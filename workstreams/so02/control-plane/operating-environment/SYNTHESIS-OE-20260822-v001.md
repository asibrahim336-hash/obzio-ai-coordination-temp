# CUR-ENV-01 synthesis — five lanes reconciled

**Commission:** `COM-CUR-ENV-01-20260822-v001`
**Immutable SO-02 source:** `fe0a595206e5986de7eaac6cabc619215a1eb81b` (read-only)
**Return branch:** `cursor/operating-environment-return-20260822-v001`
**Root controller and sole shared-state writer:** `bc-c6f63d58-9611-495a-96f6-2f2dcbef696d`
**decision_changed:** `[SO-02 founder browser/setup batch HALTED; strategic development and human-operator implementation guidance for this capability moves to Cursor]`

Every lane state below is `VERIFIED_ADMISSIBLE`, never `ACCEPTED`. Custody holding is not agreement.

---

## 1. Strengthened interpretation of the intent

The instruction is not "pick a browser tool". Read against the live account review and the CUR-01 result together, it is: **stop the estate's coordination defects from scaling, and build a founder operating environment whose state, logic and evidence survive any provider being removed.**

Three things follow that were not stated but are implied by the evidence.

**The bottleneck is admission, not capability.** Independent compilation of the repository found nothing in the estate qualifying above `OBSERVED`, with eight of sixteen workstreams claiming more than their evidence supports. Adding capability to a system that cannot tell proposed from accepted multiplies the confusion. Admission machinery is therefore not overhead alongside the operating environment — it is the first component of it.

**"Portable" has a sharper meaning than "open".** The clearest instance: a named open-weights model in the directives is roughly 2.78 trillion parameters. The weights are public and no laptop will ever run them. Open weights and runnable-by-us are different properties, and only the second delivers sovereignty. Substitutability must be measured as "can we actually run or replace this", not "is the licence permissive".

**Some gaps are permanent, not immature.** A cloud VM has no route to the founder's browser or microphone, and every mechanism for building one admits a third party into the trust boundary. That is not a maturity problem that time fixes. It is why the recommended shape is one canonical control plane with swappable execution planes, rather than a single topology that will supposedly grow into completeness.

---

## 2. What was initiated and how

Five isolated lanes under the multi-parent protocol, with the root controller as sole writer of shared projection state, each lane on a disjoint branch and namespace, each returning only `READY_TO_COMMIT`. The single-top-level-agent restriction was recorded as scoped to the completed CUR-01 experiment and not inherited.

| Lane | Head | Entries | Custody |
|---|---|---|---|
| L1 Cursor baseline | `dd978019` | 56 | recomputed, matches |
| L2 Capability research | `b6126c8d` | 241 | recomputed, matches |
| L3 Independent acceptance | `541eff44` | — | criteria precede verdict, verified |
| L4 Currentness | `a58646ed` | 13 | recomputed, matches |
| L5 ChatGPT scale | `e08e71be` | 19 | recomputed, matches |

356 files integrated, every one inside the SO-02 allowlist, zero cross-lane contamination, zero credential material.

**Control routes actually used:** GitHub immutable-SHA custody; the Cursor cloud MCP surface for run identity, environment and capacity observation; live HTTPS document and registry harvesting via `curl` and `gh api` for research evidence; GitHub Actions as a substitute runtime; and cross-model dispatch across two model families.

---

## 3. Independent acceptance — constituted, and it refused

The acceptance lane ran on a different model family from the run that produced the CUR-01 evidence, committed its criteria as a separate earlier commit than its verdict, wrote its own hasher rather than reuse the producer's verifier, and **refused**.

Two defects were then reproduced directly by the root controller against its own tooling: a wholly fabricated read-back naming a nonexistent commit passed the producer's verifier, and an `IDLE → ERROR` transition passed the capacity detector. Both are corrected in executable code with the acceptor's own forgeries as regression tests.

The `PASS_TWO_OR_MORE_ROUTES` and `MAJOR_ORCHESTRATION_LAYER_QUALIFIED` claims are withdrawn. R1 GitHub immutable-SHA custody survived challenge and remains usable. R2 did not: it observed the producing run itself and depends on R1 for custody, so two transports were not two failure domains.

**The independent currentness lane, which never read that verdict and used mechanical admission compilation instead, lands the same workstream at `PROPOSED`.** Two instruments, no shared context, same conclusion.

This is the structure to reuse: independence achieved through isolated context, criteria committed before results, distinct model identity, adversarial tests, and a prohibition on the producer touching the verdict — with no founder in the loop at any point.

---

## 4. Recommended topology and the decisive trade-off

**One Git-canonical control plane with three swappable execution planes:** a cloud plane holding no authenticated session and no microphone by design; a device-local browser plane operating logged-in surfaces under per-connection approval; and a device-local compute plane that is empty on the Chromebook and fills when the MacBook arrives — all behind one adapter boundary and one evaluation suite.

The two serious alternatives are the cloud-agent topology running today and a MacBook-local-first topology. Their deficits are different in kind: the cloud topology's gaps are permanent, while the local topology's gap is merely scheduled, with every component verified live and permissively licensed and only the hardware missing. Treating the first as today's plane and the second as a plane that fills on arrival dominates either as a destination.

**Correction to an earlier report.** I previously told you browser control was unsupported in this runtime, based on the CUR-01 census. That was wrong. Chrome runs headless here and a display server with VNC is live; what is absent is the agent-facing tool, not the capability. This widens the browser options rather than closing them.

---

## 5. Programme components now built

- **Admission and currentness:** an executable compiler that classifies 171 refs, 8 PRs and 16 workstreams from repository evidence rather than claims, refuses to resolve competing pointer claims, and detects overlapping whole-operation commissions. 71 tests weighted to old-behaviour probes.
- **ChatGPT scale:** 31 differentiated functions across 12 typed project slots, with overlap prevented by a machine-checked partition of 32 internal decision classes — including one reserved and unclaimable class that makes a "whole-operation commission" structurally impossible.
- **OpenAI activation:** 59 official documentation URLs fetched and hashed, a bounded canary that proves retrievability by identifier rather than text generation, and ten adversarial tests confirming every credential-leak path is refused.
- **Cursor configuration:** a staged proposal deliberately held outside `.cursor/` so adoption stays an explicit act, plus hook scripts with their own executable proof.
- **Integration controls:** a lane guard and evidence-integrity module, 30 tests, now wired into CI.

---

## 6. What is deliberately not decided

No named tool, model or architecture is bound. Nothing is merged or promoted. The staged Cursor configuration is not applied. The competing pointer claims between PR #6 and PR #7 are left unresolved because choosing is a founder-bound act, not a compilation result. Ten project slots remain `PENDING_CENSUS` because counts were available but project identities were not, and inventing a mapping would have been the confident and useless answer.

---

## 7. Honest limits

Capacity non-interference was measured only at the visible top-level run layer; it cannot see compute or rate-limit contention. The eleven-project figure comes from your review, not the repository — the repository can be proven never to have held the enumeration, but not the real number. The v008 payload is unrecoverable; only its absence is reproducible. Whether the W01–W24 lanes ran cannot be determined from git. One product name in the discovery seeds resolved to no real product across repository, registry, extension-store and DNS probes, and is recorded `UNRESOLVED` rather than guessed at — which is itself the argument for a read-back gate on intake, since an unconfirmed transcription entered a work order and survived several hands.
