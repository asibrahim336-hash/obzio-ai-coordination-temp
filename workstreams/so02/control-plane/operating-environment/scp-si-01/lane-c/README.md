# Authorship sidecar — SCP-SI-01 lane C

A non-destructive query layer that answers **who authored this** for the estate's
authority-bearing artifacts, at a granularity finer than one message.

**State** `READY_TO_COMMIT`
**Integration commit audited against** `f0fb3f51a25db67b33bdd558c73055f3d02ddb60`
on `cursor/operating-environment-return-20260822-v001`, re-fetched during this run.
This branch was cut at `7f29043eece45f42f018d841718a257cfd18739b`; integration then
advanced one commit, so the slice was rebuilt against the newer head. All three
pinned source artifacts are byte-identical at both commits and the rebuild changed
exactly two leaves — the recorded commit and the timestamp. Every one of the 136
segment classifications and every tally is unchanged. `DIRECTLY_REPRODUCED`
**Runtime** Python 3 standard library only. No third-party imports, no pytest.
Everything below runs under `python3 -I`.
**This is a proposal, not a binding.** `decision_changed: []`. It classifies; it
removes nothing and rewrites nothing.

## Contents

| Path | What it is |
|---|---|
| `tools/authorship_sidecar.py` | the library and CLI — segmenter, signals, classifier, query layer, verifier, adapters |
| `tools/test_authorship_sidecar.py` | 60 `unittest` cases |
| `tools/run_slice.py` | runs the sidecar over the bounded real slice and writes the report |
| `tools/reproduce_prior_defect.py` | reproduces the prior defect against the estate's live `provctl.py` |
| `tools/build_receipts.py` | the two receipt stages — read-back, then manifest closure |
| `tools/build_declaration.py` | generates the write declaration with its hashes taken from disk |
| `tools/verify_declaration_evidence.py` | checks the declaration against the bytes on disk, which the admission gate does not |
| `tools/reproduce_gate_blindness.py` | reproduces that gap against the estate's live gate |
| `tools/release.sh` | runs all nine steps in the one order that is acyclic |
| `fixtures/mixed-message-founder-and-pasted.md` | founder words + pasted third-party block + refusal, in one message |
| `fixtures/adopted-and-disavowed.md` | adoption, adoption-inside-attribution, and disavowal defeating adoption |
| `fixtures/position-without-evidence.md` | the positional trap: founder-titled headings over text with no founder evidence |
| `fixtures/agent-representation.md` | an agent speaking for the founder beside the founder speaking for himself |
| `sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json` | the sidecar over the real slice |
| `sidecar/SLICE-REPORT-20260827-v001.json` | what it found, with every disagreement |
| `findings/INDEX-LOCATION-FINDING.md` | `NOT_FOUND` for the 928-item index, and what was searched |
| `findings/DEFECT-REPRODUCTION.md` | the reproduced prior defect |
| `findings/GATE-EVIDENCE-BLINDNESS.md` | a defect found in the admission gate itself, reproduced |

## Exact test commands

Run from the repository root. Each is copy-pasteable and each exits 0 on success.

```bash
# 1. the test suite — 60 cases, stdlib unittest, isolated interpreter
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/test_authorship_sidecar.py

# 2. reproduce the prior defect against the estate's live provctl.py
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/reproduce_prior_defect.py --repo-root .

# 3. rebuild the sidecar and the slice report over the real artifacts
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/run_slice.py \
    --repo-root . --commit "$(git rev-parse origin/cursor/operating-environment-return-20260822-v001)"

# 4. recompute a committed sidecar against its pinned sources
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/authorship_sidecar.py \
    verify workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json \
    --repo-root .

# 5. run a default-excluding authority query
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/authorship_sidecar.py \
    query workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json

# 6. classify any markdown record ad hoc
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/authorship_sidecar.py \
    classify workstreams/so02/control-plane/operating-environment/FOUNDER-STANDING-INSTRUCTION-20260822.md

# 7. is the write declaration's evidence true of the files on disk
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/verify_declaration_evidence.py \
    --repo-root .

# 8. reproduce the gap in the admission gate's evidence check
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/reproduce_gate_blindness.py \
    --repo-root .
```

