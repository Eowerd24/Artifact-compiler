"""Per-owner idempotency/result store (M-b, D2).

Canonical evidence (backed up), not a disposable projection — a SQLite table
under this repo's own state root (`library/idempotency.db`, sibling to
`library/events.jsonl`). Only definite-success results are stored: a refused
import is safe and cheap to re-attempt (it re-scans and refuses the same
way), so it is not idempotency-tracked. This also means an `unknown`
disposition is never stored — nothing here ever becomes a replay candidate
until it has a definite, successful outcome.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

from ucc_contracts.idempotency import StoredIdempotencyRecord

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

    def put(self, *, idempotency_key: str, fingerprint: str, operation_type: str,
            disposition: str, result: dict, created_at: str) -> None:
        """Only ever called for a definite, non-`unknown` disposition — see
        module docstring. INSERT, not UPSERT: a caller reaching `put()` has
        already confirmed via `evaluate_idempotency()` that no conflicting
        record exists for this key."""
        self._conn.execute(
            "INSERT INTO idempotency_records "
            "(idempotency_key, request_fingerprint, operation_type, disposition, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (idempotency_key, fingerprint, operation_type, disposition,
             json.dumps(result, ensure_ascii=False, separators=(",", ":")), created_at),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
