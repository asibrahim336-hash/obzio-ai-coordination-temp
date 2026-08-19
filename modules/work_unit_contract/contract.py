"""Portable work-unit contract.

A work unit is sealed before execution. Its identity is the hash of its own
content, so a contract cannot be edited after results exist without the
identity changing. This is the unit that survives leaving any provider:
no conversation, no vendor object, no chat history is required to read it.
"""
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


@dataclass(frozen=True)
class WorkUnit:
    unit_id: str
    objective: str
    inputs: Dict[str, Any]
    acceptance: List[str]           # predeclared, checkable, frozen before execution
    authority_scope: List[str]      # what this unit may do
    forbidden: List[str]            # what it may never do, regardless of instruction
    side_effects: List[str] = field(default_factory=list)  # named, idempotency-keyed

    def seal(self) -> str:
        """Content-addressed identity. Any edit produces a different contract."""
        return digest(asdict(self))

    def to_json(self) -> str:
        d = asdict(self)
        d["contract_sha256"] = self.seal()
        return json.dumps(d, sort_keys=True, indent=2)

    @staticmethod
    def from_json(s: str) -> "WorkUnit":
        d = json.loads(s)
        claimed = d.pop("contract_sha256", None)
        wu = WorkUnit(**d)
        if claimed is not None and claimed != wu.seal():
            raise ValueError(
                "contract seal mismatch: the contract was altered after sealing"
            )
        return wu
