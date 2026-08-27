#!/usr/bin/env python3
"""Authorship sidecar — a non-destructive query layer over the authority index.

Standard library only. Runs under `python3 -I`.

## What this is

A *sidecar*. It holds no authority content of its own. Every record is a set of
classified character spans pinned to the sha256 of the artifact those spans index.
Resolving a span requires the pinned artifact and fails closed if the artifact has
changed. That is deliberate: an authorship layer that copies the text becomes a
second index, drifts from the first, and the estate then has two answers to the
same question.

## The defect this exists to defeat

Ahmed Sadek, standing amendment 2026-08-23, FOUNDER_AUTHORED:

    "Git authorship is not founder authorship."
    "The correct signal is a quoted founder utterance, not a commit header."

The estate's own record names the mechanism one level deeper: the prior
classifier reached FOUNDER verdicts from *position* (a block quotation sitting
under a heading whose title began "Verbatim") and from *exact substring match*
(a quotation counted as verified because it appeared literally somewhere inside a
segment already marked founder). Both were reproduced against
`w10-provenance/tools/provctl.py` at integration commit
7f29043eece45f42f018d841718a257cfd18739b; see
`findings/DEFECT-REPRODUCTION.md`.

So this module holds two hard invariants, both EARNED (each names that defect):

* **Position is inert.** No positional fact — role field, heading text, quote
  depth, file name, ordinal, git author — may raise a segment above
  `UNRESOLVED_USER_ROLE`. Position may only *bound* the scope in which textual
  evidence applies.
* **A substring match is a locator, not a verdict.** `locate_quote` reports which
  segment a quotation lands in; the verdict is that segment's class. A hit inside
  `NONFOUNDER_PASTED` refuses.

## Segmentation granularity

Classification happens *below* message granularity. A single user-role message
routinely carries the founder's own words and third-party material pasted into
it; one class per message is the defect, not a simplification of it. Segments are
paragraph-scale and their offsets are recomputable from the pinned source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from typing import Any, Iterable, Sequence

SIDECAR_SCHEMA = "authorship-sidecar/1.0"

# --------------------------------------------------------------------------
# Authorship classes
# --------------------------------------------------------------------------

FOUNDER_DIRECT = "FOUNDER_DIRECT"
FOUNDER_ADOPTED = "FOUNDER_ADOPTED"
FOUNDER_REPRESENTED = "FOUNDER_REPRESENTED"
NONFOUNDER_PASTED = "NONFOUNDER_PASTED"
UNRESOLVED_USER_ROLE = "UNRESOLVED_USER_ROLE"

CLASSES = (
    FOUNDER_DIRECT,
    FOUNDER_ADOPTED,
    FOUNDER_REPRESENTED,
    NONFOUNDER_PASTED,
    UNRESOLVED_USER_ROLE,
)

CLASS_MEANING = {
    FOUNDER_DIRECT: "the founder's own words, first-hand",
    FOUNDER_ADOPTED: "material he explicitly took as his own",
    FOUNDER_REPRESENTED: "an agent speaking for him",
    NONFOUNDER_PASTED: "third-party content pasted into a founder-authored message",
    UNRESOLVED_USER_ROLE: (
        "authorship not determinable from evidence in scope; the user role proves "
        "who typed it, not who authored it"
    ),
}

#: Default authority queries exclude these two. Opting either in is an explicit
#: act by the caller and is recorded in the query result.
DEFAULT_EXCLUDED = frozenset({NONFOUNDER_PASTED, UNRESOLVED_USER_ROLE})

LOCAL_EVIDENCE = "LOCAL_EVIDENCE"
SCOPE_INHERITED = "SCOPE_INHERITED"
NO_EVIDENCE = "NO_EVIDENCE"


# --------------------------------------------------------------------------
# Hashing and normalisation
# --------------------------------------------------------------------------

def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def bundle_sha256(entries: Sequence[dict]) -> str:
    """The estate's manifest-closure hash: sha256 of canonical json of entries."""
    return sha256_text(canonical_json(list(entries)))


def normalise(text: str) -> str:
    """Fold case, whitespace, dashes, quotes and markdown emphasis for *matching only*.

    Never used to rewrite stored content. Offsets and hashes always refer to the
    unmodified source bytes.

    The emphasis fold is deliberate parity with `w10-provenance/tools/provctl.py`.
    Without it, a register citation of a sentence the founder wrote with a bolded
    word inside it reads as absent, and this lane would report a false
    disagreement with the register — a defect this lane hit and corrected in
    development rather than shipping.
    """
    text = unicodedata.normalize("NFKC", text)
    for src, dst in (
        ("\u2014", "-"), ("\u2013", "-"), ("\u2012", "-"), ("\u2010", "-"),
        ("\u2212", "-"),
        ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
        ("\u00a0", " "),
    ):
        text = text.replace(src, dst)
    text = text.replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", text).strip().lower()


# --------------------------------------------------------------------------
# Evidence signals
#
# Every signal is textual. None of them reads a role field, a heading, a path or
# a commit. `provenance` is the provenance class of the *rule*, per the standing
# discipline: an unclassified constraint is not in force.
# --------------------------------------------------------------------------

class Signal:
    __slots__ = ("name", "kind", "strength", "pattern", "provenance", "basis")

    def __init__(self, name: str, kind: str, strength: str, pattern: str,
                 provenance: str, basis: str) -> None:
        self.name = name
        self.kind = kind
        self.strength = strength
        self.pattern = re.compile(pattern)
        self.provenance = provenance
        self.basis = basis


SELF_ID = "SELF_ID"
ATTRIBUTION = "ATTRIBUTION"
ADOPTION = "ADOPTION"
REPRESENTATION = "REPRESENTATION"
DISAVOWAL = "DISAVOWAL"
RESUMPTION = "RESUMPTION"

STRONG = "STRONG"
WEAK = "WEAK"

_FQ = "FOUNDER_AUTHORED"
_EARNED = "EARNED"
_ASSIST = "ASSISTANT_AUTHORED"

