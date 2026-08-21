"""Deterministic checks for founder-intent-processing artefacts.

The central invariant: you can always tell what the founder SAID from what
the operator INFERRED, and every inference is traceable back to words that
provably exist in the source."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.artefacts import read_json
from obzio_spine.checkkit import CheckReport

REQUIRED_ARTEFACTS = [
    "correction.json",
    "interpretation.json",
    "surface_impact.json",
    "change_orders.json",
]


def run_checks(run_dir: str) -> CheckReport:
    r = CheckReport("founder-intent-processing")

    missing = [a for a in REQUIRED_ARTEFACTS
               if not os.path.exists(os.path.join(run_dir, a))]
    if missing:
        r.fail("artefacts_present", f"missing artefacts: {missing}", missing=missing)
        return r

    corr = read_json(os.path.join(run_dir, "correction.json"))
    interp = read_json(os.path.join(run_dir, "interpretation.json"))
    impact = read_json(os.path.join(run_dir, "surface_impact.json"))
    orders = read_json(os.path.join(run_dir, "change_orders.json"))

    source = corr["source_text"]
    claims = interp["literal_claims"]
    imps = interp["system_implications"]

    # --- CHK-FI-01 every literal claim is VERBATIM in the source ---------
    # This is the anti-paraphrase control. A claim whose span does not
    # reproduce the source is a fabrication, however plausible it reads.
    for c in claims:
        span = source[c["start"]:c["end"]]
        if span != c["text"]:
            r.fail("CHK-FI-01_claim_verbatim",
                   f"claim {c['id']} is not verbatim: artefact says {c['text']!r} "
                   f"but source[{c['start']}:{c['end']}] is {span!r}",
                   claim=c["id"], claimed=c["text"], actual=span)

    # --- CHK-FI-02 no implication is dressed up as a literal claim -------
    claim_ids = {c["id"] for c in claims}
    for im in imps:
        if im.get("inferred") is not True:
            r.fail("CHK-FI-02_implication_marked_inferred",
                   f"implication {im['id']} is not marked inferred=true",
                   implication=im["id"])
        if im["statement"] in source:
            # An implication whose statement appears verbatim in the source is
            # not an inference; it is a claim being double-counted.
            r.warn("CHK-FI-02_implication_marked_inferred",
                   f"implication {im['id']} restates source text verbatim",
                   implication=im["id"])

    # --- CHK-FI-03 every implication traces to a real claim --------------
    for im in imps:
        if im["derived_from"] not in claim_ids:
            r.fail("CHK-FI-03_implication_traceable",
                   f"implication {im['id']} derives from unknown claim "
                   f"{im['derived_from']!r}",
                   implication=im["id"], derived_from=im["derived_from"])
        if not im.get("rule_id"):
            r.fail("CHK-FI-03_implication_traceable",
                   f"implication {im['id']} names no rule", implication=im["id"])
        if im.get("confidence") not in ("HIGH", "MEDIUM", "LOW"):
            r.fail("CHK-FI-03_implication_traceable",
                   f"implication {im['id']} has no valid confidence",
                   implication=im["id"])

    # --- CHK-FI-04 every affected surface has at least one change order --
    affected = {e["surface"] for e in impact["affected_surfaces"]}
    ordered = {o["surface"] for o in orders}
    for s in sorted(affected - ordered):
        r.fail("CHK-FI-04_surface_has_order",
               f"surface {s!r} is affected but has no change order", surface=s)

    # --- CHK-FI-05 no change order targets an unaffected surface ---------
    for s in sorted(ordered - affected):
        r.fail("CHK-FI-05_order_targets_affected_surface",
               f"change order targets {s!r} which is not in the impact map",
               surface=s)

    # --- CHK-FI-06 no implication evaporates -----------------------------
    # An implication that reaches zero surfaces is a correction the system
    # absorbed and then lost. This is the quiet failure this pack exists for.
    for im in imps:
        if not im.get("surfaces"):
            r.fail("CHK-FI-06_no_orphan_implication",
                   f"implication {im['id']} (rule {im['rule_id']}, from "
                   f"{im['derived_from']}) reaches no surface: the correction "
                   f"would be silently dropped",
                   implication=im["id"], rule=im["rule_id"])

    # --- CHK-FI-07 low-confidence changes need founder confirmation ------
    conf_by_imp = {im["id"]: im["confidence"] for im in imps}
    for o in orders:
        c = conf_by_imp.get(o["implication_id"])
        if c == "LOW" and not o.get("requires_founder_confirmation"):
            r.fail("CHK-FI-07_low_confidence_gated",
                   f"order {o['id']} acts on LOW-confidence implication "
                   f"{o['implication_id']} without founder confirmation",
                   order=o["id"])

    # --- CHK-FI-08 a one-off must not become standing policy -------------
    scope_by_claim = {c["id"]: c["scope"] for c in claims}
    imp_by_id = {im["id"]: im for im in imps}
    policy_surfaces = {e["surface"] for e in impact["affected_surfaces"]
                       if "policy" in e.get("tags", [])}
    for o in orders:
        im = imp_by_id.get(o["implication_id"])
        if not im:
            continue
        if (o["surface"] in policy_surfaces
                and scope_by_claim.get(im["derived_from"]) == "ONE_OFF"
                and o["action"] != "REVIEW"):
            r.fail("CHK-FI-08_oneoff_not_promoted",
                   f"order {o['id']} applies a ONE_OFF claim "
                   f"({im['derived_from']}) to policy surface {o['surface']!r} "
                   f"with action {o['action']}",
                   order=o["id"])

    # --- CHK-FI-09 the correction did something --------------------------
    if claims and not orders:
        r.fail("CHK-FI-09_correction_has_effect",
               f"{len(claims)} claims extracted but zero change orders emitted")

    return r


if __name__ == "__main__":
    rep = run_checks(sys.argv[1])
    print(rep.summary())
    for f in rep.findings:
        print(f"  [{f.severity}] {f.check}: {f.message}")
    sys.exit(0 if rep.passed else 1)
