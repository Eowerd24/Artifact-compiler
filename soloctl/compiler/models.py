"""Compiler data model (EXTRACTOR_BLUEPRINT.md §2, generalized for Phase 6).

`ArtifactCandidate` is the language-neutral successor of the WP1 `Block`:
every field `Block` had is kept with the same name, type, and meaning, and
three fields are added so that the language label, the artifact type, and
(later) the emitter stay separate concerns:

    fence label (lang_raw)  ->  language (lang)  ->  artifact_type  ->  emitter
    "postgres"                  "sql"                "script"           SqlEmitter
    "md"                        "markdown"           "runbook"          RunbookEmitter

The candidate never names its emitter — that is resolved by
`soloctl.emitters.registry.EmitterRegistry`, so the extractor stays ignorant
of which emitters exist or are enabled.

`Block` remains importable as an alias of `ArtifactCandidate` so existing
callers and tests keep working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ArtifactType = Literal["script", "prompt", "runbook"]


@dataclass(frozen=True)
class SourceRef:
    path: str
    line_start: int
    line_end: int
    turn: int | None = None
    role: str | None = None


@dataclass(frozen=True)
class ArtifactCandidate:
    lang: str                       # normalized language ("bash", "sql", ...)
    body: str                       # verbatim fence content
    body_norm: str                  # normalized for hashing (blueprint §6)
    sha256: str                     # of body_norm
    name_proposal: str              # slug, pre-collision-resolution
    description: str                # harvested (blueprint §5)
    heading_path: tuple[str, ...]
    flags: tuple[str, ...]          # risk flags (annotate, never block)
    src: SourceRef
    artifact_type: ArtifactType     # script | prompt | runbook
    lang_raw: str                   # fence label exactly as classified ("pwsh")
    supersedes: str | None = None   # sha256 of the latest prior revision
    superseded_count: int = 0
    dialect: str | None = None      # language sub-variant from the label
                                    # (SQL only today: "postgresql", "mysql", ...)


# WP1/WP2 name, kept so `from soloctl.compiler.extract import Block` and any
# isinstance checks keep working. It is the same class, not a subclass.
Block = ArtifactCandidate


@dataclass(frozen=True)
class SkipRecord:
    reason: str   # unlabeled | non-target-lang | console | user-turn |
                  # dupe-in-library | superseded | empty | unsupported-emitter
    lang: str | None
    src: SourceRef
    detail: str = ""


@dataclass(frozen=True)
class ExtractResult:
    blocks: tuple[ArtifactCandidate, ...]
    skipped: tuple[SkipRecord, ...]
    stats: dict

    @property
    def candidates(self) -> tuple[ArtifactCandidate, ...]:
        """Phase 6 name for `blocks` (same tuple)."""
        return self.blocks