SIGNALS: tuple[Signal, ...] = (
    # ---- the founder speaking as himself -------------------------------
    Signal(
        "FOUNDER_SELF_IDENTIFICATION", SELF_ID, STRONG,
        r"\bi am ahmed(?: sadek)?\b|\bi,? ahmed sadek\b"
        r"|\bfounder of obzio, speaking directly\b"
        r"|\bdirect standing founder instruction\b"
        r"|\bfounder clarification\b",
        _FQ,
        "He identifies himself in the text: 'I am Ahmed Sadek, founder of Obzio, "
        "speaking directly and exercising founder authority.'",
    ),
    Signal(
        "FOUNDER_FIRST_PERSON_AUTHORITY", SELF_ID, STRONG,
        r"\bunder my authority\b|\bmy founder-established intent\b"
        r"|\bexercising founder authority\b"
        r"|\bi never designated\b|\bi never issued\b|\bi am removing\b"
        r"|\bi directly amend\b|\byou do not need my permission\b"
        r"|\buntil i (?:directly )?amend\b|\bi am not asking for\b"
        r"|\bi ratify\b|\bmy controlling instruction\b|\bi expect\b"
        r"|\bmy (?:ruling|decision) is\b",
        _FQ,
        "First-person possession of the authority itself, e.g. 'Every surface in "
        "the Ahmed/Obzio-controlled estate is writable under my authority'.",
    ),
    Signal(
        "FOUNDER_FIRST_PERSON_DIRECTIVE", SELF_ID, WEAK,
        r"\bi (?:want|need|require|instruct|direct|disagree|decide|rule)\b"
        r"|\bmy (?:instruction|intent|words|message|plan|amendment|authority)\b"
        r"|\bapply this test\b|\bstop reporting\b",
        _ASSIST,
        "First-person directive language. Weak: an agent drafting on his behalf "
        "writes the same sentences, which is how the protected-surface label was "
        "mis-certified. Never sufficient alone.",
    ),

    # ---- third-party material pasted in --------------------------------
    Signal(
        "THIRD_PARTY_SPEECH_ACT_ATTRIBUTION", ATTRIBUTION, STRONG,
        r"\bthis is (?:[a-z0-9 .'\-]{1,40}?)'s (?:recommendation|proposal|words|text"
        r"|analysis|summary|answer|reply|advice|opinion|view|position)\b"
        r"|\b(?:chatgpt|claude|gemini|gpt|the (?:vendor|provider|assistant|model)|"
        r"[a-z]+)'s (?:recommendation|proposal|advisory) (?:is|was|follows|below)\b"
        r"|\b(?:advisory proposal|advisory recommendation)\b"
        r"|\b(?:recommendation|proposal|assessment|summary) from (?:chatgpt|claude|"
        r"gemini|the vendor|the provider|support|legal|counsel)\b"
        r"|\bnot a founder ruling\b",
        _FQ,
        "He labels the material as another speaker's: 'This is ChatGPT's "
        "recommendation, not a founder ruling or a replacement for Ahmed's "
        "established intent.'",
    ),
    Signal(
        "PASTE_MARKER", ATTRIBUTION, STRONG,
        r"\b(?:pasted|copied|quoting|forwarded|reproduced) (?:below|here|from|verbatim)\b"
        r"|\bhere(?:'s| is| are)? what (?:[a-z0-9 .'\-]{1,40}) (?:sent|said|wrote|replied)\b"
        r"|\bbegin (?:quote|paste)\b|\bend (?:quote|paste)\b"
        r"|\b(?:from|per) the (?:docs|documentation|vendor|provider|support ticket)\b"
        r"|^\s*[a-z0-9 .'\-]{2,40} (?:said|says|wrote|writes|replied|reports):",
        _EARNED,
        "Names the defect: a pasted block inside a user-role message was counted as "
        "founder text because the message was in the user role. Reproduced against "
        "provctl.py, findings/DEFECT-REPRODUCTION.md.",
    ),
    Signal(
        "FOREIGN_SPEAKER_BANNER", ATTRIBUTION, STRONG,
        r"^\s*(?:chatgpt|claude|gemini|gpt|openai|anthropic|vendor|provider|support|"
        r"legal|counsel|[a-z]+ assistant)\b[^.\n]{0,60}"
        r"(?:advisory|recommendation|proposal|response|output|draft|note)\b",
        _EARNED,
        "Same defect. A banner line naming a foreign speaker opens a pasted block; "
        "'CHATGPT ADVISORY PROPOSAL' is the real instance in this estate's record.",
    ),

    # ---- the founder taking other material as his own ------------------
    Signal(
        "EXPLICIT_ADOPTION_OF_OTHER_MATERIAL", ADOPTION, STRONG,
        r"\bi adopt\b|\bi am adopting\b|\bi take (?:this|the following|that) as my own\b"
        r"|\btreat (?:this|the following|it) as (?:my|mine)\b"
        r"|\bconsider (?:this|the following) my (?:instruction|words|ruling)\b"
        r"|\bi ratify (?:this|the following|that)\b"
        r"|\b(?:this|that|the following) (?:fully )?aligns with my founder-established intent\b"
        r"|\bauthored under my direct instruction\b"
        r"|\b(?:instruments|manifests|mandates)[^.\n]{0,80}\bi (?:have )?commissioned\b"
        r"|\bare first-class founder material\b"
        r"|\badopted deliberately\b|\bi approve (?:this|the following) as my own\b",
        _FQ,
        "He states the adoption: 'Instruments authored under my direct instruction "
        "- including operating mandates, manifests, evidence and harness "
        "definitions I have commissioned - are first-class founder material.'",
    ),
    Signal(
        "EXPLICIT_DISAVOWAL", DISAVOWAL, STRONG,
        r"\bi (?:have )?not (?:agreed|adopted|approved|ratified)\b"
        r"|\bi (?:do not|don't) adopt\b|\bi am not adopting\b"
        r"|\bi disagree with (?:that|this|it)\b"
        r"|\bnot a (?:founder ruling|replacement for)\b"
        r"|\brecorded as advisory only\b|\badvisory only\b"
        r"|\bvoid unless (?:i|he|the founder) ratif",
        _FQ,
        "He states the refusal: 'This is ChatGPT's recommendation, not a founder "
        "ruling or a replacement for Ahmed's established intent.' A disavowal "
        "defeats an adoption marker in the same scope.",
    ),
    Signal(
        "FOUNDER_RESUMPTION", RESUMPTION, STRONG,
        r"\bi disagree with that\b|\bback to my (?:own )?words\b"
        r"|\bmy (?:answer|ruling|decision) (?:is|follows)\b"
        r"|\bend of (?:the )?paste\b|\bthat was (?:their|his|her|its) text\b",
        _EARNED,
        "Closes a pasted scope so the founder's own following words are not swept "
        "into it. Without it the safe-direction bias would over-suppress.",
    ),

    # ---- an agent speaking for the founder -----------------------------
    Signal(
        "AGENT_SPEAKING_FOR_FOUNDER", REPRESENTATION, STRONG,
        r"\bon (?:the founder's|ahmed's|his) behalf\b"
        r"|\bspeaking for (?:the founder|ahmed)\b"
        r"|\b(?:the founder|ahmed) (?:asked|instructed|stated|ruled|labelled|labeled|"
        r"identifies|identified|says|said|wants|requires|amended|confirmed) (?:that )?\b"
        r"|\b(?:the founder's|ahmed's) (?:claim|words|intent|instruction|amendment|"
        r"authority|record|message|standing)\b"
        r"|\brecorded by\b|\bthis rule is prepended\b"
        r"|\bassistant-authored summary of his authority\b"
        r"|\bhe (?:amends|supersedes|ratifies|directly amends)\b"
        r"|\bfounder-authored\b.{0,40}\bin his own words\b",
        _EARNED,
        "Names the defect: FOUNDER-AUTHORITY-20260822T2225Z.json was an "
        "assistant-authored summary of his authority treated as his authority. "
        "Third-person reference to the founder is an agent's voice, not his.",
    ),
    Signal(
        "RECORDER_METADATA_LABEL", REPRESENTATION, STRONG,
        # `normalise` strips markdown emphasis before matching, so the pattern is
        # written against the folded text: `**Speaker:**` arrives as `speaker:`.
        r"^\s*(?:speaker|recorded|recorded by|status|authority_basis|standing|"
        r"always-applied projection|decision_changed|verdict|evidence_label)\s*:",
        _EARNED,
        "A field label asserting who spoke is the recorder's assertion, not the "
        "speaker's utterance. Trusting it is the positional error one step removed.",
    ),
)


