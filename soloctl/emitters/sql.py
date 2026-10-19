"""SQL emitter — scaffolded (WP3). Records the dialect from the fence label,
falling back to soloctl.toml's `default_sql_dialect`; verification is not
designed yet."""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    EmitContext, VerificationPlan, comment_header, normalize_body,
    require_supported, scaffold_plan, script_header_rows, slug_filename,
)


class SqlEmitter:
    name = "sql"
    artifact_type: ArtifactType = "script"
    extension = ".sql"

    def __init__(self, default_dialect: str | None = None) -> None:
        self.default_dialect = default_dialect

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.lang == "sql" and candidate.artifact_type == "script"

    def dialect(self, candidate: ArtifactCandidate) -> str | None:
        """Fence label wins (```postgres); otherwise the configured default."""
        require_supported(self, candidate)
        return candidate.dialect or self.default_dialect

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return normalize_body(candidate.body)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        rows = script_header_rows(filename, candidate, context)
        rows.insert(1, ("dialect", self.dialect(candidate) or "unspecified"))
        return f"{comment_header('--', rows)}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        return scaffold_plan(self.name, self.artifact_type,
                             "dialect-aware parse (no database connection)")

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False    # SQL runs through a client, never as an executable file
