"""Canonical transcript parser — the inverse of render.py. Round-trips every
field render_transcript produces; raises TranscriptParseError with an
actionable message on anything malformed.
"""
from __future__ import annotations

import json
import re

from ..errors import TranscriptParseError
from .models import Role, Transcript, Turn
from .render import SCHEMA_VERSION

_FRONT_MATTER_RX = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_TURN_MARKER_RX = re.compile(
    r"^<!--\s*turn\s+(\d+)\s+role=(\w+)(?:\s+ts=(\S+))?\s*-->\s*$", re.MULTILINE)

_REQUIRED_FIELDS = {
    "kind", "schema", "source", "adapter", "conversation_id",
    "title", "exported_at", "turns",
}
_KNOWN_ROLES = {"user", "assistant", "system", "tool"}


def _parse_scalar(raw: str) -> str | None:
    if raw == "null":
        return None
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranscriptParseError(
                f"malformed quoted front matter value {raw!r}: {exc}"
            ) from exc
    return raw


def _parse_front_matter(fm_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in fm_text.split("\n"):
        if not line.strip():
            continue
        if ":" not in line:
            raise TranscriptParseError(
                f"malformed front matter line (missing ':'): {line!r}"
            )
        key, _, rest = line.partition(":")
        fields[key.strip()] = rest.strip()
    return fields


def _parse_turns(body: str) -> list[Turn]:
    matches = list(_TURN_MARKER_RX.finditer(body))
    turns: list[Turn] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip("\n")
        role_raw = m.group(2).lower()
        role: Role = role_raw if role_raw in _KNOWN_ROLES else "unknown"  # type: ignore[assignment]
        turns.append(Turn(
            index=int(m.group(1)),
            role=role,
            content_md=content,
            timestamp=m.group(3),
        ))
    return turns


def parse_transcript(text: str) -> Transcript:
    """Parse canonical transcript markdown produced by render_transcript."""
    m = _FRONT_MATTER_RX.match(text)
    if not m:
        raise TranscriptParseError(
            "missing or malformed front matter: expected a '---' delimited "
            "YAML block at the very start of the file"
        )

    fields = _parse_front_matter(m.group(1))
    body = text[m.end():]

    missing = _REQUIRED_FIELDS - fields.keys()
    if missing:
        raise TranscriptParseError(
            f"front matter missing required field(s): {sorted(missing)}"
        )

    if fields["kind"] != "transcript":
        raise TranscriptParseError(
            f"unexpected front matter 'kind': {fields['kind']!r} (expected 'transcript')"
        )

    try:
        schema = int(fields["schema"])
    except ValueError:
        raise TranscriptParseError(
            f"front matter 'schema' must be an integer, got {fields['schema']!r}"
        ) from None
    if schema != SCHEMA_VERSION:
        raise TranscriptParseError(
            f"unsupported transcript schema version {schema} (this soloctl "
            f"supports schema {SCHEMA_VERSION})"
        )

    try:
        declared_turns = int(fields["turns"])
    except ValueError:
        raise TranscriptParseError(
            f"front matter 'turns' must be an integer, got {fields['turns']!r}"
        ) from None

    turns = _parse_turns(body)
    if len(turns) != declared_turns:
        raise TranscriptParseError(
            f"front matter declares {declared_turns} turn(s) but {len(turns)} "
            f"turn marker(s) were found in the body"
        )

    return Transcript(
        source=_parse_scalar(fields["source"]) or "",
        adapter=_parse_scalar(fields["adapter"]) or "",
        title=_parse_scalar(fields["title"]) or "",
        conversation_id=_parse_scalar(fields["conversation_id"]),
        turns=tuple(turns),
        exported_at=_parse_scalar(fields["exported_at"]),
    )
