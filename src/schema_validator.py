"""
schema_validator.py
Runtime JSON Schema validation at major emission boundaries.

Provides cached validators for the JSON Schemas in ``schema/``.
Schemas are loaded once on first use and compiled into
``Draft202012Validator`` instances for reuse.

Two validation modes:
- ``validate_payload`` — returns error messages (non-raising).
- ``assert_valid``     — raises ``SchemaValidationError`` on failure.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

_VALIDATOR_CACHE: dict[str, jsonschema.Draft202012Validator] = {}


class SchemaValidationError(ValueError):
    """Raised when an internal artifact fails runtime schema validation."""


def _load_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    """Load and cache a Draft 2020-12 validator for *schema_name*."""
    if schema_name not in _VALIDATOR_CACHE:
        path = _SCHEMA_DIR / schema_name
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.Draft202012Validator.check_schema(schema)
        _VALIDATOR_CACHE[schema_name] = jsonschema.Draft202012Validator(schema)
    return _VALIDATOR_CACHE[schema_name]


def validate_payload(instance: dict[str, Any], schema_name: str) -> list[str]:
    """Validate *instance* against the named schema.

    Returns a list of human-readable error messages.  Empty list means valid.
    """
    validator = _load_validator(schema_name)
    return [e.message for e in validator.iter_errors(instance)]


def assert_valid(instance: dict[str, Any], schema_name: str) -> None:
    """Validate *instance* against the named schema; raise on failure.

    Use this for internal boundaries where schema violations indicate a
    code bug (e.g., provenance reports, route records).
    """
    errors = validate_payload(instance, schema_name)
    if errors:
        raise SchemaValidationError(
            f"Schema {schema_name!r} validation failed: {'; '.join(errors)}"
        )
