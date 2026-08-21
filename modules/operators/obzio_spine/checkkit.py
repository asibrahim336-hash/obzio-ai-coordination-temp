"""Deterministic check harness.

A check is a pure function of files on disk. It returns findings. It does not
print, does not raise on a normal failure, and never repairs anything -- a
check that fixes what it finds cannot be trusted to report."""

from dataclasses import dataclass, asdict, field
from typing import List


@dataclass
class Finding:
    check: str
    severity: str          # "FAIL" | "WARN"
    message: str
    evidence: dict = field(default_factory=dict)

    def to_json(self):
        return asdict(self)


@dataclass
class CheckReport:
    pack: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def failures(self):
        return [f for f in self.findings if f.severity == "FAIL"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "WARN"]

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, check, message, **evidence):
        self.findings.append(Finding(check, "FAIL", message, evidence))

    def warn(self, check, message, **evidence):
        self.findings.append(Finding(check, "WARN", message, evidence))

    def to_json(self):
        return {
            "pack": self.pack,
            "passed": self.passed,
            "failure_count": len(self.failures),
            "warning_count": len(self.warnings),
            "findings": [f.to_json() for f in self.findings],
        }

    def summary(self) -> str:
        return (
            f"{self.pack}: {'PASS' if self.passed else 'FAIL'} "
            f"({len(self.failures)} failures, {len(self.warnings)} warnings)"
        )
