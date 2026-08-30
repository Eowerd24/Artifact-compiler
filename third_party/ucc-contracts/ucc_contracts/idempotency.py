"""Idempotency evaluation helper (D2 / DC-001 / S2-C).

Pure decision logic only — no I/O, no storage. This package contains no
domain services (module docstring, `__init__.py`), so persistence (a SQLite
table keyed by (idempotency_key, request_fingerprint) under each owner's own
state root) is each repo's own responsibility; this module is the one place
the *rule* for replay vs. conflict vs. new is written down, so it can't drift
between nodectl / Artifact Compiler / VM-Factory's three implementations.

Locked behaviors (UCC-Standards §15, roadmap M-b, S2-C):
- identical replay (same key, same request fingerprint) returns the stored
  result verbatim — callers must not re-execute the operation;
- same key with a *different* fingerprint is a refusal (`idempotency_conflict`),
  never a silent overwrite and never a merge;
- an unseen key proceeds — the caller executes and then stores the result;
- a stored result with `disposition: unknown` evaluates as `in_flight`
  (`outcome_unknown`), never auto-replayed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IdempotencyOutcome(str, Enum):
    NEW = "new"          # no record for this key yet — caller should proceed
    REPLAY = "replay"    # same key + same fingerprint — return the stored result verbatim
    CONFLICT = "conflict"  # same key + different fingerprint — refuse, never overwrite
    IN_FLIGHT = "in_flight"  # same key + disposition unknown — outcome unknown, reconcile first


@dataclass(frozen=True)
class StoredIdempotencyRecord:
    """What a caller's own store looks up by `idempotency_key`. `result` is
    the previously-stored `ucc.result` document, returned verbatim on replay."""
    idempotency_key: str
    request_fingerprint: str
    result: dict
    disposition: Optional[str] = None


def evaluate_idempotency(
    idempotency_key: str,
    request_fingerprint: str,
    stored: Optional[StoredIdempotencyRecord],
) -> IdempotencyOutcome:
    """The one shared decision: given what (if anything) is stored for this
    key, what should the caller do? Raises ValueError if the caller passes a
    stored record for the wrong key — that is a caller bug (wrong lookup),
    not a case this function's outcome vocabulary should paper over."""
    if stored is None:
        return IdempotencyOutcome.NEW
    if stored.idempotency_key != idempotency_key:
        raise ValueError(
            f"stored record key {stored.idempotency_key!r} does not match "
            f"the lookup key {idempotency_key!r}"
        )
    if stored.request_fingerprint == request_fingerprint:
        disp = stored.disposition
        if disp is None and isinstance(stored.result, dict):
            disp = stored.result.get("disposition")
        if disp == "unknown":
            return IdempotencyOutcome.IN_FLIGHT
        return IdempotencyOutcome.REPLAY
    return IdempotencyOutcome.CONFLICT


def idempotency_conflict_problem(
    *, request_id: str, operation_id: str, correlation_id: str,
    message: str = "idempotency key reused with a different request body",
) -> dict:
    """Build the typed `ucc.problem` (kind=conflict, code=idempotency_conflict)
    a caller returns on `IdempotencyOutcome.CONFLICT`, so all three repos
    produce byte-identical problem shapes for the same situation."""
    return {
        "schema": "ucc.problem",
        "schema_version": 1,
        "kind": "conflict",
        "code": "idempotency_conflict",
        "message": message,
        "retryable": False,
        "request_id": request_id,
        "operation_id": operation_id,
        "correlation_id": correlation_id,
    }


def outcome_unknown_problem(
    *, request_id: str, operation_id: str, correlation_id: str,
    message: str = "a prior dispatch has an unknown outcome; reconcile it before retrying",
) -> dict:
    """Build the typed `ucc.problem` (kind=outcome_unknown, code=outcome_unknown)
    a caller returns on `IdempotencyOutcome.IN_FLIGHT`."""
    return {
        "schema": "ucc.problem",
        "schema_version": 1,
        "kind": "outcome_unknown",
        "code": "outcome_unknown",
        "message": message,
        "retryable": False,
        "request_id": request_id,
        "operation_id": operation_id,
        "correlation_id": correlation_id,
    }
