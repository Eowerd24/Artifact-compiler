"""Bash emitter — COMPILER_PLAN.md §2 header template, strict-mode preamble."""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    ARTIFACT_PATH, EmitContext, VerificationCheck, VerificationPlan,
    comment_header, normalize_body, require_supported, script_header_rows,
    slug_filename,
)

_SHEBANG = "#!/usr/bin/env bash\n"
_PREAMBLE = "set -euo pipefail\nIFS=$'\\n\\t'\n"


class BashEmitter:
    name = "bash"
    artifact_type: ArtifactType = "script"
    extension = ".sh"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.lang == "bash" and candidate.artifact_type == "script"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        # The header supplies its own shebang; a second one mid-file is noise.
        return normalize_body(candidate.body, strip_shebang=True)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        header = comment_header("#", script_header_rows(filename, candidate, context))
        return f"{_SHEBANG}{header}{_PREAMBLE}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        notes: tuple[str, ...] = ()
        if candidate.flags:
            notes = (f"risk flags present ({', '.join(candidate.flags)}): "
                     f"review these lines during manual verification",)
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="bash-syntax", kind="external", required=True,
                    description="parse without executing (bash -n)",
                    tool="bash", argv=("bash", "-n", ARTIFACT_PATH)),
                VerificationCheck(
                    name="shellcheck", kind="external", required=True,
                    description="static analysis at warning severity",
                    tool="shellcheck",
                    argv=("shellcheck", "--shell=bash", "--severity=warning",
                          ARTIFACT_PATH)),
            ),
            complete=True,
            notes=notes,
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return True
