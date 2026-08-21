# Operator Packs v1 — Source

Published 2026-08-20. Ten operator packs plus their shared machinery, exactly as
they existed on disk at publication time.

## What the ten packs are

Each pack is a self-contained operator: a documented boundary of responsibility,
a state machine that drives it, a set of executable checks, and a test suite that
exercises the whole thing.

| # | Pack | Concern |
|---|------|---------|
| 01 | `strategic-orchestration` | Decomposing strategy into scheduled, owned work |
| 02 | `founder-intent-processing` | Turning founder intent into committed, checkable objectives |
| 03 | `repository-engineering` | Changing repositories safely, including byte transport |
| 04 | `independent-acceptance` | Accepting or rejecting work independently of its producer |
| 05 | `continuity-recovery` | Surviving interruption and resuming without loss |
| 06 | `06-browser-execution` | Driving a browser as an execution surface |
| 07 | `07-capability-manufacture` | Manufacturing new capabilities on demand |
| 08 | `08-knowledge-currentness` | Keeping knowledge current and dated |
| 09 | `09-infrastructure-operation` | Operating infrastructure with exactly-once intent |
| 10 | `10-economics-measurement` | Measuring economic effect of operation |

## Two generations, two shapes

The packs were built in two waves and their file layouts differ. This is a real
structural difference, not an artefact of publication:

- **Packs 01-05** (`strategic-orchestration` … `continuity-recovery`) carry
  `engine.py` and `oracle.py`, and import shared machinery from the
  `obzio_spine/` package published alongside them. Two carry an extra module:
  `repository-engineering/transport.py` and `independent-acceptance/fence.py`.
- **Packs 06-10** carry `acceptance.py` instead of `engine.py` + `oracle.py`, and
  each vendored its own identical copy of `_spine.py` rather than importing a
  shared package.

All ten carry `LAUNCH.md`, `BOUNDARIES.md`, `state_machine.py`, `checks.py`,
`test_pack.py` and `MANIFEST.json`.

## The vendored spine

Packs 06-10 each shipped a byte-identical copy of `_spine.py`. Six identical
copies existed on disk (one per pack, plus one at the pack-set root). Rather than
publish six copies, this branch publishes it **once**:

    modules/operators/_spine.py
    sha256 431773539ced6556fdd9a631fc80d42404aa2f30846a1d127826dd099a01f182
    43,928 bytes

Every pack 06-10 directory in this branch therefore lacks the `_spine.py` it had
on disk. The content is not lost — it is the file above, and all six on-disk
copies hashed to that exact value.

## Tests at publication

All tests passed at the time of publication.

**Packs 01-05 — 161 tests**, verified by running `run_all_tests.sh`:

    strategic-orchestration     30 passed, 0 failed   (0.195s)
    founder-intent-processing   30 passed, 0 failed   (0.184s)
    repository-engineering      33 passed, 0 failed   (9.469s)
    independent-acceptance      35 passed, 0 failed   (0.773s)
    continuity-recovery         33 passed, 0 failed   (1.143s)
    ALL PACKS PASSED

**Packs 06-10 — 79 tests**: 15 + 15 + 17 + 16 + 16.

Total: **240 tests, all passing.**

## Commit-first acceptance

Every pack is built around one design decision: the producer must **commit** to a
checkable claim *before* it sees the acceptance verdict, and the acceptor decides
against that prior commitment rather than against a post-hoc narrative.

Concretely: `state_machine.py` will not advance past its commit state without a
recorded expectation; `checks.py` evaluates that recorded expectation; and the
acceptor (`oracle.py` in packs 01-05, `acceptance.py` in packs 06-10) reads only
the committed artefact. A producer cannot revise its claim after seeing whether
the claim would pass.

The reasoning behind this design, including which of its guarantees are *not*
enforceable in the current implementation, is recorded in `PROVENANCE.md`. Read
that before relying on any acceptance result from these packs.

## Per-pack file counts and sizes

| Directory | Files | Bytes |
|-----------|------:|------:|
| `(root)` | 5 | 51,160 |
| `obzio_spine/` | 9 | 47,391 |
| `strategic-orchestration/` | 8 | 61,409 |
| `founder-intent-processing/` | 8 | 62,525 |
| `repository-engineering/` | 9 | 68,036 |
| `independent-acceptance/` | 9 | 83,238 |
| `continuity-recovery/` | 8 | 77,151 |
| `06-browser-execution/` | 7 | 61,611 |
| `07-capability-manufacture/` | 7 | 69,711 |
| `08-knowledge-currentness/` | 7 | 68,909 |
| `09-infrastructure-operation/` | 7 | 76,226 |
| `10-economics-measurement/` | 7 | 74,774 |
| **Total** | **91** | **802,141** |

`(root)` is `MANIFEST.json`, `build_manifests.py`, `run_all_tests.sh`,
`make_manifest.py` and the de-duplicated `_spine.py`.

## What is not published here

`__pycache__/` directories were excluded. On disk they held 52 `.pyc` files —
compiled build output, regenerable from the sources in this branch, and not
source. Counting them, the on-disk tree was ~148 files; the source tree is 96
files, which becomes 91 after de-duplicating the five redundant `_spine.py`
copies.
