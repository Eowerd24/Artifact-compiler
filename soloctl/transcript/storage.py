"""Save canonical transcripts under library/transcripts/YYYY/MM/<slug>.md.

Collision policy is deterministic and matches the artifact-naming policy in
COMPILER_PLAN.md: backup.md, backup-2.md, backup-3.md, ... An existing
transcript file is never overwritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..library.atomic import atomic_write_text
from ..library.paths import LibraryPaths
from .models import Transcript
from .render import render_transcript


def slugify_title(text: str, max_len: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def next_available_path(directory: Path, slug: str, suffix: str = ".md") -> Path:
    """First non-existing directory/slug[.md|-2.md|-3.md|...]."""
    candidate = directory / f"{slug}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{slug}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _plan_destination(paths: LibraryPaths, transcript: Transcript,
                       when: datetime | None) -> tuple[Path, str]:
    when = when or datetime.now(timezone.utc)
    slug = slugify_title(transcript.title) or "untitled"
    month_dir = paths.resolve("transcripts", f"{when.year:04d}", f"{when.month:02d}")
    return next_available_path(month_dir, slug), slug


def preview_transcript_destination(paths: LibraryPaths, transcript: Transcript, *,
                                    when: datetime | None = None) -> Path:
    """Compute the path a save_transcript call would use, without writing."""
    dest, _slug = _plan_destination(paths, transcript, when)
    return dest


@dataclass(frozen=True)
class SavedTranscript:
    path: Path
    relative_path: Path
    slug: str


def save_transcript(paths: LibraryPaths, transcript: Transcript, *,
                     when: datetime | None = None) -> SavedTranscript:
    """Render and atomically write a transcript. Never overwrites an
    existing file — resolves a fresh collision-safe name instead."""
    dest, slug = _plan_destination(paths, transcript, when)
    rendered = render_transcript(transcript)
    atomic_write_text(dest, rendered, exist_ok=False)
    return SavedTranscript(
        path=dest, relative_path=dest.relative_to(paths.root), slug=slug)
