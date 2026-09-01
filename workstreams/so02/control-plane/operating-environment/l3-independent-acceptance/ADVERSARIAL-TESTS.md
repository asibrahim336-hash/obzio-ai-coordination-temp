# CUR-ORCH-QUAL-01 independent adversarial reproductions

Evidence reviewed at immutable commit
`11a60dcf6dbc2eac4e6d975efab5d985ebbabd62`. The criteria were fixed first
at `9a390df3ebdd19e1403317be24c74e6abc249415`. No producer transcript or run
events were read.

The machine-readable reproduction is
`INDEPENDENT-VERIFICATION-REPORT.json`; `independent_verify.py` regenerates
it without importing producer code for substantive checks. Producer code is
invoked only by the report's two explicitly labelled adversarial probes.

## Producer gates

This VM did not expose a `python` command, so a temporary `/tmp` shim mapped
that command to the installed Python 3.12.3 interpreter. With that
compatibility binding, the exact commissioned commands produced:

- `python -I .../scctl.py validate`: exit 0, `PASS`.
- `python -I .../orchqual.py verify`: exit 0, `PASS`.
- `python -I -m unittest discover ...`: exit 0, 92 tests, `OK`.

The gates are reproducibly green, but the adversarial probes below show that
their success conditions are insufficient.

## Adversarial tests and outcomes

### A1 — Listed-entry manifest recomputation

Independent SHA-256 and size recomputation matched all 13 listed entries.
The independently recomputed producer `bundle_sha256` is
`b2ce7d6f8b670798f520bbe4d84925d0902bfe5366e9620f8e4ba11054ce1f2c`.

Outcome: **PASS for listed-entry integrity; FAIL for closure.**

### A2 — Material-file omission

Set equality over the receipts bundle found
`REMOTE-READBACK.json` present but unmanifested. Producer code explicitly
excludes that file. The changed workflow, `control-plane.json`,
`events.jsonl`, and `runtime-surface-locators.json` are also relied on by
terminal, CI, custody or projection claims but are not manifested.

Outcome: **FAIL.** The manifest can be satisfied while omitting the material
read-back proof and material state used by the claim.

### A3 — Independent remote read-back of the stipulated evidence head

The acceptor created a fresh no-checkout clone, fetched
`11a60dcf6dbc2eac4e6d975efab5d985ebbabd62`, and read every listed blob from
that clone. All 13 hashes and sizes matched; 126,492 bytes were compared.

Outcome: **PASS.** The listed final-head bytes have remote custody. This does
not cure manifest incompleteness or prove that the omitted read-back record
is true.

### A4 — Phase/read-back gate forgery

In a temporary copy, the real `REMOTE-READBACK.json` was replaced by a
synthetic record naming all-zero commit identity, invented transport names,
one non-manifest path and matching self-asserted digests. No remote operation
was performed. The producer's unmodified `orchqual.py verify` returned exit
0 and `PASS`.

The bypass works because the read-back file is excluded from the manifest,
and `verify_readback` does not bind its bundle hash to the manifest, its
comparison paths/count to manifest entries, its commit to a remotely
existing object, or its booleans to a performed read-back.

Outcome: **FAIL.** The phase field prevents only one textual state
combination; it does not fail closed on forged read-back evidence.

### A5 — Operational reality of R2

R2 queried the producing run's own ID while that run was `RUNNING` and
returned zero events. The two provider artifacts were left in a VM-local
directory; neither artifact's SHA-256 corresponds to a manifested file.
Only a producer-authored summary and the two unverified hashes were committed.
The route did not prove top-level run creation or follow-up submission.

Outcome: **FAIL.** Observation of the current producer and retrieval of its
metadata are real capabilities, but this is not the advertised independent
end-to-end orchestration/result route, and the raw result is not replayable
from immutable custody.

### A6 — Two-route independence

R1 and R2 use different declared transports and different external service
surfaces. They nevertheless share the same root controller, Cloud Agent VM,
producer state and acceptance assertions. R2 queried that same controller,
and its durable form depends on R1/GitHub because its provider directory is
explicitly non-durable. A compromised controller can manufacture both
records; a GitHub failure prevents R2 from completing the required custody
ladder.

Outcome: **FAIL.** This is transport diversity, not independent trust or
failure domains. The aggregate `PASS_TWO_OR_MORE_ROUTES` is materially
misclassified.

### A7 — Capacity recomputation and sensitivity

Independent logic selected the eight records explicitly labelled
`pre_existing_po03`, compared all four snapshots, and reproduced
`ZERO_PO03_CAPACITY_INTERFERENCE`: no disappearance, kill or degraded-state
transition is present in the supplied snapshots.

Two synthetic regressions were then injected:

- `IDLE -> QUEUED`: both the acceptor and producer detector returned
  `CAPACITY_INTERFERENCE_FAIL`.
- `IDLE -> ERROR`: the acceptor returned `CAPACITY_INTERFERENCE_FAIL`, while
  the producer detector returned `ZERO_PO03_CAPACITY_INTERFERENCE`.

