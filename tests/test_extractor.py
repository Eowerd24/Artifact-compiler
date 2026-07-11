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