Command 3 rewrites the two files under `sidecar/`. It is deterministic: the same
inputs produce byte-identical output, which is what makes the manifest hashes in
`receipts/so02/2026-08-27/scp-c/MANIFEST.json` reproducible. Re-running it
against a moved integration head changed exactly two leaves, the recorded commit
and the timestamp; all 136 classifications were identical. `DIRECTLY_REPRODUCED`

To rebuild every artifact and receipt in one step, including the declaration and
the admission verdict:

```bash
bash workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/release.sh \
    "$(git rev-parse origin/cursor/operating-environment-return-20260822-v001)"
```

That is the same nine steps, in the one order that is acyclic. Four artifacts
here hash each other — the declaration's evidence covers `READ-BACK.json`,
`ADMISSION.json` is the verdict on the declaration, and `MANIFEST.json` covers
all three — so the receipt builder is staged rather than single-pass, and
rebuilding out of order leaves the declaration asserting hashes that are no
longer true. `release.sh` exits non-zero if the gate refuses, so a refusal
cannot be read as an admission.

### Why `verify_declaration_evidence.py` exists

`EARNED`, and the defect is in the gate this lane was told to invoke. The
admission gate's evidence check delegates to
`evidence_integrity.verify_manifest_closure`, which asks whether every
`present_paths` entry is covered and whether `bundle_sha256` binds the entry
list. Both are answerable without opening a single declared file, so **a
declaration whose recorded hashes are stale, or invented, passes the gate.**
That is the shape of the `verify_readback_truth` defect this estate already
recorded — shape checked, truth never — one layer out.

`DIRECTLY_REPRODUCED`, without tampering, on this lane's own declaration: three
deliverable files were edited and one added after the declaration was generated,
and re-running the gate returned `WRITE_ADMITTED` with `EVIDENCE_RECOMPUTED`
while two of the eighteen recorded hashes were wrong and a fourth file was
covered by nothing. Verbatim output in
`receipts/so02/2026-08-27/scp-c/raw/gate-blindness-observed.txt`, written up in
`findings/GATE-EVIDENCE-BLINDNESS.md`, and reproducible on demand with
`tools/reproduce_gate_blindness.py`.

So the hashes are generated from disk by `build_declaration.py` in the same run
as the push, and `verify_declaration_evidence.py` asks the question the gate
cannot — do these hashes describe the files that are actually there. It runs as
step 7 of `release.sh`, before the gate. It binds this lane's own release path
and proposes nothing for anyone else's; `write_admission.py` is outside lane C's
write scope and was not touched.

## The five authorship classes

| Class | Meaning | In a default authority query? |
|---|---|---|
| `FOUNDER_DIRECT` | the founder's own words, first-hand | yes |
| `FOUNDER_ADOPTED` | material he explicitly took as his own | yes |
| `FOUNDER_REPRESENTED` | an agent speaking for him | yes for segment queries, **refused** for quotation verdicts |
| `NONFOUNDER_PASTED` | third-party content pasted into a founder-authored message | **no** — opt in explicitly |
| `UNRESOLVED_USER_ROLE` | authorship not determinable from evidence in scope | **no** — opt in explicitly |

`FOUNDER_REPRESENTED` sits deliberately in the middle. An agent's rendering of his
authority is visible to a consumer enumerating the authority surface, and refused
to a consumer asking "did he say this". Those are different questions and
collapsing them is how `FOUNDER-AUTHORITY-20260822T2225Z.json` came to be cited as
his words.

## Design constraints, with provenance stated

Per the standing discipline, an unclassified constraint is not in force.