# --------------------------------------------------------------------------
# Segmentation
# --------------------------------------------------------------------------

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
_QUOTE_PREFIX = re.compile(r"^((?:\s{0,3}>\s?)+)")


def _quote_depth(line: str) -> tuple[int, str]:
    """Return (blockquote depth, line with quote markers stripped)."""
    depth = 0
    rest = line
    while True:
        m = re.match(r"^\s{0,3}>\s?", rest)
        if not m:
            break
        depth += 1
        rest = rest[m.end():]
    return depth, rest


class Segment:
    __slots__ = ("ordinal", "char_start", "char_end", "line_start", "line_end",
                 "text", "quote_depth", "kind", "scope_id")

    def __init__(self, ordinal: int, char_start: int, char_end: int,
                 line_start: int, line_end: int, text: str, quote_depth: int,
                 kind: str, scope_id: int) -> None:
        self.ordinal = ordinal
        self.char_start = char_start
        self.char_end = char_end
        self.line_start = line_start
        self.line_end = line_end
        self.text = text
        self.quote_depth = quote_depth
        self.kind = kind
        self.scope_id = scope_id


def segment_text(text: str) -> list[Segment]:
    """Split one item's text into paragraph-scale segments with exact offsets.

    Segment boundaries: markdown headings (own segment), horizontal rules (own
    segment), fenced blocks (atomic), blank lines, and any change of blockquote
    depth.

    *Scope* boundaries, which bound how far textual evidence propagates, are
    coarser: a level-1 heading, a horizontal rule, or a change of blockquote
    depth. Sub-headings do not reset scope, because one founder utterance
    routinely carries its own `##` subheads and resetting at each of them
    discards his authorship three sentences after he asserted it. A change of
    blockquote depth does reset, which is what keeps an assistant's unquoted
    commentary from inheriting the authorship of the quotation above it.

    Structure decides *where* a boundary falls and how far evidence carries. It
    never decides authorship: see `classify_segments`, where every class comes
    from a textual signal.
    """
    if not text:
        return []
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    segments: list[Segment] = []
    buf: list[tuple[int, str]] = []  # (line index, raw line)
    buf_depth = 0
    buf_kind = "prose"
    scope_id = 0
    in_fence = False

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        if any(raw.strip() for _, raw in buf):
            first_i, _ = buf[0]
            last_i, last_raw = buf[-1]
            char_start = offsets[first_i]
            char_end = offsets[last_i] + len(last_raw)
            segments.append(Segment(
                ordinal=len(segments),
                char_start=char_start,
                char_end=char_end,
                line_start=first_i + 1,
                line_end=last_i + 1,
                text=text[char_start:char_end],
                quote_depth=buf_depth,
                kind=buf_kind,
                scope_id=scope_id,
            ))
        buf = []

    for i, raw in enumerate(lines):
        depth, body = _quote_depth(raw)

        if in_fence:
            buf.append((i, raw))
            if _FENCE.match(body):
                in_fence = False
                flush()
            continue

        if _FENCE.match(body):
            flush()
            buf_depth, buf_kind = depth, "fence"
            buf.append((i, raw))
            in_fence = True
            continue

        if not body.strip():
            # A bare ">" continues a block quotation; a truly empty line ends a
            # paragraph. Either way the paragraph boundary is here.
            flush()
            continue

        heading = _HEADING.match(body)
        if heading:
            flush()
            if len(heading.group(1)) == 1 or depth != buf_depth:
                scope_id += 1
            buf_depth, buf_kind = depth, "heading"
            buf.append((i, raw))
            flush()
            continue

        if _HR.match(body):
            flush()
            scope_id += 1
            buf_depth, buf_kind = depth, "rule"
            buf.append((i, raw))
            flush()
            continue

        if buf and depth != buf_depth:
            flush()

        if depth != buf_depth and (segments or buf):
            scope_id += 1

        if not buf:
            buf_depth, buf_kind = depth, "prose"
        buf.append((i, raw))

    flush()
    return segments


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def detect_signals(segment_body: str) -> list[dict]:
    """Every textual signal firing in one segment, with the matched span."""
    hay = normalise(segment_body)
    found: list[dict] = []
    for sig in SIGNALS:
        for m in sig.pattern.finditer(hay):
            found.append({
                "signal": sig.name,
                "kind": sig.kind,
                "strength": sig.strength,
                "matched": m.group(0)[:160],
                "match_span_in_normalised_text": [m.start(), m.end()],
                "rule_provenance": sig.provenance,
            })
            break  # one hit per signal is enough; the count is not evidence
    return found


