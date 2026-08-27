# Full ChatGPT export coverage extractor — run on the laptop

One command turns the raw Drive assets into the coverage report and the
portable founder-message corpus. Nothing here depends on Metamate, on Cursor,
on this repository or on any account.

## Requirements

Python 3.8 or newer. Nothing else. No `pip install`, no network, no API key.
macOS ships a usable Python 3; on Windows use the python.org installer.

Copy `extract_full_export.py` anywhere. It is self-contained.

## Run it

Download the Drive assets into one folder, then:

```bash
python3 extract_full_export.py \
  --input  ~/Downloads/CHATGPT_ESTATE_01 \
  --out    ~/obzio-coverage \
  --authority-index ~/Downloads/UNIFIED-AUTHORITY-INDEX-928.json
```

Put every asset in `--input`, including the ones that are not archives. The
tool identifies each file from its bytes, so the 392,652,498-byte hash-named
file from `Obzio Relay Returns` can go in the same folder with no rename: if it
is a container it will be opened, and if it is not, section 1 of the report
says what it actually is.

`--authority-index` is repeatable; pass both
`UNIFIED-AUTHORITY-INDEX-928.json` and
`obzio_authority_extract_claude_raw.json` to widen the comparison. Omit it and
section 7 reports `NOT RUN` rather than guessing.

Useful flags: `--shard-mb` (default 45), `--echo-min-count` (default 3),
`--no-samples` to keep sample values out of the profiler tables,
`--keep-extracted` to retain the unpacked tree for inspection.

## What you get in `--out`

| File | Contents |
|---|---|
| `FULL-EXPORT-COVERAGE-REPORT.md` | The eight-section report. Every number carries its denominator and instrument. |
| `FOUNDER-MESSAGES-FULL.NNN.jsonl` | One founder-authored message per line, sorted by timestamp, sharded under the size limit. |
| `ECHO-MESSAGES.NNN.jsonl` | Messages excluded as template echo, so the split is auditable and reversible. |
| `coverage-metrics.json` | Every counted fact as machine-readable JSON. |
| `MANIFEST.json` | SHA-256 and byte count of every output. |

Upload the report and the `FOUNDER-MESSAGES-FULL.*.jsonl` shards to the return
folder. The JSONL is the durable artefact: plain UTF-8, one JSON object per
line, readable by anything.

## What the tool decides, and how to change it

**Authorship.** `author.role == "user"` is an envelope. The tool subtracts
custom-instruction injections (`metadata.is_user_system_message`, or
`content_type == user_editable_context`), nodes hidden from the conversation,
and nodes empty after whitespace normalisation. What remains is the
*addressable* population, and every echo percentage is a share of that number,
never of the raw envelope.

**Echo.** A message's fingerprint is the SHA-1 of the first 600 whitespace-
normalised characters. A fingerprint occurring at or above `--echo-min-count`
marks all its members as echo. The report also gives a stricter reading over
messages of at least 200 normalised characters, where recurrence cannot be
short conversational filler. Both readings are printed with the same
denominator so they can be compared directly.

**Duplicates.** The same conversation appears in more than one archive. The
tool indexes every payload first, keeps only the copy with the most mapping
nodes, and scans that one. Without this every node count would be inflated by
whatever overlap the archives happen to have.

**Superseded authority.** Acts are partitioned by `status`/`superseded` before
their content is admitted. A founder message whose only match is a superseded
act is reported separately from one matched by a live act and from one absent
entirely. A content-only query would collapse all three and report dead
authority as live coverage.

**Memory.** `conversations.json` is streamed one conversation at a time rather
than loaded whole. Measured on a 600 MB file: 63 MB peak RSS streaming against
1,553 MB for `json.load`, a 25x reduction, and faster. This is what lets a
full export open on a laptop.

## Verifying the tool before trusting its numbers

```bash
python3 test_extract_full_export.py
```

This builds a synthetic export whose true counts were worked out by hand, runs
the extractor against it, and compares. The expected values are literals in the
test, so the check is independent of the extractor's own logic rather than the
tool agreeing with itself.

The fixture deliberately includes the awkward cases: a root node carrying no
message, a custom-instructions envelope wearing `author.role == "user"`, a
hidden user node, an empty user node, one conversation present in two archives
at different completeness, a template repeated across three conversations, an
archive whose filename says nothing about its type, a nested archive, and one
corrupt archive that must surface as a named blocker rather than silence.

Hand-derived expected values:

| Measure | Expected | Why |
|---|---:|---|
| Distinct conversations | 7 | C1–C7, after two duplicate copies are dropped |
| Total mapping nodes | 20 | 5+2+4+2+3+2+2 across the winning copies |
| Message-bearing nodes | 19 | 20 less one root node carrying no message |
| User-role envelope | 11 | before any authorship reduction |
| Addressable user messages | 8 | 11 less 1 context envelope, 1 hidden, 1 empty |
| Template echo | 3 | one template across C2, C3, C4 |
| Founder-authored | 5 | 8 less 3 |
| Covered by a live act | 1 | matched to `A001`, status CURRENT |
| Covered only by a superseded act | 1 | matched to `A002`, status SUPERSEDED |
| Absent from the index | 3 | the remainder |
| Named blockers | 1 | `broken-archive.zip` |

## If something defeats it

The tool never reports a partial success as complete. An archive that will not
open, an entry that will not decompress and a payload that will not parse each
land in section 8 with the exact exception type and message, and the run
continues so the rest is still counted. A named blocker in section 8 is the
result for that asset.
