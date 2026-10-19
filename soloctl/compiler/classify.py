"""Fence-label classification (EXTRACTOR_BLUEPRINT.md §3 "classify").

Maps a fence info-string's first token to a normalized language, an artifact
type, and an optional dialect. This is a static lookup table — no content
sniffing, no heuristics — so classification is deterministic and the whole
policy is readable in one screen.

Which emitter handles a classified candidate is deliberately *not* decided
here; see `soloctl.emitters.registry`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import ArtifactType

__all__ = [
    "LabelClass", "LABELS", "CONSOLE_LABELS", "SUPPORTED_LANGUAGES",
    "classify_label",
]


@dataclass(frozen=True)
class LabelClass:
    language: str
    artifact_type: ArtifactType
    dialect: str | None = None


_BASH = LabelClass("bash", "script")
_PYTHON = LabelClass("python", "script")
_POWERSHELL = LabelClass("powershell", "script")
_PROMPT = LabelClass("prompt", "prompt")
_RUNBOOK = LabelClass("markdown", "runbook")

LABELS: dict[str, LabelClass] = {
    "bash": _BASH, "sh": _BASH, "shell": _BASH, "zsh": _BASH,
    "python": _PYTHON, "py": _PYTHON,
    "powershell": _POWERSHELL, "pwsh": _POWERSHELL, "ps1": _POWERSHELL,
    "sql": LabelClass("sql", "script"),
    "postgres": LabelClass("sql", "script", "postgresql"),
    "postgresql": LabelClass("sql", "script", "postgresql"),
    "mysql": LabelClass("sql", "script", "mysql"),
    "sqlite": LabelClass("sql", "script", "sqlite"),
    "tsql": LabelClass("sql", "script", "tsql"),
    "prompt": _PROMPT,
    "markdown": _RUNBOOK, "md": _RUNBOOK, "runbook": _RUNBOOK,
}

# Mixed `$`-prompts and output: always skipped (blueprint §3, v0 policy).
CONSOLE_LABELS: frozenset[str] = frozenset(
    {"console", "terminal", "shell-session", "shellsession"})

SUPPORTED_LANGUAGES: frozenset[str] = frozenset(c.language for c in LABELS.values())


def classify_label(label: str) -> LabelClass | None:
    """Classify a lower-cased fence label; None if it is not a recognized
    artifact language (the caller records a `non-target-lang` skip)."""
    return LABELS.get(label)
