#!/usr/bin/env python3
"""Run the sidecar over a bounded slice of the real authority-bearing artifacts.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/run_slice.py \
        --repo-root . --commit <integration-sha>

Writes, relative to the lane directory:

* `sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json` — the sidecar itself
* `sidecar/SLICE-REPORT-20260827-v001.json` — what it found, including every
  disagreement with an existing classification

Both are hash-checked *and* parsed after write, because a hash-valid unparsable
artifact is a defect already in this estate's record.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402

LANE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        os.pardir))

# The bounded slice. Every path is read only.
OE = os.path.join("workstreams", "so02", "control-plane", "operating-environment")
SLICE = {
    "founder_record": os.path.join(OE, "FOUNDER-STANDING-INSTRUCTION-20260822.md"),
    "always_applied_rule": os.path.join(".cursor", "rules",
                                        "00-founder-standing-authority.mdc"),
    "founder_corpus": os.path.join(OE, "w10-provenance",
                                   "FOUNDER-CORPUS-20260823-v001.json"),
    "provenance_register": os.path.join(OE, "w10-provenance",
                                        "PROVENANCE-REGISTER-20260823-v001.json"),
    "derestriction_register": os.path.join(OE, "w4-platform-roles",
                                           "DE-RESTRICTION-REGISTER-20260822-v001.json"),
}

# The corpus's legacy speaker_class vocabulary mapped onto this lane's classes,
# so a disagreement is a disagreement about the same question rather than about
# vocabulary. FOUNDER_QUOTING_OTHER and NONFOUNDER_PASTED are the same claim.
LEGACY_EQUIVALENT = {
    "FOUNDER_DIRECT": A.FOUNDER_DIRECT,
    "FOUNDER_QUOTING_OTHER": A.NONFOUNDER_PASTED,
}


def resolve(repo_root: str, rel: str) -> str:
    return os.path.join(repo_root, rel)


def existing(repo_root: str) -> dict[str, str | None]:
    out = {}
    for key, rel in SLICE.items():
        path = resolve(repo_root, rel)
        out[key] = rel if os.path.exists(path) else None
    return out


def build(repo_root: str, commit: str) -> tuple[dict, dict[str, str]]:
    views = []

    rel = SLICE["founder_record"]
    if os.path.exists(resolve(repo_root, rel)):
        views.append(A.adapter_markdown_record(
            rel, item_id="FSI-20260822", role="founder_record",
            legacy={"estate_status": "CONTROLLING",
                    "estate_claim": "the founder's words reproduced verbatim"},
            repo_root=repo_root))

    rel = SLICE["always_applied_rule"]
    if os.path.exists(resolve(repo_root, rel)):
        views.append(A.adapter_markdown_record(
            rel, item_id="RULE-00-FOUNDER-STANDING", role="always_applied_rule",
            legacy={"estate_status": "alwaysApply: true",
                    "estate_claim": "always-applied projection of founder authority"},
            repo_root=repo_root))

    rel = SLICE["founder_corpus"]
    if os.path.exists(resolve(repo_root, rel)):
        views.append(A.adapter_founder_corpus(rel, repo_root=repo_root))

    sidecar = A.build_sidecar(
        views,
        sidecar_id="SCP-C-AUTHORSHIP-SIDECAR-SLICE-20260827-v001",
        built_against_commit=commit,
        notes=("Bounded slice. Sidecar over the artifacts that actually carry "
               "authority in this estate; the 928-item authority index named in "
               "the commission does not exist at any ref, see "
               "findings/INDEX-LOCATION-FINDING.md."),
    )
    # Paths recorded in the sidecar are repository-relative so the artifact is
    # portable; the span bases are resolved back out of the pinned artifacts.
    return sidecar, A.load_span_bases(sidecar, repo_root)


def class_counts(rec: dict) -> dict[str, int]:
    counts = {c: 0 for c in A.CLASSES}
    for seg in rec["segments"]:
        counts[seg["authorship_class"]] += 1
    return counts


def estate_claim_disagreements(sidecar: dict) -> list[dict]:
    """Where the estate's claim *about an artifact* differs from what it contains.

    The corpus's four verdicts are reproduced exactly, so the interesting
    disagreement is not verdict-level. It is that two artifacts the estate treats
    as carrying founder authority contain material that is not the founder's.
    """
    rows = []
    by_id = {rec["item_id"]: rec for rec in sidecar["items"]}

    rec = by_id.get("FSI-20260822")
    if rec:
        counts = class_counts(rec)
        non_founder = (counts[A.FOUNDER_REPRESENTED] + counts[A.NONFOUNDER_PASTED]
                       + counts[A.UNRESOLVED_USER_ROLE])
        rows.append({
            "item_id": rec["item_id"],
            "artifact": rec["source_artifact_path"],
            "estate_claim": (
                "'The founder's words are reproduced verbatim below. Nothing in "
                "this file paraphrases, compresses or interprets them.' - the "
                "file's own header, lines 10-13"
            ),
            "estate_treats_it_as": "CONTROLLING founder record",
            "sidecar_finds": counts,
            "segment_count": rec["segment_count"],
            "non_founder_direct_segments": non_founder,
            "disagreement": (
                "The claim is true of the block quotations and false of the file. "
                f"{counts[A.FOUNDER_DIRECT]} of {rec['segment_count']} segments are "
                f"the founder's own words; {non_founder} are not, including "
                f"{counts[A.NONFOUNDER_PASTED]} segments of third-party material "
                "pasted into it and "
                f"{counts[A.FOUNDER_REPRESENTED]} of agent commentary. A consumer "
                "quoting 'from the verbatim founder record' without segmenting "
                "can quote any of them."
            ),
            "severity": "MATERIAL",
            "evidence_label": "DIRECTLY_REPRODUCED",
        })

    rec = by_id.get("RULE-00-FOUNDER-STANDING")
    if rec:
        counts = class_counts(rec)
        rows.append({
            "item_id": rec["item_id"],
            "artifact": rec["source_artifact_path"],
            "estate_claim": (
                "alwaysApply: true; titled 'Founder standing authority - Ahmed "
                "Sadek, Obzio'; prepended to every agent turn in this repository"
            ),
            "estate_treats_it_as": "the governing always-applied authority surface",
            "sidecar_finds": counts,
            "segment_count": rec["segment_count"],
            "founder_direct_segments": counts[A.FOUNDER_DIRECT],
            "disagreement": (
                f"{counts[A.FOUNDER_DIRECT]} of {rec['segment_count']} segments are "
                "founder-direct. The surface that governs every turn contains no "
                "founder-verbatim text; it is an agent's rendering of his "
                "authority throughout, which is precisely the artifact class that "
                "produced the protected-surface misattribution "
                "(FOUNDER-AUTHORITY-20260822T2225Z.json). The rule file itself "
                "points at the verbatim record for the founder's words, so this is "
                "not a defect in the file - it is a defect in citing the file as "
                "if it were his words."
            ),
            "severity": "MATERIAL",
            "evidence_label": "DIRECTLY_REPRODUCED",
        })
    return rows


def corpus_disagreements(sidecar: dict) -> list[dict]:
    """Where the sidecar and the corpus's own `speaker_class` differ."""
    rows = []
    for rec in sidecar["items"]:
        legacy_class = rec["legacy"]["fields"].get("speaker_class")
        if not legacy_class:
            continue
        mapped = LEGACY_EQUIVALENT.get(legacy_class)
        present = rec["classes_present"]
        disagrees = rec["is_mixed_authorship"] or (mapped not in present)
        rows.append({
            "item_id": rec["item_id"],
            "legacy_heading": rec["legacy"]["fields"].get("heading"),
            "legacy_speaker_class": legacy_class,
            "legacy_is_founder_corpus": rec["legacy"]["fields"].get("is_founder_corpus"),
            "legacy_granularity": "one class for the whole heading-delimited block",
            "sidecar_segment_count": rec["segment_count"],
            "sidecar_classes_present": present,
            "sidecar_is_mixed": rec["is_mixed_authorship"],
            "disagrees": disagrees,
            "disagreement_kind": (
                "LEGACY_SINGLE_CLASS_HIDES_MIXED_AUTHORSHIP" if rec["is_mixed_authorship"]
                else ("LEGACY_CLASS_NOT_REPRODUCED" if mapped not in present else None)
            ),
            "segments": [
                {"segment_id": s["segment_id"], "lines": [s["line_start"], s["line_end"]],
                 "class": s["authorship_class"], "confidence": s["confidence"],
                 "basis": s["decision_basis"]}
                for s in rec["segments"]
            ],
        })
    return rows


