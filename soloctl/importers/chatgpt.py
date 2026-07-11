"""chatgpt-v1 — imports a single conversation from a ChatGPT export.

Per IMPORTER_BLUEPRINT.md §5: conversations.json holds every conversation
as a `mapping` **tree** (node -> parent/children), not a flat list, because
every edit and every regenerated response survives as a sibling branch.
Policy is current-path-only: walk backward from `current_node` to the
root and reverse. That walk is the entire mechanism that keeps abandoned
branches out of the transcript — there is no separate "is this
regenerated?" check anywhere in this file.

This adapter only parses. It has no opinion on markdown rendering, naming,
extraction, or the library, and the extractor/compiler must never grow a
ChatGPT-shaped branch to compensate for anything done here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ImporterSchemaError
from ..transcript.models import Role, Transcript, Turn
from ._json_export import detect_json_array, load_conversations_json, select_entry
from .base import ConversationSummary

NAME = "chatgpt"
VERSION = "chatgpt-v1"
FILENAME = "conversations.json"

_ROLE_MAP: dict[str, Role] = {
    "user": "user", "assistant": "assistant", "system": "system", "tool": "tool",
}


def _entry_id(entry: dict[str, Any]) -> str | None:
    cid = entry.get("conversation_id") or entry.get("id")
    return cid if isinstance(cid, str) and cid else None


def _entry_title(entry: dict[str, Any]) -> str:
    title = entry.get("title")
    return title if isinstance(title, str) else ""


def _epoch_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds")


def _linearize(entry: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    """Walk the mapping tree from current_node to the root and reverse:
    the active, chronological path. Nodes off this path (regenerated
    responses, edited-away messages) are never visited."""
    label = _entry_id(entry) or _entry_title(entry) or "?"
    mapping = entry.get("mapping")
    if not isinstance(mapping, dict):
        raise ImporterSchemaError(
            f"{path}: conversation {label!r} is missing a 'mapping' object"
        )
    if "current_node" not in entry:
        raise ImporterSchemaError(
            f"{path}: conversation {label!r} is missing 'current_node'"
        )

    current_node = entry["current_node"]
    if current_node is None:
        return []  # a conversation that was started but never messaged

    if current_node not in mapping:
        raise ImporterSchemaError(
            f"{path}: conversation {label!r} has current_node {current_node!r} "
            f"which is not present in 'mapping'"
        )

    chain: list[dict[str, Any]] = []
    node_id: str | None = current_node
    seen: set[str] = set()
    while node_id is not None:
        if node_id in seen:
            raise ImporterSchemaError(
                f"{path}: conversation {label!r} has a cycle in 'mapping' "
                f"reachable from current_node {current_node!r}"
            )
        seen.add(node_id)
        node = mapping.get(node_id)
        if not isinstance(node, dict):
            raise ImporterSchemaError(
                f"{path}: conversation {label!r} references mapping node "
                f"{node_id!r} which is missing or not an object"
            )
        chain.append(node)
        node_id = node.get("parent")
    chain.reverse()

    return [n["message"] for n in chain if isinstance(n.get("message"), dict)]


def _extract_content(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, dict):
        return "", {"missing_content": True}
    content_type = content.get("content_type")
    if content_type == "text":
        parts = content.get("parts")
        if isinstance(parts, list):
            text_parts = [p for p in parts if isinstance(p, str) and p]
            return "\n\n".join(text_parts), {}
        return "", {"missing_content": True}
    return "", {"unsupported_content_type": content_type}


def _message_role(message: dict[str, Any]) -> Role:
    author = message.get("author")
    role_raw = author.get("role") if isinstance(author, dict) else None
    return _ROLE_MAP.get(role_raw, "unknown")


def _build_turns(messages: list[dict[str, Any]]) -> tuple[Turn, ...]:
    turns = []
    for index, message in enumerate(messages, start=1):
        content_md, metadata = _extract_content(message)
        turns.append(Turn(
            index=index,
            role=_message_role(message),
            content_md=content_md,
            timestamp=_epoch_to_iso(message.get("create_time")),
            metadata=metadata,
        ))
    return tuple(turns)


class ChatGPTImporter:
    name = NAME
    version = VERSION

    def detect(self, path: Path) -> float:
        return detect_json_array(path, FILENAME, ("mapping", "current_node"))

    def list_conversations(self, path: Path) -> tuple[ConversationSummary, ...]:
        entries = load_conversations_json(path, FILENAME)
        summaries = []
        for entry in entries:
            messages = _linearize(entry, path)
            summaries.append(ConversationSummary(
                conversation_id=_entry_id(entry) or "?",
                title=_entry_title(entry) or "untitled",
                turn_count=len(messages),
                exported_at=_epoch_to_iso(entry.get("update_time")),
            ))
        return tuple(summaries)

    def parse(self, path: Path, conversation_id: str | None = None) -> Transcript:
        entries = load_conversations_json(path, FILENAME)
        entry = select_entry(
            entries, conversation_id,
            id_of=_entry_id, title_of=_entry_title, path=path,
        )
        messages = _linearize(entry, path)
        turns = _build_turns(messages)
        exported_at = (_epoch_to_iso(entry.get("update_time"))
                       or _epoch_to_iso(entry.get("create_time")))
        return Transcript(
            source=NAME,
            adapter=VERSION,
            title=_entry_title(entry) or "untitled",
            conversation_id=_entry_id(entry),
            turns=turns,
            exported_at=exported_at,
        )
