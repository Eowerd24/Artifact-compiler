"""Emitter registry (Phase 7).

Matching rule: exactly one enabled emitter must `supports()` a candidate.
  - zero matches  -> `unsupported-emitter` (UnsupportedEmitterError from
                     `resolve()`, or a SkipRecord from `assign()` so nothing
                     disappears silently downstream)
  - many matches  -> EmitterConfigurationError. Overlapping emitters are an
                     internal configuration bug; the registry never resolves
                     one by picking a winner (first-registered, priority, ...).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..compiler.models import ArtifactCandidate, SkipRecord
from ..config import DEFAULT_ENABLED_EMITTERS, SoloctlConfig
from ..errors import EmitterConfigurationError, UnsupportedEmitterError
from .base import ArtifactEmitter
from .bash import BashEmitter
from .powershell import PowerShellEmitter
from .prompt import PromptEmitter
from .python import PythonEmitter
from .runbook import RunbookEmitter
from .sql import SqlEmitter

__all__ = [
    "BUILTIN_EMITTERS", "EmitterAssignment", "EmitterRegistry",
    "default_registry", "registry_from_config",
]

# name -> factory(sql_dialect). The factory signature is uniform so the
# registry needs no per-emitter construction logic beyond this table.
BUILTIN_EMITTERS: dict[str, Callable[[str | None], ArtifactEmitter]] = {
    "bash": lambda _dialect: BashEmitter(),
    "python": lambda _dialect: PythonEmitter(),
    "powershell": lambda _dialect: PowerShellEmitter(),
    "sql": lambda dialect: SqlEmitter(default_dialect=dialect),
    "prompt": lambda _dialect: PromptEmitter(),
    "runbook": lambda _dialect: RunbookEmitter(),
}


@dataclass(frozen=True)
class EmitterAssignment:
    assigned: tuple[tuple[ArtifactCandidate, ArtifactEmitter], ...]
    unsupported: tuple[SkipRecord, ...]


class EmitterRegistry:
    def __init__(self, emitters: Iterable[ArtifactEmitter]) -> None:
        self._emitters: tuple[ArtifactEmitter, ...] = tuple(emitters)
        seen: set[str] = set()
        for emitter in self._emitters:
            if not isinstance(emitter, ArtifactEmitter):
                raise EmitterConfigurationError(
                    f"{emitter!r} does not implement the ArtifactEmitter protocol "
                    f"(name, artifact_type, extension, supports, normalize, "
                    f"propose_filename, render, verification_plan, executable)")
            if emitter.name in seen:
                raise EmitterConfigurationError(
                    f"two emitters are registered under the name {emitter.name!r}; "
                    f"emitter names must be unique")
            seen.add(emitter.name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self._emitters)

    def get(self, name: str) -> ArtifactEmitter:
        for emitter in self._emitters:
            if emitter.name == name:
                return emitter
        raise EmitterConfigurationError(
            f"no emitter named {name!r} is registered; registered: {list(self.names)}")

    def resolve(self, candidate: ArtifactCandidate) -> ArtifactEmitter:
        matches = [e for e in self._emitters if e.supports(candidate)]
        if len(matches) == 1:
            return matches[0]
        location = f"{candidate.src.path}:{candidate.src.line_start}"
        if not matches:
            raise UnsupportedEmitterError(
                candidate.lang, candidate.artifact_type, location,
                detail=f"enabled emitters: {list(self.names) or 'none'}")
        raise EmitterConfigurationError(
            f"emitters {[e.name for e in matches]} all claim the "
            f"{candidate.artifact_type!r} candidate in language {candidate.lang!r} "
            f"at {location}; exactly one emitter may support a candidate — "
            f"fix the overlapping supports() rules")

    def assign(self, candidates: Iterable[ArtifactCandidate]) -> EmitterAssignment:
        """Resolve every candidate. Unsupported candidates become
        `unsupported-emitter` skip records (so the caller can keep the
        fences_seen == emitted + skipped accounting); configuration errors
        still raise."""
        assigned: list[tuple[ArtifactCandidate, ArtifactEmitter]] = []
        unsupported: list[SkipRecord] = []
        for candidate in candidates:
            try:
                assigned.append((candidate, self.resolve(candidate)))
            except UnsupportedEmitterError as exc:
                unsupported.append(SkipRecord(
                    exc.reason, candidate.lang, candidate.src,
                    detail=f"{candidate.artifact_type}: no enabled emitter"))
        return EmitterAssignment(tuple(assigned), tuple(unsupported))


def default_registry(enabled: Iterable[str] = DEFAULT_ENABLED_EMITTERS, *,
                     sql_dialect: str | None = None) -> EmitterRegistry:
    """Build a registry of built-in emitters, in `enabled` order."""
    names = list(enabled)
    unknown = [n for n in names if n not in BUILTIN_EMITTERS]
    if unknown:
        raise EmitterConfigurationError(
            f"unknown emitter name(s) {unknown} in enabled_emitters; "
            f"valid names are {list(BUILTIN_EMITTERS)}")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise EmitterConfigurationError(
            f"emitter name(s) {dupes} listed more than once in enabled_emitters")
    return EmitterRegistry(BUILTIN_EMITTERS[n](sql_dialect) for n in names)


def registry_from_config(config: SoloctlConfig) -> EmitterRegistry:
    """The registry soloctl.toml describes (`enabled_emitters`,
    `default_sql_dialect`)."""
    return default_registry(config.enabled_emitters,
                            sql_dialect=config.default_sql_dialect)
