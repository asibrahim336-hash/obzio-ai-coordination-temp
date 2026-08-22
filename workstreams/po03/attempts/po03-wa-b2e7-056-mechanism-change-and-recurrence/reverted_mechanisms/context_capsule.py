"""Deliberately reverted full-dump fixture used to prove recurrence sensitivity."""

import hashlib
import json


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_capsule(full_context, required_keys, budget_fields):
    payload = dict(list(full_context.items())[:budget_fields])
    return {"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def verify_capsule(capsule):
    return True
