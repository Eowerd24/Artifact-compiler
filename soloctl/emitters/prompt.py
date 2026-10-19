"""Prompt emitter — YAML front matter + prompt text (COMPILER_PLAN.md D3).

Template placeholders (`{name}`, `{{ name }}`) found in the body are listed
in the front matter's `placeholders` key, so the lint can tell a declared
template variable from a leftover. All checks are in-process (no model
calls), so the plan is complete.
"""
from __future__ import annotations

import re

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    EmitContext, VerificationCheck, VerificationPlan, markdown_front_matter,
    normalize_body, require_supported, risk_notes, slug_filename,
)

# `{{ name }}` (Jinja/Mustache) or a single-brace `{name}` (str.format). A
# name is an identifier, so JSON examples like {"a": 1} never match, and a
# shell expansion `${name}` quoted in a prompt is not a template slot.
PLACEHOLDER_RX = re.compile(
    r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}|(?<![{$])\{([A-Za-z_]\w*)\}(?!\})")


def find_placeholders(text: str) -> tuple[str, ...]:
    """Distinct placeholder names in first-appearance order."""
    names = (m.group(1) or m.group(2) for m in PLACEHOLDER_RX.finditer(text))
    return tuple(dict.fromkeys(names))


class PromptEmitter:
    name = "prompt"
    artifact_type: ArtifactType = "prompt"
    extension = ".md"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.artifact_type == "prompt"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return normalize_body(candidate.body)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def placeholders(self, candidate: ArtifactCandidate) -> tuple[str, ...]:
        return find_placeholders(self.normalize(candidate))

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        front = markdown_front_matter(
            "prompt", filename, candidate, context,
            extra=[("placeholders", list(self.placeholders(candidate)))])
        return f"{front}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="prompt-front-matter", kind="in-process", required=True,
                    description='YAML front matter is present and well-formed, '
                                'with kind "prompt" and every key soloctl '
                                'writes'),
                VerificationCheck(
                    name="prompt-body", kind="in-process", required=True,
                    description="the body below the front matter is not blank"),
                VerificationCheck(
                    name="prompt-placeholders", kind="in-process", required=True,
                    description="body placeholders ({name}, {{ name }}) match "
                                "the front matter's `placeholders` list exactly, "
                                "and no editorial fill-ins remain (TODO, TBD, "
                                "FIXME, [insert ...], <insert ...>)"),
            ),
            complete=True,
            notes=risk_notes(candidate),
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False