def register_quote_verdicts(sidecar: dict, sources: dict[str, str],
                            register_path: str) -> dict:
    """Locate every register quotation in the segmented view and report verdicts.

    Two passes. Scoped to the governing corpus, which is what the register
    itself cites; and unscoped over every artifact in the sidecar, which is what
    a naive substring check does. The gap between the two passes is the estate's
    substring defect measured rather than asserted.
    """
    probes = A.load_provenance_quotations(register_path)
    corpus_items = [rec["item_id"] for rec in sidecar["items"]
                    if rec["item_id"].startswith("FC-SEG-")]
    rows = []
    for p in probes:
        scoped = A.verdict_for_quote(sidecar, sources, p["quote"],
                                     item_ids=corpus_items)
        unscoped = A.verdict_for_quote(sidecar, sources, p["quote"])
        rows.append({
            "constraint_id": p["constraint_id"],
            "register_provenance_class": p["register_provenance_class"],
            "prior_verdict": p["prior_verdict"],
            "cited_segment_heading": p["cited_segment_heading"],
            "quote": p["quote"],
            "scoped_to_governing_corpus": {
                "verdict": scoped["verdict"],
                "classes_landed_in": scoped["classes_landed_in"],
                "landing_count": scoped["landing_count"],
            },
            "unscoped_over_whole_slice": {
                "verdict": unscoped["verdict"],
                "classes_landed_in": unscoped["classes_landed_in"],
                "landing_count": unscoped["landing_count"],
                "ambiguous": unscoped["ambiguous"],
            },
            "scoping_changes_the_verdict": scoped["verdict"] != unscoped["verdict"],
            "agrees_with_register_when_scoped": (
                (scoped["verdict"] == A.ADMITTED_FOUNDER)
                == (p["register_provenance_class"] == "FOUNDER_AUTHORED")
            ),
        })
    scoped_tally: dict[str, int] = {}
    unscoped_tally: dict[str, int] = {}
    for r in rows:
        k = r["scoped_to_governing_corpus"]["verdict"]
        scoped_tally[k] = scoped_tally.get(k, 0) + 1
        k = r["unscoped_over_whole_slice"]["verdict"]
        unscoped_tally[k] = unscoped_tally.get(k, 0) + 1
    return {
        "probe_count": len(rows),
        "scoped_item_ids": corpus_items,
        "scoped_verdict_tally": scoped_tally,
        "unscoped_verdict_tally": unscoped_tally,
        "scoping_changed_the_verdict_count": sum(
            1 for r in rows if r["scoping_changes_the_verdict"]),
        "disagreement_count_when_scoped": sum(
            1 for r in rows if not r["agrees_with_register_when_scoped"]),
        "probes": rows,
    }


