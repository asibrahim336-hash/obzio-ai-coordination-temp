"""Partial acceptance oracle for founder-intent-processing.

DOES NOT IMPORT engine.py.

HONEST SCOPE -- this is a PARTIAL_ORACLE, not a full one.
--------------------------------------------------------
What CAN be independently derived from a correction plus a surface registry:

  * the literal claims. These are the founder's own words at byte offsets, and
    a second implementation can recover them independently by segmenting the
    source itself. This is the pack's core deliverable -- separating what was
    SAID from what was INFERRED -- so the oracle covers the half that matters
    most and can actually be checked.
  * a set of structural invariants that follow from the spec rather than from
    the output: every claim verbatim, every inference marked, every
    implication reaching a surface, every LOW-confidence order gated.

What CANNOT be independently derived:

  * the system implications themselves. Which rules should fire on a given
    correction is a JUDGEMENT. Re-deriving them would mean reimplementing the
    rule table, and two copies of the same rule table are not two opinions --
    they are one opinion stored twice. Committing to them would be faking
    independence, so this oracle does not.

The segmenter below is written as a character scan rather than a regex, so it
is a genuinely different implementation of the same idea and can disagree with
engine.segment(). If it ever does, the run diverges and defaults to REJECT --
which is the correct outcome: two implementations disagreeing about what the
founder said is exactly the condition a human should look at.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.expectation import Expectation, Derivation, canonical_digest

COVERS = ("source_digest", "claim_count", "claim_texts", "claim_spans",
          "registry_surfaces", "all_claims_verbatim", "all_inferences_marked",
          "every_implication_reaches_a_surface", "low_confidence_orders_gated")

UNCOVERED = (
    "which implication rules should fire (judgement, not derivable)",
    "whether the scope classification is correct",
    "whether the affected-surface set is complete",
    "whether the change orders describe the right change",
)

TERMINATORS = ".!?"


def independent_segment(text: str):
    """Character scan. Deliberately NOT the regex used by engine.segment().

    Returns [(start, end, text)] with byte offsets into the original string,
    preserving exact source bytes so verbatim-ness stays checkable."""
    out = []
    i, n = 0, len(text)
    while i < n:
        while i < n and (text[i].isspace() or text[i] == "\n"):
            i += 1
        if i >= n:
            break
        start = i
        while i < n and text[i] not in TERMINATORS and text[i] != "\n":
            i += 1
        while i < n and text[i] in TERMINATORS:
            i += 1
        end = i
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            out.append((start, end, text[start:end]))
    return out


def inputs_digest(correction_text, registry) -> str:
    return canonical_digest({"text": correction_text,
                             "registry": {k: sorted(v.get("tags", []))
                                          for k, v in registry.items()}})


def derive_expectation(correction_text: str, registry: dict) -> Expectation:
    segs = independent_segment(correction_text)
    fields = {
        "source_digest": hashlib.sha256(correction_text.encode()).hexdigest(),
        "claim_count": len(segs),
        "claim_texts": [t for _, _, t in segs],
        "claim_spans": [[s, e] for s, e, _ in segs],
        "registry_surfaces": sorted(registry),
        # Invariants that follow from the spec, committed before any output.
        "all_claims_verbatim": True,
        "all_inferences_marked": True,
        "every_implication_reaches_a_surface": True,
        "low_confidence_orders_gated": True,
    }
    return Expectation(fields=fields, derivation=Derivation.PARTIAL_ORACLE,
                       covers=COVERS, uncovered=UNCOVERED)


def extract_actual(run_dir: str) -> dict:
    def rd(n):
        with open(os.path.join(run_dir, n), encoding="utf-8") as f:
            return json.load(f)
    corr = rd("correction.json")
    interp = rd("interpretation.json")
    impact = rd("surface_impact.json")
    orders = rd("change_orders.json")

    src = corr["source_text"]
    claims = interp["literal_claims"]
    imps = interp["system_implications"]

    conf = {i["id"]: i["confidence"] for i in imps}
    return {
        "source_digest": hashlib.sha256(src.encode()).hexdigest(),
        "claim_count": len(claims),
        "claim_texts": [c["text"] for c in claims],
        "claim_spans": [[c["start"], c["end"]] for c in claims],
        "registry_surfaces": sorted(corr.get("registry_surfaces", [])),
        "all_claims_verbatim": all(
            src[c["start"]:c["end"]] == c["text"] for c in claims),
        "all_inferences_marked": all(i.get("inferred") is True for i in imps),
        "every_implication_reaches_a_surface": all(i.get("surfaces") for i in imps),
        "low_confidence_orders_gated": all(
            o.get("requires_founder_confirmation")
            for o in orders if conf.get(o["implication_id"]) == "LOW"),
    }
