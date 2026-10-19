"""SQL emitter. Records the dialect from the fence label, falling back to
soloctl.toml's `default_sql_dialect`.

Verification never connects to a database. The required check is an
in-process lexical scan soloctl runs itself; a real dialect-aware parse
needs sqlfluff, which soloctl doesn't depend on, so that check is advisory.
"""
from __future__ import annotations

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    ARTIFACT_PATH, EmitContext, VerificationCheck, VerificationPlan,
    comment_header, normalize_body, require_supported, risk_notes,
    script_header_rows, slug_filename,
)

# soloctl dialect name (from a fence label or soloctl.toml) -> sqlfluff's.
SQLFLUFF_DIALECTS: dict[str, str] = {
    "postgresql": "postgres", "postgres": "postgres",
    "mysql": "mysql", "sqlite": "sqlite", "tsql": "tsql", "ansi": "ansi",
}
SQLFLUFF_FALLBACK = "ansi"


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
        dialect = self.dialect(candidate)
        fluff = SQLFLUFF_DIALECTS.get((dialect or "").lower(), SQLFLUFF_FALLBACK)
        notes: tuple[str, ...] = ()
        if fluff == SQLFLUFF_FALLBACK and (dialect or "").lower() != SQLFLUFF_FALLBACK:
            notes = (f"dialect {dialect or 'unspecified'!r} has no sqlfluff "
                     f"mapping; the sqlfluff parse uses {SQLFLUFF_FALLBACK!r}",)
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="sql-lexical", kind="in-process", required=True,
                    description="lexical scan without a database: the body "
                                "below the header has at least one statement; "
                                "string literals, quoted identifiers and block "
                                "comments are closed; parentheses balance "
                                "outside them; the last statement ends with ';' "
                                "(tsql: or a GO line). Not a parse"),
                VerificationCheck(
                    name="sqlfluff-parse", kind="external", required=False,
                    description=f"dialect-aware parse ({fluff}), no database "
                                f"connection; advisory because sqlfluff is "
                                f"not a soloctl dependency",
                    tool="sqlfluff",
                    argv=("sqlfluff", "parse", "--dialect", fluff, ARTIFACT_PATH)),
            ),
            complete=True,
            notes=(*notes, *risk_notes(candidate)),
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False    # SQL runs through a client, never as an executable file