def reconcile_with_the_estates_own_figure(register_path: str,
                                          derestriction_path: str) -> dict:
    """Cross-check the baseline's '17 of 27 misattributed, 10 survived' figure.

    Recomputed from the two registers rather than carried forward, because a
    number quoted from a summary is the thing this lane exists to distrust.
    """
    with open(register_path, encoding="utf-8") as fh:
        new = json.load(fh)
    with open(derestriction_path, encoding="utf-8") as fh:
        old = json.load(fh)
    prior_founder_bound = {c["constraint_id"] for c in old.get("constraints", [])
                           if c.get("verdict") == "FOUNDER_BOUND"}
    survived, overturned, unmapped = [], [], []
    seen = set()
    for c in new.get("constraints", []):
        if c.get("prior_verdict") != "FOUNDER_BOUND":
            continue
        seen.add(c["constraint_id"])
        if c.get("provenance_class") == "FOUNDER_AUTHORED":
            survived.append(c["constraint_id"])
        else:
            overturned.append({"constraint_id": c["constraint_id"],
                               "re_derived_class": c.get("provenance_class")})
    unmapped = sorted(prior_founder_bound - seen)
    return {
        "baseline_claim": "17 of 27 misattributed, 10 survived quotation testing",
        "prior_founder_bound_in_derestriction_register": len(prior_founder_bound),
        "carried_into_the_re_derived_register": len(seen),
        "survived_as_founder_authored": len(survived),
        "overturned": len(overturned),
        "survived_ids": sorted(survived),
        "overturned_detail": sorted(overturned, key=lambda r: r["constraint_id"]),
        "prior_ids_not_carried_forward": unmapped,
        "verdict": ("BASELINE_FIGURE_REPRODUCED"
                    if len(survived) == 10 and len(overturned) == 17
                    else "BASELINE_FIGURE_NOT_REPRODUCED"),
        "evidence_label": "DIRECTLY_REPRODUCED",
    }


