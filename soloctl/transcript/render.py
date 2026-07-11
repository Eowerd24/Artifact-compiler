"""The one canonical transcript renderer. Transcript IR -> markdown with YAML
front matter and HTML turn-marker comments. See parse.py for the inverse.
"""
from __future__ import annotations

import json
import re

from .models import Transcript

SCHEMA_VERSION = 1

_RESERVED_SCALARS = {"null", "true", "false", "yes", "no", "~"}
_UNSAFE_LEADING_CHARS = set("-?:,[]{}#&*!|>'\"%@`")


def _needs_quoting(value: str) -> bool:
    if value == "":
        return True
    if value != value.strip():
        return True
    if value.lower() in _RESERVED_SCALARS:
        return True
    if any(c in value for c in ':#"\n'):
        return True
    if value[0] in _UNSAFE_LEADING_CHARS:
        return True
    return False


def _yaml_scalar(value: str | None) -> str:
    if value is None:
        return "null"
    if _needs_quoting(value):
        return json.dumps(value, ensure_ascii=False)
    return value


def _turn_marker(turn) -> str:
    marker = f"<!-- turn {turn.index} role={turn.role}"
    if turn.timestamp:
        marker += f" ts={turn.timestamp}"
    return marker + " -->"


def render_transcript(transcript: Transcript) -> str:
    """Render a Transcript to canonical markdown. Deterministic: same
    Transcript always renders to the same bytes."""
    front_matter = "\n".join([
        "---",
        "kind: transcript",
        f"schema: {SCHEMA_VERSION}",
        f"source: {_yaml_scalar(transcript.source)}",
        f"adapter: {_yaml_scalar(transcript.adapter)}",
        f"conversation_id: {_yaml_scalar(transcript.conversation_id)}",
        f"title: {_yaml_scalar(transcript.title)}",
        f"exported_at: {_yaml_scalar(transcript.exported_at)}",
        f"turns: {len(transcript.turns)}",
        "---",
    ])

    parts = [front_matter]
    for turn in transcript.turns:
        marker = _turn_marker(turn)
        content = re.sub(r"\r\n", "\n", turn.content_md).strip("\n")
        parts.append(marker if not content else f"{marker}\n{content}")

    return "\n\n".join(parts) + "\n"
