from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from soloctl.errors import (
    AmbiguousImporterError, ImporterSchemaError,
)
from soloctl.importers.chatgpt import ChatGPTImporter
from soloctl.transcript.parse import parse_transcript
from soloctl.transcript.render import render_transcript

FIX = Path(__file__).parent / "fixtures" / "chatgpt" / "v1"


def test_detect_recognizes_conversations_json():
    importer = ChatGPTImporter()
    assert importer.detect(FIX / "simple-conversation.json") == 1.0


def test_detect_rejects_unrelated_json():
    claude_fixture = Path(__file__).parent / "fixtures" / "claude" / "v1" / "basic-conversation.json"
    importer = ChatGPTImporter()
    assert importer.detect(claude_fixture) == 0.0


def test_simple_conversation():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "simple-conversation.json")
    assert transcript.source == "chatgpt"
    assert transcript.adapter == "chatgpt-v1"
    assert transcript.title == "Simple chat"
    assert transcript.conversation_id == "conv-simple-1"
    assert len(transcript.turns) == 2
    assert [t.role for t in transcript.turns] == ["user", "assistant"]
    assert transcript.turns[0].content_md == "How do I list files?"
    assert transcript.turns[1].content_md == "Use `ls -la`."
    assert transcript.turns[0].timestamp is not None


def test_regenerated_response_only_current_branch_survives():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "regenerated-response.json")
    assert len(transcript.turns) == 2
    bodies = " ".join(t.content_md for t in transcript.turns)
    assert "Old draft haiku" not in bodies
    assert "Waves kiss the cold shore" in bodies


def test_edited_user_message_only_final_edit_survives():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "edited-user-message.json")
    assert len(transcript.turns) == 2
    bodies = " ".join(t.content_md for t in transcript.turns)
    assert "delete a file" not in bodies
    assert "rm filename" not in bodies
    assert "permanently shred" in bodies
    assert "shred -u filename" in bodies


def test_tool_calls_preserve_role():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "tool-calls.json")
    assert [t.role for t in transcript.turns] == ["user", "tool", "assistant"]


def test_missing_current_node_is_a_schema_error():
    importer = ChatGPTImporter()
    with pytest.raises(ImporterSchemaError) as exc_info:
        importer.parse(FIX / "missing-current-node.json")
    assert "current_node" in str(exc_info.value)


def test_missing_message_content_is_recorded_not_fatal():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "missing-message-content.json")
    assert len(transcript.turns) == 2
    assert transcript.turns[1].content_md == ""
    assert transcript.turns[1].metadata.get("missing_content") is True


def test_unknown_content_type_is_recorded_not_fatal():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "unknown-content-type.json")
    assert len(transcript.turns) == 1
    assert transcript.turns[0].content_md == ""
    assert transcript.turns[0].metadata.get("unsupported_content_type") == "image_asset_pointer"


def test_duplicate_titles_require_explicit_id():
    importer = ChatGPTImporter()
    with pytest.raises(AmbiguousImporterError):
        importer.parse(FIX / "duplicate-titles.json", "Weekly sync")

    transcript = importer.parse(FIX / "duplicate-titles.json", "conv-dup-2")
    assert transcript.conversation_id == "conv-dup-2"
    assert transcript.turns[0].content_md == "Second one"


def test_multiple_conversations_without_selector_is_ambiguous():
    importer = ChatGPTImporter()
    with pytest.raises(AmbiguousImporterError):
        importer.parse(FIX / "duplicate-titles.json")


def test_empty_conversation_yields_zero_turns():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "empty-conversation.json")
    assert transcript.turns == ()
    assert transcript.title == "Never sent"


def test_malformed_top_level_not_a_list_fails_explicitly():
    importer = ChatGPTImporter()
    with pytest.raises(Exception):  # ImporterSchemaError via load_conversations_json
        importer.parse(FIX / "malformed-not-a-list.json")


def test_list_conversations():
    importer = ChatGPTImporter()
    summaries = importer.list_conversations(FIX / "duplicate-titles.json")
    assert len(summaries) == 2
    assert {s.conversation_id for s in summaries} == {"conv-dup-1", "conv-dup-2"}


def test_imported_transcript_uses_the_canonical_renderer_and_roundtrips():
    importer = ChatGPTImporter()
    transcript = importer.parse(FIX / "simple-conversation.json")
    rendered = render_transcript(transcript)
    roundtripped = parse_transcript(rendered)
    assert roundtripped.source == transcript.source
    assert roundtripped.adapter == transcript.adapter
    assert roundtripped.title == transcript.title
    assert [t.content_md for t in roundtripped.turns] == [t.content_md for t in transcript.turns]


def test_zip_archive_containing_conversations_json(tmp_path: Path):
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(FIX / "simple-conversation.json", "conversations.json")

    importer = ChatGPTImporter()
    assert importer.detect(zip_path) == 1.0
    transcript = importer.parse(zip_path)
    assert transcript.title == "Simple chat"
    assert len(transcript.turns) == 2


def test_directory_containing_conversations_json(tmp_path: Path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "conversations.json").write_bytes(
        (FIX / "simple-conversation.json").read_bytes())

    importer = ChatGPTImporter()
    assert importer.detect(export_dir) == 1.0
    transcript = importer.parse(export_dir)
    assert transcript.title == "Simple chat"
