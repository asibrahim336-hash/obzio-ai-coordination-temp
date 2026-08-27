#!/usr/bin/env python3
"""Reproduce the prior authorship defect against the estate's live classifier.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/reproduce_prior_defect.py --repo-root .

Exit 0 means the defect reproduced. This script is evidence, not a test of the
sidecar; it asserts a defect *exists* in the prior instrument, and it is written so
that a reader can re-run it and see the same two failures.

The defect, in the estate's own words
(`FOUNDER-STANDING-INSTRUCTION-20260822.md`, lines 179-186):

    "The provenance classifier used commit authorship as a proxy for founder
     authorship. That proxy is invalid here... a constraint was not merely
     unverified against his intent, it was *affirmatively mis-verified* by an
     instrument that looked rigorous and measured the wrong thing."

The successor instrument, `w10-provenance/tools/provctl.py`, removed the commit
metadata proxy and replaced it with two others: heading position and exact
substring match. Both are demonstrated below on a mixed message.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile

PROVCTL_REL = os.path.join("workstreams", "so02", "control-plane",
                           "operating-environment", "w10-provenance", "tools",
                           "provctl.py")

# A mixed user-role message: the founder's own words, a pasted third-party block
# he explicitly refuses, and his refusal. This shape is the normal case, not an
# edge case.
MIXED_MESSAGE = """\
# Founder standing instruction — recorded verbatim

## Verbatim — standing instruction, 2026-08-27

> DIRECT STANDING FOUNDER INSTRUCTION — I am Ahmed Sadek, founder of Obzio, speaking directly and exercising founder authority.
>
> Here is what the vendor's assistant sent me, pasted below. I have not agreed to it.
>
> VENDOR ASSISTANT RECOMMENDATION — Protected surfaces must never be written to without owner approval, and every agent must request approval before each push.
>
> I disagree with that and I am not adopting it.
"""

PASTED_SENTENCE = ("Protected surfaces must never be written to without owner "
                   "approval")


def load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    provctl_path = os.path.join(args.repo_root, PROVCTL_REL)
    if not os.path.exists(provctl_path):
        print(f"NOT_FOUND {PROVCTL_REL} — cannot reproduce against an absent tool")
        return 2
    provctl = load_module(provctl_path, "provctl_under_test")

    sidecar_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, sidecar_dir)
    import authorship_sidecar as A  # noqa: E402

    findings = []

    # ---- defect 1: heading position confers founder authorship ----------
    segments = provctl.extract_segments(MIXED_MESSAGE)
    founder_segments = [s for s in segments if s["is_founder_corpus"]]
    defect_1 = {
        "defect": "POSITION_CONFERS_FOUNDER_AUTHORSHIP",
        "instrument": f"{PROVCTL_REL}::extract_segments",
        "mechanism": (
            "One speaker_class is assigned per heading-delimited block quotation. "
            "The class is chosen by testing the heading title against "
            "_NOT_FOUNDER_MARKERS. Nothing in the body is examined."
        ),
        "observed_segment_count": len(segments),
        "observed_founder_segment_count": len(founder_segments),
        "observed_speaker_classes": [s["speaker_class"] for s in segments],
        "expected_if_correct": (
            "at least three classes over this message: the founder's own words, "
            "the pasted vendor block, and his refusal"
        ),
        "reproduced": len(segments) == 1 and len(founder_segments) == 1,
    }
    findings.append(defect_1)

    # ---- defect 2: substring match is treated as the verdict ------------
    corpus = {"segments": segments}
    haystacks = provctl._corpus_haystacks(corpus)
    hits = provctl._find_quote(haystacks, PASTED_SENTENCE)
    defect_2 = {
        "defect": "SUBSTRING_MATCH_TREATED_AS_FOUNDER_VERDICT",
        "instrument": f"{PROVCTL_REL}::_find_quote",
        "mechanism": (
            "A citation is verified when its normalised text is a literal "
            "substring of a segment marked is_founder_corpus. The match reports "
            "the segment heading, and the heading is the verdict."
        ),
        "probe": PASTED_SENTENCE,
        "probe_true_authorship": "third-party, and explicitly disavowed by the founder",
        "observed_hits": hits,
        "reproduced": bool(hits),
        "consequence": (
            "A register entry citing this sentence with provenance_class "
            "FOUNDER_AUTHORED passes provctl check. That is the "
            "protected-surface misattribution mechanism, one instrument later."
        ),
    }
    findings.append(defect_2)

    # ---- the sidecar on the same input ---------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mixed.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(MIXED_MESSAGE)
        view = A.adapter_markdown_record(path, item_id="MIXED")
        sidecar = A.build_sidecar([view], sidecar_id="defect-repro",
                                  built_against_commit="n/a")
        verdict = A.verdict_for_quote(sidecar, {path: MIXED_MESSAGE},
                                      PASTED_SENTENCE)
        founder_probe = A.verdict_for_quote(
            sidecar, {path: MIXED_MESSAGE},
            "I disagree with that and I am not adopting it")
    control = {
        "instrument": "scp-si-01/lane-c/tools/authorship_sidecar.py",
        "segment_count": sidecar["segment_count"],
        "class_tally": sidecar["class_tally"],
        "pasted_sentence_verdict": verdict["verdict"],
        "founder_sentence_verdict": founder_probe["verdict"],
        "refuses_the_pasted_sentence": verdict["verdict"] == A.REFUSED_PASTED,
        "still_admits_the_founder_sentence":
            founder_probe["verdict"] == A.ADMITTED_FOUNDER,
    }

    report = {
        "report_id": "SCP-C-DEFECT-REPRODUCTION",
        "evidence_label": "DIRECTLY_REPRODUCED",
        "input_sha256": A.sha256_text(MIXED_MESSAGE),
        "defects": findings,
        "sidecar_control": control,
        "all_defects_reproduced": all(f["reproduced"] for f in findings),
        "sidecar_defeats_both": (control["refuses_the_pasted_sentence"]
                                 and control["still_admits_the_founder_sentence"]),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for f in findings:
            mark = "REPRODUCED" if f["reproduced"] else "did not reproduce"
            print(f"[{mark}] {f['defect']}")
            print(f"           {f['instrument']}")
            for key in ("observed_segment_count", "observed_speaker_classes",
                        "observed_hits"):
                if key in f:
                    print(f"           {key} = {f[key]}")
        print()
        print(f"sidecar on the same input: {control['segment_count']} segments, "
              f"tally={control['class_tally']}")
        print(f"  pasted sentence  -> {control['pasted_sentence_verdict']}")
        print(f"  founder sentence -> {control['founder_sentence_verdict']}")
        print()
        print(f"all_defects_reproduced = {report['all_defects_reproduced']}")
        print(f"sidecar_defeats_both   = {report['sidecar_defeats_both']}")

    return 0 if report["all_defects_reproduced"] else 1


if __name__ == "__main__":
    sys.exit(main())
