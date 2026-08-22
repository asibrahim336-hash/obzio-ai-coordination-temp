# PO-03 cohort c6 recovery fault matrix

Commission: COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001
Function: transactional-recovery-and-fault-injection
Fault class rows: 45
False completions observed: 0

| Unit | Fault class | Injected at state transition | Verdict |
| --- | --- | --- | --- |
| 041-session-loss-injection | SESSION_LOST_AFTER_CREATED | CREATED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_LEASED | LEASED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_RUNNING | RUNNING -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_CHECKPOINTED | CHECKPOINTED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_RESULT_STAGING | RESULT_STAGING -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_RESULT_STAGED | RESULT_STAGED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_RESULT_VERIFIED | RESULT_VERIFIED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_RESULT_COMMITTED | RESULT_COMMITTED -> (session gone) | PASS |
| 041-session-loss-injection | SESSION_LOST_AFTER_PARENT_INGESTED | PARENT_INGESTED -> (session gone) | PASS |
| 042-lost-callback-replay | LOST_RETURN_MESSAGE_AFTER_DURABLE_RESULT_COMMIT | RESULT_COMMITTED | FAIL |
| 043-partial-and-commit-failure | PARTIAL_WRITE_KILLED_BEFORE_ATOMIC_LINK | RUNNING -> CHECKPOINTED | PASS |
| 043-partial-and-commit-failure | LINKED_BUT_UNFSYNCED_DIRECTORY_ENTRY | RUNNING -> CHECKPOINTED | PASS |
| 043-partial-and-commit-failure | CRASH_MID_REPLACEMENT_OF_DERIVED_STATE | controller recovery-state regeneration | PASS |
| 043-partial-and-commit-failure | CRASH_BETWEEN_HASH_CHAINED_EVENTS | CHECKPOINTED -> RESULT_STAGING | PASS |
| 043-partial-and-commit-failure | PRE_COMMIT_FAILURE_WITH_UNCOMMITTED_BYTES | RESULT_STAGING -> (no commit) | PASS |
| 043-partial-and-commit-failure | POST_COMMIT_FAILURE_BEFORE_CALLBACK | RESULT_COMMITTED -> (no callback) | PASS |
| 043-partial-and-commit-failure | IMMUTABLE_FILE_REWRITE_ATTEMPT | CREATED (immutable capsule) | PASS |
| 044-push-failure-injection | PRE_PUSH_FAILURE_COMMIT_LOCAL_ONLY | RESULT_COMMITTED -> (push never executed) | PASS |
| 044-push-failure-injection | POST_PUSH_REPORT_LOST_CONTROLLER_ALREADY_FETCHED | RESULT_COMMITTED -> pushed -> (report lost) | PASS |
| 044-push-failure-injection | POST_PUSH_REPORT_LOST_CONTROLLER_NOT_FETCHED | RESULT_COMMITTED -> pushed -> (report lost, no fetch) | FAIL |
| 044-push-failure-injection | PUSH_REJECTED_NON_FAST_FORWARD | RESULT_COMMITTED -> push refused | PASS |
| 045-stale-lease-fencing | SUPERSEDED_WORKER_COMMITS_AFTER_OWNERSHIP_TRANSFER | LEASED (transferred) -> RESULT_COMMITTED | PASS |
| 045-stale-lease-fencing | EXPIRED_LEASE_WITHOUT_OWNERSHIP_TRANSFER | LEASED (expired) -> RESULT_COMMITTED | FAIL |
| 045-stale-lease-fencing | NEVER_ALLOCATED_HIGHER_FENCE_TOKEN | LEASED -> RESULT_COMMITTED | FAIL |
| 045-stale-lease-fencing | INTERLEAVED_FENCE_ALLOCATION | CREATED -> LEASED (fence allocation) | FAIL |
| 045-stale-lease-fencing | CONCURRENT_FENCE_ALLOCATION_ACROSS_REAL_PROCESSES | CREATED -> LEASED (fence allocation) | OBSERVATION_ONLY |
| 046-duplicate-callback-idempotence | IDENTICAL_CALLBACK_REPLAYED_FIVE_TIMES | RESULT_COMMITTED -> PARENT_INGESTED (replayed) | PASS |
| 046-duplicate-callback-idempotence | RETRIED_CALLBACK_WITH_REGENERATED_TIMESTAMPS | RESULT_COMMITTED -> PARENT_INGESTED (re-emitted) | FAIL |
| 046-duplicate-callback-idempotence | CONCURRENT_DUPLICATE_CALLBACK_SAME_CLOCK | RESULT_COMMITTED -> PARENT_INGESTED (interleaved) | FAIL |
| 046-duplicate-callback-idempotence | CONCURRENT_DUPLICATE_CALLBACK_SKEWED_CLOCK | RESULT_COMMITTED -> PARENT_INGESTED (interleaved) | FAIL |
| 046-duplicate-callback-idempotence | REPAIR_CANDIDATE_UNDER_IDENTICAL_AND_REGENERATED_DUPLICATES | RESULT_COMMITTED -> PARENT_INGESTED (candidate) | PASS |
| 047-corrupt-artifact-recovery | CLAIMED_HASH_DOES_NOT_MATCH_COMMITTED_BYTES | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | CLAIMED_BYTE_COUNT_DOES_NOT_MATCH_COMMITTED_BYTES | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | COMMITTED_BYTES_TRUNCATED_AFTER_HASHING | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | ARTIFACT_PATH_ABSENT_FROM_THE_COMMIT | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | RESULT_COMMIT_DOES_NOT_EXIST | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | LOCATOR_POINTS_AT_A_TREE_NOT_A_BLOB | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | LOCATOR_IS_NOT_A_DURABLE_GIT_OBJECT | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | WORKTREE_TAMPERED_AFTER_THE_COMMIT | RESULT_COMMITTED -> PARENT_INGESTED (ingestion check) | PASS |
| 047-corrupt-artifact-recovery | EMPTY_OR_MISSING_ARTIFACT_SET | RESULT_COMMITTED -> PARENT_INGESTED (contract check) | PASS |
| 048-provider-runtime-loss-and-code2-fixture | TOTAL_PROVIDER_RUNTIME_LOSS_AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT | RUNNING -> PROVIDER_COMPLETED_UNCOMMITTED -> (runtime gone) | PASS |
| 048-provider-runtime-loss-and-code2-fixture | TOTAL_PROVIDER_RUNTIME_LOSS_AFTER_STAGING_BEFORE_PROVIDER_REPORT | RUNNING -> (runtime gone before any report) | PASS |
| 048-provider-runtime-loss-and-code2-fixture | PROVIDER_COMPLETION_WITH_NO_DURABLE_RESULT_CLAIMS_COMPLETED | PROVIDER_COMPLETED_UNCOMMITTED -> COMPLETED (attempted) | PASS |
| 048-provider-runtime-loss-and-code2-fixture | FROZEN_CODE2_FAULT_FIXTURE | n/a (frozen historical fault) | PASS |
| 048-provider-runtime-loss-and-code2-fixture | RECOVERY_WITHOUT_FOUNDER_RELAY | n/a (static and behavioural check) | PASS |