| # | Constraint | Provenance | Basis |
|---|---|---|---|
| 1 | The sidecar never writes the index and never copies its content. Records are character spans pinned to a `sha256`; resolving one requires the pinned artifact and fails closed when it changes. | `EARNED` | Two indexes of the same thing drift and the estate then has two answers. Named in the system map: lane C "must not create a replacement index". |
| 2 | Legacy fields are copied through unmodified under `legacy.fields` and hashed. | `FOUNDER_AUTHORED` | "Provenance survives everything. Direct founder intent outranks derived summaries." |
| 3 | Classification happens below message granularity. | `EARNED` | One class per message cannot represent a message containing his words and a paste. Reproduced against `provctl.extract_segments`: one mixed message, one `FOUNDER_DIRECT` segment. |
| 4 | **Position is inert.** No positional fact — role, heading, quote depth, path, ordinal, git author — may raise a segment above `UNRESOLVED_USER_ROLE`. Position may only bound the scope in which textual evidence applies. | `FOUNDER_AUTHORED` | "Git authorship is not founder authorship… The only valid founder-provenance signal is a quoted founder utterance. A classifier using commit metadata is measuring the wrong thing." |
| 5 | **A substring match is a locator, not a verdict.** The verdict is the landing segment's class. | `EARNED` | Reproduced against `provctl._find_quote`: a disavowed third-party sentence verified as a founder quotation. |
| 6 | Attribution inheritance outranks self-identification inheritance: once a pasted scope opens it stays open until the scope ends or a resumption marker fires. | `EARNED` | The asymmetry is deliberate. Misreading pasted material as founder material is what produced the protected-surface label; the reverse error only under-claims authority. |
| 7 | Representation outranks first-person drafting. | `EARNED` | An agent drafting in his voice writes first-person directives. The de-restriction register's `FOUNDER_BOUND` verdicts are what that costs. |
| 8 | An ambiguous quotation — landing in both an admitted and an excluded class — is refused unless the excluded class is opted in. | `EARNED` | Measured: 6 of the 29 live register citations are ambiguous across the slice, because the founder record's sentences are copied verbatim into an agent-authored projection of it. |
| 9 | Default authority queries exclude `NONFOUNDER_PASTED` and `UNRESOLVED_USER_ROLE`; opting either in is explicit and is recorded in the result. | `ASSISTANT_AUTHORED` | Directly instructed by the SCP-SI-01 lane C commission. Inert unless ratified; implemented because the commission is the operative instruction for this lane, and stated as assistant-authored rather than dressed as founder intent. |
| 10 | Every structured artifact is hash-checked **and parsed** after read-back. | `EARNED` | A hash-valid unparsable artifact is already in this estate's record; commit `3b97d6ff` repaired a truncated one. |
| 11 | `normalise` folds markdown emphasis at exact parity with `provctl.normalise`. | `EARNED` | Without it this lane produced a false disagreement with the register on `FA-06`. See `findings/DEFECT-REPRODUCTION.md`. |
| 12 | This lane's write declaration is generated from disk in the same run as the push, and its hashes are recomputed against disk before the gate is invoked. Binds lane C's release path only. | `EARNED` | The admission gate's evidence check never opens a declared file, so it returned `WRITE_ADMITTED` / `EVIDENCE_RECOMPUTED` on this lane's own declaration while two of its eighteen hashes were wrong. Reproduced in this run; see `findings/GATE-EVIDENCE-BLINDNESS.md`. |

## What the bounded slice found

`DIRECTLY_REPRODUCED` — every number is recomputed by `run_slice.py` in the run
that writes it.

**6 items, 136 segments, `SIDECAR_VERIFIED` against pinned sources.**

| Item | Segments | Classes | Legacy class |
|---|---|---|---|
| `FSI-20260822` — the governing verbatim founder record | 67 | direct 33, represented 6, pasted 10, unresolved 18 | none |
| `RULE-00-FOUNDER-STANDING` — the always-applied rule | 34 | direct **0**, represented 2, unresolved 32 | none |
| `FC-SEG-00` | 4 | direct 4 | `FOUNDER_DIRECT` |
| `FC-SEG-01` | 1 | direct 1 | `FOUNDER_DIRECT` |
| `FC-SEG-02` | 3 | pasted 3 | `FOUNDER_QUOTING_OTHER` |
| `FC-SEG-03` | 27 | direct 27 | `FOUNDER_DIRECT` |

