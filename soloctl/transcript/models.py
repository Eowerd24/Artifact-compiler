"""Canonical Transcript IR — the one contract every importer produces and
every downstream consumer (renderer, extractor-to-be) reads.

Frozen dataclasses. metadata is wrapped in MappingProxyType so a caller can't
accidentally mutate a shared dict through one Turn/Transcript instance and
have it silently show up in another.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

Role = Literal["user", "assistant", "system", "tool", "unknown"]

_EMPTY_MAP: Mapping[str, Any] = MappingProxyType({})


def _frozen_map(data: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not data:
        return _EMPTY_MAP
    return MappingProxyType(dict(data))


@dataclass(frozen=True)
class Turn:
    index: int
    role: Role
    content_md: str
    timestamp: str | None = None
    model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_MAP)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_map(self.metadata))


@dataclass(frozen=True)
class Transcript:
    source: str
    adapter: str
    title: str
    conversation_id: str | None
    turns: tuple[Turn, ...]
    exported_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_MAP)

    def __post_init__(self) -> None:
        object.__setattr__(self, "turns", tuple(self.turns))
        object.__setattr__(self, "metadata", _frozen_map(self.metadata))
