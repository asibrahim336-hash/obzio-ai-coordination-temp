# LANE C-1 (CURSOR) — FULL-EXPORT COVERAGE: BLOCKED RETURN

**Date:** 27/08/2026
**Lane:** C-1 Cursor, open the full export
**Role-priority basis (FC-01):** **COVERAGE.** End the data gap; do not interpret.
**Status:** `DATA GAP NOT CLOSED — NAMED CREDENTIAL BLOCKER — INSTRUMENT BUILT AND VERIFIED`

## 1. Result

Zero bytes of the export were retrieved. **0 of 9 named assets, 0 of 527,426,083
named bytes.** No denominator in the brief could be replaced with a true one,
because no asset opened.

The blocker is not size, and not binary encoding. **This surface has no Google
identity.** Every Drive asset is private to Ahmed's Google account, and this
cloud agent holds no Google credential, no OAuth token, no service account and
no browser session. Nothing was ever decoded, so the question of whether the
payload is binary never arose.

The instrument that would have produced every requested number was built,
tested and committed instead. It runs on the laptop, unchanged.

## 2. The blocker, per asset and per route (R2)

Tested directly rather than inherited. Three folder ids across three
anonymous route classes: **9 probes, 9 refusals, 0 successes.**

| Route | `CHATGPT_ESTATE_01` | `Obzio Relay Returns` | Return folder `1ESu3k…` |
|---|---|---|---|
| `drive.google.com/drive/folders/<id>` | 302 → `accounts.google.com/v3/signin` | 302 → signin | 302 → signin |
| `drive.google.com/embeddedfolderview?id=<id>` | **HTTP 401** | HTTP 401 | HTTP 401 |
| `drive.google.com/uc?export=download&id=<id>` | 302 → signin | 302 → signin | 302 → signin |

Exact response text on the 401:

> Sign in to your Google Account — You must sign in to access this content.

Drive API v3, no key:

> HTTP 403 `PERMISSION_DENIED` — "Method doesn't allow unregistered callers
> (callers without established identity). Please use API Key or other form of
> API consumer identity to call this API."

Credential surfaces checked and absent: injected secrets are
`AUREA_E2E_SUPABASE_*` only (4 of 4, none Google); no `~/.config/gcloud`, no
application-default credentials, no `rclone`/`gdrive`/`gcloud` binary; GCE
metadata service unreachable (`http=000`); no Drive-capable tool namespace in
the agent's catalogue. Network egress itself is open — `github.com` and
`pypi.org` both return 200 — so this is an identity boundary, not a network
one.

**Not attempted, by rule:** no sign-in, no credential entry, no anti-bot
handling, no scraping of an authenticated session.

## 3. Two prior diagnoses, corrected

- **Metamate's `php_oom`/size report.** Not reproducible here and not the
  operative blocker on this surface. Bounded to Metamate: this run produced no
  evidence about what Metamate encountered.
- **The briefing's replacement hypothesis — "the actual error is that they are
  BINARY and cannot be returned as text".** Also not the operative blocker
  here. Binary-ness is real and would defeat a text-only surface, but on this
  surface the request is refused before any byte is served. Correcting one
  wrong cause with another wrong cause would have left the same gap.

Both are superseded **as explanations for this surface only**. Neither is
disproved for the surface that reported it (R2: blocks bind to their asset and
session class).

## 4. The structural collision

This is the finding worth carrying forward, and it is not a Cursor problem.

- **Cursor** has the filesystem, `unzip`, and open egress — and **no Drive
  identity**.
- **ChatGPT and Claude** have exercised Drive connectors — and cannot unpack a
  110 MB binary.

The capability and the credential sit on opposite sides. **No single currently
constituted surface can close this gap alone.** Every prior attempt failed on
whichever half its surface lacked, and each surface reported the failure in the
vocabulary of its own half, which is why the cause has now been misdiagnosed
twice.

