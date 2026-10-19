"""Markdown runbook emitter — YAML front matter + runbook body
(COMPILER_PLAN.md D3).

All checks are structural lints over the markdown-it token stream, run
in-process; nothing embedded in the runbook is executed, so the plan is
complete.
"""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    EmitContext, VerificationCheck, VerificationPlan, markdown_front_matter,
    normalize_body, require_supported, risk_notes, slug_filename,
)


class RunbookEmitter:
    name = "runbook"
    artifact_type: ArtifactType = "runbook"
    extension = ".md"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.artifact_type == "runbook"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return normalize_body(candidate.body)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        front = markdown_front_matter("runbook", filename, candidate, context)
        return f"{front}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="runbook-front-matter", kind="in-process", required=True,
                    description='YAML front matter is present and well-formed, '
                                'with kind "runbook" and every key soloctl '
                                'writes'),
                VerificationCheck(
                    name="runbook-title", kind="in-process", required=True,
                    description="markdown-it structure lint: the first block "
                                "of the body is a heading"),
                VerificationCheck(
                    name="runbook-fences-labeled", kind="in-process", required=True,
                    description="markdown-it structure lint: every embedded "
                                "code fence has a language label"),
            ),
            complete=True,
            notes=risk_notes(candidate),
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False