def _strip_structure(segment_text_raw: str) -> str:
    """Remove blockquote markers and heading hashes for signal matching.

    Structural characters are stripped so that the *same* sentence classifies the
    same way whether or not somebody wrapped it in a block quotation. Position
    must not change the verdict.
    """
    out = []
    for line in segment_text_raw.split("\n"):
        _, body = _quote_depth(line)
        h = _HEADING.match(body)
        if h:
            body = h.group(2)
        out.append(body)
    return "\n".join(out)


class Classified:
    __slots__ = ("segment", "authorship_class", "confidence", "signals",
                 "decision_basis", "inherited_from")

    def __init__(self, segment: Segment, authorship_class: str, confidence: str,
                 signals: list[dict], decision_basis: str,
                 inherited_from: int | None) -> None:
        self.segment = segment
        self.authorship_class = authorship_class
        self.confidence = confidence
        self.signals = signals
        self.decision_basis = decision_basis
        self.inherited_from = inherited_from


def _kinds(signals: Iterable[dict], kind: str, strength: str | None = None) -> list[dict]:
    return [s for s in signals
            if s["kind"] == kind and (strength is None or s["strength"] == strength)]


def classify_segments(segments: Sequence[Segment]) -> list[Classified]:
    """Assign one of the five classes to each segment from textual evidence.

    Precedence inside a segment, highest first:

    1. STRONG attribution, unless a STRONG adoption also fires and no disavowal
       does -> then FOUNDER_ADOPTED. Adoption is how `FOUNDER_ADOPTED` arises at
       all: the class belongs to the adopted *material*, not to his sentence
       about adopting it.
    2. STRONG attribution                    -> NONFOUNDER_PASTED
    3. STRONG representation                 -> FOUNDER_REPRESENTED
    4. STRONG self-identification            -> FOUNDER_DIRECT
    5. inherited class from the nearest preceding segment in the same scope that
       had local evidence                    -> that class, confidence
                                                SCOPE_INHERITED
    6. nothing                               -> UNRESOLVED_USER_ROLE

    Two asymmetries, both EARNED, both naming the reproduced misattribution:

    * Representation outranks self-identification. A paragraph that both refers to
      the founder in the third person and uses first-person directive language is
      an agent drafting in his voice, which is precisely how the
      protected-surface constraint acquired a FOUNDER_BOUND verdict.
    * Attribution inheritance outranks self-identification inheritance. Once a
      pasted scope opens it stays open until the scope ends or a resumption
      marker fires. Misreading pasted material as founder material caused real
      damage in this estate; the reverse error only under-claims authority.
    """
    out: list[Classified] = []
    # scope_id -> (class, ordinal) of the last locally determined segment
    inherit: dict[int, tuple[str, int]] = {}

    for seg in segments:
        body = _strip_structure(seg.text)
        signals = detect_signals(body)

        attribution = _kinds(signals, ATTRIBUTION, STRONG)
        adoption = _kinds(signals, ADOPTION, STRONG)
        representation = _kinds(signals, REPRESENTATION, STRONG)
        self_id = _kinds(signals, SELF_ID, STRONG)
        disavowal = _kinds(signals, DISAVOWAL, STRONG)
        resumption = _kinds(signals, RESUMPTION, STRONG)

        cls: str | None = None
        confidence = LOCAL_EVIDENCE
        basis = ""
        inherited_from: int | None = None

        if attribution and adoption and not disavowal:
            cls = FOUNDER_ADOPTED
            basis = (
                "third-party material carrying an explicit founder adoption and no "
                f"disavowal: {attribution[0]['signal']} + {adoption[0]['signal']}"
            )
        elif attribution:
            cls = NONFOUNDER_PASTED
            basis = f"third-party attribution in the text: {attribution[0]['signal']}"
            if disavowal:
                basis += f"; disavowed: {disavowal[0]['signal']}"
        elif representation:
            cls = FOUNDER_REPRESENTED
            basis = (
                "an agent refers to the founder in the third person or asserts a "
                f"speaker label: {representation[0]['signal']}"
            )
        elif self_id:
            cls = FOUNDER_DIRECT
            basis = f"first-hand founder self-identification: {self_id[0]['signal']}"

        if cls is not None:
            # An adoption marker inside founder-direct speech is recorded, but the
            # segment stays FOUNDER_DIRECT: his sentence about adopting material
            # is his own words, and the adopted material is elsewhere.
            if cls == FOUNDER_DIRECT and adoption:
                basis += "; carries an adoption marker whose referent is other material"
            inherit[seg.scope_id] = (cls, seg.ordinal)
        else:
            prior = inherit.get(seg.scope_id)
            if prior is not None and prior[0] in (
                FOUNDER_DIRECT, FOUNDER_ADOPTED, NONFOUNDER_PASTED
            ):
                if prior[0] == NONFOUNDER_PASTED and resumption:
                    cls = UNRESOLVED_USER_ROLE
                    confidence = NO_EVIDENCE
                    basis = (
                        "a resumption marker closed the pasted scope and no founder "
                        "evidence fires locally; unresolved rather than assumed"
                    )
                    inherit.pop(seg.scope_id, None)
                else:
                    cls = prior[0]
                    confidence = SCOPE_INHERITED
                    inherited_from = prior[1]
                    basis = (
                        f"inherited from segment {prior[1]} in the same structural "
                        f"scope, which carried local evidence for {prior[0]}"
                    )
            else:
                cls = UNRESOLVED_USER_ROLE
                confidence = NO_EVIDENCE
                basis = (
                    "no authorship evidence in scope. Position in the user role, "
                    "under a heading, or inside a block quotation is not evidence."
                )

        out.append(Classified(seg, cls, confidence, signals, basis, inherited_from))
    return out