def derestriction_founder_bound_check(sidecar: dict, sources: dict[str, str],
                                      path: str) -> dict:
    """The 27 prior FOUNDER_BOUND verdicts, retested by locating their statements.

    The de-restriction register reached FOUNDER_BOUND through document titles and
    commit authorship. Each statement is located in the segmented view; a
    statement that lands nowhere has no founder-authored text behind it at all.
    """
    with open(path, encoding="utf-8") as fh:
        register = json.load(fh)
    rows = []
    for c in register.get("constraints", []):
        if c.get("verdict") != "FOUNDER_BOUND":
            continue
        statement = c.get("statement", "")
        result = A.verdict_for_quote(sidecar, sources, statement)
        rows.append({
            "constraint_id": c.get("constraint_id"),
            "prior_verdict": "FOUNDER_BOUND",
            "statement": statement,
            "sidecar_verdict": result["verdict"],
            "classes_landed_in": result["classes_landed_in"],
            "supported_by_founder_text": result["verdict"] == A.ADMITTED_FOUNDER,
        })
    return {
        "prior_founder_bound_count": len(rows),
        "supported_by_founder_text": sum(1 for r in rows if r["supported_by_founder_text"]),
        "unsupported": sum(1 for r in rows if not r["supported_by_founder_text"]),
        "method_note": (
            "A statement is located as written. The register paraphrased most "
            "constraints, so a miss means 'no verbatim founder text carries this "
            "statement', not 'the founder rejected it'. That is exactly the "
            "distinction the prior method collapsed."
        ),
        "constraints": rows,
    }


