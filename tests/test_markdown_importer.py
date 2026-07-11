from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.cli import perform_import
from soloctl.config import SoloctlConfig
from soloctl.errors import ImporterError
from soloctl.importers import build_default_registry
from soloctl.importers.markdown import MarkdownImporter
from soloctl.library.repository import init_library

CANONICAL = """---
kind: transcript
schema: 1
source: chatgpt
adapter: chatgpt-v1
conversation_id: abc123
title: Forge provisioning
exported_at: null
turns: 1
---

<!-- turn 1 role=assistant -->
Already canonical.
"""

PLAIN = """# Notes

Some plain markdown with a snippet.

```bash
echo hi
```
"""


def _config(tmp_path: Path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    return config


def test_import_canonical_transcript_markdown(tmp_path: Path):
    src = tmp_path / "existing.md"
    src.write_text(CANONICAL, encoding="utf-8")
    importer = MarkdownImporter()
    transcript = importer.parse(src)
    assert transcript.source == "chatgpt"
    assert transcript.adapter == "chatgpt-v1"
    assert transcript.conversation_id == "abc123"
    assert transcript.title == "Forge provisioning"
    assert len(transcript.turns) == 1


def test_import_plain_markdown_becomes_one_assistant_turn(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    importer = MarkdownImporter()
    transcript = importer.parse(src)
    assert transcript.source == "markdown"
    assert transcript.adapter == "markdown-v1"
    assert len(transcript.turns) == 1
    assert transcript.turns[0].role == "assistant"
    assert "echo hi" in transcript.turns[0].content_md


def test_title_override(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)
    outcome = perform_import(config, src, title="Custom Title", dry_run=True)
    assert outcome.title == "Custom Title"


def test_invalid_utf8_raises_clear_error(tmp_path: Path):
    src = tmp_path / "bad.md"
    src.write_bytes(b"\xff\xfe not valid utf-8")
    importer = MarkdownImporter()
    with pytest.raises(ImporterError) as exc_info:
        importer.parse(src)
    assert str(src) in str(exc_info.value)


def test_unreadable_missing_path_raises_clear_error(tmp_path: Path):
    missing = tmp_path / "does-not-exist.md"
    importer = MarkdownImporter()
    with pytest.raises(ImporterError) as exc_info:
        importer.parse(missing)
    assert str(missing) in str(exc_info.value)


def test_dry_run_writes_nothing(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    transcripts_dir = config.library_root / "transcripts"
    before = list(transcripts_dir.rglob("*.md"))
    outcome = perform_import(config, src, dry_run=True)
    after = list(transcripts_dir.rglob("*.md"))

    assert outcome.dry_run is True
    assert outcome.proposed_destination is not None
    assert before == after == []


def test_real_import_writes_under_library_transcripts(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    outcome = perform_import(config, src, dry_run=False)
    assert outcome.written is not None
    assert outcome.written.path.exists()
    assert outcome.written.path.is_relative_to(config.library_root / "transcripts")


def test_filename_collision_gets_deterministic_suffix(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    first = perform_import(config, src, title="Same Title", dry_run=False)
    second = perform_import(config, src, title="Same Title", dry_run=False)

    assert first.written.path != second.written.path
    assert first.written.path.exists()
    assert second.written.path.exists()
    assert second.written.path.name.endswith("-2.md")
    # Original content of the first file must remain untouched.
    assert "Already canonical" not in first.written.path.read_text(encoding="utf-8")


def test_explicit_adapter_override(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)
    registry = build_default_registry()
    outcome = perform_import(config, src, adapter="markdown-v1", dry_run=True, registry=registry)
    assert outcome.adapter == "markdown-v1"
