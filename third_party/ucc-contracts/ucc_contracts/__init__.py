"""ucc-contracts: authoritative shared contracts for the Unified Control Center.

This package contains ONLY primitives, envelopes, validation helpers, schema
loading, lifecycle transition tables, and port DTOs/refusal codes. It contains
no domain services and imports no repository's domain code. All three
repositories (nodectl, Artifact Compiler, VM-Factory) depend on it and must not
maintain divergent copies of these primitives.
"""
from .ids import (
    ID_PREFIXES,
    new_id,
    is_valid_id,
    parse_id,
    is_valid_hash,
    is_safe_relpath,
)
from .schema import load_schema, validate_document, SchemaValidationError
from .transitions import load_transitions, is_legal_transition, TransitionError
from .idempotency import (
    IdempotencyOutcome,
    StoredIdempotencyRecord,
    evaluate_idempotency,
    idempotency_conflict_problem,
)

__all__ = [
    "ID_PREFIXES", "new_id", "is_valid_id", "parse_id",
    "is_valid_hash", "is_safe_relpath",
    "load_schema", "validate_document", "SchemaValidationError",
    "load_transitions", "is_legal_transition", "TransitionError",
    "IdempotencyOutcome", "StoredIdempotencyRecord",
    "evaluate_idempotency", "idempotency_conflict_problem",
]
