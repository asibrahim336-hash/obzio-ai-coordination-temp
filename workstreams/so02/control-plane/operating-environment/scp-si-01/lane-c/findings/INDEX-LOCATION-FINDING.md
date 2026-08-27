# Where the 928-item authority index is — `NOT_FOUND`

**Lane** SCP-SI-01 lane C
**Integration commit audited against** `7f29043eece45f42f018d841718a257cfd18739b`
on `cursor/operating-environment-return-20260822-v001`, re-fetched during this run
**Evidence label** `DIRECTLY_REPRODUCED` for every count below; each was recomputed
in this run, not carried forward

## Verdict

```
NOT_FOUND asibrahim336-hash/obzio-ai-coordination-temp / all 122 remote refs /
          no path — no artifact at any ref holds 928 items
```

`NOT_FOUND` authorises nothing. No index was created, no index was replaced, and
the deliverable is a sidecar over what does exist.

## What was searched

The commission records the index as holding **928 items** but gives no path, so the
search was exhaustive rather than path-guided.

| Search | Method | Result |
|---|---|---|
| Name | `git grep -il 'authority.index\|authority_index\|AUTHORITY-INDEX'` across all 122 remote refs | one hit, `SCP-SI-01-SYSTEM-MAP.md` line 56, which is the commission text itself |
| Path | `git ls-tree -r` for any path matching `index` across all refs | five hits, all fetched web documentation under `receipts/.../raw/` |
| Size, structured | every JSON/JSONL blob over 5 KB unique across all refs — 965 blobs — parsed, every array counted at every depth, every JSONL line counted | largest collection anywhere is **571**, `workstreams/po03/control/events/ledger.jsonl` at `cursor/po03-wave-a-b195-1a9f`. No collection of 928 |
| Size, unstructured | every non-JSON blob over 3 KB unique across all refs — 1,293 blobs — line-counted and markdown-table-row-counted, window 850–1010 | 14 hits, all source files or fetched docs; none an index. Nearest: `CHATGPT-CONSTITUTION-20260822-v001.md` at 934 lines |
| Tree size | file count per ref | nearest is 922, `cursor/po03-wa-route-04-material-6e19`; the return branch holds 824. Neither is an index of anything |

The figure `928` appears nowhere in this repository as a count. Every textual match
for the digits is a substring of a sha256 or a git object id.

## What does exist, and what the sidecar was therefore built over

The estate has no single authority index. It has a small set of authority-bearing
artifacts, and these are what the sidecar indexes:

| Artifact | Items | What it is |
|---|---|---|
| `…/FOUNDER-STANDING-INSTRUCTION-20260822.md` | 195 lines | the governing verbatim founder record |
| `…/w10-provenance/FOUNDER-CORPUS-20260823-v001.json` | **4 segments**, 3 founder + 1 excluded | the corpus a `FOUNDER_AUTHORED` verdict may be tested against. This is the closest thing to an authority index that exists |
| `…/w10-provenance/PROVENANCE-REGISTER-20260823-v001.json` | **86 constraints**, 29 founder quotations | the live provenance classification |
| `…/w4-platform-roles/DE-RESTRICTION-REGISTER-20260822-v001.json` | **76 constraints**, 27 prior `FOUNDER_BOUND` | the superseded register, kept as evidence of what the defective method produced |
| `.cursor/rules/00-founder-standing-authority.mdc` | 144 lines | the always-applied projection of founder authority |

86 + 76 = 162, and 4 corpus segments. Nothing sums to 928 on any grouping tried.

## How to read the discrepancy

Two readings are consistent with the evidence and this lane cannot choose between
them from inside the repository:

1. **`HYPOTHESIS`** — 928 counts items in a store outside this repository, most
   plausibly conversation items in the founder's ChatGPT account. The estate's own
   record notes that surface as unreachable from a cloud agent: the L5 lane
   recorded the OpenAI evidence layer and the coordinator's baseline records the
   GitHub evidence layer returning `BLOCKED` with zero observed repository state.
   An index of 928 conversation items would fit the authorship problem this lane
   was commissioned to solve far better than 4 corpus segments do.
2. **`HYPOTHESIS`** — 928 is an assistant-authored figure that entered a summary
   and was inherited unexamined. That is the documented failure mode of this
   estate, named by the founder about the protected-surface label: "originated in
   assistant-generated commission text, was inherited unexamined from run to run,
   hardened into a taboo."

Either way the number is `UNVERIFIED` and must not be requoted as measured. The
sidecar is built so that reading 1 costs nothing to satisfy: adding a conversation
store is one adapter function returning `IndexView`, and no other file changes. See
the README's integration section.

## Consequence for the deliverable

Lane C was told to extend the authority index and must not create a replacement.
Since the named index does not exist, the sidecar extends the artifacts that
actually carry authority, holds no content of its own, and is content-addressed to
the artifacts it indexes. It cannot become a competing index because it has nothing
in it to compete with: every record is a set of character spans pinned to a
sha256, and resolving a span requires the pinned artifact.