The brief's premise that Cursor is "the only surface with a filesystem" is also
worth re-testing: `state/ACCESS_CAPABILITY_MATRIX_20260816.md` records Claude
Cowork with `files, shell, connectors` **and** a Google Drive connector
exercised read/write. If both still hold on one Cowork session, that single
surface spans the split.

## 5. Routes

| Route | Founder action | Assessment |
|---|---|---|
| **A. Laptop** — download the assets, run the committed extractor | download + one command | **Recommended.** No new permission, no third-party exposure, no credential in a temporary surface. FC-03 puts the official setup on the laptop; this produces the artefact there directly. |
| **B. Give this agent a Google credential** | create OAuth/service-account, add to Cursor secrets | **Rejected on strategy, not capability.** AGENTS.md §7 makes new external OAuth an explicit stop boundary, and FC-03 states this Cursor account will not join the official setup — this spends a durable credential on a surface being discarded. |
| **C. Claude Cowork** — Drive connector to pull, shell to unpack, same extractor | authorise the session | **Strongest alternate if A is unattractive.** Positively authorised by FC-03. Must be re-tested per asset before it is relied on: `WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_…_v001.md` §1 rules that surfaces hold *different* Google accounts, so a Drive connector does not imply reach into *this* folder. |

Route A and Route C run the identical artefact; the extractor is stdlib-only
Python 3 with no host dependency, so choosing between them costs nothing and
commits to nothing.

## 6. What was built and verified instead

`tools/chatgpt-export/extract_full_export.py` — single file, Python 3.8+,
standard library only, no network, no install. It produces every deliverable
the lane asked for: true denominators, authorship separation, the
`memories`/`projects` read, the sharded portable JSONL, and the delta against
the 928-act index.

Verified by content, not by length (R4). `test_extract_full_export.py` builds a
synthetic export whose counts were derived by hand, runs the extractor, and
compares against literals held in the test — **63 of 63 checks pass**. The
fixture carries the cases that break naive parsers: a root node with no
message, a custom-instructions envelope wearing `author.role == "user"`, a
hidden user node, an empty user node, one conversation present in two archives
at different completeness, a template repeated across three conversations, an
archive whose filename states nothing about its type, a nested archive, and a
corrupt archive that must surface as a named blocker rather than silence. A
second phase covers malformed input — object-rooted payloads, null mappings,
conversations with no id, multimodal parts, non-dict nodes, an encrypted
archive, unparseable JSON, and a non-archive binary standing in for the
hash-named Drive object. Each must be counted or named, never silently
dropped.

Measured at realistic scale, denominator one 600.0 MB `conversations.json`:

- streaming parse **63 MB peak RSS** against **1,553 MB** for `json.load` —
  25x smaller and faster. This is the failure mode that stops a full export
  opening, and it is now removed.
- full pipeline: 14,463 conversations, 347,112 message nodes, 173,556 user
  messages, 8 shards all under 50 MB, 12.7 s, 479 MB peak.

Design points that change the numbers, all of them counting decisions rather
than interpretation:

- **Authorship.** The user-role envelope is reduced by custom-instruction
  injections, hidden nodes and empty nodes *before* echo share is computed, so
  the percentage has an honest denominator. Both the specified threshold
  (fingerprint over the first 600 normalised characters, flagged at ≥3) and a
  stricter reading over messages ≥200 characters are reported side by side.
- **Duplicates.** The same conversation appears in more than one archive.
  Every payload is indexed first and only the copy with the most mapping nodes
  is scanned. Without this, every node count inflates by whatever overlap the
  archives happen to have.
- **Superseded authority (R13).** Acts are partitioned by `status`/`superseded`
  before their content is admitted. A founder message matched only by a
  superseded act is counted separately from one matched by a live act and from
  one absent entirely. A content-only query collapses all three and reports
  dead authority as live coverage — the error made on 27 Aug.
