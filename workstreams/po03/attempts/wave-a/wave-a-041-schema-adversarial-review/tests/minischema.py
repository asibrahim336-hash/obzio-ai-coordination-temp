#!/usr/bin/env python3
"""Dependency-free checker for the JSON Schema subset used by the PO-03 contracts.

The commission requires clean-runtime execution without third-party packages, so
this reviewer cannot rely on `jsonschema` being importable.  This module covers
exactly the keywords that appear in `contracts/transactional-result.schema.json`:
type, const, enum, required, properties, additionalProperties, items, anyOf,
minLength, pattern, minimum and local `$ref` into `$defs`.

When `jsonschema` *is* importable the harness cross-checks both implementations
and records disagreement rather than trusting this one.
"""

from __future__ import annotations

import re
from typing import Any

_IGNORED = {"$schema", "$id", "title", "description", "$comment", "$defs", "examples"}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        # JSON Schema does not treat booleans as integers.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError(f"unsupported type keyword: {expected}")


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref: {ref}")
    node: Any = root
    for token in ref[2:].split("/"):
        node = node[token.replace("~1", "/").replace("~0", "~")]
    return node


def validate(instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    root = schema if root is None else root
    errors: list[str] = []

    if "$ref" in schema:
        return validate(instance, _resolve(schema["$ref"], root), root, path)

    for keyword, constraint in schema.items():
        if keyword in _IGNORED or keyword in {"properties", "required", "additionalProperties", "items"}:
            continue
        if keyword == "type":
            expected = constraint if isinstance(constraint, list) else [constraint]
            if not any(_type_ok(instance, name) for name in expected):
                errors.append(f"{path}: type is not {expected}")
        elif keyword == "const":
            if instance != constraint:
                errors.append(f"{path}: not const {constraint!r}")
        elif keyword == "enum":
            if instance not in constraint:
                errors.append(f"{path}: {instance!r} not in enum")
        elif keyword == "minLength":
            if isinstance(instance, str) and len(instance) < constraint:
                errors.append(f"{path}: shorter than minLength {constraint}")
        elif keyword == "pattern":
            if isinstance(instance, str) and re.search(constraint, instance) is None:
                errors.append(f"{path}: does not match pattern {constraint}")
        elif keyword == "minimum":
            if isinstance(instance, (int, float)) and not isinstance(instance, bool) and instance < constraint:
                errors.append(f"{path}: below minimum {constraint}")
        elif keyword == "anyOf":
            if not any(not validate(instance, sub, root, path) for sub in constraint):
                errors.append(f"{path}: matches no anyOf branch")
        else:
            raise ValueError(f"unsupported keyword in schema subset: {keyword}")

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}.{name}: required property missing")
        properties = schema.get("properties", {})
        for name, value in instance.items():
            if name in properties:
                errors.extend(validate(value, properties[name], root, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{name}: additional property not permitted")

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], root, f"{path}[{index}]"))

    return errors
