"""Locked dry-run invariant: a secret-refused dry run must not append events
(Decision 1-of-2 §1.24; SPEC-001 §C.7)."""
from pathlib import Path
import pytest
from soloctl.cli import perform_import
from soloctl.config import SoloctlConfig
from soloctl.library.repository import init_library
from soloctl.library.paths import LibraryPaths
from soloctl.errors import SecretDetected


def test_secret_dry_run_appends_no_event(tmp_path):
    cfg = SoloctlConfig(library_root=tmp_path / "library")
    init_library(cfg)
    events = LibraryPaths(cfg.library_root).events_file
    before = events.read_text(encoding="utf-8") if events.exists() else ""

    src = tmp_path / "leak.md"
    src.write_text("# t\n\nuser: token=ghp_" + "a" * 40 + "\n", encoding="utf-8")
    with pytest.raises(SecretDetected):
        perform_import(cfg, src, dry_run=True)

    after = events.read_text(encoding="utf-8") if events.exists() else ""
    assert after == before, "dry-run secret refusal must not write a ledger event"


def test_secret_real_run_still_logs_refusal(tmp_path):
    cfg = SoloctlConfig(library_root=tmp_path / "library")
    init_library(cfg)
    events = LibraryPaths(cfg.library_root).events_file
    before = events.read_text(encoding="utf-8") if events.exists() else ""

    src = tmp_path / "leak.md"
    src.write_text("# t\n\nuser: token=ghp_" + "a" * 40 + "\n", encoding="utf-8")
    with pytest.raises(SecretDetected):
        perform_import(cfg, src, dry_run=False)

    after = events.read_text(encoding="utf-8") if events.exists() else ""
    assert len(after) > len(before), "a real (non-dry) refusal must still be audited"
