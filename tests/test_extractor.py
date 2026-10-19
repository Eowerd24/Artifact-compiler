"""Extractor regression tests — converted from the soloctl-0.1.0 bare-assert
selftest.py into pytest, covering the same behaviors 1:1."""
from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.compiler.extract import SecretDetected, extract

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_paste_simple():
    r = extract(load("paste-simple.md"), source="paste-simple.md")
    assert r.stats["fences_seen"] == len(r.blocks) + len(r.skipped)
    assert len(r.blocks) == 2
    names = [b.name_proposal for b in r.blocks]
    assert "disk-usage-report" in names
    assert "rotate-panel-key" in names
    d = next(b for b in r.blocks if b.name_proposal == "disk-usage-report")
    assert d.description.startswith("Prints the top consumers")
    assert d.heading_path == ("Homelab snippets", "Disk usage report")
    rp = next(b for b in r.blocks if b.name_proposal == "rotate-panel-key")
    assert rp.description == "Homelab snippets / Rotate panel key"
    reasons = sorted(s.reason for s in r.skipped)
    assert reasons == ["non-target-lang", "unlabeled"]
    assert not r.stats["transcript_mode"]


def test_transcript():
    r = extract(load("transcript-forge.md"), source="transcript-forge.md")
    assert r.stats["fences_seen"] == len(r.blocks) + len(r.skipped)
    assert r.stats["transcript_mode"] and r.stats["turns"] == 6
    assert len(r.blocks) == 1
    b = r.blocks[0]
    assert b.name_proposal == "tailnet-join"
    assert "v2" in b.body
    assert b.superseded_count == 1 and b.supersedes is not None
    assert b.description == "Add idempotency and error handling."
    assert b.src.turn == 4 and b.src.role == "assistant"
    assert "sudo" in b.flags and "firewall" in b.flags
    reasons = sorted(s.reason for s in r.skipped)
    assert reasons == ["console", "non-target-lang", "superseded", "user-turn"]
    sup = next(s for s in r.skipped if s.reason == "superseded")
    assert "tailnet-join" in sup.detail


def test_include_user_and_all_revisions():
    r = extract(load("transcript-forge.md"), source="t", include_user=True)
    assert any(b.src.role == "user" for b in r.blocks)
    r2 = extract(load("transcript-forge.md"), source="t", all_revisions=True)
    assert sum(1 for b in r2.blocks if "tailnet" in b.name_proposal
              or "join-node" in b.name_proposal) >= 2


def test_idempotence_via_library_hashes():
    first = extract(load("paste-simple.md"), source="p")
    hashes = frozenset(b.sha256 for b in first.blocks)
    second = extract(load("paste-simple.md"), source="p", library_hashes=hashes)
    assert len(second.blocks) == 0
    assert sum(1 for s in second.skipped if s.reason == "dupe-in-library") == 2


def test_secret_aborts_whole_run():
    with pytest.raises(SecretDetected) as exc_info:
        extract(load("paste-secret.md"), source="paste-secret.md")
    exc = exc_info.value
    assert exc.label == "gh-token"
    assert exc.line > 0


def test_kv_literal_vs_reference():
    ok = "```bash\nPASSWORD=\"$1\"\nTOKEN=$(cat ~/.creds/x)\napi_key=${KEY}\n```"
    r = extract(ok, source="inline")
    assert len(r.blocks) == 1

    bad = "```bash\npassword=hunter2secret123\n```"
    with pytest.raises(SecretDetected):
        extract(bad, source="inline")


def test_normalization_stability():
    a = extract("```bash\necho hi \n```", source="a").blocks[0]
    b = extract("```bash\r\necho hi\r\n```", source="b").blocks[0]
    assert a.sha256 == b.sha256


def test_name_fallbacks():
    r = extract("```bash\n#!/usr/bin/env bash\n# rotate the panel key\nssh-keygen\n```",
                source="x")
    assert r.blocks[0].name_proposal == "rotate-the-panel-key"
    r2 = extract("```bash\nssh-keygen\n```", source="x")
    assert r2.blocks[0].name_proposal == "block-01"


def test_empty_fence():
    r = extract("```bash\n```", source="x")
    assert len(r.blocks) == 0 and r.skipped[0].reason == "empty"


def test_fences_seen_invariant_holds_for_mixed_document():
    r = extract(load("transcript-forge.md"), source="t", all_revisions=True)
    assert r.stats["fences_seen"] == len(r.blocks) + len(r.skipped)