def write_json(path: str, payload: dict) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    reread, problems = A.read_back_and_parse(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    return {
        "path": path,
        "size_bytes": len(raw),
        "sha256": A.sha256_bytes(raw),
        "parsed_after_read_back": reread is not None,
        "read_back_problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--commit", required=True,
                        help="the integration commit this run was audited against")
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    present = existing(repo_root)
    missing = [SLICE[k] for k, v in present.items() if v is None]

    sidecar, sources = build(repo_root, args.commit)
    verify = A.verify_sidecar(sidecar, sources)

    register_path = resolve(repo_root, SLICE["provenance_register"])
    quotes = (register_quote_verdicts(sidecar, sources, register_path)
              if os.path.exists(register_path) else
              {"skipped": f"NOT_FOUND {SLICE['provenance_register']}"})

    derestriction_path = resolve(repo_root, SLICE["derestriction_register"])
    prior = (derestriction_founder_bound_check(sidecar, sources, derestriction_path)
             if os.path.exists(derestriction_path) else
             {"skipped": f"NOT_FOUND {SLICE['derestriction_register']}"})

    default_query = A.authority_segments(sidecar)
    opted_query = A.authority_segments(
        sidecar, include=[A.NONFOUNDER_PASTED, A.UNRESOLVED_USER_ROLE])

    report = {
        "report_id": "SCP-C-SLICE-REPORT-20260827-v001",
        "lane": "SCP-SI-01 lane C",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_a_proposal_not_a_binding": True,
        "decision_changed": [],
        "audited_against_integration_commit": args.commit,
        "evidence_label": "DIRECTLY_REPRODUCED",
        "evidence_note": (
            "Every number below is recomputed by this script from the pinned "
            "artifacts in the same run that writes it. Rerun the command in the "
            "README to reproduce."
        ),
        "slice": {
            "paths_read": {k: v for k, v in SLICE.items()},
            "present": {k: v for k, v in present.items() if v},
            "not_found": missing,
        },
        "sidecar_verification": {
            "failures": verify,
            "verdict": "SIDECAR_VERIFIED" if not verify else "SIDECAR_FAILED_VERIFICATION",
        },
        "totals": {
            "item_count": sidecar["item_count"],
            "segment_count": sidecar["segment_count"],
            "mixed_authorship_item_count": sidecar["mixed_authorship_item_count"],
            "class_tally": sidecar["class_tally"],
        },
        "per_item": [
            {"item_id": rec["item_id"],
             "source_artifact_path": rec["source_artifact_path"],
             "role": rec["role"],
             "legacy_speaker_class": rec["legacy"]["fields"].get("speaker_class"),
             "segment_count": rec["segment_count"],
             "classes_present": rec["classes_present"],
             "is_mixed_authorship": rec["is_mixed_authorship"],
             "class_counts": class_counts(rec),
             "adoption_marker_count": len(rec["adoption_markers"]),
             "disavowal_marker_count": len(rec["disavowal_markers"]),
             "adopted_segment_count": rec["adopted_segment_count"]}
            for rec in sidecar["items"]
        ],
        "adoption_finding": {
            "adoption_markers_found": sum(len(rec["adoption_markers"])
                                          for rec in sidecar["items"]),
            "segments_classified_founder_adopted": sidecar["class_tally"][A.FOUNDER_ADOPTED],
            "reading": (
                "FOUNDER_ADOPTED belongs to the material he took, not to his "
                "sentence about taking it. Adoption markers appear in this slice; "
                "no third-party segment in it sits inside an adoption scope, "
                "because the one pasted block in the record carries an explicit "
                "disavowal instead. The class is exercised by fixtures, not by "
                "this slice, and that is the finding rather than a gap."
            ),
            "fixture_exercising_the_class": (
                "workstreams/so02/control-plane/operating-environment/scp-si-01/"
                "lane-c/fixtures/adopted-and-disavowed.md"
            ),
        },
        "query_behaviour": {
            "default_query_segment_count": default_query["segment_count"],
            "default_excluded_classes": default_query["excluded_by_default"],
            "with_both_classes_opted_in_segment_count": opted_query["segment_count"],
            "segments_suppressed_by_default": (
                opted_query["segment_count"] - default_query["segment_count"]),
        },
        "disagreements_with_existing_corpus_classification": corpus_disagreements(sidecar),
        "disagreements_with_estate_claims_about_artifacts":
            estate_claim_disagreements(sidecar),
        "provenance_register_quotation_verdicts": quotes,
        "derestriction_register_prior_founder_bound": prior,
        "reconciliation_with_baseline_figure": (
            reconcile_with_the_estates_own_figure(register_path, derestriction_path)
            if os.path.exists(register_path) and os.path.exists(derestriction_path)
            else {"skipped": "one or both registers NOT_FOUND"}
        ),
    }

    sidecar_path = os.path.join(LANE_DIR, "sidecar",
                                "AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json")
    report_path = os.path.join(LANE_DIR, "sidecar",
                               "SLICE-REPORT-20260827-v001.json")
    written = [write_json(sidecar_path, sidecar), write_json(report_path, report)]

    for w in written:
        status = "parsed" if w["parsed_after_read_back"] else "UNPARSABLE"
        print(f"{status:>10}  {w['sha256'][:16]}  {w['size_bytes']:>8}B  "
              f"{os.path.relpath(w['path'], repo_root)}")
        for p in w["read_back_problems"]:
            print(f"            FAIL {p}")

    print(f"\nitems={sidecar['item_count']} segments={sidecar['segment_count']} "
          f"mixed_items={sidecar['mixed_authorship_item_count']}")
    print(f"tally={sidecar['class_tally']}")
    print(f"verification={report['sidecar_verification']['verdict']}")
    if isinstance(quotes.get("probe_count"), int):
        print(f"register quotations: {quotes['probe_count']} probes")
        print(f"  scoped to governing corpus : {quotes['scoped_verdict_tally']}")
        print(f"  unscoped over whole slice  : {quotes['unscoped_verdict_tally']}")
        print(f"  scoping changed the verdict for "
              f"{quotes['scoping_changed_the_verdict_count']} probes; "
              f"{quotes['disagreement_count_when_scoped']} disagree with the "
              f"register when scoped")
    if isinstance(prior.get("unsupported"), int):
        print(f"prior FOUNDER_BOUND: {prior['prior_founder_bound_count']} tested, "
              f"{prior['supported_by_founder_text']} supported by locatable founder "
              f"text, {prior['unsupported']} not")
    rec = report["reconciliation_with_baseline_figure"]
    if "verdict" in rec:
        print(f"baseline 17/27+10 reconciliation: {rec['verdict']} "
              f"(survived={rec['survived_as_founder_authored']}, "
              f"overturned={rec['overturned']}, "
              f"carried={rec['carried_into_the_re_derived_register']})")

    bad = [w for w in written if not w["parsed_after_read_back"]]
    return 1 if (verify or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