- **Identification before assumption.** Every input is typed from its magic
  bytes. The 392,652,498-byte hash-named object needs no rename and no guess;
  if it is a container it is opened, and if not, section 1 of the generated
  report states what it actually is.

## 7. Prior-artifact disposition (R3)

| Artifact | Disposition |
|---|---|
| `state/ACCESS_CAPABILITY_MATRIX_20260816.md` | **EXTENDED.** Its `Google Drive — personal` connector row is the evidence basis for Route C. The matrix has no Cursor cloud-agent row; §2 above supplies one: open egress, no Google identity. |
| `receipts/CLAUDE_V009_DIRECT_TRANSPORT_ACCESS_DEFECT_20260819_v001.md` | **REUSED** as the receipt form — per-route access defect, coverage boundary stated, no bypass attempted. Not superseded: different surface, different asset. |
| `receipts/METAMATE_ARCHIVE_INTEGRITY_AND_RESTRICTED_CONTENT_DEFECT_20260819_v001.md` | **REUSED** as method — bounded defect receipt, preserve originals, recompute hashes independently. Not superseded: it governs the 12/08 Metamate/R0 16-file set, not the ChatGPT export zips. |
| `dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md` | **REUSED and binding.** §1 (surfaces hold different Google accounts; no cross-account assumption) qualifies Route C. §5 (recover through native routes first, then one exact founder action) is the precedent this return follows. §1's rule against hardening Drive into architecture is why outputs are committed to git as well. |
| `workstreams/so02/control-plane/launch/CURSOR-LAUNCH-NOW.md` | **REUSED** as lane context. Its constraint "Claude's current account allowance is exhausted" is **SUPERSEDED** by FC-03 (27 Aug), which positively authorises Claude. |
| `conversations-011(1).json`, `UNIFIED-AUTHORITY-INDEX-928.json`, `obzio_authority_extract_claude_raw.json` | **NOT REACHED.** Named readable in the brief, but they sit in the same private Drive folder and are refused identically. The extractor consumes all three; the index feeds section 7 of its report. |

Nothing here supersedes the 928-act index, REGISTRY.yaml v2.3, or the taxonomy
bridge. None were rebuilt.

## 8. Boundaries observed

`FC-02` — Obzio is a 3D platform selling agent harnesses **and more**. The open
part is **left OPEN** and is not filled by inference anywhere in this return.
Nothing in this lane touches it: coverage and structure only, no founder
profile, no strategy reading (brief item 6).

`FC-03` — nothing was invested in the temporary layer. The artefact is
stdlib-only Python committed to git, carrying no Metamate, Cursor, account or
network dependency.

Protected surfaces untouched: no third-party contact, no spend, no secret or
owner-identity act, no new OAuth, no production/DNS/deployment mutation, no
deletion, no strategy binding.

## 9. The unavoidable founder action

One action, because Route A needs nothing else:

1. Download the five zips plus the hash-named object from `CHATGPT_ESTATE_01`
   and `Obzio Relay Returns`, and the three JSON files from `1ESu3k…`, into one
   folder on the laptop.
2. Run, with Python 3.8+ already present on macOS:

```bash
python3 extract_full_export.py \
  --input  ~/Downloads/CHATGPT_ESTATE_01 \
  --out    ~/obzio-coverage \
  --authority-index ~/Downloads/UNIFIED-AUTHORITY-INDEX-928.json
```

3. Upload `FULL-EXPORT-COVERAGE-REPORT.md` and the
   `FOUNDER-MESSAGES-FULL.*.jsonl` shards from `~/obzio-coverage` to
   `1ESu3kDZ9NgwKqz_xIz-krF3Oc7lLul0T`.

The report it writes is the return this lane owed, with real denominators
throughout. Full runbook: `tools/chatgpt-export/RUN-ON-LAPTOP.md`.

If Route C is preferred, the same file runs unchanged in a Cowork shell and no
laptop step is needed — but re-test Drive reach per asset first (§5, R2).
