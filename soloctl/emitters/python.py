"""Python emitter — same header fields as Bash, `#` comments, python3 shebang."""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    ARTIFACT_PATH, EmitContext, VerificationCheck, VerificationPlan,
    comment_header, normalize_body, require_supported, risk_notes,
    script_header_rows, slug_filename,
)

_SHEBANG = "#!/usr/bin/env python3\n"


class PythonEmitter:
    name = "python"
    artifact_type: ArtifactType = "script"
    extension = ".py"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.lang == "python" and candidate.artifact_type == "script"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return normalize_body(candidate.body, strip_shebang=True)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        # Underscores keep the file importable as a module as well as runnable.
        return slug_filename(candidate, self.extension, separator="_")

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        header = comment_header("#", script_header_rows(filename, candidate, context))
        # Only comments precede the body, so `from __future__` imports stay
        # the first statement and remain legal.
        return f"{_SHEBANG}{header}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="python-ast-parse", kind="in-process", required=True,
                    description="parse with the stdlib ast module (no execution)"),
                VerificationCheck(
                    name="ruff", kind="external", required=False,
                    description="lint for syntax errors and undefined names; "
                                "advisory because ruff is not a soloctl dependency",
                    tool="ruff",
                    argv=("ruff", "check", "--no-cache", "--select", "E9,F63,F7,F82",
                          ARTIFACT_PATH)),
            ),
            complete=True,
            notes=risk_notes(candidate),
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return True
