"""Idempotency evaluation helper (D2).

Pure decision logic only — no I/O, no storage. This package contains no
domain services (module docstring, `__init__.py`), so persistence (a SQLite
table keyed by (idempotency_key, request_fingerprint) under each owner's own
state root) is each repo's own responsibility; this module is the one place
the *rule* for replay vs. conflict vs. new is written down, so it can't drift
between nodectl / Artifact Compiler / VM-Factory's three implementations.

Locked behaviors (UCC-Standards §15, roadmap M-b):
- identical replay (same key, same request fingerprint) returns the stored
  result verbatim — callers must not re-execute the operation;
- same key with a *different* fingerprint is a refusal (`idempotency_conflict`),
  never a silent overwrite and never a merge;
- an unseen key proceeds — the caller executes and then stores the result;
- a stored result with `disposition: unknown` is never auto-replayed by
  anything in this module; callers must not persist an `unknown` result as a
  replayable record in the first place (reconciliation is a new event, not a
  replay — UCC-Standards §5).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IdempotencyOutcome(str, Enum):
    NEW = "new"          # no record for this key yet — caller should proceed
    REPLAY = "replay"    # same key + same fingerprint — return the stored result verbatim
    CONFLICT = "conflict"  # same key + different fingerprint — refuse, never overwrite


@dataclass(frozen=True)
class StoredIdempotencyRecord:
    """What a caller's own store looks up by `idempotency_key`. `result` is
    the previously-stored `ucc.result` document, returned verbatim on replay."""
    idempotency_key: str
    request_fingerprint: str
    result: dict


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