## Defects with staged repair candidates

- `DEF-PO03-C6-042-LOST-CALLBACK-NOT-REPLAYED` (FAIL, COHORT_BAR_BREACH) — repair candidate `workstreams/po03/attempts/po03-wa-b2e7-042-lost-callback-replay/repair_candidate_replay_scan.py`, adopted: False
- `DEF-PO03-C6-044-PUSH-BOUNDARY-NOT-DISTINGUISHED-OR-RECOVERED` (FAIL, COHORT_BAR_BREACH) — repair candidate `workstreams/po03/attempts/po03-wa-b2e7-044-push-failure-injection/repair_candidate_remote_recovery.py`, adopted: False
- `DEF-PO03-C6-045-FENCING-INCOMPLETE` (FAIL, AUTHORISED_CUSTODY_GAP_NOT_A_FALSE_COMPLETION) — repair candidate `workstreams/po03/attempts/po03-wa-b2e7-045-stale-lease-fencing/repair_candidate_fencing.py`, adopted: False
- `DEF-PO03-C6-046-SUPPRESSION-KEYED-ON-BYTES-NOT-TRANSACTION` (FAIL, COHORT_BAR_BREACH) — repair candidate `workstreams/po03/attempts/po03-wa-b2e7-046-duplicate-callback-idempotence/repair_candidate_idempotence.py`, adopted: False

## Observed behaviour per fault class

