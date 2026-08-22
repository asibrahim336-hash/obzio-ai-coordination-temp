"""Founder intent processing: the actual work.

A founder correction is two things fused together, and fusing them is how
operators go wrong:

  LITERAL CLAIM   -- what the founder actually said. Must survive verbatim.
  SYSTEM IMPLICATION -- what must therefore change. This is INFERRED by the
                        operator and is NOT the founder's words.

The failure mode this engine exists to prevent: an operator paraphrases the
founder, treats the paraphrase as the founder's instruction, and propagates
it. By the third hop nobody can tell what was said from what was guessed.

So: every claim carries a byte span into the source text and must match it
verbatim. Every implication is flagged INFERRED, carries the rule that
produced it, and points back at the claim it came from.
"""

import re
from dataclasses import dataclass, asdict, field
from typing import List, Dict


class IntentError(ValueError):
    pass


# ---------------------------------------------------------------- data types

@dataclass
class Claim:
    id: str
    text: str          # MUST equal source[start:end]
    start: int
    end: int
    scope: str         # STANDING | ONE_OFF | AMBIGUOUS
    polarity: str      # DIRECTIVE | PROHIBITION | CORRECTION_OF_FACT

    def to_json(self):
        return asdict(self)


@dataclass
class Implication:
    id: str
    statement: str
    inferred: bool           # always True; present so the artefact is explicit
    derived_from: str        # claim id
    rule_id: str
    confidence: str          # HIGH | MEDIUM | LOW
    surfaces: List[str] = field(default_factory=list)

    def to_json(self):
        return asdict(self)


@dataclass
class ChangeOrder:
    id: str
    surface: str
    action: str              # AMEND | ADD | REMOVE | REVIEW
    detail: str
    implication_id: str
    requires_founder_confirmation: bool

    def to_json(self):
        return asdict(self)


# ------------------------------------------------------------ classification

STANDING_MARKERS = ["always", "never", "from now on", "going forward",
                    "every time", "in future", "as a rule", "stop "]
ONEOFF_MARKERS = ["this time", "just this", "for now", "in this case",
                  "on this one", "for this one", "this once", "here"]
PROHIBITION_MARKERS = ["don't", "do not", "did not", "didn't", "never",
                       "stop ", "no longer", "avoid", "rather you did"]
FACT_MARKERS = ["actually", "in fact", "it's not", "that's wrong", "incorrect",
                "the real"]


def _scope_of(sentence: str) -> str:
    s = sentence.lower()
    standing = any(m in s for m in STANDING_MARKERS)
    oneoff = any(m in s for m in ONEOFF_MARKERS)
    if standing and oneoff:
        # Genuinely ambiguous. Refusing to guess is the point: an operator that
        # silently picks STANDING turns a one-off note into permanent policy.
        return "AMBIGUOUS"
    if standing:
        return "STANDING"
    if oneoff:
        return "ONE_OFF"
    return "AMBIGUOUS"


def _polarity_of(sentence: str) -> str:
    s = sentence.lower()
    if any(m in s for m in PROHIBITION_MARKERS):
        return "PROHIBITION"
    if any(m in s for m in FACT_MARKERS):
        return "CORRECTION_OF_FACT"
    return "DIRECTIVE"


def segment(text: str):
    """Yield (start, end, sentence) preserving exact byte offsets.

    Offsets are the whole point -- a segmenter that normalises whitespace
    destroys the ability to prove a quote is verbatim."""
    out = []
    for m in re.finditer(r"[^.!?\n]+[.!?]*", text):
        s, e = m.start(), m.end()
        raw = text[s:e]
        stripped = raw.strip()
        if not stripped:
            continue
        lead = len(raw) - len(raw.lstrip())
        s2 = s + lead
        e2 = s2 + len(stripped)
        out.append((s2, e2, text[s2:e2]))
    return out


def extract_claims(source: str) -> List[Claim]:
    claims = []
    for i, (s, e, sent) in enumerate(segment(source), start=1):
        c = Claim(
            id=f"CL-{i:02d}",
            text=sent,
            start=s,
            end=e,
            scope=_scope_of(sent),
            polarity=_polarity_of(sent),
        )
        if source[c.start:c.end] != c.text:
            raise IntentError(f"claim {c.id} span does not reproduce source text")
        claims.append(c)
    if not claims:
        raise IntentError("correction contains no extractable claim")
    return claims