# --------------------------------------------------------------------------
# Index view — what an adapter must supply
# --------------------------------------------------------------------------

class IndexItem:
    """One item of the underlying authority index, read only.

    `legacy` is copied through byte-for-byte and hashed. The sidecar never edits
    it and never writes back to the source artifact.

    `resolver` says how to recover this item's text from the pinned artifact, so
    that spans stay verifiable without the sidecar storing any content:

    * `{"kind": "file"}`                     — the item text is the whole file
    * `{"kind": "json_segment_text", "index": n}`
                                             — the item text is
                                               `segments[n]["text"]` of the file's
                                               JSON
    """

    __slots__ = ("item_id", "role", "text", "legacy", "locator", "resolver")

    def __init__(self, item_id: str, role: str, text: str,
                 legacy: dict | None = None, locator: dict | None = None,
                 resolver: dict | None = None) -> None:
        self.item_id = item_id
        self.role = role
        self.text = text
        self.legacy = dict(legacy or {})
        self.locator = dict(locator or {})
        self.resolver = dict(resolver or {"kind": "file"})


class IndexView:
    __slots__ = ("artifact_path", "artifact_sha256", "artifact_bytes", "items", "notes")

    def __init__(self, artifact_path: str, artifact_sha256: str,
                 artifact_bytes: int, items: Sequence[IndexItem],
                 notes: str = "") -> None:
        self.artifact_path = artifact_path
        self.artifact_sha256 = artifact_sha256
        self.artifact_bytes = artifact_bytes
        self.items = list(items)
        self.notes = notes


# --------------------------------------------------------------------------
# Sidecar construction
# --------------------------------------------------------------------------

def span_base_key(artifact_path: str, resolver: dict) -> str:
    """The key under which this item's span base text is supplied.

    Spans are offsets into a *span base*. For a whole-file item that is the file;
    for an item lifted out of a JSON array it is that array element's string.
    Making the distinction explicit is what stopped spans being resolved against
    the wrong text.
    """
    if resolver.get("kind") == "json_segment_text":
        return f"{artifact_path}#/segments/{resolver.get('index')}/text"
    return artifact_path


def load_span_bases(sidecar: dict, repo_root: str = ".") -> dict[str, str]:
    """Rebuild the span base texts a sidecar needs, by re-reading the artifacts."""
    out: dict[str, str] = {}
    cache: dict[str, str] = {}
    for rec in sidecar.get("items", []):
        base = rec.get("span_base") or {}
        resolver = base.get("resolver") or {"kind": "file"}
        artifact = rec.get("source_artifact_path") or base.get("artifact_path")
        if not artifact:
            continue
        path = artifact if os.path.isabs(artifact) else os.path.join(repo_root, artifact)
        if path not in cache:
            try:
                with open(path, encoding="utf-8") as fh:
                    cache[path] = fh.read()
            except OSError:
                continue
        raw = cache[path]
        # The artifact itself is always supplied, so the artifact-level pin in
        # `sources` can be checked as well as each item's span base.
        out.setdefault(artifact, raw)
        key = base.get("key") or span_base_key(artifact, resolver)
        if resolver.get("kind") == "json_segment_text":
            try:
                out[key] = json.loads(raw)["segments"][int(resolver["index"])]["text"]
            except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError):
                continue
        else:
            out[key] = raw
    return out


def build_item_record(item: IndexItem) -> dict:
    classified = classify_segments(segment_text(item.text))
    segs = []
    for c in classified:
        s = c.segment
        segs.append({
            "segment_id": f"{item.item_id}#s{s.ordinal:04d}",
            "ordinal": s.ordinal,
            "structural_kind": s.kind,
            "scope_id": s.scope_id,
            "quote_depth": s.quote_depth,
            "char_start": s.char_start,
            "char_end": s.char_end,
            "line_start": s.line_start,
            "line_end": s.line_end,
            "bytes": len(s.text.encode("utf-8")),
            "text_sha256": sha256_text(s.text),
            "authorship_class": c.authorship_class,
            "confidence": c.confidence,
            "inherited_from_ordinal": c.inherited_from,
            "decision_basis": c.decision_basis,
            "signals": c.signals,
            "included_in_default_authority_query":
                c.authorship_class not in DEFAULT_EXCLUDED,
        })

    present = sorted({s["authorship_class"] for s in segs})
    # An adoption marker and an adopted segment are different things. The founder
    # saying "instruments I commissioned are first-class founder material" is his
    # own words; FOUNDER_ADOPTED belongs to the material he took, not to that
    # sentence. Reporting both stops a zero in one column reading as an absence.
    adoption_markers = [
        {"segment_id": s["segment_id"], "lines": [s["line_start"], s["line_end"]],
         "segment_class": s["authorship_class"], "matched": sig["matched"]}
        for s in segs for sig in s["signals"] if sig["kind"] == ADOPTION
    ]
    disavowals = [
        {"segment_id": s["segment_id"], "lines": [s["line_start"], s["line_end"]],
         "matched": sig["matched"]}
        for s in segs for sig in s["signals"] if sig["kind"] == DISAVOWAL
    ]
    return {
        "item_id": item.item_id,
        "role": item.role,
        "role_is_not_authorship": (
            "The role records who typed or hosted the item. It never raises a "
            "segment's class; see the position-inert invariant."
        ),
        "item_text_sha256": sha256_text(item.text),
        "item_bytes": len(item.text.encode("utf-8")),
        "locator": item.locator,
        "span_base": {
            "key": None,  # filled in by build_sidecar, which knows the artifact
            "sha256": sha256_text(item.text),
            "resolver": item.resolver,
        },
        "legacy": {
            "fields": item.legacy,
            "legacy_sha256": sha256_text(canonical_json(item.legacy)),
            "preservation": "copied through unmodified; the sidecar never writes the index",
        },
        "segment_count": len(segs),
        "classes_present": present,
        "is_mixed_authorship": len(present) > 1,
        "adoption_markers": adoption_markers,
        "disavowal_markers": disavowals,
        "adopted_segment_count": sum(1 for s in segs
                                     if s["authorship_class"] == FOUNDER_ADOPTED),
        "segments": segs,
    }


