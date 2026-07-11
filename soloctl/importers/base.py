"""Importer contract. An adapter only parses its source format into the
canonical Transcript IR — it must never touch markdown rendering, naming,
extraction, or the library.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..transcript.models import Transcript


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: str
    title: str
    turn_count: int
    exported_at: str | None = None


@runtime_checkable
class Importer(Protocol):
    name: str
    version: str

    def detect(self, path: Path) -> float:
        """Confidence in [0.0, 1.0] that this importer can parse path."""
        ...

    def list_conversations(self, path: Path) -> tuple[ConversationSummary, ...]:
        ...

    def parse(self, path: Path, conversation_id: str | None = None) -> Transcript:
        ...
