# Obzio Operator Packs — v1 (2026-08-20)

Ten self-contained operator packs. Each pack encodes one recurring coordination
failure, the machine-enforced controls that close it, and a test suite that
proves each control by demonstrating the refusal.

**240 tests across the ten packs. All passing at time of publication.**

---

## ⚠ EVIDENCE STATUS — CITED BUT UNVERIFIED

**ALL evidence citations inside these packs — arXiv 2607.05904 and arXiv
2607.24300 — are recorded as CITED BUT UNVERIFIED.**

The building operators could not reach those sources. Both identifiers are past
the building operators' knowledge cutoff and **no independent verification of
either paper, its claims, or its reported effect sizes was performed.**

Everything in these packs was **implemented on the engineering mechanism, not on
confirmed effect sizes.** The mechanisms stand on their own and are proven by
the test suites in this repository — for example, a verifier that commits to its
decision before reading the artefact cannot be anchored by what it reads. That
property is demonstrated by executable tests, not by the citations.

**Do not upgrade this status.** Treat every cited effect size as unverified
until someone reaches the primary sources and records the result. The citations
appear in the `BOUNDARIES.md` of packs 06–10; each carries the same provenance
note inline.

---

## The ten packs

Packs 01–05 share the `obzio_spine/` package. Packs 06–10 each vendored a
single-file spine, `_spine.py` — see [Shared spine](#shared-spine) below.

| # | Pack | Failure it is built against | Tests | Spine |
|---|---|---|---|---|
| 01 | `strategic-orchestration/` | Orchestration decisions that cannot be replayed or audited; controls that feel obvious but are unenforced | 30 | `obzio_spine/` (shared) |
| 02 | `founder-intent-processing/` | A correction from the principal silently losing scope, polarity, or its ambiguity in transit to the surfaces it should change | 30 | `obzio_spine/` (shared) |
| 03 | `repository-engineering/` | Claimed repository writes verified against the working tree instead of the remote | 33 | `obzio_spine/` (shared) |
| 04 | `independent-acceptance/` | A producer accepting its own work; acceptance by recomputation, never by trust | 35 | `obzio_spine/` (shared) |
| 05 | `continuity-recovery/` | State reconstructed from memory rather than from the corpus; gaps and contradictions quietly resolved instead of reported | 33 | `obzio_spine/` (shared) |
| 06 | `06-browser-execution/` | A message composed for conversation X delivered into conversation Y, because the surface moved between reading the header and clicking send | 15 | `_shared/_spine.py` (vendored) |
| 07 | `07-capability-manufacture/` | A return that looks complete from every angle except execution — "production-ready" that was never run | 15 | `_shared/_spine.py` (vendored) |
| 08 | `08-knowledge-currentness/` | Publishing against stale pinned knowledge without reporting drift | 17 | `_shared/_spine.py` (vendored) |
| 09 | `09-infrastructure-operation/` | Non-idempotent infrastructure operations retried into inconsistent state | 16 | `_shared/_spine.py` (vendored) |
| 10 | `10-economics-measurement/` | A weak model in a strong harness mistaken for a strong model; cost bases landing in an "other" bucket | 16 | `_shared/_spine.py` (vendored) |

Every pack contains:

- `BOUNDARIES.md` — permitted acts, prohibited acts, and a control table where
  each control is labelled **MACHINE_ENFORCED** (code raises; a named test
  proves the refusal) or **BEHAVIOURAL_ONLY** (prose; nothing detects a
  violation). A control is only MACHINE_ENFORCED if a test demonstrates it.
- `LAUNCH.md` — entry point and operating instructions.
- `MANIFEST.json` — per-file byte counts and sha256, re-hashed at run time so a
  pack detects modification of its own code.
- `test_pack.py` — the suite.
- The pack's engine, checks, state machine, and oracle modules.

---

## Shared spine

`_spine.py` was **byte-identical in six copies** across the source tree. It is
published **once**, at `packs/_shared/_spine.py`.

- **sha256:** `431773539ced6556fdd9a631fc80d42404aa2f30846a1d127826dd099a01f182`
- **bytes:** 43,928

The six source locations that vendored this identical file:

| Vendored by | Source path |
|---|---|
| (root of the 06–10 set) | `packs2/_spine.py` |
| pack 06 · browser-execution | `packs2/06-browser-execution/_spine.py` |
| pack 07 · capability-manufacture | `packs2/07-capability-manufacture/_spine.py` |
| pack 08 · knowledge-currentness | `packs2/08-knowledge-currentness/_spine.py` |
| pack 09 · infrastructure-operation | `packs2/09-infrastructure-operation/_spine.py` |
| pack 10 · economics-measurement | `packs2/10-economics-measurement/_spine.py` |

**To run packs 06–10 from this repository you must restore the vendored copy**,
because each pack imports `_spine` as a sibling module:

```bash
for p in 06-browser-execution 07-capability-manufacture 08-knowledge-currentness \
         09-infrastructure-operation 10-economics-measurement; do
  cp packs/_shared/_spine.py "packs/$p/_spine.py"
done
```

Packs 01–05 use a different, already-shared spine: the `obzio_spine/` **package**
(9 modules), published intact at `packs/obzio_spine/`. It was never duplicated
and is not affected by the de-duplication above.

Note that each pack's own `MANIFEST.json` still lists `_spine.py` at its
vendored path. That is intentional — pack manifests are unmodified pack content.
After the `cp` above, every pack manifest verifies.

---

## Running the tests

### Packs 01–05

```bash
cd packs
bash run_all_tests.sh
```

`run_all_tests.sh` references absolute paths under `/tmp/packs`. To run from a
clone, either place the tree at `/tmp/packs` or run each pack directly:

```bash
for p in strategic-orchestration founder-intent-processing repository-engineering \
         independent-acceptance continuity-recovery; do
  ( cd "packs/$p" && python3 test_pack.py )
done
```

Packs 01–05 import `obzio_spine`, so `packs/` must be on `PYTHONPATH`
(running from inside `packs/` satisfies this).

### Packs 06–10

Restore the vendored spine first (see above), then:

```bash
for p in 06-browser-execution 07-capability-manufacture 08-knowledge-currentness \
         09-infrastructure-operation 10-economics-measurement; do
  ( cd "packs/$p" && python3 test_pack.py )
done
```

### Expected totals

| Pack | Tests |
|---|---|
| strategic-orchestration | 30 |
| founder-intent-processing | 30 |
| repository-engineering | 33 |
| independent-acceptance | 35 |
| continuity-recovery | 33 |
| 06-browser-execution | 15 |
| 07-capability-manufacture | 15 |
| 08-knowledge-currentness | 17 |
| 09-infrastructure-operation | 16 |
| 10-economics-measurement | 16 |
| **Total** | **240** |

No third-party dependencies. Python 3.11.

---

## Layout

```
packs/
├── README.md               ← this file
├── MANIFEST_ALL.json       ← every published path, bytes, sha256
├── MANIFEST.json           ← original manifest for the 01–05 set
├── build_manifests.py
├── make_manifest.py
├── run_all_tests.sh
├── _shared/
│   └── _spine.py           ← the de-duplicated single-file spine (packs 06–10)
├── obzio_spine/            ← shared spine package (packs 01–05), 9 modules
├── strategic-orchestration/
├── founder-intent-processing/
├── repository-engineering/
├── independent-acceptance/
├── continuity-recovery/
├── 06-browser-execution/
├── 07-capability-manufacture/
├── 08-knowledge-currentness/
├── 09-infrastructure-operation/
└── 10-economics-measurement/
```

The two source roots (`/tmp/packs` for 01–05, `/tmp/packs2` for 06–10) are
flattened into a single `packs/` tree. Pack directory names are unique across
both roots, so no path collides.

---

## What is not published here

- **`__pycache__/` — 52 `.pyc` files.** CPython 3.11 byte-compiled build
  artefacts. They are regenerated on first import, are not pack content, and are
  binary. Excluded deliberately.
- Earlier commits on this branch contain `packs/.parts/` chunk files and
  `packs/operator-packs-01-05.zip` from an abandoned transport attempt. They are
  superseded by this publication and removed from the branch tip; they remain in
  git history.

## Verification

`MANIFEST_ALL.json` records the byte count and sha256 of every path published
here, computed from disk before upload. Every path was read back from GitHub
after upload and its size and sha256 compared against that manifest.

Reference archives of the same source tree (not published in this repository):

| Archive | Bytes | sha256 |
|---|---|---|
| `packs-xz.tar.xz` | 325,844 | `559c049f9372fabd6a3a47500fbaefde22a0a576bde8432acb43f5ddeb2bdfd1` |
| `obzio-operator-packs-v1.tar.gz` | 696,932 | `92fb45310dcc87e845c77fa2e9d42d7cab098b8f7697ec1b4f1a2226d9b23b5f` |
