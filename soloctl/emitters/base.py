"""Emitter protocol (Phase 7) and the shared value types emitters return.

An emitter turns one `ArtifactCandidate` into the *content* of a draft
artifact plus a description of how it should later be verified. Emitters are
pure: they never write files, never run tools, never read the clock, and
never consult the library (non-negotiable rule 7 — "emitters do not write
files directly"). The compilation coordinator (Work Package 4) owns
collision resolution and atomic draft writes; the verification engine
(Work Package 5) owns executing a `VerificationPlan`.

Rendering follows COMPILER_PLAN.md §2 / D3: scripts carry a comment header,
`.md` artifacts carry YAML front matter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from ..compiler.models import ArtifactCandidate, ArtifactType
from ..errors import EmitterError, UnsupportedEmitterError

__all__ = [
    "ArtifactEmitter", "EmitContext", "VerificationCheck", "VerificationPlan",
    "ARTIFACT_PATH", "PLACEHOLDER", "DRAFT_REVIEW_LINE",
    "require_supported", "normalize_body", "header_value", "flags_value",
    "slug_filename", "comment_header", "script_header_rows", "risk_notes",
    "leading_shebang", "yaml_front_matter", "markdown_front_matter",
]

# Stands in for the artifact's on-disk path inside a check's argv. The
# verification engine substitutes it; emitters never know the real path.
ARTIFACT_PATH = "{artifact}"
PLACEHOLDER = "(fill in before approve)"
DRAFT_REVIEW_LINE = "DRAFT — not executable until `soloctl lib approve`"

_SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHEBANG_RX = re.compile(r"\A#![^\n]*\n?")


@dataclass(frozen=True)
class EmitContext:
    """Everything `render()` needs that isn't on the candidate. Injected by
    the caller so rendering stays deterministic (no clock, no version
    lookup inside an emitter)."""
    source: str           # e.g. 'chat:claude 2026-07-11 "forge provisioning"'
    compiled_at: str      # ISO-8601 timestamp supplied by the caller
    tool_version: str     # soloctl version string


@dataclass(frozen=True)
class VerificationCheck:
    """One automatic check, described — never executed — by an emitter.

    `kind="external"` checks name a tool and an argv tuple (never a shell
    string); `ARTIFACT_PATH` marks where the artifact path goes.
    `kind="in-process"` checks are performed by soloctl itself (e.g. parsing
    with `ast`) and have no tool/argv."""
    name: str
    kind: Literal["in-process", "external"]
    description: str
    required: bool
    tool: str | None = None
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationPlan:
    """What automatic verification should run for one artifact.

    `complete=True` means the plan holds at least one *required* check, so a
    run in which every required check passes is real evidence. `complete=False`
    means soloctl cannot establish a pass on its own — e.g. every check needs
    an external tool soloctl doesn't depend on, so all of them are advisory
    (`notes` says why). A verifier must treat an incomplete plan as "cannot
    auto-verify", never as "nothing failed, so it passed" — advisory checks
    passing, or an empty check list, is not evidence. Manual verification is
    always separate and is not represented here."""
    emitter: str
    artifact_type: ArtifactType
    checks: tuple[VerificationCheck, ...]
    complete: bool
    notes: tuple[str, ...] = ()


@runtime_checkable
class ArtifactEmitter(Protocol):
    """COMPILER_PLAN.md emitter contract, generalized per language."""

    name: str                    # matches soloctl.toml `enabled_emitters`
    artifact_type: ArtifactType
    extension: str               # including the dot: ".sh"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        """True iff this emitter handles the candidate. The registry requires
        exactly one enabled emitter to return True per candidate."""
        ...

    def normalize(self, candidate: ArtifactCandidate) -> str:
        """The candidate body as it should appear in the artifact (before the
        emitter's header). Deterministic; never changes semantics."""
        ...

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        """Bare filename (no directories), pre-collision-resolution."""
        ...

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        """Full artifact text: header/front matter + normalized body."""
        ...

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        """Describe automatic verification. Never runs anything."""
        ...

    def executable(self, candidate: ArtifactCandidate) -> bool:
        """Whether the artifact should be executable *once approved*. Drafts
        are never written executable regardless of this answer."""
        ...


# --------------------------------------------------------------------------
# Helpers shared by the built-in emitters
# --------------------------------------------------------------------------
def require_supported(emitter: ArtifactEmitter, candidate: ArtifactCandidate) -> None:
    """Refuse to operate on a candidate the emitter doesn't support — calling
    an emitter directly must not bypass the registry's matching rule."""
    if not emitter.supports(candidate):
        raise UnsupportedEmitterError(
            candidate.lang, candidate.artifact_type,
            f"{candidate.src.path}:{candidate.src.line_start}",
            detail=f"emitter {emitter.name!r} was called directly")


def normalize_body(body: str, *, strip_shebang: bool = False) -> str:
    """CRLF→LF, rstrip every line, drop leading/trailing blank lines, end
    with exactly one newline. Optionally drop a leading shebang (emitters
    that write their own)."""
    text = body.replace("\r\n", "\n")
    if strip_shebang:
        text = _SHEBANG_RX.sub("", text, count=1)
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def header_value(value: str | None, default: str = PLACEHOLDER) -> str:
    """Collapse a value onto one line so it can't break out of a comment
    header, substituting `default` when empty."""
    flat = " ".join((value or "").split())
    return flat or default


def flags_value(flags: tuple[str, ...]) -> str:
    return ", ".join(flags) if flags else "none"


def slug_filename(candidate: ArtifactCandidate, extension: str, *,
                  separator: str = "-") -> str:
    """`<name_proposal><extension>`, refusing anything that isn't a plain
    slug — a filename must never carry a path separator or traversal."""
    stem = candidate.name_proposal
    if not _SLUG_RX.match(stem):
        raise EmitterError(
            f"name proposal {stem!r} from {candidate.src.path}:"
            f"{candidate.src.line_start} is not a filename-safe slug "
            f"(expected [a-z0-9][a-z0-9_-]*); the extractor should never "
            f"produce this — report it as a bug.")
    if separator != "-":
        stem = stem.replace("-", separator)
    return stem + extension


def script_header_rows(filename: str, candidate: ArtifactCandidate,
                       context: EmitContext) -> list[tuple[str, str]]:
    """The COMPILER_PLAN.md §2 header fields, in template order."""
    return [
        ("name", filename),
        ("source", header_value(context.source, "-")),
        ("compiled", header_value(f"soloctl {context.tool_version} {context.compiled_at}")),
        ("description", header_value(candidate.description)),
        ("review", DRAFT_REVIEW_LINE),
        ("risk-flags", flags_value(candidate.flags)),
        ("verify-with", PLACEHOLDER),
    ]


def comment_header(prefix: str, rows: list[tuple[str, str]]) -> str:
    """`# name:        value` lines (keys padded to the template's column)."""
    return "".join(f"{prefix} {key + ':':<13}{value}\n" for key, value in rows)


def risk_notes(candidate: ArtifactCandidate) -> tuple[str, ...]:
    """The plan note every emitter adds when the extractor flagged risks."""
    if not candidate.flags:
        return ()
    return (f"risk flags present ({', '.join(candidate.flags)}): "
            f"review these lines during manual verification",)


def leading_shebang(body: str) -> str | None:
    """The body's own `#!` line (trailing whitespace dropped), if it has one
    on line 1 — the same line `normalize_body(strip_shebang=True)` removes."""
    m = _SHEBANG_RX.match(body.replace("\r\n", "\n"))
    return m.group(0).rstrip() if m else None


def yaml_front_matter(fields: list[tuple[str, str | list[str]]]) -> str:
    """Flat YAML front matter. Strings are JSON-quoted (always valid YAML,
    no reserved-word or colon ambiguity); lists are JSON flow sequences."""
    lines = ["---"]
    for key, value in fields:
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def markdown_front_matter(kind: str, filename: str, candidate: ArtifactCandidate,
                          context: EmitContext, *,
                          extra: list[tuple[str, str | list[str]]] | None = None) -> str:
    """Front matter shared by the `.md` emitters (prompt, runbook). `extra`
    fields go just before `verify-with`, which stays the last key."""
    return yaml_front_matter([
        ("kind", kind),
        ("name", filename),
        ("source", header_value(context.source, "-")),
        ("compiled", header_value(f"soloctl {context.tool_version} {context.compiled_at}")),
        ("description", header_value(candidate.description)),
        ("review", DRAFT_REVIEW_LINE),
        ("risk-flags", list(candidate.flags)),
        *(extra or []),
        ("verify-with", PLACEHOLDER),
    ])
