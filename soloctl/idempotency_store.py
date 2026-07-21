"""Per-owner idempotency/result store (M-b, D2).

Canonical evidence (backed up), not a disposable projection — a SQLite table
under this repo's own state root (`library/idempotency.db`, sibling to
`library/events.jsonl`). An `unknown` row is committed before dispatch,
replaced on success, removed on definite refusal, and retained after
ambiguity so retry cannot silently execute the import again. No row expires.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ucc_contracts.idempotency import StoredIdempotencyRecord


@dataclass(frozen=True)
class IdempotencyRecord(StoredIdempotencyRecord):
    disposition: str

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

    def get(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        row = self._conn.execute(
            "SELECT request_fingerprint, disposition, result_json "
            "FROM idempotency_records WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        fingerprint, disposition, result_json = row
        return IdempotencyRecord(
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            disposition=disposition,
            result=json.loads(result_json),
        )

    def put_in_flight(self, *, idempotency_key: str, fingerprint: str,
                      operation_type: str, created_at: str) -> None:
        self._conn.execute(
            "INSERT INTO idempotency_records "
            "(idempotency_key, request_fingerprint, operation_type, disposition, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (idempotency_key, fingerprint, operation_type, "unknown", "{}", created_at),
        )
        self._conn.commit()

    def complete(self, *, idempotency_key: str, result: dict) -> None:
        cursor = self._conn.execute(
            "UPDATE idempotency_records SET disposition = ?, result_json = ? "
            "WHERE idempotency_key = ?",
            ("completed", json.dumps(result, ensure_ascii=False, separators=(",", ":")),
             idempotency_key),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"missing in-flight idempotency record for {idempotency_key!r}")
        self._conn.commit()

    def delete(self, idempotency_key: str) -> None:
        self._conn.execute(
            "DELETE FROM idempotency_records WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
