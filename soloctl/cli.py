"""soloctl CLI.

Command functions here are thin: parse arguments, call a service function,
render its result model. All business logic lives in the service functions
(perform_init, perform_import) so it is unit-testable without Typer or a
terminal in the loop.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import typer

from . import __version__
from .config import SoloctlConfig, load_config
from .errors import IdempotencyConflict, OutcomeUnknown, SecretDetected, SoloctlError
from .importers import build_default_registry
from .importers.base import ConversationSummary
from .importers.registry import ImporterRegistry
from .ledger import EVENT_SCHEMA_VERSION, append_event, load_scrub_patterns, now_iso, scan_text_for_secret
from .library.paths import LibraryPaths
from .library.repository import InitResult, init_library
from .transcript.models import Transcript
from .transcript.render import render_transcript
from .transcript.storage import SavedTranscript, preview_transcript_destination, save_transcript
from .ucc_events import emit_event

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Local-first artifact compiler CLI.")

SCRUB_PATTERNS_FILENAME = "scrub-patterns.toml"


# ---------------------------------------------------------------------------
# Service layer — importable, side-effect-explicit, no printing.
# ---------------------------------------------------------------------------
def perform_init(config: SoloctlConfig) -> InitResult:
    return init_library(config)


@dataclass(frozen=True)
class ImportOutcome:
    dry_run: bool
    written: SavedTranscript | None
    proposed_destination: Path | None
    title: str
    source: str
    adapter: str
    turn_count: int


def perform_list(config: SoloctlConfig, path: Path, *,
                  adapter: str | None = None,
                  registry: ImporterRegistry | None = None) -> tuple[ConversationSummary, ...]:
    registry = registry or build_default_registry()
    importer = registry.resolve(path, adapter=adapter)
    return importer.list_conversations(path)


def _log_import_event(paths: LibraryPaths, source_path: Path, transcript: Transcript, *,
                       result: str, detail: str, dry_run: bool) -> None:
    payload = {
        "result": result,
        "detail": detail,
        "source_path": str(source_path),
        "adapter": transcript.adapter,
        "conversation_id": transcript.conversation_id,
        "turns": len(transcript.turns),
        "dry_run": dry_run,
    }
    append_event(paths.events_file, {
        "schema": EVENT_SCHEMA_VERSION,
        "event": "transcript.import",
        "ts": now_iso(),
        **payload,
    })
    # Dual-write (roadmap §4B "Shared IDs/envelopes"): the legacy ledger
    # above stays the primary, unchanged read path; this is additive.
    event_type = "transcript.import_completed" if result == "ok" else "transcript.import_refused"
    emit_event(paths.ucc_events_file, event_type=event_type, payload=payload)


def perform_import(config: SoloctlConfig, path: Path, *,
                    adapter: str | None = None,
                    conversation_id: str | None = None,
                    title: str | None = None,
                    dry_run: bool = False,
                    registry: ImporterRegistry | None = None) -> ImportOutcome:
    registry = registry or build_default_registry()
    importer = registry.resolve(path, adapter=adapter)
    transcript = importer.parse(path, conversation_id)
    if title is not None:
        transcript = replace(transcript, title=title)

    rendered = render_transcript(transcript)
    paths = LibraryPaths(config.library_root)
    scrub_patterns = load_scrub_patterns(config.library_root / SCRUB_PATTERNS_FILENAME)
    hit = scan_text_for_secret(rendered, scrub_patterns)
    if hit:
        label, line = hit
        # Dry run performs no canonical mutation and appends no canonical audit
        # event (locked Decision 1-of-2 §1.24; SPEC-001 §C.7). The refusal is
        # still surfaced to the caller via SecretDetected below.
        if not dry_run:
            _log_import_event(paths, path, transcript, result="refused",
                              detail=f"secret:{label}", dry_run=dry_run)
        # `line` is an offset into the rendered canonical transcript (front
        # matter shifts it), not the original file — SecretDetected.path
        # says so explicitly rather than implying a false-precision match
        # against the source file's own line numbers.
        raise SecretDetected(label, line, f"rendered transcript of {path}")

    if dry_run:
        proposed = preview_transcript_destination(paths, transcript)
        return ImportOutcome(
            dry_run=True, written=None, proposed_destination=proposed,
            title=transcript.title, source=transcript.source,
            adapter=transcript.adapter, turn_count=len(transcript.turns))

    saved = save_transcript(paths, transcript)
    _log_import_event(paths, path, transcript, result="ok",
                      detail=str(saved.relative_path), dry_run=dry_run)
    return ImportOutcome(
        dry_run=False, written=saved, proposed_destination=None,
        title=transcript.title, source=transcript.source,
        adapter=transcript.adapter, turn_count=len(transcript.turns))


def _resolve_config(library: Path | None) -> SoloctlConfig:
    config = load_config()
    if library is not None:
        config = replace(config, library_root=library.resolve())
    return config


# ---------------------------------------------------------------------------
# Rendering — human-readable output, no business logic.
# ---------------------------------------------------------------------------
def _render_init(result: InitResult) -> None:
    if result.already_initialized and not result.created_directories and not result.created_files:
        print(f"soloctl init — library already initialized at {result.library_root}")
        return
    print(f"soloctl init — library at {result.library_root}")
    if result.created_directories:
        print(f"  created {len(result.created_directories)} director"
              f"{'y' if len(result.created_directories) == 1 else 'ies'}")
    if result.created_files:
        for f in result.created_files:
            print(f"  created {f.relative_to(result.library_root)}")
    if not result.created_directories and not result.created_files:
        print("  nothing to do (already up to date)")


def _render_list(path: Path, summaries: tuple[ConversationSummary, ...]) -> None:
    print(f"soloctl import — conversations in {path}:")
    if not summaries:
        print("  (none)")
        return
    for s in summaries:
        exported = s.exported_at or "-"
        print(f"  {s.conversation_id:<24} {s.turn_count:>3} turns  "
              f"{exported:<26} {s.title}")


def _render_import(outcome: ImportOutcome) -> None:
    if outcome.dry_run:
        print(f"soloctl import — dry run: {outcome.title!r} "
              f"({outcome.turn_count} turn{'s' if outcome.turn_count != 1 else ''})")
        print(f"  source:      {outcome.source}")
        print(f"  adapter:     {outcome.adapter}")
        print(f"  would write: {outcome.proposed_destination}")
        print("  nothing written (--dry-run)")
        return
    assert outcome.written is not None
    print(f"soloctl import — saved {outcome.title!r} "
          f"({outcome.turn_count} turn{'s' if outcome.turn_count != 1 else ''})")
    print(f"  source:  {outcome.source}")
    print(f"  adapter: {outcome.adapter}")
    print(f"  wrote:   {outcome.written.relative_path}")


def _render_import_result(result: dict) -> None:
    """Renders the ucc.result dict returned by perform_import_idempotent's
    real (non-dry, non-replay-passthrough) path — same information as
    _render_import, different (envelope) source shape."""
    print(f"soloctl import — {result['disposition']} (result {result['result_id']})")
    print(f"  request:     {result['request_id']}")
    print(f"  operation:   {result['operation_id']}")
    print(f"  correlation: {result['correlation_id']}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.command()
def init(
    library: Path = typer.Option(None, "--library", help="Library root directory"),
) -> None:
    """Initialize the filesystem library."""
    config = _resolve_config(library)
    try:
        result = perform_init(config)
    except SoloctlError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    _render_init(result)


@app.command(name="import")
def import_(
    path: Path = typer.Argument(..., help="Markdown file or chat export to import"),
    adapter: str = typer.Option(None, "--adapter", help="Explicit importer override, e.g. chatgpt-v1"),
    conversation: str = typer.Option(
        None, "--conversation", "--conv",
        help="Select a conversation by id, exact title, or unambiguous title substring"),
    title: str = typer.Option(None, "--title", help="Override the transcript title"),
    list_only: bool = typer.Option(False, "--list", help="List conversations found in path and exit"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported without writing"),
    library: Path = typer.Option(None, "--library", help="Library root directory"),
    idempotency_key: str = typer.Option(
        None, "--idempotency-key",
        help="Opt in to idempotent replay: repeating the same key+inputs returns the "
             "stored result instead of re-importing; reusing the key with different "
             "inputs refuses (exit 3). Omit for today's exactly-once-per-invocation behavior."),
) -> None:
    """Import a transcript into the library as canonical markdown."""
    config = _resolve_config(library)
    try:
        if list_only:
            summaries = perform_list(config, path, adapter=adapter)
            _render_list(path, summaries)
            return
        if idempotency_key:
            from .idempotent_import import perform_import_idempotent
            outcome = perform_import_idempotent(
                config, path, idempotency_key=idempotency_key, adapter=adapter,
                title=title, conversation_id=conversation, dry_run=dry_run)
        else:
            outcome = perform_import(config, path, adapter=adapter, title=title,
                                     conversation_id=conversation, dry_run=dry_run)
    except SecretDetected as exc:
        typer.secho(f"REFUSED: {exc}", fg=typer.colors.RED, err=True)
        typer.secho("Nothing was written. Remove the credential from the "
                    "source and re-run.", err=True)
        raise typer.Exit(2)
    except IdempotencyConflict as exc:
        typer.secho(f"REFUSED: {exc}", fg=typer.colors.RED, err=True)
        typer.secho("This --idempotency-key was already used with different "
                    "inputs. Use a new key, or repeat the exact same inputs.", err=True)
        raise typer.Exit(3)
    except OutcomeUnknown as exc:
        typer.secho(f"REFUSED: {exc}", fg=typer.colors.RED, err=True)
        typer.secho("Reconcile the prior import outcome before retrying this key.", err=True)
        raise typer.Exit(4)
    except SoloctlError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if isinstance(outcome, dict):
        _render_import_result(outcome)
    else:
        _render_import(outcome)


@app.command()
def version() -> None:
    """Print version."""
    print(f"soloctl {__version__}")


if __name__ == "__main__":
    app()