def build_sidecar(views: Sequence[IndexView], *, sidecar_id: str,
                  built_against_commit: str, notes: str = "") -> dict:
    sources = []
    records = []
    for view in views:
        sources.append({
            "artifact_path": view.artifact_path,
            "artifact_sha256": view.artifact_sha256,
            "artifact_bytes": view.artifact_bytes,
            "item_count": len(view.items),
            "adapter_notes": view.notes,
        })
        for item in view.items:
            rec = build_item_record(item)
            rec["source_artifact_path"] = view.artifact_path
            rec["source_artifact_sha256"] = view.artifact_sha256
            rec["span_base"]["key"] = span_base_key(view.artifact_path, item.resolver)
            rec["span_base"]["artifact_path"] = view.artifact_path
            records.append(rec)

    tally: dict[str, int] = {c: 0 for c in CLASSES}
    for rec in records:
        for seg in rec["segments"]:
            tally[seg["authorship_class"]] += 1

    return {
        "schema": SIDECAR_SCHEMA,
        "sidecar_id": sidecar_id,
        "is_a_proposal_not_a_binding": True,
        "decision_changed": [],
        "built_against_commit": built_against_commit,
        "non_destructive": {
            "writes_to_index": False,
            "copies_index_content": False,
            "content_addressing": (
                "Segments are character spans plus sha256, pinned to "
                "source_artifact_sha256. Resolving a span requires the pinned "
                "artifact and fails closed when the artifact changes."
            ),
            "legacy_fields": "preserved verbatim under each record's legacy.fields",
        },
        "class_meanings": CLASS_MEANING,
        "default_authority_query_excludes": sorted(DEFAULT_EXCLUDED),
        "sources": sources,
        "item_count": len(records),
        "segment_count": sum(r["segment_count"] for r in records),
        "mixed_authorship_item_count": sum(1 for r in records if r["is_mixed_authorship"]),
        "class_tally": tally,
        "notes": notes,
        "items": records,
    }


# --------------------------------------------------------------------------
# Query layer
# --------------------------------------------------------------------------

def authority_segments(sidecar: dict, *, include: Iterable[str] = (),
                       require_local_evidence: bool = False) -> dict:
    """Segments usable as authority.

    Default excludes NONFOUNDER_PASTED and UNRESOLVED_USER_ROLE. Opting either in
    is explicit: pass it in `include`, and the result records that you did.
    """
    opted_in = sorted({c for c in include if c in DEFAULT_EXCLUDED})
    unknown = sorted({c for c in include if c not in CLASSES})
    if unknown:
        raise ValueError(f"unknown authorship class(es): {unknown}")
    allowed = (set(CLASSES) - DEFAULT_EXCLUDED) | set(opted_in)

    hits = []
    for rec in sidecar["items"]:
        for seg in rec["segments"]:
            if seg["authorship_class"] not in allowed:
                continue
            if require_local_evidence and seg["confidence"] != LOCAL_EVIDENCE:
                continue
            hits.append({
                "item_id": rec["item_id"],
                "segment_id": seg["segment_id"],
                "authorship_class": seg["authorship_class"],
                "confidence": seg["confidence"],
                "source_artifact_path": rec["source_artifact_path"],
                "source_artifact_sha256": rec["source_artifact_sha256"],
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "line_start": seg["line_start"],
                "line_end": seg["line_end"],
                "text_sha256": seg["text_sha256"],
            })
    return {
        "allowed_classes": sorted(allowed),
        "excluded_by_default": sorted(DEFAULT_EXCLUDED),
        "explicitly_opted_in": opted_in,
        "opt_in_is_explicit": bool(opted_in),
        "require_local_evidence": require_local_evidence,
        "segment_count": len(hits),
        "segments": hits,
    }


ADMITTED_FOUNDER = "QUOTE_ADMITTED_FOUNDER_AUTHORED"
REFUSED_PASTED = "QUOTE_REFUSED_LANDS_IN_NONFOUNDER_PASTED"
REFUSED_UNRESOLVED = "QUOTE_REFUSED_LANDS_IN_UNRESOLVED_USER_ROLE"
REFUSED_REPRESENTED = "QUOTE_REFUSED_LANDS_IN_FOUNDER_REPRESENTED"
REFUSED_NOT_PRESENT = "QUOTE_REFUSED_NOT_PRESENT_IN_ANY_SEGMENT"
REFUSED_SOURCE_CHANGED = "QUOTE_REFUSED_SOURCE_ARTIFACT_CHANGED"

_VERDICT_FOR_CLASS = {
    FOUNDER_DIRECT: ADMITTED_FOUNDER,
    FOUNDER_ADOPTED: ADMITTED_FOUNDER,
    FOUNDER_REPRESENTED: REFUSED_REPRESENTED,
    NONFOUNDER_PASTED: REFUSED_PASTED,
    UNRESOLVED_USER_ROLE: REFUSED_UNRESOLVED,
}


