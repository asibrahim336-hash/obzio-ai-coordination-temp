# PO-01 evidence disposition — stop now

Read-only observation at `2026-08-22T09:25:42Z`. Branch
`packs/operator-fleet-v1-20260820` was stable at
`96adfe7d79257389318af10ee9c9e3a0c2138590`: 20 commits ahead of main,
19 added paths and 8,602 added lines. It had no PR, workflow, stop receipt or
independent acceptance and had made no progress for more than 64 minutes.

Disposition: founder should stop the producer now and permit no new file. Preserve
the immutable head. This record does not contact or mutate PO-01.

- Pack 06 `browser-execution`: exact seven manifest digests matched; executable
  suite 15/15 PASS. Retain as
  `CANDIDATE / LOCAL_SIMULATION_PASS / LIVE_INTEGRATION_UNPROVEN / NOT_ACCEPTED`.
  Valuable mechanisms include send-time route verification, recipient allowlist,
  replay/forgery rejection, tamper-evident ledger and commit-first acceptance. A
  real `LiveSurface`, DOM honesty, target/content correctness and acceptor-key/UID
  separation remain unproven.
- Pack 07: retain only partial design material. Its manifest names
  `state_machine.py` and `test_pack.py`, but both are absent; integrity and
  executability fail. Vendor-code isolation controls are incomplete.
- Packs 08–10: reject as non-deliverables; each contains only a duplicate spine.
- Aggregate runner: reject. It hardcodes five `/tmp/packs/...` paths, omits packs
  06–10, exited 1 with five missing-directory errors and `AT LEAST ONE PACK FAILED`.
- 6,624 of 8,602 lines (77%) are six byte-identical `_spine.py` copies. Ingest one
  canonical spine only.

The missing packs should be recommissioned under the one-factory disjoint-ownership
contract with a repository-relative validator.

