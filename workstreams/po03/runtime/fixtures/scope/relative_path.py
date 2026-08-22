"""Scope fixture: repository-relative paths are portable and must not be flagged.

Every legitimate PO-03 path reference looks like this. If the prober flagged
these, the gate would be unsatisfiable and would be turned off.
"""

LEDGER = "workstreams/po03/control/events/ledger.jsonl"
RECEIPT = "receipts/po03/2026-08-22/ci-clean-clone.json"
WORKFLOW = ".github/workflows/po03-path-scope.yml"
