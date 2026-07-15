"""Idempotent wrapper around `perform_import` (M-b — closes G2's request/
result/problem + idempotency requirement for one real AC operation).

Additive: `perform_import` itself is untouched, so every existing caller and
test keeps working exactly as before. This wrapper is the opt-in path that
builds+validates real `ucc.request`/`ucc.result`/`ucc.problem` envelopes
around it and adds idempotent replay.

Scope decisions (see PROGRESS.md / roadmap M-b for the full write-up):
- `--dry-run` bypasses this wrapper entirely and calls `perform_import`
  directly, returning the plain `ImportOutcome` — dry-run needs no dedup
  guarantee (it's side-effect-free and safely repeatable), and building an
  envelope around it would risk violating the locked dry-run-no-write
  invariant if done carelessly. Simplest correct answer: don't route it
  through the store at all.
- The wrapper commits an in-flight record before calling `perform_import`.
  A definite refusal removes it; an ambiguous exception leaves it in place,
  so a retry refuses until operator reconciliation instead of importing twice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ucc_contracts import new_id, validate_document
from ucc_contracts.idempotency import idempotency_conflict_problem

from .cli import ImportOutcome, perform_import
from .config import SoloctlConfig
from .errors import IdempotencyConflict, OutcomeUnknown, SoloctlError
from .idempotency_store import (
    IdempotencyOutcome,
    IdempotencyStore,
    evaluate_idempotency,
    request_fingerprint,
)
from .importers.registry import ImporterRegistry
from .library.paths import LibraryPaths
from .ucc_events import ucc_now_iso

OPERATION_TYPE = "transcript.import"


def perform_import_idempotent(
    config: SoloctlConfig, path: Path, *,
    idempotency_key: str,
    adapter: Optional[str] = None,
    conversation_id: Optional[str] = None,
    title: Optional[str] = None,
    dry_run: bool = False,
    registry: Optional[ImporterRegistry] = None,
) -> dict | ImportOutcome:
    """Returns a validated `ucc.result` dict for a real (non-dry) import, or
    the plain `ImportOutcome` unchanged for a dry run (see module docstring).
    Raises `IdempotencyConflict` if the key was reused with a different
    request; re-raises `SecretDetected` unchanged on refusal (not tracked)."""
    if dry_run:
        return perform_import(config, path, adapter=adapter, conversation_id=conversation_id,
                              title=title, dry_run=True, registry=registry)

    paths = LibraryPaths(config.library_root)
    store = IdempotencyStore(paths.idempotency_db)

    payload = {
        "path": str(path), "adapter": adapter,
        "conversation_id": conversation_id, "title": title,
    }
    fingerprint = request_fingerprint(payload)
    stored = store.get(idempotency_key)
    outcome = evaluate_idempotency(idempotency_key, fingerprint, stored)

    request_id = new_id("req")
    operation_id = new_id("op")
    correlation_id = new_id("corr")

    if outcome == IdempotencyOutcome.REPLAY:
        return stored.result

    if outcome == IdempotencyOutcome.IN_FLIGHT:
        problem = {
            "schema": "ucc.problem",
            "schema_version": 1,
            "kind": "outcome_unknown",
            "code": "outcome_unknown",
            "message": "operation outcome is unknown; operator reconciliation is required",
            "retryable": False,
            "request_id": stored.result["request_id"],
            "operation_id": stored.result["operation_id"],
            "correlation_id": stored.result["correlation_id"],
        }
        validate_document("problem", problem)
        raise OutcomeUnknown(problem)

    if outcome == IdempotencyOutcome.CONFLICT:
        raise IdempotencyConflict(idempotency_conflict_problem(
            request_id=request_id, operation_id=operation_id, correlation_id=correlation_id,
        ))

    # NEW: build + validate the request envelope, run the real op, build +
    # validate the result envelope, store, return. requested_by is a
    # documented placeholder (D4) — soloctl has no persistent operator
    # identity yet.
    request_doc = {
        "schema": "ucc.request", "schema_version": 1,
        "request_id": request_id, "operation_id": operation_id, "correlation_id": correlation_id,
        "causation_id": None, "idempotency_key": idempotency_key,
        "request_fingerprint": fingerprint, "requested_at": ucc_now_iso(),
        "requested_by": new_id("act"), "operation_type": OPERATION_TYPE, "payload": payload,
    }
    validate_document("request", request_doc)

    store.begin(
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        operation_type=OPERATION_TYPE,
        result={
            "disposition": "unknown",
            "request_id": request_id,
            "operation_id": operation_id,
            "correlation_id": correlation_id,
        },
        created_at=request_doc["requested_at"],
    )

    try:
        import_outcome = perform_import(
            config,
            path,
            adapter=adapter,
            conversation_id=conversation_id,
            title=title,
            dry_run=False,
            registry=registry,
        )
    except SoloctlError:
        store.abandon(idempotency_key=idempotency_key, fingerprint=fingerprint)
        raise

    result_doc = {
        "schema": "ucc.result", "schema_version": 1,
        "result_id": new_id("res"), "request_id": request_id, "operation_id": operation_id,
        "correlation_id": correlation_id, "completed_at": ucc_now_iso(),
        "disposition": "completed",
        "resource": {"kind": "transcript_import_operation", "id": operation_id},
        "warnings": [],
    }
    validate_document("result", result_doc)
    store.complete(idempotency_key=idempotency_key, fingerprint=fingerprint,
                   disposition="completed", result=result_doc)
    return result_doc