- **SESSION_LOST_AFTER_CREATED** (PASS): only the CREATED event existed; the scanner classified the unit DISPATCH; no completion, no ingestion, chain clean, capsule intact; a fresh worker resumed from the capsule to PARENT_INGESTED with a matching read-back
- **SESSION_LOST_AFTER_LEASED** (PASS): CREATED and LEASED events survived; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; the resumption took a new lease with an advanced fence and reached PARENT_INGESTED with zero errors
- **SESSION_LOST_AFTER_RUNNING** (PASS): the chain ended at RUNNING and verified cleanly; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; resumption reached PARENT_INGESTED
- **SESSION_LOST_AFTER_CHECKPOINTED** (PASS): the checkpoint event survived the loss with its hash intact; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; resumption reached PARENT_INGESTED
- **SESSION_LOST_AFTER_RESULT_STAGING** (PASS): bytes existed only in the worktree with no commit; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; resumption committed fresh bytes and reached PARENT_INGESTED
- **SESSION_LOST_AFTER_RESULT_STAGED** (PASS): the staged byte count was recorded in the chain but nothing was durable in Git; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; resumption reached PARENT_INGESTED
- **SESSION_LOST_AFTER_RESULT_VERIFIED** (PASS): the verified hash and byte count survived in the chain while the bytes themselves were still uncommitted; classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; resumption reached PARENT_INGESTED
- **SESSION_LOST_AFTER_RESULT_COMMITTED** (PASS): the commit was durable and the chain recorded it, yet the scanner still classified RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT with no ingestion record; the resumption produced a second commit and reached PARENT_INGESTED, so no false completion appeared but the first committed result was superseded rather than replayed
- **SESSION_LOST_AFTER_PARENT_INGESTED** (PASS): the ingested result survived the loss of the session that produced it; the scanner classified the unit AWAIT_COORDINATOR_COMPLETION and no COMPLETED state was ever set by a producer
- **LOST_RETURN_MESSAGE_AFTER_DURABLE_RESULT_COMMIT** (FAIL): scan_recovery classified the unit RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT; scan_recovery reported ingested=false and produced zero ingestion records; the committed result commit is referenced nowhere in the recovery state document; the committed result document remained byte-exact and readable by immutable object id (1804 bytes); false_completion_count remained 0 and no transaction-completed.json was written; the hash-chained event file chain verified with zero errors
- **PARTIAL_WRITE_KILLED_BEFORE_ATOMIC_LINK** (PASS): the 2 MiB payload was fsynced into a hidden temporary file and the process died before os.link; no CHECKPOINTED event file ever became visible, the chain still verified, the scanner prescribed RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT
- **LINKED_BUT_UNFSYNCED_DIRECTORY_ENTRY** (PASS): the process died after os.link but before the directory fsync; the event file was present, its recomputed event_sha256 matched its claim, and verify_chain returned no errors
- **CRASH_MID_REPLACEMENT_OF_DERIVED_STATE** (PASS): the process died before os.replace; generation 1 of recovery-state.json survived byte-intact and parsed as valid JSON, so no torn derived state was observable
- **CRASH_BETWEEN_HASH_CHAINED_EVENTS** (PASS): four contiguous events survived, sequence numbering stayed dense, and verify_chain reported no previous-hash or sequence errors
- **PRE_COMMIT_FAILURE_WITH_UNCOMMITTED_BYTES** (PASS): bytes existed only in the worktree; git ls-tree at HEAD listed nothing under the slot; ingesting a result that pointed at HEAD produced RECOVERY_REQUIRED with a read-back failure error and no false completion
- **POST_COMMIT_FAILURE_BEFORE_CALLBACK** (PASS): 1796 bytes of committed result stayed readable by immutable object id and the immutable capsule survived, so the state is recoverable and no false completion appeared; the live scanner nevertheless reported ingested=false and prescribed a rerun rather than replaying the commit
- **IMMUTABLE_FILE_REWRITE_ATTEMPT** (PASS): write_once raised FileExistsError for differing bytes, treated an identical payload as a no-op, and left the capsule bytes unchanged
- **PRE_PUSH_FAILURE_COMMIT_LOCAL_ONLY** (PASS): the commit was absent from the remote; ingestion returned RECOVERY_REQUIRED with a read-back failure; the 53 committed bytes remained byte-identical in the producer clone; false_completion_count 0
- **POST_PUSH_REPORT_LOST_CONTROLLER_ALREADY_FETCHED** (PASS): push succeeded, the controller had fetched, and ingestion of the recovered document returned PARENT_INGESTED with zero errors, a matching artifact read-back and AWAIT_COORDINATOR_COMPLETION from the scanner
- **POST_PUSH_REPORT_LOST_CONTROLLER_NOT_FETCHED** (FAIL): the commit was verified present on the remote, yet ingestion returned RECOVERY_REQUIRED; the mechanism made no fetch attempt and the scanner prescribed a rerun
- **PUSH_REJECTED_NON_FAST_FORWARD** (PASS): git rejected the push (exit 1, stderr contained a rejection), the remote tip still pointed at the competing worker's commit, the producer's own bytes stayed byte-identical locally, ingestion returned RECOVERY_REQUIRED and no false completion appeared
- **SUPERSEDED_WORKER_COMMITS_AFTER_OWNERSHIP_TRANSFER** (PASS): the transfer advanced the fence from 1 to 2; the old holder's result was refused with 'fence 1 is stale; active fence is 2' and classified RECOVERY_REQUIRED; the transferred holder's identical result reached PARENT_INGESTED with zero errors; false_completion_count 0
- **EXPIRED_LEASE_WITHOUT_OWNERSHIP_TRANSFER** (FAIL): a lease granted with lease_seconds 0 was already expired, yet the holder's result reached PARENT_INGESTED with zero errors; source inspection of assert_fence_current and ingest_result found no reference to lease_seconds or granted_at, so the recorded lifetime is never read
- **NEVER_ALLOCATED_HIGHER_FENCE_TOKEN** (FAIL): with the active fence at 1, a worker presenting fence 1001 was not refused by assert_fence_current and its result reached PARENT_INGESTED; the guard rejects only tokens lower than the active fence, so a token that was never allocated passes
- **INTERLEAVED_FENCE_ALLOCATION** (FAIL): suspending one allocation inside its read-modify-write window while a second allocation completed returned token 1 to both allocators; the exclusive-creation candidate returned 1 and 2 under the identical interleaving
- **CONCURRENT_FENCE_ALLOCATION_ACROSS_REAL_PROCESSES** (OBSERVATION_ONLY): eight real processes taking six tokens each received 48 tokens with only 14 distinct values (34 duplicates) from the live allocator, and 48 tokens with 48 distinct values (0 duplicates) from the candidate
- **IDENTICAL_CALLBACK_REPLAYED_FIVE_TIMES** (PASS): the first callback was ingested and the next four were suppressed; exactly one ingestion file, one result file, one registry INGESTION row and one PARENT_INGESTED event; verify_chain clean
- **RETRIED_CALLBACK_WITH_REGENERATED_TIMESTAMPS** (FAIL): the transaction identity (task, idempotency key, lease, fence, attempt, result commit, artifact hashes) was unchanged while the document bytes differed; the second callback was not suppressed and produced two ingestion files, two result files, two registry INGESTION rows and two PARENT_INGESTED events for one transaction
- **CONCURRENT_DUPLICATE_CALLBACK_SAME_CLOCK** (FAIL): one ingestion suspended between its duplicate check and its first durable write while a second ingestion of the same document completed; the destination file stayed single, but the registry received two INGESTION rows and the event chain received two PARENT_INGESTED events for one logical ingestion
- **CONCURRENT_DUPLICATE_CALLBACK_SKEWED_CLOCK** (FAIL): with the two ingestions one second apart, the second writer raised FileExistsError: immutable file differs: .../ingestion-69d43205265055ac.json, so the coordinator crashed out of ingestion rather than recognising a duplicate
- **REPAIR_CANDIDATE_UNDER_IDENTICAL_AND_REGENERATED_DUPLICATES** (PASS): three identical replays plus one regenerated retry produced INGESTED then three DUPLICATE_SUPPRESSED_BY_IDENTITY outcomes, leaving one ingestion file, one registry row and one PARENT_INGESTED event
- **CLAIMED_HASH_DOES_NOT_MATCH_COMMITTED_BYTES** (PASS): refused with a read-back mismatch error, classified RECOVERY_REQUIRED, capsule intact, rerun from the capsule reached PARENT_INGESTED
- **CLAIMED_BYTE_COUNT_DOES_NOT_MATCH_COMMITTED_BYTES** (PASS): a byte count one higher than the committed bytes was enough on its own to produce a read-back mismatch and RECOVERY_REQUIRED; rerun reached PARENT_INGESTED
- **COMMITTED_BYTES_TRUNCATED_AFTER_HASHING** (PASS): the artifact was truncated by five bytes and re-committed while the result kept the original hash; refused with a read-back mismatch and RECOVERY_REQUIRED; rerun reached PARENT_INGESTED
- **ARTIFACT_PATH_ABSENT_FROM_THE_COMMIT** (PASS): refused with a read-back failure, RECOVERY_REQUIRED, event chain still verifiable, rerun reached PARENT_INGESTED
- **RESULT_COMMIT_DOES_NOT_EXIST** (PASS): a forty-zero commit id was refused with a read-back failure and RECOVERY_REQUIRED; rerun reached PARENT_INGESTED
- **LOCATOR_POINTS_AT_A_TREE_NOT_A_BLOB** (PASS): git cat-file blob refused the tree locator, so ingestion refused with a read-back failure and RECOVERY_REQUIRED; rerun reached PARENT_INGESTED
- **LOCATOR_IS_NOT_A_DURABLE_GIT_OBJECT** (PASS): a file:// locator was refused as non-durable; read_object_bytes also raised ValueError for http:// and for a bare relative path
- **WORKTREE_TAMPERED_AFTER_THE_COMMIT** (PASS): overwriting the worktree file with different bytes after the commit changed nothing: ingestion read the committed object, matched the recorded hash and byte count, and reached PARENT_INGESTED with zero errors
- **EMPTY_OR_MISSING_ARTIFACT_SET** (PASS): a zero-byte artifact was refused by the seeded contract with '$.artifacts[0].bytes: must be an integer >= 1' and an artifact-free committed result with '$.artifacts: committed result requires at least one artifact'; both classified RECOVERY_REQUIRED
- **TOTAL_PROVIDER_RUNTIME_LOSS_AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT** (PASS): completion_file_present=False; durable_result_committed=[]; event_chain_errors=[]; event_states=["CREATED", "LEASED", "RUNNING", "PROVIDER_COMPLETED_UNCOMMITTED"]; false_completion_count=0; immutable_input_available_for_rerun=True; ingestion_records=0; obzio_completed_event_present=False; provider_reported_completion=True; recovery_action=RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT
- **TOTAL_PROVIDER_RUNTIME_LOSS_AFTER_STAGING_BEFORE_PROVIDER_REPORT** (PASS): completion_file_present=False; durable_result_committed=[]; event_chain_errors=[]; event_states=["CREATED", "LEASED", "RUNNING"]; false_completion_count=0; immutable_input_available_for_rerun=True; ingestion_records=0; obzio_completed_event_present=False; provider_reported_completion=False; recovery_action=RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT
- **PROVIDER_COMPLETION_WITH_NO_DURABLE_RESULT_CLAIMS_COMPLETED** (PASS): complete_unit_refusal=po03-c6-048-contract-unit: cannot complete before PARENT_INGESTED; completed_claim_refused=True; ingestion_errors=["result carries no artifacts; nothing durable to ingest"]; ingestion_state=RECOVERY_REQUIRED; provider_completed_uncommitted_is_the_only_legal_state=True; self_acceptance_refused=True
- **FROZEN_CODE2_FAULT_FIXTURE** (PASS): durable_artifacts=[]; durable_result_commit_id=None; evidence_acceptance_state=NOT_TESTED; evidence_hash_matches=True; evidence_obzio_state=PROVIDER_COMPLETED_UNCOMMITTED; evidence_provider_state=COMPLETION_REPORTED_OR_LIVE_CONFLICT; evidence_result_state=UNRECOVERED_AFTER_FOUR_FOUNDER_REPORTED_ROUTES; evidence_sha256_observed=646bc5f36f4e18af543364dbfd432ccd7cc4bd7e1d35e229e462ea64ec56b148; evidence_sha256_recorded=646bc5f36f4e18af543364dbfd432ccd7cc4bd7e1d35e229e462ea64ec56b148; founder_relay_required_for_recovery=False; frozen_states_match_commission=True; is_a_completed_deliverable=False; 
- **RECOVERY_WITHOUT_FOUNDER_RELAY** (PASS): founder_supplied_inputs=[]; recovery_inputs=["control/tasks/<task>/input.json (immutable capsule)", "control/events/<task>/*.json (hash-chained events)", "control/tasks/<task>/ingestion-*.json (ingestion records)", "control/leases/<task>.json (fence token)", "git objects reached by immutable object id"]; scan_recovery_parameters=["run_id", "head_sha"]; scan_recovery_reads_only_repository_state=True
