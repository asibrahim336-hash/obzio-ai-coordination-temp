"""Two independently frozen review methodologies for a5-u03.

Both freeze their criteria (the exact anti-patterns / the exact property
comparison strategy) before being pointed at the corpus, and neither is
tuned per-snippet at review time -- each is a fixed, general-purpose checker
applied blind to whichever function it is given.
"""

from __future__ import annotations

import ast
import inspect
import random
from pathlib import Path
from typing import Callable


class StaticPatternReviewer:
    """Family A proxy: a fixed set of syntactic anti-pattern checks over the
    AST. Frozen before this unit's corpus was written."""

    name = "static_pattern_reviewer"

    def review(self, fn: Callable) -> set[str]:
        source = inspect.getsource(fn)
        tree = ast.parse(source)
        findings: set[str] = set()
        with_open_call_ids = {
            id(item.context_expr)
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            for item in node.items
            if isinstance(item.context_expr, ast.Call) and getattr(item.context_expr.func, "id", None) == "open"
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.add("bare_except")
            if isinstance(node, ast.FunctionDef):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        findings.add("mutable_default_argument")
            if isinstance(node, ast.Global):
                findings.add("global_mutable_state_without_reset")
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "open"
                and id(node) not in with_open_call_ids
            ):
                findings.add("resource_leak")
        return findings


class PropertyBasedReviewer:
    """Family B proxy: run each candidate against a reference implementation
    on generated inputs and flag a defect class whenever an output diverges.
    Frozen before this unit's corpus was written -- the property is "outputs
    of the candidate and the reference must match on a generated input",
    with no snippet-specific knowledge of what the intended bug is."""

    name = "property_based_reviewer"

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def review_dynamic(
        self, defect_class: str, candidate: Callable, reference: Callable, inputs: list[tuple]
    ) -> bool:
        """Return True (defect found) iff candidate diverges from reference on
        any generated input, including candidate raising where reference does
        not."""
        for args in inputs:
            try:
                candidate_result = candidate(*args)
            except Exception as exc:  # noqa: BLE001 -- an unexpected raise IS the defect signal
                return True
            reference_result = reference(*args)
            if candidate_result != reference_result:
                return True
        return False

    def review_static_only_snippet(self, name: str, candidate: Callable, tmp_dir: Path) -> bool:
        """Run exactly one scoped, valid, fresh-call correctness check per
        static-only snippet. Returns True only if that scoped property is
        violated -- by design these snippets do not violate it, which is the
        finding this unit records, not an oversight."""
        from .review_corpus_u03 import static_defect_fresh_call_args

        args = static_defect_fresh_call_args(name, tmp_dir)
        if name == "bare_except":
            return candidate(*args) != 42
        if name == "mutable_default_argument":
            return candidate(*args) != ["x"]
        if name == "global_mutable_state_without_reset":
            result = candidate(*args)
            return not (isinstance(result, int) and result == candidate.__globals__["_call_counter"]["n"])
        if name == "resource_leak":
            return candidate(*args) != "hello"
        raise ValueError(name)
