"""soloctl CLI.

Command functions here are thin: parse arguments, call a service function,
render its result model. All business logic lives in the service functions
(perform_init, perform_import) so it is unit-testable without Typer or a
terminal in the loop.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypeVar

import typer

from . import __version__
from .compiler.compile import CompileOutcome, compile_transcript
from .config import SoloctlConfig, load_config
from .errors import IdempotencyConflict, OutcomeUnknown, SecretDetected, SoloctlError
from .importers import build_default_registry
from .importers.base import ConversationSummary
from .importers.registry import ImporterRegistry
from .ledger import EVENT_SCHEMA_VERSION, append_event, load_scrub_patterns, now_iso, scan_text_for_secret
from .library import collections as collections_svc
from .library import tags as tags_svc
from .library.paths import LibraryPaths
from .library.repository import InitResult, init_library
from .transcript.models import Transcript
from .transcript.render import render_transcript
from .transcript.storage import SavedTranscript, preview_transcript_destination, save_transcript
from .ucc_events import emit_event
from .verification.engine import DEFAULT_TIMEOUT
from .verification.service import VerifyOutcome, verify_artifact

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Local-first artifact compiler CLI.")
tag_app = typer.Typer(no_args_is_help=True, help="Tag compiled artifacts.")
collection_app = typer.Typer(no_args_is_help=True,
                             help="Group compiled artifacts into named collections.")
app.add_typer(tag_app, name="tag")
app.add_typer(collection_app, name="collection")

SCRUB_PATTERNS_FILENAME = "scrub-patterns.toml"
T = TypeVar("T")

# `soloctl verify` exit codes beyond 0 (passed) and 1 (refused: nothing ran
# or was recorded). Distinct from import's 2-4 so scripts can tell them apart.
VERIFY_EXIT = {"passed": 0, "failed": 5, "inconclusive": 6}


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


def _render_compile(outcome: CompileOutcome) -> None:
    acc = outcome.accounting
    verb = "would write" if outcome.dry_run else "wrote"
    print(f"soloctl compile — {'dry run: ' if outcome.dry_run else ''}"
          f"{outcome.title!r} ({outcome.transcript_path})")
    for d in outcome.drafts:
        note = f"  (renamed from {d.proposed_filename})" if d.renamed else ""
        print(f"  {verb}: {d.relative_path}  [{d.emitter}]{note}")
    for s in outcome.skipped + outcome.unsupported:
        detail = f" — {s.detail}" if s.detail else ""
        print(f"  skipped {s.reason}: {s.lang or '(unlabeled)'} at "
              f"{s.src.path}:{s.src.line_start}{detail}")
    print(f"  fences: {acc['fences_seen']} = {acc['drafts']} "
          f"{'planned' if outcome.dry_run else 'written'} + {acc['skipped']} "
          f"skipped + {acc['unsupported']} unsupported")
    if outcome.dry_run:
        print("  nothing written (--dry-run)")


def _render_verify(outcome: VerifyOutcome) -> None:
    report = outcome.report
    print(f"soloctl verify — {outcome.ref} ({outcome.state}, {report.emitter})")
    for c in report.checks:
        role = "required" if c.required else "advisory"
        print(f"  {c.status:<8} {c.name} [{role}, {c.kind}] — {c.detail}")
    for note in report.plan_notes:
        print(f"  note: {note}")
    print(f"  verdict: {report.verdict.upper()}")
    for reason in report.reasons:
        print(f"    - {reason}")
    print(f"  recorded: {outcome.relative_record_path}")
    print("  automatic verification only; manual verification is separate")


def _status(status: str) -> str:
    return "" if status in ("draft", "approved") else f"  ({status.upper()})"


def _render_tag_change(verb: str, change: tags_svc.TagChange) -> None:
    print(f"soloctl tag {verb} — {change.ref}")
    if change.changed:
        print(f"  {verb + ('ed' if verb == 'add' else 'd')}: {', '.join(change.changed)}")
    if change.unchanged:
        already = "already tagged" if verb == "add" else "not tagged"
        print(f"  {already}: {', '.join(change.unchanged)}")
    print(f"  tags: {', '.join(change.tags) or '(none)'}")
    if not change.written:
        print("  nothing to do")


def _render_member_change(verb: str, change: collections_svc.MemberChange) -> None:
    print(f"soloctl collection {verb} — {change.collection.name}")
    for ref in change.changed:
        print(f"  {verb + ('ed' if verb == 'add' else 'd')}: {ref}")
    for ref in change.unchanged:
        print(f"  {'already a member' if verb == 'add' else 'not a member'}: {ref}")
    print(f"  members: {len(change.collection.members)}")
    if not change.written:
        print("  nothing to do")


def _run_library_op(fn: Callable[[], T]) -> T:
    """Run a tag/collection service call; every domain refusal exits 1."""
    try:
        return fn()
    except SoloctlError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


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


@app.command(name="compile")
def compile_(
    path: Path = typer.Argument(..., help="Canonical transcript to compile"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Show the drafts that would be written without writing"),
    include_user: bool = typer.Option(False, "--include-user",
                                      help="Also compile fences from user turns"),
    library: Path = typer.Option(None, "--library", help="Library root directory"),
) -> None:
    """Compile a canonical transcript into draft artifacts under artifacts/drafts/."""
    config = _resolve_config(library)
    try:
        outcome = compile_transcript(config, path, dry_run=dry_run,
                                     include_user=include_user)
    except SecretDetected as exc:
        typer.secho(f"REFUSED: {exc}", fg=typer.colors.RED, err=True)
        typer.secho("Nothing was written. Remove the credential from the "
                    "transcript and re-run.", err=True)
        raise typer.Exit(2)
    except SoloctlError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    _render_compile(outcome)


@app.command(name="verify")
def verify(
    artifact: str = typer.Argument(..., help="scripts/foo.sh, or the path compile printed"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT, "--timeout", min=0.1,
                                  help="Seconds allowed per external check"),
    library: Path = typer.Option(None, "--library", help="Library root directory"),
) -> None:
    """Run an artifact's automatic verification plan and record the result
    under verification/. Exit 0 passed, 5 failed, 6 inconclusive, 1 refused."""
    config = _resolve_config(library)
    try:
        outcome = verify_artifact(config, artifact, timeout=timeout)
    except SoloctlError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    _render_verify(outcome)
    raise typer.Exit(VERIFY_EXIT[outcome.report.verdict])


# --------------------------------------------------------------------------- tag
_LIBRARY_OPT = typer.Option(None, "--library", help="Library root directory")


@tag_app.command("add")
def tag_add(
    artifact: str = typer.Argument(..., help="scripts/foo.sh, or the path compile printed"),
    tags: list[str] = typer.Argument(..., help="One or more tags (a-z, 0-9, '-')"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Add tags to a compiled artifact (draft or approved)."""
    config = _resolve_config(library)
    _render_tag_change("add", _run_library_op(
        lambda: tags_svc.add_tags(config, artifact, tags)))