### Agreements

* **All four corpus verdicts are reproduced.** No verdict-level disagreement with
  `FOUNDER-CORPUS-20260823-v001.json`. What changes is granularity: 4 legacy
  classes become 35 classified segments.
* **29 of 29 register citations admitted** when scoped to the governing corpus.
  The live provenance register's founder citations all hold.
* **The baseline's "17 of 27 misattributed, 10 survived" figure is reproduced**
  exactly, recomputed from both registers rather than carried forward: 27 prior
  `FOUNDER_BOUND` constraints carried into the re-derived register, 10 survive as
  `FOUNDER_AUTHORED`, 17 overturned.

### Disagreements

1. **`MATERIAL`. The governing verbatim founder record is 4-way mixed.**
   `FOUNDER-STANDING-INSTRUCTION-20260822.md` states in its own header, lines
   10-13: "The founder's words are reproduced verbatim below. Nothing in this file
   paraphrases, compresses or interprets them." That is true of the block
   quotations and false of the file. 33 of 67 segments are his own words; 34 are
   not, including **10 segments of third-party material pasted into it** and 6 of
   agent commentary. Anyone quoting "from the verbatim founder record" without
   segmenting can quote any of them.

2. **`MATERIAL`. The always-applied rule contains no founder-verbatim text at
   all.** `.cursor/rules/00-founder-standing-authority.mdc` is prepended to every
   agent turn in this repository and is titled "Founder standing authority — Ahmed
   Sadek, Obzio". **0 of its 34 segments are `FOUNDER_DIRECT`.** It is an agent's
   rendering throughout — which is what it says it is, since it points at the
   verbatim record for his words. The defect is not the file; it is citing the
   file as if it were his words, and that is exactly the artifact class that
   produced the protected-surface misattribution.

3. **Measured: 6 of 29 register citations are ambiguous across the slice.**
   Scoped to the governing corpus, 29 of 29 admit. Unscoped, 6 refuse, because
   those sentences also appear inside the agent-authored `.mdc` projection where
   they carry no authorship evidence. A substring check cannot tell which of the
   two it found. The register is not wrong — it names its corpus. The instrument
   that verifies it does not use that name.

4. **All 27 prior `FOUNDER_BOUND` statements fail to locate as written.** This is
   reported with its limitation attached: the de-restriction register paraphrased
   its constraints, so a miss means "no verbatim founder text carries this
   statement as written", not "the founder rejected it". It is not a
   contradiction of the 10-survived figure, which is about re-derived verdicts on
   quotations rather than about locating paraphrases. Stated because 27/27 read
   alone would be a more dramatic and less true claim.

5. **`FOUNDER_ADOPTED` is 0 in this slice, by design and not by omission.**
   Adoption markers do occur — 4 in the founder record, 2 in `FC-SEG-00`, 2 in
   `FC-SEG-03`. `FOUNDER_ADOPTED` belongs to the material he took, not to his
   sentence about taking it, and the one pasted block in the real record carries
   an explicit disavowal instead of an adoption. The class is exercised by
   `fixtures/adopted-and-disavowed.md` and by four `unittest` cases. A zero here
   is a fact about the corpus.

### Honest limits

* `HYPOTHESIS` — the signal set is derived from this estate's own vocabulary. It
  will need extension for a conversation store whose paste conventions differ, and
  the shape of that extension is one tuple appended to `SIGNALS`.
* `DIRECTLY_REPRODUCED` — 50 of 136 segments are `UNRESOLVED_USER_ROLE`, 32 of
  them in the `.mdc` rule file. That is deliberate under-claiming. `UNRESOLVED` is
  excluded by default, so the cost of a false negative is a refused query, and the
  cost of a false positive is a misattributed founder instruction. The classifier
  is tuned for the first.
* This lane is the producer of this artifact and cannot accept it. Lane H's
  independent acceptance is the only check, and it is free to refuse.

