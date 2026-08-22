"""Deterministic needle-recall proxy for a5-u04.

No live frontier-model call is available in this dependency-free stdlib
runtime, so 'accepted-result rate at equal reasoning setting' cannot be
measured directly (see the scope_limitation recorded against this unit in
sources.json). What IS measured directly: for a fixed context token/char
budget, does a hashed, relevance-ranked capsule preserve a task-relevant
fact more reliably than naive whole-tree dumping truncated at the same
budget? That is the necessary precondition for the full claim.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

WORD_BANK = [
    "system", "worker", "ledger", "branch", "commit", "artifact", "lease",
    "fence", "queue", "worktree", "manifest", "checkpoint", "outbox", "hash",
    "review", "runner", "policy", "cache", "budget", "capsule", "context",
    "token", "reviewer", "scanner", "recovery", "invariant", "schema",
]


def filler_text(rng: random.Random, target_len: int) -> str:
    words = []
    length = 0
    while length < target_len:
        w = rng.choice(WORD_BANK)
        words.append(w)
        length += len(w) + 1
    return " ".join(words)


@dataclass(frozen=True)
class NeedleTask:
    query_keywords: tuple[str, ...]
    needle_file_idx: int
    needle_chunk_idx: int


def build_corpus(
    rng: random.Random, num_files: int, chunks_per_file: int, chunk_size: int = 200
) -> tuple[list[list[str]], list[NeedleTask]]:
    files: list[list[str]] = []
    tasks: list[NeedleTask] = []
    for file_idx in range(num_files):
        needle_pos = rng.randint(0, chunks_per_file - 1)
        tag = f"needletag{file_idx:04d}"
        chunks = []
        for chunk_idx in range(chunks_per_file):
            if chunk_idx == needle_pos:
                chunk = f"relevant fact for {tag} : the answer is {rng.randint(1000, 9999)} . " + filler_text(
                    rng, chunk_size
                )
                tasks.append(NeedleTask((tag,), file_idx, chunk_idx))
            else:
                chunk = filler_text(rng, chunk_size)
            chunks.append(chunk)
        files.append(chunks)
    return files, tasks


def flatten(files: list[list[str]]) -> list[tuple[int, int, str]]:
    return [(fi, ci, chunk) for fi, chunks in enumerate(files) for ci, chunk in enumerate(chunks)]


def whole_tree_dump(files: list[list[str]], budget_chars: int) -> set[tuple[int, int]]:
    """Admit chunks in natural file order until the budget is exhausted.
    Returns the set of (file_idx, chunk_idx) that survived truncation."""
    admitted: set[tuple[int, int]] = set()
    used = 0
    for fi, ci, chunk in flatten(files):
        cost = len(chunk) + 1
        if used + cost > budget_chars:
            break
        admitted.add((fi, ci))
        used += cost
    return admitted


def hashed_capsule(files: list[list[str]], budget_chars: int, query_keywords: tuple[str, ...]) -> set[tuple[int, int]]:
    """Rank chunks by keyword relevance to this specific query, breaking ties
    by content hash for determinism, and admit greedily until the budget is
    exhausted."""

    def score(chunk: str) -> int:
        return sum(1 for kw in query_keywords if kw in chunk)

    scored = []
    for fi, ci, chunk in flatten(files):
        s = score(chunk)
        if s <= 0:
            continue
        digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        scored.append((-s, digest, fi, ci, chunk))
    scored.sort()

    admitted: set[tuple[int, int]] = set()
    used = 0
    for _, _, fi, ci, chunk in scored:
        cost = len(chunk) + 1
        if used + cost > budget_chars:
            continue
        admitted.add((fi, ci))
        used += cost
    return admitted


def measure_recall(
    files: list[list[str]], tasks: list[NeedleTask], budget_chars: int
) -> dict[str, float]:
    dump_admitted = whole_tree_dump(files, budget_chars)
    dump_hits = sum(1 for t in tasks if (t.needle_file_idx, t.needle_chunk_idx) in dump_admitted)

    capsule_hits = 0
    for t in tasks:
        capsule_admitted = hashed_capsule(files, budget_chars, t.query_keywords)
        if (t.needle_file_idx, t.needle_chunk_idx) in capsule_admitted:
            capsule_hits += 1

    total = len(tasks)
    return {
        "tasks": total,
        "whole_tree_dump_recall": dump_hits / total if total else 0.0,
        "hashed_capsule_recall": capsule_hits / total if total else 0.0,
    }
