"""Shared helpers for JSON-export importers (ChatGPT, Claude): loading a
JSON array of conversation objects out of a bare file, a directory, or a
zip archive, plus the shared conversation-selection UX (exact id -> exact
title -> unambiguous title substring). Neither function knows either
adapter's conversation schema — that stays in chatgpt.py / claude.py, which
is what keeps this module reusable without leaking source-specific logic.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Callable

from ..errors import AmbiguousImporterError, ConversationNotFoundError, ImporterError, ImporterSchemaError


def _parse_array(raw: bytes, path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImporterError(f"{path}: not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ImporterSchemaError(
            f"{path}: expected a JSON array of conversations at the top "
            f"level, got {type(data).__name__}"
        )
    return data


def load_conversations_json(path: Path, filename: str) -> list[dict[str, Any]]:
    """Load filename as a JSON array from path, which may be a directory
    containing filename, a zip archive containing filename, or filename
    itself."""
    if path.is_dir():
        candidate = path / filename
        if not candidate.is_file():
            raise ImporterError(
                f"{path} is a directory without a {filename} file"
            )
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            raise ImporterError(f"cannot read {candidate}: {exc}") from exc
        return _parse_array(raw, candidate)

    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.endswith(filename)]
                if not names:
                    raise ImporterError(
                        f"{path}: no {filename} found inside the archive"
                    )
                raw = zf.read(names[0])
        except zipfile.BadZipFile as exc:
            raise ImporterError(f"{path} is not a valid zip archive: {exc}") from exc
        return _parse_array(raw, path)

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ImporterError(f"cannot read {path}: {exc}") from exc
    return _parse_array(raw, path)


def detect_json_array(path: Path, filename: str, required_keys: tuple[str, ...]) -> float:
    """Cheap structural probe for Importer.detect(): does path look like it
    contains filename, whose first array entry has every key in
    required_keys? Never raises — anything unrecognized is confidence 0.0,
    which is what lets the registry try the next importer instead of
    crashing on input meant for someone else."""
    try:
        if path.is_dir():
            candidate = path / filename
            if not candidate.is_file():
                return 0.0
            raw = candidate.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if n.endswith(filename)]
                if not names:
                    return 0.0
                raw = zf.read(names[0])
        elif path.suffix.lower() == ".json":
            raw = path.read_bytes()
        else:
            return 0.0
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return 0.0
        return 1.0 if all(key in data[0] for key in required_keys) else 0.0
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        return 0.0


def select_entry(
    entries: list[dict[str, Any]],
    conversation_id: str | None,
    *,
    id_of: Callable[[dict[str, Any]], str | None],
    title_of: Callable[[dict[str, Any]], str],
    path: Path,
) -> dict[str, Any]:
    """Selection UX shared by every JSON-export adapter: exact conversation
    id, then exact title, then an unambiguous case-insensitive title
    substring. Ties at any stage are rejected rather than guessed."""
    if conversation_id is None:
        if len(entries) == 1:
            return entries[0]
        raise AmbiguousImporterError(
            f"{path} contains {len(entries)} conversations; pass "
            f"--conversation <id-or-title> to select one"
        )

    for entry in entries:
        if id_of(entry) == conversation_id:
            return entry

    exact = [e for e in entries if title_of(e) == conversation_id]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousImporterError(
            f"{len(exact)} conversations in {path} are titled "
            f"{conversation_id!r}; use --conversation <conversation-id> instead"
        )

    needle = conversation_id.lower()
    substring = [e for e in entries if needle in title_of(e).lower()]
    if len(substring) == 1:
        return substring[0]
    if len(substring) > 1:
        titles = [title_of(e) for e in substring]
        raise AmbiguousImporterError(
            f"{conversation_id!r} matches {len(substring)} conversation "
            f"titles in {path}: {titles}; use the exact conversation-id instead"
        )

    raise ConversationNotFoundError(
        f"no conversation in {path} matches id or title {conversation_id!r}"
    )
