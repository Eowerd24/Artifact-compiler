"""Domain-specific exceptions. Every message names the failing path/value and
the corrective action, so a raised error is actionable without a traceback."""
from __future__ import annotations


class SoloctlError(Exception):
    """Base class for all soloctl domain errors."""


class ConfigError(SoloctlError):
    """Configuration file is missing, malformed, or fails validation."""


class LibraryError(SoloctlError):
    """The filesystem library is in an unexpected or unusable state."""


class PathEscapesLibraryError(LibraryError):
    """A resolved path fell outside the configured library root."""


class TranscriptError(SoloctlError):
    """Base class for canonical transcript rendering/parsing errors."""


class TranscriptParseError(TranscriptError):
    """Canonical transcript markdown could not be parsed."""


class ImporterError(SoloctlError):
    """Base class for importer/registry errors."""


class ImporterNotFoundError(ImporterError):
    """An explicit --adapter override did not match any registered importer."""


class AmbiguousImporterError(ImporterError):
    """More than one importer reported the same top confidence for an input,
    or more than one conversation within an input matched a selector."""


class UnsupportedInputError(ImporterError):
    """No registered importer recognized the input."""


class ImporterSchemaError(ImporterError):
    """An importer recognized the input format but a mandatory structure
    was missing, the wrong type, or otherwise did not match the schema this
    adapter version understands."""


class ConversationNotFoundError(ImporterError):
    """--conversation named neither an id, an exact title, nor an
    unambiguous title substring present in the input."""


class SecretDetected(SoloctlError):
    """Raised the instant a secret pattern matches. Aborts the whole
    operation before anything is written — refusal, not redaction."""

    def __init__(self, label: str, line: int, path: str) -> None:
        self.label = label
        self.line = line
        self.path = path
        super().__init__(
            f"secret [{label}] at {path}:{line} — refusing entire input"
        )


class IdempotencyConflict(SoloctlError):
    """An idempotency_key was reused with a different request body (M-b,
    D2). Carries the typed ucc.problem so callers can surface it directly."""

    def __init__(self, problem: dict) -> None:
        self.problem = problem
        super().__init__(problem["message"])


class OutcomeUnknown(SoloctlError):
    """An earlier dispatch may have started and requires reconciliation."""

    def __init__(self, problem: dict) -> None:
        self.problem = problem
        super().__init__(problem["message"])
