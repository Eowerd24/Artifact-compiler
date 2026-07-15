"""Per-owner idempotency/result store (M-b, D2).

Canonical evidence (backed up), not a disposable projection — a SQLite table
under this repo's own state root (`library/idempotency.db`, sibling to
`library/events.jsonl`). An in-flight record is committed before dispatch
and replaced only by a definite success. A definite refusal removes it; an
ambiguous exception leaves it in place for operator reconciliation and never
auto-expires.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Optional

from ucc_contracts.idempotency import (
    IdempotencyOutcome as SharedIdempotencyOutcome,
    StoredIdempotencyRecord,
    evaluate_idempotency as evaluate_shared_idempotency,
)


class IdempotencyOutcome(str, Enum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_FLIGHT = "in_flight"


def evaluate_idempotency(
    idempotency_key: str,
    request_fingerprint: str,
    stored: Optional[StoredIdempotencyRecord],
) -> IdempotencyOutcome:
    """Extend the pinned pure helper with the owner-store lifecycle state."""
    shared = evaluate_shared_idempotency(idempotency_key, request_fingerprint, stored)
    if (
        shared == SharedIdempotencyOutcome.REPLAY
        and stored is not None
        and stored.result.get("disposition") == "unknown"
    ):
        return IdempotencyOutcome.IN_FLIGHT
    return IdempotencyOutcome(shared.value)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key      TEXT PRIMARY KEY,
    request_fingerprint  TEXT NOT NULL,
    operation_type       TEXT NOT NULL,
    disposition          TEXT NOT NULL,
    result_json          TEXT NOT NULL,
    created_at           TEXT NOT NULL
);
"""


def request_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, idempotency_key: str) -> Optional[StoredIdempotencyRecord]:
        row = self._conn.execute(
            "SELECT request_fingerprint, result_json FROM idempotency_records WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        fingerprint, result_json = row
        return StoredIdempotencyRecord(
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            result=json.loads(result_json),
        )

    def begin(self, *, idempotency_key: str, fingerprint: str, operation_type: str,
              result: dict, created_at: str) -> None:
        self._conn.execute(
            "INSERT INTO idempotency_records "
            "(idempotency_key, request_fingerprint, operation_type, disposition, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (idempotency_key, fingerprint, operation_type, "unknown",
             json.dumps(result, ensure_ascii=False, separators=(",", ":")), created_at),
        )
        self._conn.commit()

    def complete(self, *, idempotency_key: str, fingerprint: str,
                 disposition: str, result: dict) -> None:
        cursor = self._conn.execute(
            "UPDATE idempotency_records SET disposition = ?, result_json = ? "
            "WHERE idempotency_key = ? AND request_fingerprint = ? AND disposition = 'unknown'",
            (disposition, json.dumps(result, ensure_ascii=False, separators=(",", ":")),
             idempotency_key, fingerprint),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            raise RuntimeError("in-flight idempotency record was not updated")
        self._conn.commit()

    def abandon(self, *, idempotency_key: str, fingerprint: str) -> None:
        self._conn.execute(
            "DELETE FROM idempotency_records "
            "WHERE idempotency_key = ? AND request_fingerprint = ? AND disposition = 'unknown'",
            (idempotency_key, fingerprint),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
