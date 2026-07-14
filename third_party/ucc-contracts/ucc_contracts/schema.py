"""JSON Schema loading and validation (Draft 2020-12).

Authority: SPEC-001 §E.9 (schemas + fixtures are the source of truth before
shared models). This module only loads and validates; it defines no domain
logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


class SchemaValidationError(Exception):
    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"{schema_name}: {'; '.join(errors)}")


def _registry() -> dict[str, dict]:
    reg: dict[str, dict] = {}
    for path in _SCHEMA_DIR.glob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        reg[doc["$id"]] = doc
    return reg


def load_schema(name: str) -> dict[str, Any]:
    """Load a schema by file stem (e.g. 'event') or by $id."""
    path = _SCHEMA_DIR / f"{name}.schema.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    reg = _registry()
    if name in reg:
        return reg[name]
    raise FileNotFoundError(f"No schema {name!r} under {_SCHEMA_DIR}.")


def _resolver_validator(schema: dict) -> Draft202012Validator:
    # Local $ref resolution across sibling schemas via the modern referencing
    # registry (jsonschema >= 4.18). Every schema is registered under its $id.
    from referencing import Registry, Resource

    resources = [
        (doc["$id"], Resource.from_contents(doc))
        for doc in _registry().values()
    ]
    registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def validate_document(name: str, document: dict) -> None:
    """Validate `document` against schema `name`. Raise SchemaValidationError."""
    schema = load_schema(name)
    validator = _resolver_validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        msgs = [f"{list(e.path)}: {e.message}" for e in errors]
        raise SchemaValidationError(name, msgs)
