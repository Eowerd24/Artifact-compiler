"""G2 dual-write: every real import also appends a schema-conformant
ucc.event to library/events/artifact-compiler.jsonl, alongside (not instead
of) the legacy transcript.import ledger event. Dry-run and the legacy
dry-run-no-write invariant apply identically to the new stream."""
import json
from pathlib import Path

import pytest

from soloctl.cli import perform_import
from soloctl.config import SoloctlConfig
from soloctl.errors import SecretDetected
from soloctl.importers import build_default_registry
from soloctl.library.repository import init_library
from ucc_contracts import validate_document

PLAIN = "# t\n\nuser: hello\n\nassistant: hi\n"


def _config(tmp_path: Path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    return config


def _read_ucc_events(config: SoloctlConfig) -> list[dict]:
    events_path = config.library_root / "events" / "artifact-compiler.jsonl"
    if not events_path.exists():
        return []
    lines = [l for l in events_path.read_text(encoding="utf-8").splitlines() if l]
    return [json.loads(l) for l in lines]


def test_real_import_appends_a_conformant_ucc_event(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    perform_import(config, src, dry_run=False, registry=build_default_registry())

    events = _read_ucc_events(config)
    assert len(events) == 1
    event = events[0]
    validate_document("event", event)  # must not raise
    assert event["event_type"] == "transcript.import_completed"
    assert event["producer"]["module_id"] == "artifact-compiler"
    assert event["producer_sequence"] == 0


def test_dry_run_appends_no_ucc_event(tmp_path: Path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    perform_import(config, src, dry_run=True, registry=build_default_registry())

    assert _read_ucc_events(config) == []


def test_secret_refusal_appends_a_refused_ucc_event(tmp_path: Path):
    src = tmp_path / "secret.md"
    src.write_text(
        "```bash\nexport GITHUB_TOKEN=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n```\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)

    with pytest.raises(SecretDetected):
        perform_import(config, src, dry_run=False, registry=build_default_registry())

    events = _read_ucc_events(config)
    assert len(events) == 1
    validate_document("event", events[0])
    assert events[0]["event_type"] == "transcript.import_refused"


def test_secret_dry_run_refusal_appends_no_ucc_event(tmp_path: Path):
    src = tmp_path / "secret.md"
    src.write_text(
        "```bash\nexport GITHUB_TOKEN=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n```\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)

    with pytest.raises(SecretDetected):
        perform_import(config, src, dry_run=True, registry=build_default_registry())

    assert _read_ucc_events(config) == []


def test_producer_sequence_increments_across_events(tmp_path: Path):
    config = _config(tmp_path)
    for i in range(3):
        src = tmp_path / f"plain{i}.md"
        src.write_text(PLAIN, encoding="utf-8")
        perform_import(config, src, dry_run=False, registry=build_default_registry())

    events = _read_ucc_events(config)
    assert [e["producer_sequence"] for e in events] == [0, 1, 2]


def test_legacy_ledger_still_written_alongside_ucc_event(tmp_path: Path):
    """Dual-write means both streams get an entry for the same import, not
    one replacing the other (roadmap §4B: 'keep legacy ledger readable')."""
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    perform_import(config, src, dry_run=False, registry=build_default_registry())

    legacy_events_path = config.library_root / "events.jsonl"
    legacy_lines = [l for l in legacy_events_path.read_text(encoding="utf-8").splitlines() if l]
    assert len(legacy_lines) == 1
    assert json.loads(legacy_lines[0])["event"] == "transcript.import"
    assert len(_read_ucc_events(config)) == 1
