from __future__ import annotations

import pytest

from soloctl.errors import TranscriptParseError
from soloctl.transcript.models import Transcript, Turn
from soloctl.transcript.parse import parse_transcript
from soloctl.transcript.render import render_transcript


def _roundtrip(transcript: Transcript) -> Transcript:
    return parse_transcript(render_transcript(transcript))


def test_basic_roundtrip():
    original = Transcript(
        source="markdown",
        adapter="markdown-v1",
        title="Example conversation",
        conversation_id=None,
        turns=(
            Turn(index=1, role="user", content_md="Create a backup script."),
            Turn(index=2, role="assistant", content_md="```bash\necho backup\n```"),
        ),
    )
    result = _roundtrip(original)
    assert result.source == original.source
    assert result.adapter == original.adapter
    assert result.title == original.title
    assert result.conversation_id == original.conversation_id
    assert len(result.turns) == 2
    for expected, actual in zip(original.turns, result.turns):
        assert actual.index == expected.index
        assert actual.role == expected.role
        assert actual.content_md == expected.content_md


def test_unicode_content():
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="Café ☕ résumé",
        conversation_id="conv-ünïcödé",
        turns=(Turn(index=1, role="assistant", content_md="héllo wörld 你好 🎉"),),
    )
    result = _roundtrip(original)
    assert result.title == original.title
    assert result.conversation_id == original.conversation_id
    assert result.turns[0].content_md == original.turns[0].content_md


def test_missing_timestamps():
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="No timestamps",
        conversation_id=None,
        turns=(Turn(index=1, role="user", content_md="hi", timestamp=None),),
    )
    result = _roundtrip(original)
    assert result.turns[0].timestamp is None


def test_timestamp_preserved():
    original = Transcript(
        source="chatgpt", adapter="chatgpt-v1", title="With timestamps",
        conversation_id="abc123",
        turns=(Turn(index=1, role="user", content_md="hi",
                    timestamp="2026-07-10T21:04:11Z"),),
    )
    result = _roundtrip(original)
    assert result.turns[0].timestamp == "2026-07-10T21:04:11Z"


def test_system_and_tool_roles():
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="Roles",
        conversation_id=None,
        turns=(
            Turn(index=1, role="system", content_md="system prompt"),
            Turn(index=2, role="tool", content_md="tool output"),
            Turn(index=3, role="unknown", content_md="???"),
        ),
    )
    result = _roundtrip(original)
    assert [t.role for t in result.turns] == ["system", "tool", "unknown"]


def test_fenced_code_preserved_exactly():
    code = "```python\ndef f(x):\n    return x + 1\n\n\nclass C:\n    pass\n```"
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="Code",
        conversation_id=None,
        turns=(Turn(index=1, role="assistant", content_md=code),),
    )
    result = _roundtrip(original)
    assert result.turns[0].content_md == code


def test_empty_turn_content():
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="Empty turn",
        conversation_id=None,
        turns=(
            Turn(index=1, role="user", content_md=""),
            Turn(index=2, role="assistant", content_md="reply"),
        ),
    )
    result = _roundtrip(original)
    assert result.turns[0].content_md == ""
    assert result.turns[1].content_md == "reply"


def test_html_comment_inside_message_content_is_preserved():
    content = "See note:\n<!-- not a turn marker -->\nDone."
    original = Transcript(
        source="markdown", adapter="markdown-v1", title="Comment inside",
        conversation_id=None,
        turns=(Turn(index=1, role="assistant", content_md=content),),
    )
    result = _roundtrip(original)
    assert result.turns[0].content_md == content


def test_invalid_front_matter_missing_delimiter():
    with pytest.raises(TranscriptParseError):
        parse_transcript("no front matter here\njust text")


def test_invalid_front_matter_unclosed():
    with pytest.raises(TranscriptParseError):
        parse_transcript("---\nkind: transcript\nsource: x\n")


def test_incorrect_declared_turn_count():
    text = (
        "---\n"
        "kind: transcript\n"
        "schema: 1\n"
        "source: markdown\n"
        "adapter: markdown-v1\n"
        "conversation_id: null\n"
        "title: Mismatch\n"
        "exported_at: null\n"
        "turns: 2\n"
        "---\n\n"
        "<!-- turn 1 role=user -->\n"
        "only one turn present\n"
    )
    with pytest.raises(TranscriptParseError):
        parse_transcript(text)


def test_missing_required_field():
    text = (
        "---\n"
        "kind: transcript\n"
        "schema: 1\n"
        "source: markdown\n"
        "title: Missing fields\n"
        "turns: 0\n"
        "---\n"
    )
    with pytest.raises(TranscriptParseError):
        parse_transcript(text)


def test_render_matches_documented_canonical_shape():
    transcript = Transcript(
        source="markdown", adapter="markdown-v1", title="Example conversation",
        conversation_id=None,
        turns=(
            Turn(index=1, role="user", content_md="Create a backup script."),
            Turn(index=2, role="assistant", content_md="```bash\necho backup\n```"),
        ),
    )
    rendered = render_transcript(transcript)
    assert rendered.startswith(
        "---\n"
        "kind: transcript\n"
        "schema: 1\n"
        "source: markdown\n"
        "adapter: markdown-v1\n"
        "conversation_id: null\n"
        "title: Example conversation\n"
        "exported_at: null\n"
        "turns: 2\n"
        "---\n"
    )
    assert "<!-- turn 1 role=user -->\nCreate a backup script." in rendered
    assert "<!-- turn 2 role=assistant -->\n```bash\necho backup\n```" in rendered
