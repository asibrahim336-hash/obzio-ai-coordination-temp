#!/usr/bin/env python3
"""Build the frozen, line-delimited PO-03 method hypothesis register."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


OBSERVED = "2026-08-22"
ROOT = Path(__file__).resolve().parent

SOURCES = {
    "anthropic-context": {
        "publisher": "Anthropic",
        "title": "Effective context engineering for AI agents",
        "url": "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents",
        "fetch_status": "HTTP_200",
        "page_sha256": "a7e9bdb6ee08624ba94ad5b0d23c4e5a68796e3692a978d3eb502a56945f5108",
        "text": (
            "Studies on needle-in-a-haystack style benchmarking have uncovered the concept "
            "of context rot: as the number of tokens in the context window increases, the "
            "model’s ability to accurately recall information from that context decreases."
        ),
    },
    "openai-evals": {
        "publisher": "OpenAI",
        "title": "Working with evals",
        "url": "https://platform.openai.com/docs/guides/evals",
        "fetch_status": "HTTP_200",
        "page_sha256": "f2ea0f6fa4e870cf2ac9a94a67ceaa6a47cc3d7d7937c017d574a3674c1aafd1",
        "text": (
            "Evaluations (often called evals) test model outputs to ensure they meet style "
            "and content criteria that you specify."
        ),
    },
    "cursor-subagents": {
        "publisher": "Cursor",
        "title": "August 19, 2026 changelog",
        "url": "https://cursor.com/changelog/08-19-26",
        "fetch_status": "HTTP_200",
        "page_sha256": "56417018ad768b2c956c4de95713f7f88c7765f81f2f872a3e7b2d8e321ddd48",
        "text": (
            "Subagents can now run on their own virtual machines. Each gets an isolated "
            "copy of the project with clean context in its own cloud environment. Have "
            "subagents test the parent agent's changes in fresh environments or swarm "
            "independent fixes without collisions."
        ),
    },
    "microservices-outbox": {
        "publisher": "microservices.io",
        "title": "Pattern: Transactional outbox",
        "url": "https://microservices.io/patterns/data/transactional-outbox.html",
        "fetch_status": "HTTP_200",
        "page_sha256": "4a86d3fb29ea43f67802cbe0ed94763ab0691684525e394d8e6619842b8cc3a5",
        "text": (
            "Messages are guaranteed to be sent if and only if the database transaction "
            "commits."
        ),
    },
    "temporal-recovery": {
        "publisher": "Temporal",
        "title": "Workflow Execution",
        "url": "https://docs.temporal.io/workflow-execution",
        "fetch_status": "HTTP_200",
        "page_sha256": "ff54921cd385e396ede8ca74ce7525f1e93f9e5af1cbf7f1c563ab4e30774561",
        "text": (
            "The Temporal Platform ensures the state of the Workflow Execution persists "
            "in the face of failures and outages and resumes execution from the latest state."
        ),
    },
    "google-overload": {
        "publisher": "Google SRE",
        "title": "Handling Overload",
        "url": "https://sre.google/sre-book/handling-overload/",
        "fetch_status": "HTTP_200",
        "page_sha256": "8ca912a82390e7f61e8bbae7baab3a74489f5068d71dee1ff24aed99375e0373",
        "text": (
            "No matter how efficient your load balancing policy, eventually some part of "
            "your system will become overloaded. Gracefully handling overload conditions "
            "is fundamental to running a reliable serving system."
        ),
    },
    "fowler-idempotent": {
        "publisher": "Martin Fowler",
        "title": "Idempotent Receiver",
        "url": "https://martinfowler.com/articles/patterns-of-distributed-systems/idempotent-receiver.html",
        "fetch_status": "HTTP_200",
        "page_sha256": "d6ad2f51dcaac9733617d185959480cbb9c7d5982bf7e903efd21269836387ad",
        "text": (
            "Identify requests from clients uniquely so you can ignore duplicate requests "
            "when client retries."
        ),
    },
    "fowler-wal": {
        "publisher": "Martin Fowler",
        "title": "Write-Ahead Log",
        "url": "https://martinfowler.com/articles/patterns-of-distributed-systems/write-ahead-log.html",
        "fetch_status": "HTTP_200",
        "page_sha256": "7195b75918c1d8ddea5cecdc8b3567c966eae69e2daa414e62f86e538cd79d73",
        "text": "Store each state change as a command in a file on a hard disk.",
    },
    "google-load-shedding": {
        "publisher": "Google SRE",
        "title": "Addressing Cascading Failures",
        "url": "https://sre.google/sre-book/addressing-cascading-failures/",
        "fetch_status": "HTTP_200",
        "page_sha256": "f16f9a582bab016af83c9393e56d7571ba91b49e371bd6b55e7a482c041dddb3",
        "text": (
            "Servers should protect themselves from becoming overloaded and crashing. "
            "When overloaded at either the frontend or backend layers, fail early and cheaply."
        ),
    },
    "anthropic-evaluator": {
        "publisher": "Anthropic",
        "title": "Building effective agents",
        "url": "https://www.anthropic.com/engineering/building-effective-agents",
        "fetch_status": "HTTP_200",
        "page_sha256": "c1fd151557284c47c744cc2297d8ceaa5fc45fa7e0a0dad630b7022b87676490",
        "text": (
            "This workflow is particularly effective when we have clear evaluation criteria, "
            "and when iterative refinement provides measurable value."
        ),
    },
    "anthropic-parallel": {
        "publisher": "Anthropic",
        "title": "Building effective agents",
        "url": "https://www.anthropic.com/engineering/building-effective-agents",
        "fetch_status": "HTTP_200",
        "page_sha256": "c1fd151557284c47c744cc2297d8ceaa5fc45fa7e0a0dad630b7022b87676490",
        "text": (
            "Parallelization is effective when the divided subtasks can be parallelized "
            "for speed, or when multiple perspectives or attempts are needed for higher "
            "confidence results."
        ),
    },
    "aws-outbox": {
        "publisher": "Amazon Web Services",
        "title": "Transactional outbox pattern",
        "url": "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html",
        "fetch_status": "HTTP_200",
        "page_sha256": "8444f45302b4af60a33ae465c2fac9a48190a915a5c2b1f893692799b6546d7f",
        "text": (
            "The events processing service might send out duplicate messages or events, "
            "so we recommend that you make the consuming service idempotent by tracking "
            "the processed messages."
        ),
    },
}

SPECS = [
    ("H-001", "anthropic-context", "Bounded hashed context capsules improve exact task-field recovery relative to indiscriminate context dumping under an equal admission budget.", "exact_field_recovery_delta", "less_than_or_equal", 0.20, 100),
    ("H-002", "openai-evals", "Freezing explicit acceptance criteria before seeing producer output reduces false-green acceptance on seeded defective results.", "false_green_rate_reduction", "less_than_or_equal", 0.20, 200),
    ("H-003", "cursor-subagents", "Blind review in an independently isolated different-family runtime detects seeded defects missed by a same-family reviewer.", "cross_family_incremental_detection_rate", "less_than_or_equal", 0.0, 120),
    ("H-004", "microservices-outbox", "A committed outbox plus hash-verified read-back recovers every result after injected return-channel loss.", "recovered_result_fraction", "less_than", 1.0, 200),
    ("H-005", "temporal-recovery", "Monotonic checkpoints reduce completed-step rework after identical induced failures relative to all-or-nothing replay.", "rework_reduction_fraction", "less_than_or_equal", 0.0, 120),
    ("H-006", "google-overload", "Attempt concurrency above fixed acceptance and recovery capacity reduces independently accepted good-result throughput.", "high_minus_capacity_matched_good_throughput", "greater_than_or_equal", 0.0, 200),
    ("H-007", "fowler-idempotent", "Tracking durable request identifiers prevents duplicate side effects under deterministic retries.", "duplicate_side_effect_fraction", "greater_than", 0.0, 100),
    ("H-008", "fowler-wal", "Writing intended state changes before acknowledgement prevents acknowledged-action loss after restart.", "acknowledged_action_loss_fraction", "greater_than", 0.0, 100),
    ("H-009", "google-load-shedding", "Bounded admission with early rejection lowers overload crash rate relative to accepting every request.", "crash_rate_reduction", "less_than_or_equal", 0.0, 100),
    ("H-010", "anthropic-evaluator", "An evaluator-optimizer loop with frozen criteria improves seeded-result quality over one-pass generation.", "quality_score_delta", "less_than_or_equal", 0.0, 100),
    ("H-011", "anthropic-parallel", "Independent parallel attempts plus deterministic aggregation reduce wrong answers relative to a single matched attempt.", "wrong_answer_rate_reduction", "less_than_or_equal", 0.0, 100),
    ("H-012", "aws-outbox", "An idempotent outbox consumer prevents duplicate result ingestion under relay replay.", "duplicate_ingestion_fraction", "greater_than", 0.0, 100),
]


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def build_entry(spec: tuple[object, ...]) -> dict[str, object]:
    hypothesis_id, source_key, hypothesis, metric, comparator, threshold, sample_size = spec
    source = dict(SOURCES[str(source_key)])
    source["observed_at"] = OBSERVED
    source["relied_text_sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    refutation = {
        "metric": metric,
        "comparator": comparator,
        "threshold": threshold,
        "sample_size": sample_size,
        "reject_when": f"{metric} is {comparator.replace('_', ' ')} {threshold}",
    }
    frozen = {
        "hypothesis_id": hypothesis_id,
        "hypothesis": hypothesis,
        "source_identity": source,
        "source_claim": source["text"],
        "refutation_condition": refutation,
        "preregistered_at": "2026-08-22T07:12:00Z",
        "decision_changed": [],
    }
    frozen["hypothesis_hash"] = hashlib.sha256(canonical(frozen)).hexdigest()
    return frozen


def main() -> int:
    entries = [build_entry(spec) for spec in SPECS]
    destination = ROOT / "hypotheses.jsonl"
    destination.write_bytes(b"".join(canonical(entry) for entry in entries))
    print(json.dumps({"entries": len(entries), "ledger_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
