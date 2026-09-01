#!/usr/bin/env python3
"""Build an exact-model qualification table from the live OpenRouter catalogue.

The point of the table is the distinction the founder's constraint depends on:
"open weights" and "runnable on the founder's own hardware" are different
properties. `hugging_face_id` evidences the first; parameter scale evidences the
second. A model can be fully open and still be unrunnable on a MacBook.
"""

from __future__ import annotations

import json
import re
import sys

FAMILIES = {
    "kimi": r"^moonshotai/",
    "qwen": r"^qwen/",
    "deepseek": r"^deepseek/",
    "glm": r"^z-ai/",
    "llama": r"^meta-llama/",
    "mistral": r"^mistralai/",
    "gpt-oss": r"^openai/gpt-oss",
    "gemma": r"^google/gemma",
}


def usd_per_mtok(v) -> float | None:
    try:
        return round(float(v) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def main() -> int:
    src = sys.argv[1]
    catalogue = json.load(open(src))
    models = catalogue["data"]

    rows = []
    for m in models:
        mid = m["id"]
        fam = next((f for f, pat in FAMILIES.items() if re.search(pat, mid)), None)
        if not fam:
            continue
        pricing = m.get("pricing") or {}
        arch = m.get("architecture") or {}
        rows.append(
            {
                "family": fam,
                "id": mid,
                "canonical_slug": m.get("canonical_slug"),
                "name": m.get("name"),
                "open_weights_hf_id": m.get("hugging_face_id") or None,
                "weights_published": bool(m.get("hugging_face_id")),
                "context_length": m.get("context_length"),
                "input_modalities": arch.get("input_modalities"),
                "usd_per_mtok_input": usd_per_mtok(pricing.get("prompt")),
                "usd_per_mtok_output": usd_per_mtok(pricing.get("completion")),
                "supports_tools": "tools" in (m.get("supported_parameters") or []),
                "supports_structured_outputs": "structured_outputs"
                in (m.get("supported_parameters") or []),
                "supports_reasoning": bool(m.get("reasoning")),
                "knowledge_cutoff": m.get("knowledge_cutoff"),
            }
        )

    rows.sort(key=lambda r: (r["family"], r["id"]))
    json.dump(
        {
            "source": "https://openrouter.ai/api/v1/models",
            "evidence_class": "DIRECTLY_REPRODUCED",
            "catalogue_total_models": len(models),
            "rows_in_named_families": len(rows),
            "rows": rows,
        },
        sys.stdout,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
