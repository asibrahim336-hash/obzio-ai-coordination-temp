#!/usr/bin/env python3
"""provctl - founder-provenance classifier for constraints in force.

Standard library only. No network. Deterministic.

The founder's rule, quoted from
`workstreams/so02/control-plane/operating-environment/FOUNDER-STANDING-INSTRUCTION-20260822.md`:

    "Going forward: any lane proposing a constraint states its provenance class in
    the same breath. An unclassified constraint is not in force."

and

    "Git authorship is not founder authorship."  (.cursor/rules/00-founder-standing-authority.mdc)

This tool mechanises three things that prose cannot enforce:

  1. `build-corpus` extracts the verbatim founder segments from the durable
     founder record by section anchor and hashes each one. The corpus is derived
     by extraction, never retyped, because a retyped quotation is a paraphrase
     with extra steps.

  2. `check` refuses a register in which any constraint lacks a provenance class,
     or in which a FOUNDER_AUTHORED verdict carries a quotation that is not a
     literal substring of a corpus segment. That is the executable form of
     "Paraphrase does not qualify."

  3. `verify-corpus` recomputes the corpus from the source file and fails if a
     single byte moved, so a later edit to the founder record cannot silently
     revalidate a quotation that no longer exists.

Subcommands:
    build-corpus   SRC OUT          extract + hash verbatim founder segments
    verify-corpus  SRC CORPUS       recompute and compare, byte for byte
    check          CORPUS REGISTER  refuse an unclassified or unquoted constraint
    diff           PRIOR REGISTER   name every verdict that changed
    counts         REGISTER         class counts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata

# --------------------------------------------------------------------------
# Corpus extraction
# --------------------------------------------------------------------------

# Only these three classes exist. The founder named them; this tool does not
# invent a fourth, and `check` rejects anything outside the set.
CLASSES = ("FOUNDER_AUTHORED", "EARNED", "ASSISTANT_AUTHORED")

DISPOSITIONS = (
    "RETAIN_FOUNDER_AUTHORED",
    "RETAIN_EARNED",
    "PURGE",
    "SEEK_RATIFICATION",
)

# A `## Verbatim` heading in the founder record introduces a block quotation.
# The heading text decides whether the speaker is the founder or somebody the
# founder is quoting. `FOUNDER_QUOTING_OTHER` is the trap this lane exists to
# avoid: the ChatGPT advisory proposal sits under a `## Verbatim` heading in the
# same file as the founder's own words and carries none of his authority.
_HEADING = re.compile(r"^##+\s+(.*)$")
_QUOTE_LINE = re.compile(r"^>\s?(.*)$")
_NOT_FOUNDER_MARKERS = ("advisory", "chatgpt advisory proposal", "recommendation")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normalise(text: str) -> str:
    """Fold the typographic differences that make a true quotation look false.

    An em dash retyped as a hyphen, a curly apostrophe retyped as a straight
    one, or a line wrapped at a different column are transcription artefacts,
    not paraphrase. Folding them keeps the substring test honest about meaning
    while still refusing a genuine rewording.
    """
    text = unicodedata.normalize("NFKC", text)
    for src, dst in (
        ("\u2014", "-"), ("\u2013", "-"), ("\u2012", "-"), ("\u2010", "-"),
        ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
        ("\u00a0", " "),
    ):
        text = text.replace(src, dst)
    text = text.replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_segments(src_text: str) -> list[dict]:
    """Pull every block quotation that sits under a `## Verbatim` heading."""
    lines = src_text.split("\n")
    segments: list[dict] = []
    current_heading = None
    heading_line = 0
    buf: list[str] = []
    buf_start = 0

    def flush() -> None:
        nonlocal buf, buf_start
        if buf and current_heading is not None:
            body = "\n".join(buf).strip("\n")
            if body.strip():
                low = current_heading.lower()
                quoting_other = any(m in low for m in _NOT_FOUNDER_MARKERS)
                segments.append({
                    "heading": current_heading,
                    "speaker_class": (
                        "FOUNDER_QUOTING_OTHER" if quoting_other else "FOUNDER_DIRECT"
                    ),
                    "is_founder_corpus": not quoting_other,
                    "heading_line": heading_line,
                    "first_line": buf_start,
                    "last_line": buf_start + len(buf) - 1,
                    "text": body,
                    "sha256": sha256_bytes(body.encode("utf-8")),
                    "bytes": len(body.encode("utf-8")),
                })
        buf = []

    for idx, line in enumerate(lines, start=1):
        h = _HEADING.match(line)
        if h:
            flush()
            title = h.group(1).strip()
            if title.lower().startswith("verbatim"):
                current_heading = title
                heading_line = idx
            else:
                current_heading = None
            continue
        q = _QUOTE_LINE.match(line)
        if q and current_heading is not None:
            if not buf:
                buf_start = idx
            buf.append(q.group(1))
        elif buf and line.strip() == "":
            # A blank line inside a block quotation is written as a bare ">".
            # A truly blank line ends the quotation.
            flush()
    flush()
    return segments


def cmd_build_corpus(args: argparse.Namespace) -> int:
    with open(args.src, "rb") as fh:
        raw = fh.read()
    segments = extract_segments(raw.decode("utf-8"))
    founder = [s for s in segments if s["is_founder_corpus"]]
    excluded = [s for s in segments if not s["is_founder_corpus"]]
    corpus = {
        "artifact_id": args.artifact_id,
        "lane": "OE-W10-PROVENANCE-REDERIVATION",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "decision_changed": [],
        "is_a_proposal_not_a_binding": True,
        "governs": (
            "The set of founder utterances against which a FOUNDER_AUTHORED "
            "provenance verdict may be tested. Nothing outside this set is "
            "founder text for the purpose of classification."
        ),
        "extraction_method": (
            "Segments are extracted from the source file by section anchor and "
            "hashed. They are never retyped. A retyped quotation is a paraphrase "
            "with extra steps, and paraphrase is the defect this lane exists to fix."
        ),
        "source": {
            "path": args.src,
            "sha256": sha256_bytes(raw),
            "bytes": len(raw),
        },
        "founder_segment_count": len(founder),
        "excluded_segment_count": len(excluded),
        "segments": segments,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"corpus written: {args.out}")
    print(f"  founder segments : {len(founder)}")
    print(f"  excluded segments: {len(excluded)}")
    for s in segments:
        flag = "FOUNDER" if s["is_founder_corpus"] else "EXCLUDED"
        print(f"  [{flag}] L{s['first_line']}-{s['last_line']} "
              f"{s['bytes']:>6}B {s['sha256'][:12]} {s['heading'][:58]}")
    return 0


def cmd_verify_corpus(args: argparse.Namespace) -> int:
    with open(args.src, "rb") as fh:
        raw = fh.read()
    corpus = _load(args.corpus)
    failures: list[str] = []
    if corpus["source"]["sha256"] != sha256_bytes(raw):
        failures.append(
            "SOURCE_CHANGED: the founder record no longer hashes to the value "
            "the corpus was built from. Every quotation in the register is "
            "unverified until the corpus is rebuilt."
        )
    fresh = extract_segments(raw.decode("utf-8"))
    if len(fresh) != len(corpus["segments"]):
        failures.append(
            f"SEGMENT_COUNT_CHANGED: {len(corpus['segments'])} -> {len(fresh)}"
        )
    for old, new in zip(corpus["segments"], fresh):
        if old["sha256"] != new["sha256"]:
            failures.append(f"SEGMENT_CHANGED: {old['heading']}")
        if old["is_founder_corpus"] != new["is_founder_corpus"]:
            failures.append(f"SPEAKER_CLASS_CHANGED: {old['heading']}")
    for f in failures:
        print(f"FAIL {f}")
    if failures:
        return 1
    print(f"corpus verified: {len(fresh)} segments recomputed byte-identical")
    return 0


# --------------------------------------------------------------------------
# Register checking
# --------------------------------------------------------------------------

def _corpus_haystacks(corpus: dict) -> list[tuple[str, str]]:
    return [
        (s["heading"], normalise(s["text"]))
        for s in corpus["segments"]
        if s["is_founder_corpus"]
    ]


# Every field in this map holds founder words and is substring-checked against the
# corpus exactly as a FOUNDER_AUTHORED quotation is. A quote that voids a
# constraint has to be as real as a quote that authors one.
SINGLE_QUOTE_FIELDS = (
    "founder_ratification_quote",
    "founder_void_quote",
    "founder_contradiction_quote",
)


def _find_quote(haystacks: list[tuple[str, str]], quote: str) -> list[str]:
    text = normalise(quote)
    if not text:
        return []
    return [h for h, hay in haystacks if text in hay]


def check_register(corpus: dict, register: dict, repo_root: str) -> list[str]:
    failures: list[str] = []
    haystacks = _corpus_haystacks(corpus)
    seen: set[str] = set()

    for c in register.get("constraints", []):
        cid = c.get("constraint_id", "<no id>")
        for field in SINGLE_QUOTE_FIELDS:
            q = c.get(field)
            if q is None:
                continue
            if not _find_quote(haystacks, q):
                failures.append(
                    f"{cid}: {field.upper()}_NOT_IN_CORPUS - {q[:70]!r} appears "
                    f"in no founder segment"
                )

    for c in register.get("constraints", []):
        cid = c.get("constraint_id", "<no id>")
        if cid in seen:
            failures.append(f"{cid}: DUPLICATE_CONSTRAINT_ID")
        seen.add(cid)

        # "An unclassified constraint is not in force."
        klass = c.get("provenance_class")
        if klass is None:
            failures.append(f"{cid}: UNCLASSIFIED - not in force")
            continue
        if klass not in CLASSES:
            failures.append(f"{cid}: UNKNOWN_CLASS {klass!r}")
            continue
        if not c.get("statement"):
            failures.append(f"{cid}: NO_STATEMENT")
        disp = c.get("recommended_disposition")
        if disp not in DISPOSITIONS:
            failures.append(f"{cid}: BAD_DISPOSITION {disp!r}")

        if klass == "FOUNDER_AUTHORED":
            quotes = c.get("founder_quotations") or []
            if not quotes:
                failures.append(
                    f"{cid}: FOUNDER_AUTHORED_WITHOUT_QUOTATION - this is the "
                    f"defect the lane exists to fix"
                )
            for q in quotes:
                if not normalise(q.get("quote", "")):
                    failures.append(f"{cid}: EMPTY_QUOTATION")
                    continue
                where = _find_quote(haystacks, q.get("quote", ""))
                if not where:
                    failures.append(
                        f"{cid}: QUOTATION_NOT_IN_CORPUS - "
                        f"{q.get('quote','')[:70]!r} appears in no founder "
                        f"segment. Paraphrase does not qualify."
                    )
                elif q.get("segment_heading") and q["segment_heading"] not in where:
                    failures.append(
                        f"{cid}: QUOTATION_SEGMENT_MISMATCH - cited "
                        f"{q['segment_heading']!r}, found in {where}"
                    )
            if disp != "RETAIN_FOUNDER_AUTHORED":
                failures.append(f"{cid}: FOUNDER_AUTHORED must retain, got {disp!r}")

        elif klass == "EARNED":
            if not c.get("defect_caught"):
                failures.append(f"{cid}: EARNED_WITHOUT_NAMED_DEFECT")
            paths = c.get("defect_evidence_paths") or []
            if not paths:
                failures.append(f"{cid}: EARNED_WITHOUT_RECEIPT")
            for p in paths:
                if not os.path.exists(os.path.join(repo_root, p)):
                    failures.append(f"{cid}: DEFECT_RECEIPT_MISSING {p}")
            if disp != "RETAIN_EARNED":
                failures.append(f"{cid}: EARNED must retain, got {disp!r}")

        else:  # ASSISTANT_AUTHORED
            if not c.get("what_it_constrains"):
                failures.append(f"{cid}: ASSISTANT_AUTHORED_WITHOUT_CONSTRAINT_SCOPE")
            if not c.get("removal_unlocks"):
                failures.append(f"{cid}: ASSISTANT_AUTHORED_WITHOUT_UNLOCK")
            if disp not in ("PURGE", "SEEK_RATIFICATION"):
                failures.append(
                    f"{cid}: ASSISTANT_AUTHORED is void unless ratified; "
                    f"disposition must be PURGE or SEEK_RATIFICATION, got {disp!r}"
                )
            if c.get("founder_quotations"):
                failures.append(
                    f"{cid}: ASSISTANT_AUTHORED_WITH_FOUNDER_QUOTATION - if it is "
                    f"quotable it is not in this class"
                )
            # "Void unless I ratify it." A ratification request the founder cannot
            # answer in one word is a reading assignment, which the estate's
            # conflict rule already forbids.
            if disp == "SEEK_RATIFICATION" and not c.get("ratification_question"):
                failures.append(f"{cid}: SEEK_RATIFICATION_WITHOUT_BINARY_QUESTION")
            if disp == "PURGE" and c.get("ratification_question"):
                failures.append(f"{cid}: PURGE_WITH_RATIFICATION_QUESTION")

        if c.get("evidence_label") not in ("DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS"):
            failures.append(f"{cid}: BAD_EVIDENCE_LABEL {c.get('evidence_label')!r}")

    declared = register.get("counts", {})
    actual: dict[str, int] = {k: 0 for k in CLASSES}
    for c in register.get("constraints", []):
        k = c.get("provenance_class")
        if k in actual:
            actual[k] += 1
    if declared and declared != actual:
        failures.append(f"COUNTS_MISMATCH declared={declared} actual={actual}")
    total = register.get("total_classified")
    if total is not None and total != len(register.get("constraints", [])):
        failures.append(
            f"TOTAL_MISMATCH declared={total} actual={len(register.get('constraints', []))}"
        )
    return failures


def cmd_check(args: argparse.Namespace) -> int:
    corpus = _load(args.corpus)
    register = _load(args.register)
    failures = check_register(corpus, register, args.repo_root)
    for f in failures:
        print(f"FAIL {f}")
    n = len(register.get("constraints", []))
    if failures:
        print(f"\nREFUSED: {len(failures)} failure(s) over {n} constraints")
        return 1
    print(f"PASS: {n} constraints, each classified, each citation checkable")
    return 0


# --------------------------------------------------------------------------
# Diff against the prior classification
# --------------------------------------------------------------------------

# The prior lane's class names map onto the founder's three classes one to one.
PRIOR_TO_NEW = {
    "FOUNDER_BOUND": "FOUNDER_AUTHORED",
    "EARNED_CONTROL": "EARNED",
    "ASSISTANT_IMPOSED": "ASSISTANT_AUTHORED",
}


def cmd_diff(args: argparse.Namespace) -> int:
    prior = _load(args.prior)
    new = _load(args.register)
    prior_by_id = {c["constraint_id"]: c for c in prior.get("constraints", [])}
    new_by_id = {c["constraint_id"]: c for c in new.get("constraints", [])}

    changed, unchanged, added, dropped, restated = [], [], [], [], []
    for cid, pc in prior_by_id.items():
        nc = new_by_id.get(cid)
        if nc is None:
            dropped.append(cid)
            continue
        was = PRIOR_TO_NEW.get(pc.get("verdict"), pc.get("verdict"))
        now = nc.get("provenance_class")
        if was != now:
            changed.append((cid, was, now))
        else:
            unchanged.append((cid, was, now))
            # A class that survives while the constraint's text is rewritten is
            # still a changed verdict. Reporting only class movement would hide
            # every constraint narrowed to the width its quotation supports.
            if nc.get("restated"):
                restated.append((cid, now))
    for cid in new_by_id:
        if cid not in prior_by_id:
            added.append(cid)

    print(f"prior constraints        : {len(prior_by_id)}")
    print(f"new constraints          : {len(new_by_id)}")
    print(f"class changed            : {len(changed)}")
    print(f"class held, text restated: {len(restated)}")
    print(f"wholly unchanged         : {len(unchanged) - len(restated)}")
    print(f"added by this lane       : {len(added)}")
    if dropped:
        print(f"dropped                  : {dropped}")
    print("\n-- class changed --")
    for cid, was, now in sorted(changed):
        print(f"  {cid:<6} {was:<18} -> {now}")
    print("\n-- class held, restated to the width the evidence supports --")
    for cid, now in sorted(restated):
        print(f"  {cid:<6} {now}")
    if added:
        print("\n-- added (founder-authored constraints no prior entry captured) --")
        for cid in sorted(added):
            print(f"  {cid}")
    return 0


def cmd_counts(args: argparse.Namespace) -> int:
    reg = _load(args.register)
    tally: dict[str, int] = {}
    disp: dict[str, int] = {}
    for c in reg.get("constraints", []):
        tally[c.get("provenance_class")] = tally.get(c.get("provenance_class"), 0) + 1
        d = c.get("recommended_disposition")
        disp[d] = disp.get(d, 0) + 1
    print(json.dumps({"by_class": tally, "by_disposition": disp,
                      "total": len(reg.get("constraints", []))}, indent=2,
                     sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="provctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-corpus")
    b.add_argument("src")
    b.add_argument("out")
    b.add_argument("--artifact-id", default="OE-W10-FOUNDER-CORPUS-20260823-v001")
    b.set_defaults(fn=cmd_build_corpus)

    v = sub.add_parser("verify-corpus")
    v.add_argument("src")
    v.add_argument("corpus")
    v.set_defaults(fn=cmd_verify_corpus)

    c = sub.add_parser("check")
    c.add_argument("corpus")
    c.add_argument("register")
    c.add_argument("--repo-root", default=".")
    c.set_defaults(fn=cmd_check)

    d = sub.add_parser("diff")
    d.add_argument("prior")
    d.add_argument("register")
    d.set_defaults(fn=cmd_diff)

    n = sub.add_parser("counts")
    n.add_argument("register")
    n.set_defaults(fn=cmd_counts)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
