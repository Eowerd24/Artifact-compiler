from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from soloctl.errors import AmbiguousImporterError, ImporterSchemaError
from soloctl.importers.claude import ClaudeImporter
from soloctl.transcript.parse import parse_transcript
from soloctl.transcript.render import render_transcript

FIX = Path(__file__).parent / "fixtures" / "claude" / "v1"


def test_detect_recognizes_chat_messages():
    importer = ClaudeImporter()
    assert importer.detect(FIX / "basic-conversation.json") == 1.0


def test_detect_rejects_unrelated_json():
    chatgpt_fixture = Path(__file__).parent / "fixtures" / "chatgpt" / "v1" / "simple-conversation.json"
    importer = ClaudeImporter()
    assert importer.detect(chatgpt_fixture) == 0.0


def test_basic_conversation():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "basic-conversation.json")
    assert transcript.source == "claude"
    assert transcript.adapter == "claude-v1"
    assert transcript.title == "Basic Claude chat"
    assert transcript.conversation_id == "conv-basic-1"
    assert len(transcript.turns) == 2
    assert [t.role for t in transcript.turns] == ["user", "assistant"]
    assert transcript.turns[0].content_md == "Explain recursion simply."
    assert transcript.turns[0].timestamp == "2026-07-10T21:00:01.000000Z"


def test_conversation_with_artifacts_recorded_in_metadata():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "with-artifacts.json")
    assert transcript.turns[1].metadata.get("artifacts") == [
        {"identifier": "art-1", "title": "index.html", "type": "text/html"}
    ]
    # Content is referenced, never fetched: nothing beyond the reference dict itself.
    assert transcript.turns[1].content_md == "Here you go."


def test_conversation_with_attachments_recorded_in_metadata():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "with-attachments.json")
    assert transcript.turns[0].metadata.get("attachments") == [
        {"file_name": "notes.txt", "file_type": "text/plain"}
    ]


def test_missing_timestamps():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "missing-timestamps.json")
    assert all(t.timestamp is None for t in transcript.turns)


def test_unknown_sender_maps_to_unknown_role():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "unknown-sender.json")
    assert transcript.turns[0].role == "unknown"


def test_empty_content_is_recorded_not_fatal():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "empty-content.json")
    assert transcript.turns[0].content_md == ""
    assert transcript.turns[0].metadata.get("missing_content") is True


def test_multiple_conversations_require_selector():
    importer = ClaudeImporter()
    with pytest.raises(AmbiguousImporterError):
        importer.parse(FIX / "multiple-conversations.json")

    transcript = importer.parse(FIX / "multiple-conversations.json", "conv-multi-2")
    assert transcript.turns[0].content_md == "Two"


def test_list_conversations():
    importer = ClaudeImporter()
    summaries = importer.list_conversations(FIX / "multiple-conversations.json")
    assert len(summaries) == 2
    assert {s.conversation_id for s in summaries} == {"conv-multi-1", "conv-multi-2"}


def test_malformed_top_level_not_a_list_fails_explicitly():
    importer = ClaudeImporter()
    with pytest.raises(Exception):
        importer.parse(FIX / "malformed-not-a-list.json")


def test_missing_chat_messages_is_a_schema_error(tmp_path: Path):
    bad = tmp_path / "no-chat-messages.json"
    bad.write_text('[{"uuid": "c1", "name": "No messages key"}]', encoding="utf-8")
    importer = ClaudeImporter()
    with pytest.raises(ImporterSchemaError) as exc_info:
        importer.parse(bad)
    assert "chat_messages" in str(exc_info.value)


def test_imported_transcript_uses_the_canonical_renderer_and_roundtrips():
    importer = ClaudeImporter()
    transcript = importer.parse(FIX / "basic-conversation.json")
    rendered = render_transcript(transcript)
    roundtripped = parse_transcript(rendered)
    assert roundtripped.title == transcript.title
    assert [t.content_md for t in roundtripped.turns] == [t.content_md for t in transcript.turns]


def test_zip_archive_containing_conversations_json(tmp_path: Path):
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(FIX / "basic-conversation.json", "conversations.json")

    importer = ClaudeImporter()
    assert importer.detect(zip_path) == 1.0
    transcript = importer.parse(zip_path)
    assert transcript.title == "Basic Claude chat"