## Integrating it

### Read the sidecar

```python
import sys; sys.path.insert(0, "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools")
import authorship_sidecar as A

sidecar, problems = A.read_back_and_parse(
    "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/"
    "sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json")
assert not problems, problems               # hash-valid but unparsable is a defect

sources = A.load_span_bases(sidecar, repo_root=".")
assert A.verify_sidecar(sidecar, sources) == []   # recompute; never trust the file
```

`verify_sidecar` must pass before any verdict from the sidecar is used. It refuses
if any pinned artifact changed. That is not pedantry: a stale sidecar over an
edited record is a classifier asserting authorship for text it never saw.

### Ask the two questions

```python
# 1. what may be treated as authority?  Default excludes the two classes.
result = A.authority_segments(sidecar)
result = A.authority_segments(sidecar, include=[A.NONFOUNDER_PASTED])   # explicit
result = A.authority_segments(sidecar, require_local_evidence=True)     # strictest

# 2. did he say this?  Scope to the corpus that governs.
v = A.verdict_for_quote(sidecar, sources, "No surface is off-limits because of a "
                        "name on a list",
                        item_ids=["FC-SEG-00", "FC-SEG-01", "FC-SEG-02", "FC-SEG-03"])
assert v["verdict"] == A.ADMITTED_FOUNDER
```

Scope quotation verdicts. An unscoped verdict is honest but pessimistic: it fails
closed on any sentence that also appears in an agent-authored projection, which in
this estate is 6 of 29 live citations.

Segments carry no text. To display one, resolve it against the pinned span base:

```python
seg = result["segments"][0]
rec = next(r for r in sidecar["items"] if r["item_id"] == seg["item_id"])
text = sources[rec["span_base"]["key"]][seg["char_start"]:seg["char_end"]]
assert A.sha256_text(text) == seg["text_sha256"]
```

Over the committed slice the three query modes return 73 segments by default, 86
with `NONFOUNDER_PASTED` opted in, and 33 under `require_local_evidence`. Those
numbers are the check that an integration is wired up correctly.

### Add a new index

One function, returning an `IndexView`. No other file changes, and nothing in the
classifier or the query layer needs to know the new shape.

```python
def adapter_conversation_store(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    payload = json.loads(raw.decode("utf-8"))
    items = [
        A.IndexItem(
            item_id=msg["id"],
            role=msg["role"],                  # recorded, never used to classify
            text=msg["content"],
            legacy={k: v for k, v in msg.items() if k != "content"},
            locator={"json_pointer": f"/messages/{i}"},
            resolver={"kind": "file"},         # or a new resolver kind
        )
        for i, msg in enumerate(payload["messages"])
    ]
    return A.IndexView(path, A.sha256_bytes(raw), len(raw), items,
                       notes="conversation store; one item per message")
```

If the new items are lifted out of a JSON array rather than being whole files, add
a resolver kind to `load_span_bases` and `span_base_key` so spans stay
recomputable. `adapter_founder_corpus` is the worked example.

### Add or change a signal

Append a `Signal` tuple to `SIGNALS`. It must declare `provenance` as one of
`FOUNDER_AUTHORED`, `EARNED` or `ASSISTANT_AUTHORED`, and a non-empty `basis`;
`test_every_signal_declares_its_rule_provenance` fails otherwise. A signal sees one
segment's structure-stripped text and nothing else, which is what keeps constraint
4 true. Add the fixture case in the same change, because
`findings/DEFECT-REPRODUCTION.md` is only worth anything while it is re-runnable.

### What a consumer must not do

* Do not write to the sidecar to record a decision. It is derived; rebuild it.
* Do not treat `FOUNDER_REPRESENTED` as a founder utterance.
* Do not use an unverified sidecar. `verify_sidecar` returning `[]` is the
  precondition for every other call.
* Do not read `UNRESOLVED_USER_ROLE` as "probably his". It means the evidence is
  absent, and the user role proves who typed it, not who authored it.