@tag_app.command("remove")
def tag_remove(
    artifact: str = typer.Argument(..., help="scripts/foo.sh, or the path compile printed"),
    tags: list[str] = typer.Argument(..., help="One or more tags"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Remove tags from an artifact (also works once the file is gone)."""
    config = _resolve_config(library)
    _render_tag_change("remove", _run_library_op(
        lambda: tags_svc.remove_tags(config, artifact, tags)))


@tag_app.command("list")
def tag_list(
    artifact: str = typer.Argument(None, help="Show this artifact's tags"),
    tag: str = typer.Option(None, "--tag", help="Show the artifacts carrying this tag"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """List all tags, one artifact's tags, or the artifacts with a tag."""
    config = _resolve_config(library)
    if artifact and tag:
        typer.secho("ERROR: give an artifact or --tag, not both", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if artifact:
        one = _run_library_op(lambda: tags_svc.artifact_tags(config, artifact))
        print(f"{one.ref}: {', '.join(one.tags) or '(no tags)'}{_status(one.status)}")
    elif tag:
        hits = _run_library_op(lambda: tags_svc.artifacts_with_tag(config, tag))
        print(f"soloctl tag list — {tag}: {len(hits)} artifact{'s' if len(hits) != 1 else ''}")
        for h in hits:
            print(f"  {h.ref}{_status(h.status)}")
    else:
        index = _run_library_op(lambda: tags_svc.all_tags(config))
        print(f"soloctl tag list — {len(index)} tag{'s' if len(index) != 1 else ''}")
        for name, refs in index.items():
            print(f"  {name:<24} {len(refs)}")


# ------------------------------------------------------------------- collection
@collection_app.command("create")
def collection_create(
    name: str = typer.Argument(..., help="Collection name (a-z, 0-9, '-')"),
    title: str = typer.Option(None, "--title", help="Human-readable title"),
    description: str = typer.Option(None, "--description", help="What the collection is for"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Create an empty collection (a no-op if it already exists unchanged)."""
    config = _resolve_config(library)
    change = _run_library_op(lambda: collections_svc.create_collection(
        config, name, title=title, description=description))
    state = "created" if change.created else "already exists"
    print(f"soloctl collection create — {name}: {state}")


@collection_app.command("add")
def collection_add(
    name: str = typer.Argument(..., help="Collection name"),
    artifacts: list[str] = typer.Argument(..., help="Artifacts to append, in order"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Append artifacts to a collection."""
    config = _resolve_config(library)
    _render_member_change("add", _run_library_op(
        lambda: collections_svc.add_members(config, name, artifacts)))


@collection_app.command("remove")
def collection_remove(
    name: str = typer.Argument(..., help="Collection name"),
    artifacts: list[str] = typer.Argument(..., help="Members to remove"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Remove members from a collection (also works once a file is gone)."""
    config = _resolve_config(library)
    _render_member_change("remove", _run_library_op(
        lambda: collections_svc.remove_members(config, name, artifacts)))


@collection_app.command("show")
def collection_show(
    name: str = typer.Argument(..., help="Collection name"),
    library: Path = _LIBRARY_OPT,
) -> None:
    """Show a collection's members and their status."""
    config = _resolve_config(library)
    view = _run_library_op(lambda: collections_svc.show_collection(config, name))
    c = view.collection
    print(f"soloctl collection show — {c.name}" + (f": {c.title}" if c.title else ""))
    if c.description:
        print(f"  {c.description}")
    if not view.members:
        print("  (no members)")
    for i, m in enumerate(view.members, 1):
        print(f"  {i:>3}. {m.ref}{_status(m.status)}")


@collection_app.command("list")
def collection_list(library: Path = _LIBRARY_OPT) -> None:
    """List collections."""
    config = _resolve_config(library)
    found = _run_library_op(lambda: collections_svc.list_collections(config))
    print(f"soloctl collection list — {len(found)} collection{'s' if len(found) != 1 else ''}")
    for c in found:
        print(f"  {c.name:<24} {len(c.members):>3} members  {c.title}")


@app.command()
def version() -> None:
    """Print version."""
    print(f"soloctl {__version__}")


if __name__ == "__main__":
    app()
