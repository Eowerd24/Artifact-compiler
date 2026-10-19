"""Compilation coordinator (Work Package 4, items 1-3).

    canonical transcript -> extract -> registry.assign -> render -> drafts

This is the only module that turns candidates into files. The stages it
calls stay pure (the extractor and emitters never write, never read the
clock, never look at the library); everything stateful lives here:

  - **Collision resolution** against the library: a draft never overwrites
    anything. The emitter's `propose_filename()` is the starting point; if
    that name is taken in `drafts/<kind>/` or `approved/<kind>/` (or by an
    earlier draft in the same run), the coordinator retries with
    `<name>-2`, `<name>-3`, ... by handing the emitter a candidate whose
    `name_proposal` carries the suffix. The emitter then derives the
    filename *and* the header's `name:` line from it, so they always agree,
    and the emitter's own naming rules (Python's snake_case) still apply.
  - **Atomic draft writes** via `library.atomic` with `exist_ok=False`, so a
    file that appears between the check and the write (TOCTOU) is never
    clobbered — the coordinator moves on to the next suffix instead.
  - **Fence accounting**: `fences_seen == drafts + skipped + unsupported`,
    self-checked before anything is written. Nothing disappears silently
    between the transcript and the drafts directory.

Ordering invariants (never regress):

  1. Secret refusal precedes any write. The whole transcript is scanned
     (D4 whole-input abort) before it is even parsed, then the extractor
     scans every fence again; either raises `SecretDetected` before the
     first draft is written.
  2. Every candidate is rendered in memory before the first write, so an
     emitter error leaves the drafts directory untouched.
  3. Dry run writes nothing and appends no event. (No compile event exists
     yet in either mode — see HANDOFF_NOTES.md WP4, open decision 6.)

Contract-free by design: this module must not import `ucc_contracts`
(directly or through `ucc_events`, `artifact_store`, `artifact_port`, or the
idempotency modules). AC's core pipeline moves ahead of UCC; contract
coupling stays at the edges. `tests/test_compile.py` enforces this.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from pathlib import Path

from .. import __version__
from ..config import SoloctlConfig
from ..emitters.base import ArtifactEmitter, EmitContext
from ..emitters.registry import EmitterRegistry, registry_from_config
from ..errors import LibraryError, SecretDetected
from ..ledger import load_scrub_patterns, now_iso, scan_text_for_secret
from ..library.atomic import atomic_write_text
from ..library.paths import APPROVED, ARTIFACTS, DRAFTS, LibraryPaths
from ..transcript.models import Transcript
from ..transcript.parse import parse_transcript
from .classify import SUPPORTED_LANGUAGES
from .extract import extract
from .models import ArtifactCandidate, ArtifactType, SkipRecord

__all__ = [
    "KIND_DIRS", "SCRUB_PATTERNS_FILENAME", "DraftOutcome", "CompileOutcome",
    "compile_transcript",
]

SCRUB_PATTERNS_FILENAME = "scrub-patterns.toml"

# artifact_type -> subdirectory under drafts/ and approved/. Owned here, not
# by emitters: where an artifact lives is library layout, not rendering.
KIND_DIRS: dict[ArtifactType, str] = {
    "script": "scripts",
    "prompt": "prompts",
    "runbook": "runbooks",
}

# Upper bound on `-N` suffixes tried per candidate. Hitting it means
# something is badly wrong with the library (or a writer is racing us in a
# loop); refuse rather than spin.
MAX_COLLISION_SUFFIX = 1000


@dataclass(frozen=True)
class DraftOutcome:
    candidate: ArtifactCandidate   # with the resolved name_proposal
    emitter: str
    artifact_type: ArtifactType
    path: Path                     # absolute
    relative_path: Path            # relative to the library root
    proposed_filename: str         # emitter's choice before collision resolution
    written: bool                  # False on a dry run

    @property
    def renamed(self) -> bool:
        return self.path.name != self.proposed_filename


@dataclass(frozen=True)
class CompileOutcome:
    dry_run: bool
    transcript_path: Path
    title: str
    drafts: tuple[DraftOutcome, ...]
    skipped: tuple[SkipRecord, ...]        # extractor skips
    unsupported: tuple[SkipRecord, ...]    # `unsupported-emitter` (registry)
    fences_seen: int

    @property
    def written(self) -> tuple[DraftOutcome, ...]:
        return tuple(d for d in self.drafts if d.written)

    @property
    def accounting(self) -> dict[str, int]:
        """`fences_seen == drafts + skipped + unsupported`. On a real run
        `drafts` are written; on a dry run they are planned."""
        return {
            "fences_seen": self.fences_seen,
            "drafts": len(self.drafts),
            "written": len(self.written),
            "skipped": len(self.skipped),
            "unsupported": len(self.unsupported),
        }


def compile_transcript(config: SoloctlConfig, path: Path, *,
                       dry_run: bool = False,
                       registry: EmitterRegistry | None = None,
                       library_hashes: frozenset[str] = frozenset(),
                       include_user: bool = False,
                       compiled_at: str | None = None) -> CompileOutcome:
    """Compile one canonical transcript into draft artifacts.

    `library_hashes` is passed straight to `extract()` for exact-content
    dedup. The library has no hash index yet (manifest/index is WP5), so the
    CLI passes an empty set; callers that have hashes can inject them.
    `compiled_at` exists for deterministic tests; it defaults to now.
    """
    paths = LibraryPaths(config.library_root)
    if not paths.drafts.is_dir():
        raise LibraryError(
            f"no drafts directory at {paths.drafts}; run 'soloctl init "
            f"--library {paths.root}' first")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LibraryError(f"cannot read transcript {path}: {exc}") from exc
    source = _source_label(paths, path)

    # (1) Secret refusal before anything else — whole input first (even
    # before parsing: parse errors quote the offending line), then the
    # extractor's own per-fence scan. Both raise before any write.
    scrub = load_scrub_patterns(paths.root / SCRUB_PATTERNS_FILENAME)
    hit = scan_text_for_secret(text, scrub)
    if hit:
        label, line = hit
        raise SecretDetected(label, line, source)
    transcript = parse_transcript(text)
    result = extract(text, source=source, library_hashes=library_hashes,
                     only=SUPPORTED_LANGUAGES, include_user=include_user,
                     scrub_patterns=scrub)

    registry = registry or registry_from_config(config)
    assignment = registry.assign(result.candidates)
    fences_seen = result.stats["fences_seen"]

    # (2) Plan every draft — names resolved, content rendered — in memory.
    context = EmitContext(source=_context_source(transcript),
                          compiled_at=compiled_at or now_iso(),
                          tool_version=__version__)
    claimed: set[Path] = set()
    plans = [_plan(paths, emitter, candidate, claimed, context)
             for candidate, emitter in assignment.assigned]

    # (3) Accounting self-check, before the first write.
    accounted = len(plans) + len(result.skipped) + len(assignment.unsupported)
    if fences_seen != accounted:
        raise AssertionError(
            f"compile accounting broken: {fences_seen} fences != {len(plans)} "
            f"drafts + {len(result.skipped)} skipped + "
            f"{len(assignment.unsupported)} unsupported")

    drafts = tuple(_outcome(paths, p, written=False) if dry_run
                   else _write(paths, p, claimed, context) for p in plans)
    return CompileOutcome(
        dry_run=dry_run, transcript_path=path, title=transcript.title,
        drafts=drafts, skipped=result.skipped,
        unsupported=assignment.unsupported, fences_seen=fences_seen)


# ---------------------------------------------------------------------------
# Naming / collision resolution
# ---------------------------------------------------------------------------
@dataclass
class _Plan:
    emitter: ArtifactEmitter
    original: ArtifactCandidate    # as the extractor produced it
    suffix: int                    # 1 = no suffix
    resolved: ArtifactCandidate    # original with `-N` in name_proposal
    dest: Path
    rendered: str


def _kind_dirs(paths: LibraryPaths, artifact_type: ArtifactType) -> tuple[Path, Path]:
    kind = KIND_DIRS[artifact_type]
    return (paths.resolve(ARTIFACTS, DRAFTS, kind),
            paths.resolve(ARTIFACTS, APPROVED, kind))


def _with_suffix(candidate: ArtifactCandidate, n: int) -> ArtifactCandidate:
    if n == 1:
        return candidate
    return replace(candidate, name_proposal=f"{candidate.name_proposal}-{n}")


def _free_name(paths: LibraryPaths, emitter: ArtifactEmitter,
               candidate: ArtifactCandidate, claimed: Collection[Path],
               start: int) -> tuple[int, ArtifactCandidate, Path]:
    """First `<name>[-N]` (N >= start) whose filename is free in both
    drafts/<kind>/ and approved/<kind>/ and not claimed earlier in this run."""
    drafts_dir, approved_dir = _kind_dirs(paths, emitter.artifact_type)
    for n in range(start, MAX_COLLISION_SUFFIX + 1):
        resolved = _with_suffix(candidate, n)
        filename = emitter.propose_filename(resolved)
        dest = drafts_dir / filename
        if dest in claimed or dest.exists() or (approved_dir / filename).exists():
            continue
        return n, resolved, dest
    raise LibraryError(
        f"no free filename for {candidate.name_proposal!r} in {drafts_dir} "
        f"after {MAX_COLLISION_SUFFIX} attempts; clean up the drafts directory")


def _plan(paths: LibraryPaths, emitter: ArtifactEmitter,
          candidate: ArtifactCandidate, claimed: set[Path],
          context: EmitContext, start: int = 1) -> _Plan:
    n, resolved, dest = _free_name(paths, emitter, candidate, claimed, start)
    claimed.add(dest)
    return _Plan(emitter, candidate, n, resolved, dest,
                 emitter.render(resolved, context))


def _write(paths: LibraryPaths, plan: _Plan, claimed: set[Path],
           context: EmitContext) -> DraftOutcome:
    """Write one planned draft. If its name was taken after planning (another
    writer), move on to the next free suffix and re-render, so the header
    always names the file it is in. Never overwrites."""
    while True:
        try:
            atomic_write_text(plan.dest, plan.rendered, exist_ok=False)
        except FileExistsError:
            plan = _plan(paths, plan.emitter, plan.original, claimed, context,
                         start=plan.suffix + 1)
            continue
        return _outcome(paths, plan, written=True)


def _outcome(paths: LibraryPaths, plan: _Plan, *, written: bool) -> DraftOutcome:
    return DraftOutcome(
        candidate=plan.resolved, emitter=plan.emitter.name,
        artifact_type=plan.emitter.artifact_type, path=plan.dest,
        relative_path=plan.dest.relative_to(paths.root.resolve()),
        proposed_filename=plan.emitter.propose_filename(plan.original),
        written=written)


# ---------------------------------------------------------------------------
# Provenance strings
# ---------------------------------------------------------------------------
def _source_label(paths: LibraryPaths, path: Path) -> str:
    """Transcript path as it appears in SourceRefs and refusals: relative to
    the library root when inside it, else as given."""
    try:
        return str(path.resolve().relative_to(paths.root.resolve()))
    except ValueError:
        return str(path)


def _context_source(transcript: Transcript) -> str:
    """Header `source:` value, e.g. `chatgpt 2026-07-11 "forge provisioning"`."""
    parts = [transcript.source or transcript.adapter or "-"]
    if transcript.exported_at:
        parts.append(transcript.exported_at)
    if transcript.title:
        parts.append(f'"{transcript.title}"')
    return " ".join(parts)