def locate_quote(sidecar: dict, sources: dict[str, str], quote: str, *,
                 item_ids: Iterable[str] | None = None,
                 artifact_paths: Iterable[str] | None = None) -> list[dict]:
    """Where a quotation lands, and what the landing segment's class is.

    A substring match is a *locator*. It answers "where is this text" and never
    "is this founder text". The verdict is the landing segment's class. That
    separation is the fix for the reproduced defect, in which a literal match
    inside a coarsely founder-marked block was itself treated as the verdict.

    `item_ids` and `artifact_paths` scope the search. Scoping matters more than it
    looks: sentences in this estate's founder record are copied verbatim into
    agent-authored projections of that record, so an unscoped substring hit
    cannot say which of the two it found. Leaving the scope open is the honest
    default and produces an ambiguous verdict that fails closed; naming the
    governing corpus is what a caller does when it knows which corpus governs.
    """
    needle = normalise(quote)
    landings: list[dict] = []
    if not needle:
        return landings

    wanted_items = set(item_ids) if item_ids is not None else None
    wanted_paths = set(artifact_paths) if artifact_paths is not None else None

    for rec in sidecar["items"]:
        if wanted_items is not None and rec["item_id"] not in wanted_items:
            continue
        if wanted_paths is not None and rec["source_artifact_path"] not in wanted_paths:
            continue
        base = rec.get("span_base") or {}
        key = base.get("key") or rec["source_artifact_path"]
        expected = base.get("sha256") or rec["source_artifact_sha256"]
        raw = sources.get(key)
        if raw is None:
            continue
        if sha256_text(raw) != expected:
            landings.append({
                "item_id": rec["item_id"],
                "segment_id": None,
                "authorship_class": None,
                "verdict": REFUSED_SOURCE_CHANGED,
                "detail": (
                    f"{key} no longer hashes to the value the sidecar was pinned "
                    "to; every span over it is unverified until the sidecar is rebuilt"
                ),
            })
            continue
        for seg in rec["segments"]:
            span = raw[seg["char_start"]:seg["char_end"]]
            if sha256_text(span) != seg["text_sha256"]:
                landings.append({
                    "item_id": rec["item_id"],
                    "segment_id": seg["segment_id"],
                    "authorship_class": None,
                    "verdict": REFUSED_SOURCE_CHANGED,
                    "detail": "segment span does not recompute to its recorded hash",
                })
                continue
            if needle in normalise(_strip_structure(span)):
                landings.append({
                    "item_id": rec["item_id"],
                    "segment_id": seg["segment_id"],
                    "authorship_class": seg["authorship_class"],
                    "confidence": seg["confidence"],
                    "verdict": _VERDICT_FOR_CLASS[seg["authorship_class"]],
                    "decision_basis": seg["decision_basis"],
                    "line_start": seg["line_start"],
                    "line_end": seg["line_end"],
                })
    return landings


def verdict_for_quote(sidecar: dict, sources: dict[str, str], quote: str, *,
                      include: Iterable[str] = (),
                      item_ids: Iterable[str] | None = None,
                      artifact_paths: Iterable[str] | None = None) -> dict:
    """One verdict for one quotation, refusing when any landing is excluded.

    Fails closed on ambiguity. A quotation that lands in both a founder segment
    and a pasted segment is refused unless the pasted class is explicitly opted
    in, because a citation that is true in one reading and false in another is
    not evidence of authority.
    """
    opted = {c for c in include if c in DEFAULT_EXCLUDED}
    scope = {
        "item_ids": sorted(item_ids) if item_ids is not None else None,
        "artifact_paths": sorted(artifact_paths) if artifact_paths is not None else None,
        "scoped": item_ids is not None or artifact_paths is not None,
    }
    landings = locate_quote(sidecar, sources, quote, item_ids=item_ids,
                            artifact_paths=artifact_paths)
    if not landings:
        return {
            "quote": quote,
            "verdict": REFUSED_NOT_PRESENT,
            "landing_count": 0,
            "classes_landed_in": [],
            "ambiguous": False,
            "landings": [],
            "scope": scope,
            "explicitly_opted_in": sorted(opted),
        }
    classes = {l.get("authorship_class") for l in landings}
    admitted = {FOUNDER_DIRECT, FOUNDER_ADOPTED} | opted
    if any(l["verdict"] == REFUSED_SOURCE_CHANGED for l in landings):
        verdict = REFUSED_SOURCE_CHANGED
    elif classes and classes <= admitted:
        verdict = ADMITTED_FOUNDER
    else:
        blocking = sorted(c for c in classes if c not in admitted)
        verdict = _VERDICT_FOR_CLASS.get(blocking[0], REFUSED_UNRESOLVED)
    return {
        "quote": quote,
        "verdict": verdict,
        "landing_count": len(landings),
        "classes_landed_in": sorted(c for c in classes if c),
        "ambiguous": len(classes) > 1,
        "scope": scope,
        "explicitly_opted_in": sorted(opted),
        "landings": landings,
    }


# --------------------------------------------------------------------------
# Read-back verification: hash *and* parse
# --------------------------------------------------------------------------

def verify_sidecar(sidecar: dict, sources: dict[str, str]) -> list[str]:
    """Recompute every span against the pinned sources. Absence of a check is not a pass."""
    failures: list[str] = []
    if sidecar.get("schema") != SIDECAR_SCHEMA:
        failures.append(f"SCHEMA_UNKNOWN: {sidecar.get('schema')!r}")
    for src in sidecar.get("sources", []):
        raw = sources.get(src["artifact_path"])
        if raw is None:
            failures.append(f"SOURCE_ABSENT: {src['artifact_path']}")
            continue
        if sha256_text(raw) != src["artifact_sha256"]:
            failures.append(f"SOURCE_CHANGED: {src['artifact_path']}")
    tally: dict[str, int] = {c: 0 for c in CLASSES}
    for rec in sidecar.get("items", []):
        base = rec.get("span_base") or {}
        key = base.get("key") or rec["source_artifact_path"]
        raw = sources.get(key)
        if raw is None:
            failures.append(f"SPAN_BASE_ABSENT: {key}")
            continue
        if base.get("sha256") and sha256_text(raw) != base["sha256"]:
            failures.append(f"SPAN_BASE_CHANGED: {key}")
        for seg in rec["segments"]:
            span = raw[seg["char_start"]:seg["char_end"]]
            if sha256_text(span) != seg["text_sha256"]:
                failures.append(f"SEGMENT_HASH_MISMATCH: {seg['segment_id']}")
            if seg["authorship_class"] not in CLASSES:
                failures.append(f"CLASS_UNKNOWN: {seg['segment_id']} "
                                f"{seg['authorship_class']!r}")
            expected = seg["authorship_class"] not in DEFAULT_EXCLUDED
            if seg["included_in_default_authority_query"] != expected:
                failures.append(f"DEFAULT_QUERY_FLAG_WRONG: {seg['segment_id']}")
            tally[seg["authorship_class"]] += 1
    if tally != sidecar.get("class_tally"):
        failures.append(f"CLASS_TALLY_MISMATCH: recomputed {tally} vs recorded "
                        f"{sidecar.get('class_tally')}")
    if sum(tally.values()) != sidecar.get("segment_count"):
        failures.append("SEGMENT_COUNT_MISMATCH")
    return failures