Outcome: **raw observation PASS; detector FAIL.** A real error regression is
silently accepted because `ERROR` is absent from the producer's interference
states. The instrument also cannot observe within-run slowdown, as the
producer correctly discloses.

### A8 — Event-log integrity

The acceptor independently canonicalised each of 22 events after removing
`event_sha256`, recomputed every hash, checked contiguous sequence,
predecessor links, unique IDs and idempotency keys, and obtained head
`0cf5cc66b623d158a2b278102517c85df235f01d56973a8afcc52fc29deaa1a8`.

Alteration, deletion, reorder and a one-event rehash/splice were each
detected in synthetic copies.

Outcome: **PASS.**

### A9 — Protected branch write claim

All 23 producer-changed paths are inside the commission allowlist. None of
the three producer commits is reachable from the current heads of `main`,
the strategic-control base, the named PO-03 branch, the two named SOO
branches or any of the 62 observed `cursor/po03-*` heads. The strategic base
currently resolves exactly to
`fe0a595206e5986de7eaac6cabc619215a1eb81b`.

No retained repository push event or audit record for the qualification
window was available. Current refs and ancestry cannot exclude a transient
protected write later removed by force-push.

Outcome: **PASS for current refs, ancestry and path scope; NOT VERIFIED for
the producer's absolute historical no-write claim.**

### A10 — OWNER_REQUIRED and NOT_SUPPORTED classifications

- OpenAI and Cursor REST probes record reachable HTTP 401 responses and
  absent credentials. Issuing/attaching owner-held keys is genuinely an
  owner act; these classifications are supported, although no authenticated
  route was proved.
- Browser/computer control was absent from the recorded runtime tool census.
  `NOT_SUPPORTED_IN_THIS_RUNTIME` is supported and is correctly non-gating.
- The SW return route's receiver was tested, but the owner action to send an
  SW launch is no longer current: governing base `fe0a5952` says SW remains
  paused and uncontacted. That stale owner action must not be executed.
- Appointment of an independent acceptor was genuinely outside producer
  self-certification and has now occurred through this lane.

Outcome: **mixed; FAIL for currentness of the SW action, no evidence that the
credential and browser states merely hide an unattempted in-runtime
capability.**

### A11 — Credential-bearing locators

All JSON locator fields in the bundle, route register and surface locator
register were parsed for URL user-info, sensitive query keys and common
secret prefixes. No value was printed or retained.

Outcome: **PASS; no credential-bearing locator found.**

### A12 — `decision_changed` and strategy binding

Sixteen producer-changed JSON/JSONL machine records were recursively checked;
all `decision_changed` fields are empty. All event payload fields are empty,
and no producer event is a `STRATEGY_DECISION`. No changed artifact performs
spend, outreach, merge, production cutover or strategy binding.

Outcome: **PASS.**

### A13 — GitHub Actions circularity

The cited run really executed on a GitHub-hosted Ubuntu runner and all steps
passed. Its checkout log shows the PR merge ref
`574b2f29118d16cc62aee6d193239dcd2f50f0e0`, not a direct checkout of the
receipt's claimed immutable head `7b6c10bd...`.

More importantly, the producer added the `orchqual.py verify` workflow step
in the same evidence branch and authored the verifier, test suite, manifest
scope and success booleans. The runner independently executed bytes; no
independent actor fixed the assertions or acceptance rule. The forged
read-back probe passes the same check.

Outcome: **FAIL as independent corroboration of truth; PASS only as
reproducibility on a separate machine.** It cannot close the final
read-back/self-reference gap.

### A14 — Currentness and chronology

The evidence forked from `a5adfdff...`; the governing acceptance base
`fe0a5952...` is a later descendant and carries the founder
operating-environment correction. The evidence branch therefore contains
now-superseded owner routing, particularly the SW launch action.

Outcome: **limitation.** The historical bytes remain evidence, but their
owner-action queue is not a current launch surface.

## Internal acceptance sub-lanes

### SL-CUSTODY — cryptographic integrity and custody

Emphasis: immutable provenance, complete manifests, independent hashing,
remote read-back, event chaining, phase gates and protected refs.

Verdict: **REFUSED.** Listed bytes and event chaining pass, but manifest
closure fails and the producer verifier accepts a wholly forged read-back.
These are remediable engineering defects, but they falsify the current
complete-custody claim.

### SL-OPERATIONAL — capability reality and governance

Emphasis: end-to-end work launch/result retrieval, route independence,
capacity sensitivity, current authority and non-circular corroboration.

Verdict: **REFUSED.** R2 is self-observation without committed raw artifacts,
the two routes share the decisive controller and GitHub custody path, an
`ERROR` regression passes the detector, the SW owner action is stale, and CI
executes producer-authored assertions.

The sub-lanes agree on refusal. They differ on the strongest reason:
SL-CUSTODY treats the integrity defects as potentially curable, while
SL-OPERATIONAL finds the advertised two-independent-route classification
substantively false. The operational reasoning is stronger for the final
decision because fixing hashes alone would not create an independent second
route.
