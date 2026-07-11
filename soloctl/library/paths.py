"""Safe path resolution under a library root.

Every path a caller wants to read or write is resolved through here so that
no combination of configuration or user input can produce a path outside the
configured library root.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import PathEscapesLibraryError

TRANSCRIPTS = "transcripts"
ARTIFACTS = "artifacts"
DRAFTS = "drafts"
APPROVED = "approved"
REVOKED = "revoked"
SUPERSEDED = "superseded"
COLLECTIONS = "collections"
VERIFICATION = "verification"
EVENTS_FILE = "events.jsonl"

# Artifact-type subdirectories under drafts/ and approved/. Emitters land in
# WP3/4; the directories exist from WP1 so init produces the full layout.
ARTIFACT_KINDS = ("scripts", "prompts", "runbooks")


@dataclass(frozen=True)
class LibraryPaths:
    root: Path

    def resolve(self, *parts: str) -> Path:
        """Resolve root/*parts and guarantee the result stays under root."""
        root_resolved = self.root.resolve()
        candidate = (root_resolved / Path(*parts)).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            raise PathEscapesLibraryError(
                f"resolved path {candidate} escapes library root {root_resolved}; "
                f"refusing to touch it"
            ) from None
        return candidate

    @property
    def transcripts(self) -> Path:
        return self.resolve(TRANSCRIPTS)

    def transcript_month_dir(self, year: str, month: str) -> Path:
        return self.resolve(TRANSCRIPTS, year, month)

    @property
    def artifacts(self) -> Path:
        return self.resolve(ARTIFACTS)

    @property
    def drafts(self) -> Path:
        return self.resolve(ARTIFACTS, DRAFTS)

    @property
    def approved(self) -> Path:
        return self.resolve(ARTIFACTS, APPROVED)

    @property
    def revoked(self) -> Path:
        return self.resolve(ARTIFACTS, REVOKED)

    @property
    def superseded(self) -> Path:
        return self.resolve(ARTIFACTS, SUPERSEDED)

    @property
    def collections(self) -> Path:
        return self.resolve(COLLECTIONS)

    @property
    def verification(self) -> Path:
        return self.resolve(VERIFICATION)

    @property
    def events_file(self) -> Path:
        return self.resolve(EVENTS_FILE)

    def required_directories(self) -> tuple[Path, ...]:
        dirs = [self.transcripts, self.artifacts]
        for state in (DRAFTS, APPROVED):
            for kind in ARTIFACT_KINDS:
                dirs.append(self.resolve(ARTIFACTS, state, kind))
        dirs += [self.revoked, self.superseded, self.collections, self.verification]
        return tuple(dirs)