def read_back_and_parse(path: str) -> tuple[dict | None, list[str]]:
    """Hash-check and *parse*. A hash-valid unparsable artifact is a defect."""
    problems: list[str] = []
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return None, [f"UNREADABLE: {path}: {exc}"]
    digest = sha256_bytes(raw)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"HASH_VALID_BUT_UNPARSABLE: {path} sha256={digest}: {exc}"]
    if not isinstance(parsed, dict):
        problems.append(f"PARSED_BUT_NOT_AN_OBJECT: {path}")
    return parsed, problems


# --------------------------------------------------------------------------
# Adapters over the artifacts that actually exist in this estate
# --------------------------------------------------------------------------

def _read(path: str) -> tuple[str, str, int]:
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw.decode("utf-8"), sha256_bytes(raw), len(raw)


def adapter_markdown_record(path: str, *, item_id: str, role: str = "founder_record",
                            legacy: dict | None = None,
                            repo_root: str = "") -> IndexView:
    """Treat one markdown authority record as a single item, segmented within.

    `path` is recorded as given, so passing a repository-relative path with
    `repo_root` keeps the sidecar portable between checkouts.
    """
    text, digest, nbytes = _read(os.path.join(repo_root, path) if repo_root else path)
    return IndexView(
        artifact_path=path,
        artifact_sha256=digest,
        artifact_bytes=nbytes,
        items=[IndexItem(item_id=item_id, role=role, text=text, legacy=legacy or {},
                         locator={"whole_file": True},
                         resolver={"kind": "file"})],
        notes=("One item, the whole record. Segmentation happens below message "
               "granularity, which is the point."),
    )


def adapter_founder_corpus(path: str, *, repo_root: str = "") -> IndexView:
    """Adapt `FOUNDER-CORPUS-*.json`, preserving each segment's legacy fields.

    The corpus assigns one `speaker_class` per heading-delimited block. Those
    values are carried through untouched as `legacy.fields` so the two answers
    can be compared instead of one silently replacing the other.
    """
    text, digest, nbytes = _read(os.path.join(repo_root, path) if repo_root else path)
    corpus = json.loads(text)
    items = []
    for i, seg in enumerate(corpus.get("segments", [])):
        legacy = {k: v for k, v in seg.items() if k != "text"}
        items.append(IndexItem(
            item_id=f"FC-SEG-{i:02d}",
            role="user",
            text=seg.get("text", ""),
            legacy=legacy,
            locator={
                "json_pointer": f"/segments/{i}",
                "heading": seg.get("heading"),
                "source_line_range": [seg.get("first_line"), seg.get("last_line")],
            },
            resolver={"kind": "json_segment_text", "index": i},
        ))
    return IndexView(
        path, digest, nbytes, items,
        notes=("Items are the corpus's own segment strings. Each item's span base "
               "is that string, resolved back out of the pinned JSON; the file is "
               "pinned as well, so a change to either refuses."))


def load_provenance_quotations(path: str) -> list[dict]:
    """The register's founder quotations, as probes to be located, not verdicts."""
    with open(path, encoding="utf-8") as fh:
        register = json.load(fh)
    probes = []
    for c in register.get("constraints", []):
        for q in c.get("founder_quotations") or []:
            probes.append({
                "constraint_id": c.get("constraint_id"),
                "register_provenance_class": c.get("provenance_class"),
                "prior_verdict": c.get("prior_verdict"),
                "cited_corpus_id": q.get("corpus_id"),
                "cited_segment_heading": q.get("segment_heading"),
                "quote": q.get("quote", ""),
            })
    return probes


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_classify(args: argparse.Namespace) -> int:
    text, digest, nbytes = _read(args.path)
    view = adapter_markdown_record(args.path, item_id=args.item_id)
    sidecar = build_sidecar([view], sidecar_id="ad-hoc",
                            built_against_commit=args.commit or "unrecorded")
    for rec in sidecar["items"]:
        for seg in rec["segments"]:
            print(f"L{seg['line_start']:>4}-{seg['line_end']:<4} "
                  f"{seg['authorship_class']:<22} {seg['confidence']:<16} "
                  f"{seg['decision_basis'][:70]}")
    print(f"\nsegments={sidecar['segment_count']} tally={sidecar['class_tally']}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    sidecar, problems = read_back_and_parse(args.sidecar)
    if sidecar is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    sources = load_span_bases(sidecar, args.repo_root)
    failures = problems + verify_sidecar(sidecar, sources)
    for f in failures:
        print(f"FAIL {f}")
    if failures:
        return 1
    print(f"sidecar verified: {sidecar['item_count']} items, "
          f"{sidecar['segment_count']} segments recomputed against pinned sources")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    sidecar, problems = read_back_and_parse(args.sidecar)
    if sidecar is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    result = authority_segments(sidecar, include=args.include,
                               require_local_evidence=args.require_local_evidence)
    print(json.dumps({k: v for k, v in result.items() if k != "segments"}, indent=2))
    for seg in result["segments"][:args.limit]:
        print(f"  {seg['authorship_class']:<22} {seg['confidence']:<16} "
              f"{seg['source_artifact_path']}:L{seg['line_start']}-{seg['line_end']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="authorship_sidecar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("classify", help="segment and classify one markdown record")
    p.add_argument("path")
    p.add_argument("--item-id", default="ITEM-01")
    p.add_argument("--commit", default=None)
    p.set_defaults(func=_cmd_classify)

    p = sub.add_parser("verify", help="recompute a sidecar against its pinned sources")
    p.add_argument("sidecar")
    p.add_argument("--repo-root", default=".")
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("query", help="run a default-excluding authority query")
    p.add_argument("sidecar")
    p.add_argument("--include", nargs="*", default=[],
                   help="explicitly opt a default-excluded class back in")
    p.add_argument("--require-local-evidence", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=_cmd_query)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
