"""claude-v1 — imports a single conversation from a Claude data export.

Per IMPORTER_BLUEPRINT.md §5: Claude's conversations.json is a flat
`chat_messages` list, already in chronological order — unlike ChatGPT
there is no mapping tree to walk, no branches to exclude. Attachment and
artifact references are recorded in turn metadata verbatim (whatever the
export includes); their content is never fetched, in v1 or otherwise.

Assumption flagged for review: the exact shape of `attachments`/`files`/
`artifacts` entries on a message is inferred from the blueprint's brief
description, not a captured real export. If a real export's shape differs,
only this file (and its fixtures) should need to change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import ImporterSchemaError
from ..transcript.models import Role, Transcript, Turn
from ._json_export import detect_json_array, load_conversations_json, select_entry
from .base import ConversationSummary

NAME = "claude"
VERSION = "claude-v1"
FILENAME = "conversations.json"

_ROLE_MAP: dict[str, Role] = {"human": "user", "assistant": "assistant"}
_REFERENCE_ONLY_KEYS = ("attachments", "files", "artifacts")


def _entry_id(entry: dict[str, Any]) -> str | None:
    cid = entry.get("uuid") or entry.get("id")
    return cid if isinstance(cid, str) and cid else None


def _entry_title(entry: dict[str, Any]) -> str:
    name = entry.get("name")
    return name if isinstance(name, str) else ""


def _entry_messages(entry: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    messages = entry.get("chat_messages")
    if not isinstance(messages, list):
        label = _entry_id(entry) or _entry_title(entry) or "?"
        raise ImporterSchemaError(
            f"{path}: conversation {label!r} is missing a 'chat_messages' list"
        )
    return messages


def _message_role(message: dict[str, Any]) -> Role:
    return _ROLE_MAP.get(message.get("sender"), "unknown")


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in _REFERENCE_ONLY_KEYS:
        value = message.get(key)
        if isinstance(value, list) and value:
            meta[key] = value
    return meta


def _build_turns(messages: list[dict[str, Any]], path: Path) -> tuple[Turn, ...]:
    turns = []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            raise ImporterSchemaError(
                f"{path}: chat_messages[{index - 1}] is not an object"
            )
        text = message.get("text")
        metadata = _message_metadata(message)
        if isinstance(text, str):
            content_md = text
        else:
            content_md = ""
            metadata = {**metadata, "missing_content": True}
        timestamp = message.get("created_at")
        if not isinstance(timestamp, str):
            timestamp = None
        turns.append(Turn(
            index=index,
            role=_message_role(message),
            content_md=content_md,
            timestamp=timestamp,
            metadata=metadata,
        ))
    return tuple(turns)


class ClaudeImporter:
    name = NAME
    version = VERSION

    def detect(self, path: Path) -> float:
        return detect_json_array(path, FILENAME, ("chat_messages",))

    def list_conversations(self, path: Path) -> tuple[ConversationSummary, ...]:
        entries = load_conversations_json(path, FILENAME)
        summaries = []
        for entry in entries:
            messages = _entry_messages(entry, path)
            updated_at = entry.get("updated_at")
            summaries.append(ConversationSummary(
                conversation_id=_entry_id(entry) or "?",
                title=_entry_title(entry) or "untitled",
                turn_count=len(messages),
                exported_at=updated_at if isinstance(updated_at, str) else None,
            ))
        return tuple(summaries)

    def parse(self, path: Path, conversation_id: str | None = None) -> Transcript:
        entries = load_conversations_json(path, FILENAME)
        entry = select_entry(
            entries, conversation_id,
            id_of=_entry_id, title_of=_entry_title, path=path,
        )
        messages = _entry_messages(entry, path)
        turns = _build_turns(messages, path)
        updated_at = entry.get("updated_at")
        created_at = entry.get("created_at")
        exported_at = (updated_at if isinstance(updated_at, str)
                       else created_at if isinstance(created_at, str) else None)
        return Transcript(
            source=NAME,
            adapter=VERSION,
            title=_entry_title(entry) or "untitled",
            conversation_id=_entry_id(entry),
            turns=turns,
            exported_at=exported_at,
        )