# ----------------------------------------------------------- implication rules
#
# Each rule is (rule_id, predicate, statement template, surface tags, confidence).
# Rules are data, not branching code, so the artefact can name exactly which
# rule fired.

RULES = [
    ("R-STANDING-PROHIBITION",
     lambda c: c.scope == "STANDING" and c.polarity == "PROHIBITION",
     "A standing prohibition must be encoded wherever the prohibited act is "
     "currently permitted or instructed.",
     ["policy", "prompt", "checklist"], "HIGH"),
    ("R-STANDING-DIRECTIVE",
     lambda c: c.scope == "STANDING" and c.polarity == "DIRECTIVE",
     "A standing directive must be added to the operating instructions that "
     "govern the affected act.",
     ["policy", "prompt"], "HIGH"),
    ("R-FACT-CORRECTION",
     lambda c: c.polarity == "CORRECTION_OF_FACT",
     "A corrected fact must be propagated to every surface that restates it, "
     "including already-published copies.",
     ["reference", "published"], "HIGH"),
    ("R-ONEOFF",
     lambda c: c.scope == "ONE_OFF",
     "A one-off instruction applies to the current instance only and must NOT "
     "be promoted to standing policy.",
     ["instance"], "MEDIUM"),
    ("R-AMBIGUOUS-SCOPE",
     lambda c: c.scope == "AMBIGUOUS",
     "Scope is undetermined from the correction text; founder confirmation is "
     "required before any standing surface is changed.",
     ["clarification"], "LOW"),
]


def derive_implications(claims: List[Claim], registry: Dict[str, dict]) -> List[Implication]:
    """Rules fire per claim. Every output is marked INFERRED.

    Note what this deliberately does NOT do: it never rewrites the claim text
    into the implication. The implication is the operator's own sentence."""
    imps = []
    n = 0
    for c in claims:
        for rule_id, pred, statement, tags, conf in RULES:
            if not pred(c):
                continue
            n += 1
            surfaces = sorted(
                name for name, meta in registry.items()
                if set(meta.get("tags", [])) & set(tags)
            )
            imps.append(Implication(
                id=f"IM-{n:02d}",
                statement=statement,
                inferred=True,
                derived_from=c.id,
                rule_id=rule_id,
                confidence=conf,
                surfaces=surfaces,
            ))
    return imps


def map_surfaces(implications: List[Implication], registry: Dict[str, dict]) -> dict:
    affected = {}
    for im in implications:
        for s in im.surfaces:
            entry = affected.setdefault(s, {
                "surface": s,
                "kind": registry[s].get("kind", "unknown"),
                "path": registry[s].get("path", ""),
                "tags": sorted(registry[s].get("tags", [])),
                "implications": [],
                "max_confidence": "LOW",
            })
            entry["implications"].append(im.id)
            order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
            if order[im.confidence] > order[entry["max_confidence"]]:
                entry["max_confidence"] = im.confidence
    for e in affected.values():
        e["implications"] = sorted(set(e["implications"]))
    return {"affected_surfaces": [affected[k] for k in sorted(affected)],
            "unaffected_surfaces": sorted(set(registry) - set(affected))}


ACTION_FOR_RULE = {
    "R-STANDING-PROHIBITION": "AMEND",
    "R-STANDING-DIRECTIVE": "AMEND",
    "R-FACT-CORRECTION": "AMEND",
    "R-ONEOFF": "REVIEW",
    "R-AMBIGUOUS-SCOPE": "REVIEW",
}


def emit_change_orders(implications: List[Implication],
                       surface_map: dict) -> List[ChangeOrder]:
    orders = []
    n = 0
    known = {e["surface"] for e in surface_map["affected_surfaces"]}
    for im in implications:
        for s in im.surfaces:
            if s not in known:
                raise IntentError(f"implication {im.id} targets unmapped surface {s!r}")
            n += 1
            orders.append(ChangeOrder(
                id=f"CO-{n:03d}",
                surface=s,
                action=ACTION_FOR_RULE[im.rule_id],
                detail=im.statement,
                implication_id=im.id,
                # LOW confidence never changes a surface unilaterally.
                requires_founder_confirmation=(im.confidence == "LOW"),
            ))
    return orders