def test_extractor_contains_no_importer_specific_logic():
    """Architectural boundary check: the extractor only ever sees rendered
    canonical markdown text. It must never grow a branch for a specific
    import source (ChatGPT, Claude, ...) — that would violate the
    importer/extractor separation the whole compiler design depends on."""
    import soloctl.compiler.extract as extract_module

    source = Path(extract_module.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("chatgpt", "claude", "mapping", "current_node", "chat_messages"):
        assert forbidden not in lowered, f"extractor references {forbidden!r}"


# --------------------------------------------------------------------------
# Work Package 3 — language-neutral ArtifactCandidate extraction. Everything
# above is the WP1 baseline and stays byte-for-byte; the tests below extend it.
# --------------------------------------------------------------------------
from soloctl.compiler.classify import LABELS, SUPPORTED_LANGUAGES  # noqa: E402
from soloctl.compiler.extract import (  # noqa: E402
    DEFAULT_ONLY, ArtifactCandidate, Block,
)
from soloctl.errors import UnknownLanguageError  # noqa: E402

GH_TOKEN = "ghp_" + "A" * 36


def _one(label: str, body: str = "x = 1", **kw) -> ArtifactCandidate:
    r = extract(f"```{label}\n{body}\n```", source="inline",
                only=SUPPORTED_LANGUAGES, **kw)
    assert len(r.blocks) == 1, r.skipped
    return r.blocks[0]


def test_polyglot_transcript_extracts_every_supported_language():
    r = extract(load("transcript-polyglot.md"), source="polyglot",
                only=SUPPORTED_LANGUAGES)
    assert r.stats["fences_seen"] == len(r.candidates) + len(r.skipped) == 10
    got = [(c.lang, c.lang_raw, c.artifact_type, c.dialect, c.name_proposal)
           for c in r.candidates]
    assert got == [
        ("bash", "bash", "script", None, "disk-audit"),
        ("python", "py", "script", None, "disk-audit-python"),
        ("powershell", "pwsh", "script", None, "disk-audit-powershell"),
        ("sql", "postgres", "script", "postgresql", "largest-tables"),
        ("prompt", "prompt", "prompt", None, "summarize-audit"),
        ("markdown", "md", "runbook", None, "disk-full-runbook"),
    ]
    for c in r.candidates:
        assert c.src.turn == 2 and c.src.role == "assistant"
        assert c.description == "Give me tooling to audit disk usage across the fleet."
    runbook = r.candidates[-1]
    assert runbook.flags == ("sudo",)
    assert sorted(s.reason for s in r.skipped) == [
        "console", "non-target-lang", "unlabeled", "user-turn"]
    assert next(s for s in r.skipped if s.reason == "non-target-lang").lang == "yaml"
    assert r.stats["by_artifact_type"] == {"script": 4, "prompt": 1, "runbook": 1}


def test_default_only_is_still_bash_so_wp1_callers_are_unchanged():
    assert DEFAULT_ONLY == frozenset({"bash"})
    r = extract(load("transcript-polyglot.md"), source="polyglot")
    assert [c.lang for c in r.candidates] == ["bash"]
    assert r.stats["fences_seen"] == len(r.candidates) + len(r.skipped)
    not_selected = [s for s in r.skipped if s.detail.endswith("not selected")]
    assert sorted(s.lang for s in not_selected) == [
        "md", "postgres", "prompt", "pwsh", "py", "python"]


@pytest.mark.parametrize("label,lang,artifact_type,dialect", [
    ("bash", "bash", "script", None), ("sh", "bash", "script", None),
    ("shell", "bash", "script", None), ("zsh", "bash", "script", None),
    ("python", "python", "script", None), ("py", "python", "script", None),
    ("powershell", "powershell", "script", None),
    ("pwsh", "powershell", "script", None), ("ps1", "powershell", "script", None),
    ("sql", "sql", "script", None),
    ("postgres", "sql", "script", "postgresql"),
    ("postgresql", "sql", "script", "postgresql"),
    ("mysql", "sql", "script", "mysql"), ("sqlite", "sql", "script", "sqlite"),
    ("tsql", "sql", "script", "tsql"),
    ("prompt", "prompt", "prompt", None),
    ("markdown", "markdown", "runbook", None), ("md", "markdown", "runbook", None),
    ("runbook", "markdown", "runbook", None),
])
def test_label_classification(label, lang, artifact_type, dialect):
    c = _one(label)
    assert (c.lang, c.artifact_type, c.dialect, c.lang_raw) == (
        lang, artifact_type, dialect, label)


def test_label_table_covers_exactly_the_specified_labels():
    assert set(LABELS) == {
        "bash", "sh", "shell", "zsh", "python", "py", "powershell", "pwsh",
        "ps1", "sql", "postgres", "postgresql", "mysql", "sqlite", "tsql",
        "prompt", "markdown", "md", "runbook"}
    assert SUPPORTED_LANGUAGES == {
        "bash", "python", "powershell", "sql", "prompt", "markdown"}


def test_label_is_case_insensitive_and_ignores_info_attributes():
    c = _one("Python title=x.py")
    assert c.lang == "python" and c.lang_raw == "python"


@pytest.mark.parametrize("label", ["console", "terminal", "shell-session"])
def test_console_family_is_skipped_even_with_every_language_selected(label):
    r = extract(f"```{label}\n$ ls\nfile\n```", source="x", only=SUPPORTED_LANGUAGES)
    assert not r.blocks and [s.reason for s in r.skipped] == ["console"]


def test_unlabeled_fence_is_skipped_even_with_every_language_selected():
    r = extract("```\nprint('hi')\n```", source="x", only=SUPPORTED_LANGUAGES)
    assert not r.blocks and [s.reason for s in r.skipped] == ["unlabeled"]


def test_user_turn_skip_applies_to_every_language():
    doc = ("<!-- turn 1 role=user -->\n```python\nprint('mine')\n```\n\n"
           "<!-- turn 2 role=assistant -->\n```sql\nSELECT 1;\n```\n")
    r = extract(doc, source="x", only=SUPPORTED_LANGUAGES)
    assert [c.lang for c in r.blocks] == ["sql"]
    assert [s.reason for s in r.skipped] == ["user-turn"]
    r2 = extract(doc, source="x", only=SUPPORTED_LANGUAGES, include_user=True)
    assert sorted(c.lang for c in r2.blocks) == ["python", "sql"]
    assert r2.stats["fences_seen"] == len(r2.blocks) + len(r2.skipped)


def test_supersede_within_one_non_bash_language_last_wins():
    doc = ("## Report\n\n```python\nprint('v1')\n```\n\n"
           "## Report\n\n```python\nprint('v2')\nprint('extra')\n```\n")
    r = extract(doc, source="x", only=SUPPORTED_LANGUAGES)
    assert len(r.blocks) == 1
    b = r.blocks[0]
    assert "v2" in b.body and b.superseded_count == 1 and b.supersedes
    assert [s.reason for s in r.skipped] == ["superseded"]


def test_supersede_never_crosses_languages():
    # Same heading (so name_proposal matches) and near-identical bodies:
    # within one language this would collapse; across languages it must not.
    doc = ("## Greet\n\n```bash\necho hello\n```\n\n"
           "## Greet\n\n```powershell\necho hello\n```\n")
    r = extract(doc, source="x", only=SUPPORTED_LANGUAGES)
    assert [c.lang for c in r.blocks] == ["bash", "powershell"]
    assert all(c.superseded_count == 0 for c in r.blocks)
    assert r.blocks[0].sha256 == r.blocks[1].sha256   # hash is content-only


@pytest.mark.parametrize("label", [
    "python", "pwsh", "sql", "prompt", "md", "", "console", "json"])
def test_secret_in_any_fence_aborts_whole_input(label):
    doc = ("```bash\necho fine\n```\n\n"
           f"```{label}\nTOKEN = \"{GH_TOKEN}\"\n```\n")
    with pytest.raises(SecretDetected) as exc_info:
        extract(doc, source="mixed.md", only=SUPPORTED_LANGUAGES)
    assert exc_info.value.label == "gh-token"
    assert exc_info.value.line == 6


def test_library_hash_dedup_covers_every_language():
    t = load("transcript-polyglot.md")
    first = extract(t, source="p", only=SUPPORTED_LANGUAGES)
    hashes = frozenset(c.sha256 for c in first.candidates)
    second = extract(t, source="p", only=SUPPORTED_LANGUAGES, library_hashes=hashes)
    assert second.candidates == ()
    dupes = [s for s in second.skipped if s.reason == "dupe-in-library"]
    assert len(dupes) == len(first.candidates) == 6
    assert second.stats["fences_seen"] == len(second.skipped)


def test_multi_language_extraction_is_deterministic():
    t = load("transcript-polyglot.md")
    runs = [extract(t, source="p", only=SUPPORTED_LANGUAGES) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_comment_name_fallback_uses_each_languages_comment_syntax():
    assert _one("sql", "-- top customers\nSELECT 1;").name_proposal == "top-customers"
    assert _one("python", "# rotate logs\nprint(1)").name_proposal == "rotate-logs"
    assert _one("pwsh", "# list drives\nGet-PSDrive").name_proposal == "list-drives"
    assert _one("md", "# Disk full\n\n1. step").name_proposal == "disk-full"
    # prompts have no comment syntax: a leading '#' is prompt text, not a name
    assert _one("prompt", "# Role\nYou are helpful.").name_proposal == "block-01"
    # SQL doesn't treat '#' as a comment, bash doesn't treat '--' as one
    assert _one("sql", "# nope\nSELECT 1;").name_proposal == "block-01"
    assert _one("bash", "-- nope\necho 1").name_proposal == "block-01"


def test_only_rejects_names_that_are_not_normalized_languages():
    for bad in ({"runbook"}, {"pwsh"}, {"json"}):
        with pytest.raises(UnknownLanguageError) as exc_info:
            extract("```bash\necho\n```", source="x", only=bad)
        assert "markdown" in str(exc_info.value)   # names the valid choices


def test_block_is_an_alias_of_artifact_candidate():
    assert Block is ArtifactCandidate
    r = extract("```bash\necho hi\n```", source="x")
    assert isinstance(r.blocks[0], Block)
    assert r.candidates is r.blocks
    c = r.blocks[0]
    assert (c.artifact_type, c.lang_raw, c.dialect) == ("script", "bash", None)


def test_classifier_and_models_contain_no_importer_specific_logic():
    """Same boundary as the extract.py check above, for the WP3 modules."""
    import soloctl.compiler.classify as classify_module
    import soloctl.compiler.models as models_module

    for mod in (classify_module, models_module):
        lowered = Path(mod.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("chatgpt", "claude", "mapping", "current_node", "chat_messages"):
            assert forbidden not in lowered, f"{mod.__name__} references {forbidden!r}"
