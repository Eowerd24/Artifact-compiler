"""Shared ucc.event emission (G2, roadmap §4B "Shared IDs/envelopes").

Dual-writes a schema-conformant `ucc.event` alongside the legacy
`transcript.import` ledger event in `ledger.py`. The legacy ledger stays the
primary, unchanged read path; this is additive. Once AC grows real
Artifact/ArtifactRevision records (a later work package — see HANDOFF_NOTES),
`subject` below should point at the real revision id instead of the
operation id it uses today.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ucc_contracts import new_id, validate_document

MODULE_ID = "artifact-compiler"


def ucc_now_iso() -> str:
    """RFC3339 UTC with fractional seconds and a literal 'Z' (UCC-Standards
    §1) — distinct from ledger.now_iso(), which emits a `+00:00` offset that
    does not match the shared timestamp pattern."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _next_producer_sequence(events_path: Path) -> int:
    """Producer owns its own sequence (UCC-Standards §4); derived from the
    count of events already on disk since this is a local single-process CLI
    with no separate sequence-state store."""
    if not events_path.exists():
        return 0
    with events_path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def build_event(*, event_type: str, payload: dict[str, Any],
                 producer_sequence: int) -> dict[str, Any]:
    operation_id = new_id("op")
    instance_id = new_id("act")
    actor_id = new_id("act")
    now = ucc_now_iso()
    event = {
        "schema": "ucc.event",
        "schema_version": 1,
        "event_id": new_id("evt"),
        "event_type": event_type,
        "occurred_at": now,
        "recorded_at": now,
        "producer": {"module_id": MODULE_ID, "instance_id": instance_id},
        "actor": {"kind": "human", "id": actor_id},
        # No canonical Artifact/ArtifactRevision id exists yet (directory-shaped
        # library only); the subject is this operation itself until that model
        # lands, rather than a fabricated revision id.
        "subject": {"kind": "transcript_import_operation", "id": operation_id},
        "operation_id": operation_id,
        "request_id": new_id("req"),
        "correlation_id": new_id("corr"),
        # causation_id omitted: unlike ucc.request, ucc.event's causation_id
        # is not nullable (must be a valid id if present at all) — this is a
        # root-cause event, not caused by a prior one.
        "producer_sequence": producer_sequence,
        "payload": payload,
    }
    validate_document("event", event)
    return event


def emit_event(events_path: Path, *, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build, validate, and append one ucc.event. Raises SchemaValidationError
    rather than writing a non-conformant record."""
    sequence = _next_producer_sequence(events_path)
    event = build_event(event_type=event_type, payload=payload, producer_sequence=sequence)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    fd = os.open(events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return event
