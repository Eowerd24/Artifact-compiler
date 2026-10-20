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


class InvalidNameError(LibraryError):
    """A tag or collection name isn't a lower-case slug. Refused, never
    silently rewritten: the message suggests the slug form."""


class UnknownArtifactError(LibraryError):
    """An artifact argument doesn't name a soloctl draft or approved
    artifact (bad form, no such file, or no `compiled:` stamp)."""


class AmbiguousArtifactError(LibraryError):
    """The same `<kind>/<filename>` exists in both drafts/ and approved/ —
    a broken library invariant. Refused rather than picking one."""


class StaleReferenceError(LibraryError):
    """A stored reference's `compiled:` stamp doesn't match the file now at
    that name: the name was reused by a different compile. Never re-attached
    silently; remove the stale entry first."""


class UnknownCollectionError(LibraryError):
    """No `collections/<name>.json` exists."""


class CollectionConflictError(LibraryError):
    """`collection create` named an existing collection with a different
    title or description."""


class RegistryCorruptError(LibraryError):
    """tags.json or a collection file isn't valid soloctl JSON. Refused, and
    never overwritten: fix or remove the file by hand."""


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


class CompilerError(SoloctlError):
    """Base class for extractor/classifier errors."""


class UnknownLanguageError(CompilerError):
    """`extract(only=...)` named a language the classifier never produces —
    usually an emitter name ("runbook") or a raw fence label ("pwsh") passed
    where a normalized language ("markdown", "powershell") was expected."""

    def __init__(self, unknown: list[str], supported: list[str]) -> None:
        self.unknown = unknown
        self.supported = supported
        super().__init__(
            f"unknown extractor language(s) {unknown}: `only` takes normalized "
            f"language names, one of {supported}"
        )


class EmitterError(SoloctlError):
    """Base class for emitter protocol/registry errors."""


class UnsupportedEmitterError(EmitterError):
    """No enabled emitter supports a candidate (reason code
    `unsupported-emitter`). Not a bug: enable the emitter in soloctl.toml's
    `enabled_emitters`, or accept that the candidate is skipped."""

    reason = "unsupported-emitter"

    def __init__(self, lang: str, artifact_type: str, location: str,
                 detail: str = "") -> None:
        self.lang = lang
        self.artifact_type = artifact_type
        self.location = location
        super().__init__(
            f"{self.reason}: no enabled emitter supports a {artifact_type!r} "
            f"candidate in language {lang!r} at {location}"
            + (f" ({detail})" if detail else "")
            + ". Enable a matching emitter in soloctl.toml `enabled_emitters`."
        )


class EmitterConfigurationError(EmitterError):
    """The emitter set itself is wrong: duplicate names, an unknown emitter
    named in `enabled_emitters`, or more than one emitter claiming the same
    candidate. An internal configuration bug — never resolved by guessing."""


class VerificationError(SoloctlError):
    """Automatic verification couldn't produce a trustworthy result: the
    artifact is unreadable or not UTF-8, it changed while checks ran, no
    built-in emitter produces its kind/extension, or a stored result can't be
    written. Nothing is recorded; the message says what to fix."""


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
    """A prior idempotent dispatch may have run and needs reconciliation."""

    def __init__(self, problem: dict) -> None:
        self.problem = problem
        super().__init__(problem["message"])
