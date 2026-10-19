"""PowerShell emitter — scaffolded (WP3). Matching, normalization, filename
and a comment-header render are real; verification is not designed yet."""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    EmitContext, VerificationPlan, comment_header, normalize_body,
    require_supported, scaffold_plan, script_header_rows, slug_filename,
)


class PowerShellEmitter:
    name = "powershell"
    artifact_type: ArtifactType = "script"
    extension = ".ps1"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.lang == "powershell" and candidate.artifact_type == "script"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return normalize_body(candidate.body)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        header = comment_header("#", script_header_rows(filename, candidate, context))
        return f"{header}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return scaffold_plan(self.name, self.artifact_type,
                             "PowerShell parser + PSScriptAnalyzer via pwsh")

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False    # run via `pwsh -File`; revisit with the full emitter
