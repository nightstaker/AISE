"""Tiny JSON-schema validator covering the subset we use.

Why hand-rolled instead of pulling in ``jsonschema``: the schemas in
``src/aise/schemas/`` only use a small slice (``required``, ``type``,
``oneOf``, ``enum``, ``pattern``, ``minLength``, ``minimum``,
``minItems``, ``minProperties``, ``maxProperties``, ``items``,
``properties``, ``additionalProperties``, ``definitions`` / ``$ref``).
Pulling in a full jsonschema dep + its transitive ``referencing`` /
``rpds-py`` for one validator call per phase is overkill.

The validator returns a list of human-readable error strings (empty
on success). It does NOT raise — callers decide what to do with errors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_JSON = "string|number|integer|boolean|object|array|null"


def _match_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    raise ValueError(f"Unknown type {expected!r}; allowed: {_JSON}")


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local ``#/definitions/foo`` ref against the root schema.
    External refs are not supported (we keep schemas self-contained).
    """
    if not ref.startswith("#/"):
        raise ValueError(f"Only local refs supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"Ref {ref!r} not found in schema")
        node = node[part]
    return node


def _validate_node(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str
) -> list[str]:
    errors: list[str] = []

    # $ref short-circuit
    if "$ref" in schema:
        return _validate_node(value, _resolve_ref(schema["$ref"], root), root, path)

    # oneOf — one and only one must validate
    if "oneOf" in schema:
        matches = sum(
            1
            for sub in schema["oneOf"]
            if not _validate_node(value, sub, root, path)
        )
        if matches != 1:
            errors.append(
                f"{path}: must match exactly one of oneOf branches "
                f"(matched {matches})"
            )
        return errors

    # const
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")

    # type
    expected_type = schema.get("type")
    if expected_type and not _match_type(value, expected_type):
        errors.append(f"{path}: expected type {expected_type!r}, got {type(value).__name__}")
        return errors  # type mismatch ⇒ later checks would be noise

    # enum
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}, got {value!r}")

    # string-specific
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: minLength={schema['minLength']}, got len={len(value)}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(
                f"{path}: must match pattern {schema['pattern']!r}, got {value!r}"
            )

    # numeric-specific
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: minimum={schema['minimum']}, got {value}")

    # array-specific
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: minItems={schema['minItems']}, got len={len(value)}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(value):
                errors.extend(
                    _validate_node(item, item_schema, root, f"{path}[{i}]")
                )

    # object-specific
    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(
                f"{path}: minProperties={schema['minProperties']}, got len={len(value)}"
            )
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(
                f"{path}: maxProperties={schema['maxProperties']}, got len={len(value)}"
            )
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for k, v in value.items():
            sub = props.get(k)
            if sub is not None:
                errors.extend(_validate_node(v, sub, root, f"{path}.{k}"))
        # additionalProperties=False not strictly enforced — most of our
        # schemas allow extras (forward-compat). Honor it only when set
        # explicitly to False.
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                errors.append(f"{path}: additional properties not allowed: {sorted(extra)!r}")

    return errors


def validate(value: Any, schema: dict[str, Any]) -> list[str]:
    """Validate ``value`` against ``schema``. Return list of error strings."""
    return _validate_node(value, schema, schema, "$")


def validate_file(json_path: Path | str, schema_path: Path | str) -> list[str]:
    """Convenience: read both, parse, validate, return errors."""
    with open(json_path, encoding="utf-8") as f:
        value = json.load(f)
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    return validate(value, schema)
