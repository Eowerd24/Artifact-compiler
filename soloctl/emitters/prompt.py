"""Prompt emitter — scaffolded (WP3). YAML front matter + prompt text
(COMPILER_PLAN.md D3); verification is not designed yet."""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    EmitContext, VerificationPlan, markdown_front_matter, normalize_body,
    require_supported, scaffold_plan, slug_filename,
)


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

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        front = markdown_front_matter("prompt", filename, candidate, context)
        return f"{front}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return scaffold_plan(self.name, self.artifact_type,
                             "front-matter/placeholder lint (no model calls)")

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False
