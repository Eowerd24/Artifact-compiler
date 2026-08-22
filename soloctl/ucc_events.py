"""Shared ucc.event emission for legacy imports and canonical Artifact mutations."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ucc_contracts import new_id, validate_document

MODULE_ID = "artifact-compiler"


def ucc_now_iso() -> str:
    """Return RFC3339 UTC with fractional seconds and a literal Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _next_producer_sequence(events_path: Path) -> int:
    """Return the next sequence for this single-process local producer."""
    if not events_path.exists():
        return 0
    with events_path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def build_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    producer_sequence: int,
    actor_id: str | None = None,
    subject: dict[str, str] | None = None,
    operation_id: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    operation_id = operation_id or new_id("op")
    request_id = request_id or new_id("req")
    correlation_id = correlation_id or new_id("corr")
    actor_id = actor_id or new_id("act")
    subject = subject or {
        "kind": "transcript_import_operation",
        "id": operation_id,
    }
    now = ucc_now_iso()
    event = {
        "schema": "ucc.event",
        "schema_version": 1,
        "event_id": new_id("evt"),
        "event_type": event_type,
        "occurred_at": now,
        "recorded_at": now,
        "producer": {
            "module_id": MODULE_ID,
            "instance_id": new_id("act"),
        },
        "actor": {"kind": "human", "id": actor_id},
        "subject": subject,
        "operation_id": operation_id,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "producer_sequence": producer_sequence,
        "payload": payload,
    }
    validate_document("event", event)
    return event


def emit_event(
    events_path: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    actor_id: str | None = None,
    subject: dict[str, str] | None = None,
    operation_id: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Validate and append one event; optional identifiers preserve real causality."""
    event = build_event(
        event_type=event_type,
        payload=payload,
        producer_sequence=_next_producer_sequence(events_path),
        actor_id=actor_id,
        subject=subject,
        operation_id=operation_id,
        request_id=request_id,
        correlation_id=correlation_id,
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return event
