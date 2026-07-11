"""markdown-v1 — the passthrough importer.

Accepts either an existing canonical transcript (front matter + turn
markers) or a plain markdown file, which becomes one anonymous assistant
turn. This is the only importer implemented in Work Package 1; ChatGPT and
Claude adapters land in later work packages and must not leak any
source-specific logic into this module or into the extractor.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ImporterError, TranscriptParseError
from ..transcript.models import Transcript, Turn
from ..transcript.parse import parse_transcript
from .base import ConversationSummary

NAME = "markdown"
VERSION = "markdown-v1"

_SUPPORTED_SUFFIXES = {".md", ".markdown"}


def _read_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ImporterError(
            f"cannot read {path}: {exc}. Check the path exists and is readable."
        ) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImporterError(
            f"{path} is not valid UTF-8 ({exc}). The markdown importer requires "
            f"UTF-8 encoded text."
        ) from exc


def _passthrough(text: str, path: Path) -> Transcript:
    content = text.strip("\n")
    return Transcript(
        source="markdown",
        adapter=VERSION,
        title=path.stem,
        conversation_id=None,
        turns=(Turn(index=1, role="assistant", content_md=content),),
    )


class MarkdownImporter:
    name = NAME
    version = VERSION

    def detect(self, path: Path) -> float:
        if path.suffix.lower() in _SUPPORTED_SUFFIXES:
            return 1.0
        return 0.0

    def list_conversations(self, path: Path) -> tuple[ConversationSummary, ...]:
        transcript = self.parse(path)
        summary = ConversationSummary(
            conversation_id=transcript.conversation_id or path.stem,
            title=transcript.title,
            turn_count=len(transcript.turns),
            exported_at=transcript.exported_at,
        )
        return (summary,)

    def parse(self, path: Path, conversation_id: str | None = None) -> Transcript:
        text = _read_text(path)
        try:
            return parse_transcript(text)
        except TranscriptParseError:
            return _passthrough(text, path)
