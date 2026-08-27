#!/usr/bin/env python3
"""Lane D / Defect 1 — the quoted-other paragraph is not the founder's word.

## The defect, DIRECTLY_REPRODUCED

`provctl.py`'s `extract_segments` decides whether a `## Verbatim` block is
founder-authored by scanning the HEADING only (`_NOT_FOUNDER_MARKERS`, checked
against `current_heading.lower()`). A single heading can introduce a block
quotation that itself embeds someone else's words, mid-body, while the founder
explicitly disclaims them in the same breath:

    > DIRECT STANDING FOUNDER INSTRUCTION — I am Ahmed Sadek ...
    >
    > Here is what the vendor's assistant sent me, pasted below. I have not
    > agreed to it.
    >
    > VENDOR ASSISTANT RECOMMENDATION — Protected surfaces must never be
    > written to without owner approval, and every agent must request
    > approval before each push.
    >
    > I disagree with that and I am not adopting it.

The heading is "Verbatim — standing instruction, 2026-08-27". It carries none
of `_NOT_FOUNDER_MARKERS` ("advisory", "chatgpt advisory proposal",
"recommendation"), so the WHOLE block — including the embedded, explicitly
rejected vendor sentence — is classified `FOUNDER_DIRECT` /
`is_founder_corpus: true`. `_find_quote` then does a plain substring test
against that whole blob, so a register that cites the rejected vendor sentence
as a `FOUNDER_AUTHORED` quotation is certified. `check` prints `PASS`.

This is the same defect class the cohort exists to fix, one level down: not
"who typed the message" and not "whose git identity signed the commit," but
"which exact bytes are truly the founder's own words," inside a block that is
correctly attributed to him as a container while a paragraph inside it is not
his content.

## The mechanism change

Do not change segmentation, hashing or `verify-corpus` — those are relied on
elsewhere (existing corpus artifacts pin `founder_segment_count`,
`excluded_segment_count` and per-segment SHA-256 to the CURRENT segment
boundaries; re-segmenting at paragraph level would silently invalidate every
already-issued corpus file and is not this lane's call to make on a shared
artifact). Instead, narrow what `check`'s quote matcher is allowed to see:
before a founder-attributed segment's text is exposed to `_find_quote`, drop
any of its OWN paragraphs that themselves carry one of the same
`_NOT_FOUNDER_MARKERS` the heading check already trusts. A founder block can
correctly CONTAIN a quotation of someone else while none of that paragraph is
his authored content — this applies the heading rule one level deeper, using
the identical, already-founder-ratified marker set, at paragraph grain
instead of heading grain.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_provctl():
    repo_root = Path(__file__).resolve().parents[7]
    path = repo_root / "workstreams/so02/control-plane/operating-environment/w10-provenance/tools/provctl.py"
    spec = importlib.util.spec_from_file_location("provctl_canonical", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["provctl_canonical"] = module
    spec.loader.exec_module(module)
    return module


provctl = _load_provctl()


def founder_only_text(raw_text: str) -> str:
    """Drop any paragraph of a founder-attributed segment that itself quotes another speaker.

    Paragraphs are exactly the units `extract_segments` already joins with
    ``"\\n\\n"`` (a bare ``>`` line inside a blockquote is a paragraph break,
    not a segment break — see `provctl.extract_segments`). Reusing that same
    join point means this needs no new parser and cannot disagree with the
    extractor about where one paragraph ends and the next begins.
    """
    paragraphs = raw_text.split("\n\n")
    kept = [
        p for p in paragraphs
        if not any(marker in p.lower() for marker in provctl._NOT_FOUNDER_MARKERS)
    ]
    return "\n\n".join(kept)


def guarded_corpus_haystacks(corpus: dict) -> list[tuple[str, str]]:
    return [
        (s["heading"], provctl.normalise(founder_only_text(s["text"])))
        for s in corpus["segments"]
        if s["is_founder_corpus"]
    ]


def check_register_guarded(corpus: dict, register: dict, repo_root: str) -> list[str]:
    """Run the canonical `check_register`, but with paragraph-guarded haystacks.

    Monkeypatches `provctl._corpus_haystacks` for the duration of the call so
    every other rule in `check_register` (unclassified constraints, duplicate
    ids, disposition checks, evidence labels, ...) runs completely unchanged —
    only what counts as founder-matchable text is narrowed.
    """
    original = provctl._corpus_haystacks
    provctl._corpus_haystacks = guarded_corpus_haystacks
    try:
        return provctl.check_register(corpus, register, repo_root)
    finally:
        provctl._corpus_haystacks = original


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus")
    parser.add_argument("register")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    with open(args.corpus, encoding="utf-8") as fh:
        corpus = json.load(fh)
    with open(args.register, encoding="utf-8") as fh:
        register = json.load(fh)

    failures = check_register_guarded(corpus, register, args.repo_root)
    for f in failures:
        print(f"FAIL {f}")
    n = len(register.get("constraints", []))
    if failures:
        print(f"\nREFUSED: {len(failures)} failure(s) over {n} constraints")
        return 1
    print(f"PASS: {n} constraints, each classified, each citation checkable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
