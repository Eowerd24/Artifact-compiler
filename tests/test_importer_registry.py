from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.errors import (
    AmbiguousImporterError, ImporterNotFoundError, UnsupportedInputError,
)
from soloctl.importers import build_default_registry
from soloctl.importers.registry import ImporterRegistry


class _StubImporter:
    def __init__(self, name: str, version: str, confidence: float) -> None:
        self.name = name
        self.version = version
        self._confidence = confidence

    def detect(self, path: Path) -> float:
        return self._confidence

    def list_conversations(self, path: Path):
        return ()

    def parse(self, path: Path, conversation_id: str | None = None):
        raise NotImplementedError


def test_ambiguous_detection_is_rejected(tmp_path: Path):
    registry = ImporterRegistry((
        _StubImporter("a", "a-v1", 1.0),
        _StubImporter("b", "b-v1", 1.0),
    ))
    with pytest.raises(AmbiguousImporterError):
        registry.resolve(tmp_path / "whatever.dat")


def test_unsupported_input_is_rejected(tmp_path: Path):
    registry = ImporterRegistry((_StubImporter("a", "a-v1", 0.0),))
    with pytest.raises(UnsupportedInputError):
        registry.resolve(tmp_path / "whatever.dat")


def test_higher_confidence_wins_without_ambiguity(tmp_path: Path):
    registry = ImporterRegistry((
        _StubImporter("a", "a-v1", 0.5),
        _StubImporter("b", "b-v1", 1.0),
    ))
    resolved = registry.resolve(tmp_path / "whatever.dat")
    assert resolved.version == "b-v1"


def test_explicit_adapter_override_bypasses_detection(tmp_path: Path):
    registry = ImporterRegistry((_StubImporter("a", "a-v1", 0.0),))
    resolved = registry.resolve(tmp_path / "whatever.dat", adapter="a-v1")
    assert resolved.version == "a-v1"


def test_unknown_explicit_adapter_fails_clearly(tmp_path: Path):
    registry = ImporterRegistry((_StubImporter("a", "a-v1", 1.0),))
    with pytest.raises(ImporterNotFoundError):
        registry.resolve(tmp_path / "whatever.dat", adapter="does-not-exist")


def test_default_registry_disambiguates_markdown_chatgpt_and_claude(tmp_path: Path):
    registry = build_default_registry()
    md = tmp_path / "chat.md"
    md.write_text("# hi\n", encoding="utf-8")
    resolved = registry.resolve(md)
    assert resolved.version == "markdown-v1"
