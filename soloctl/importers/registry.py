"""Importer registry: probes all registered importers, selects a single
clear match, and never guesses on a tie or an all-zero-confidence input.

Importers are keyed by their versioned `version` string (e.g. "markdown-v1"),
which is what --adapter overrides and what Transcript.adapter records —
`name` stays the short, unversioned source label ("markdown", "chatgpt").
"""
from __future__ import annotations

from pathlib import Path

from ..errors import AmbiguousImporterError, ImporterNotFoundError, UnsupportedInputError
from .base import Importer


class ImporterRegistry:
    def __init__(self, importers: tuple[Importer, ...] = ()) -> None:
        self._importers: list[Importer] = []
        for importer in importers:
            self.register(importer)

    def register(self, importer: Importer) -> None:
        if any(i.version == importer.version for i in self._importers):
            raise ImporterNotFoundError(
                f"an importer with version {importer.version!r} is already registered"
            )
        self._importers.append(importer)

    @property
    def importers(self) -> tuple[Importer, ...]:
        return tuple(self._importers)

    def get(self, version: str) -> Importer:
        for importer in self._importers:
            if importer.version == version:
                return importer
        available = sorted(i.version for i in self._importers)
        raise ImporterNotFoundError(
            f"unknown adapter {version!r}; available adapters: {available}"
        )

    def resolve(self, path: Path, *, adapter: str | None = None) -> Importer:
        """Pick the importer for path. An explicit adapter always wins."""
        if adapter is not None:
            return self.get(adapter)

        scored = [(importer, importer.detect(path)) for importer in self._importers]
        candidates = [(importer, conf) for importer, conf in scored if conf > 0.0]
        if not candidates:
            raise UnsupportedInputError(
                f"no importer recognized {path}; pass --adapter explicitly "
                f"or check that the file format is supported"
            )

        best_confidence = max(conf for _, conf in candidates)
        best = [importer for importer, conf in candidates if conf == best_confidence]
        if len(best) > 1:
            names = ", ".join(sorted(i.version for i in best))
            raise AmbiguousImporterError(
                f"ambiguous input {path}: importers [{names}] all report "
                f"confidence {best_confidence}; use --adapter to disambiguate"
            )
        return best[0]
