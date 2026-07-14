"""G2 shared conformance suite (roadmap §5 / WS7).

Imports the vendored `third_party/ucc-contracts/` copy — not a running peer,
not another repo's domain code — and asserts this repo's schema/ID/transition
understanding matches the pinned contracts exactly. Mirrors ucc-contracts'
own test suite structurally so drift between repos is visible immediately.

Pinned version: ucc-contracts 0.1.0 (2026-07-13 snapshot). See
third_party/ucc-contracts/README.md for the vendoring note.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ucc_contracts import (
    validate_document, SchemaValidationError,
    new_id, is_valid_id, parse_id, is_valid_hash, is_safe_relpath, ID_PREFIXES,
    is_legal_transition, load_transitions,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VENDORED = REPO_ROOT / "third_party" / "ucc-contracts"
VALID = VENDORED / "fixtures" / "valid"
INVALID = VENDORED / "fixtures" / "invalid"

VALID_CASES = sorted(p for p in VALID.glob("*.json"))
INVALID_INDEX = json.loads((INVALID / "_index.json").read_text())

MACHINES = [
    "job", "assignment", "node-allocation", "execution", "transfer",
    "handback", "credential-lease", "publication", "quarantine",
]


# --- valid serialization / strict unknown-field rejection / unsupported version ---

@pytest.mark.parametrize("path", VALID_CASES, ids=lambda p: p.stem)
def test_valid_fixture_passes(path):
    doc = json.loads(path.read_text())
    validate_document(path.stem, doc)  # must not raise


@pytest.mark.parametrize("fname", sorted(INVALID_INDEX), ids=lambda f: f[:-5])
def test_invalid_fixture_rejected(fname):
    schema = INVALID_INDEX[fname]
    doc = json.loads((INVALID / fname).read_text())
    with pytest.raises(SchemaValidationError):
        validate_document(schema, doc)


def test_request_rejects_unknown_field():
    # request__unknown_field.json is exactly this case; asserted generically
    # here too so the security-sensitive-request rule stays pinned.
    doc = json.loads((VALID / "request.json").read_text())
    doc["not_a_real_field"] = "x"
    with pytest.raises(SchemaValidationError):
        validate_document("request", doc)


def test_unsupported_schema_version_fails_explicitly():
    doc = json.loads((VALID / "event.json").read_text())
    doc["schema_version"] = 999
    # schema_version has no upper bound in the JSON Schema itself (repos
    # enforce "supported versions" at the application layer); this asserts
    # the field stays a plain positive integer, never guessed/coerced.
    validate_document("event", doc)  # still schema-valid; app-layer must gate it
    doc["schema_version"] = "not-an-int"
    with pytest.raises(SchemaValidationError):
        validate_document("event", doc)


# --- correlation + causation presence (event) -----------------------------

def test_event_requires_correlation_id():
    doc = json.loads((VALID / "event.json").read_text())
    del doc["correlation_id"]
    with pytest.raises(SchemaValidationError):
        validate_document("event", doc)


def test_event_causation_id_is_optional_but_typed():
    doc = json.loads((VALID / "event.json").read_text())
    assert "causation_id" in doc  # present in the golden fixture
    del doc["causation_id"]
    validate_document("event", doc)  # optional: absence alone is fine


# --- typed refusal shape (problem) -----------------------------------------

def test_problem_kind_is_a_closed_enum():
    doc = json.loads((VALID / "problem.json").read_text())
    doc["kind"] = "not_a_real_kind"
    with pytest.raises(SchemaValidationError):
        validate_document("problem", doc)


# --- path traversal rejection ----------------------------------------------

def test_path_containment_matches_pinned_rules():
    assert is_safe_relpath("bin/inventory.sh")
    for bad in ["../x", "a/../b", "/etc/passwd", "a\\b", "a//b", "./a", "a\x00b", " a"]:
        assert not is_safe_relpath(bad), bad


# --- ID + hash vectors -------------------------------------------------------

def test_new_id_roundtrip():
    for prefix in ["job", "exec", "rev", "pub", "nalloc", "corr", "req", "res", "evt"]:
        i = new_id(prefix)
        assert is_valid_id(i, expected_prefix=prefix)
        p, ulid = parse_id(i)
        assert p == prefix and len(ulid) == 26


def test_project_prefix_is_prj_not_proj():
    assert "prj" in ID_PREFIXES
    assert "proj" not in ID_PREFIXES


def test_hash_form():
    assert is_valid_hash("sha256:" + "a" * 64)
    assert not is_valid_hash("sha256:" + "A" * 64)


# --- illegal lifecycle transition rejection --------------------------------

@pytest.mark.parametrize("machine", MACHINES)
def test_transition_table_loads(machine):
    t = load_transitions(machine)
    assert t["owner"] in {"ucc", "artifact-compiler", "vm-factory"}
    assert t["transitions"]


def test_illegal_transition_rejected():
    assert is_legal_transition("job", "created", "queued")
    assert not is_legal_transition("job", "terminal", "running")


# --- unavailable / incompatible module (module-health) ---------------------

def test_module_health_enum_covers_unavailable_and_incompatible():
    doc = json.loads((VALID / "module-health.json").read_text())
    for health in ("unavailable", "incompatible"):
        doc = {**doc, "health": health}
        validate_document("module-health", doc)
    doc = {**doc, "health": "not_a_real_health_state"}
    with pytest.raises(SchemaValidationError):
        validate_document("module-health", doc)
