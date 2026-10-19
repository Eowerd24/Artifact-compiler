"""PowerShell emitter — `#` comment header, body shebang hoisted to line 1,
`#Requires` statements surfaced in the verification plan.

Neither check can run without `pwsh`, which soloctl doesn't depend on, so
both are advisory and the plan is `complete=False`: soloctl alone cannot
establish that a PowerShell artifact passes automatic verification.
"""
from __future__ import annotations

import re

from ..compiler.models import ArtifactCandidate, ArtifactType
from .base import (
    ARTIFACT_PATH, EmitContext, VerificationCheck, VerificationPlan,
    comment_header, leading_shebang, normalize_body, require_supported,
    risk_notes, script_header_rows, slug_filename,
)

# Fixed scripts passed to `pwsh -CommandWithArgs` (PowerShell 7.4+). They are
# constants: no artifact content is ever interpolated into them, and the
# artifact path arrives as `$args[0]`, a separate argv element. `ParseFile`
# only parses; nothing in the artifact runs.
PWSH_PARSE_SCRIPT = (
    "$tokens = $null; $errors = $null; "
    "$null = [System.Management.Automation.Language.Parser]::ParseFile("
    "$args[0], [ref]$tokens, [ref]$errors); "
    "foreach ($e in $errors) { [Console]::Error.WriteLine("
    "[string]$e.Extent.StartLineNumber + ': ' + $e.Message) }; "
    "if ($errors) { exit 1 }"
)
PSSA_SCRIPT = "Invoke-ScriptAnalyzer -Path $args[0] -Severity Warning,Error -EnableExit"
_PWSH_PREFIX = ("pwsh", "-NoProfile", "-NonInteractive", "-CommandWithArgs")

_REQUIRES_RX = re.compile(r"^[ \t]*#requires[ \t]+(\S[^\n]*?)[ \t]*$",
                          re.IGNORECASE | re.MULTILINE)


class PowerShellEmitter:
    name = "powershell"
    artifact_type: ArtifactType = "script"
    extension = ".ps1"

    def supports(self, candidate: ArtifactCandidate) -> bool:
        return candidate.lang == "powershell" and candidate.artifact_type == "script"

    def normalize(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        # A shebang only works on line 1, so render() moves it above the header.
        return normalize_body(candidate.body, strip_shebang=True)

    def propose_filename(self, candidate: ArtifactCandidate) -> str:
        require_supported(self, candidate)
        return slug_filename(candidate, self.extension)

    def requires(self, candidate: ArtifactCandidate) -> tuple[str, ...]:
        """The arguments of each `#Requires` statement, in body order. They
        stay where the author wrote them (PowerShell honors them on any line)."""
        require_supported(self, candidate)
        return tuple(_REQUIRES_RX.findall(self.normalize(candidate)))

    def render(self, candidate: ArtifactCandidate, context: EmitContext) -> str:
        filename = self.propose_filename(candidate)
        header = comment_header("#", script_header_rows(filename, candidate, context))
        shebang = leading_shebang(candidate.body)
        top = f"{shebang}\n" if shebang else ""
        return f"{top}{header}\n{self.normalize(candidate)}"

    def verification_plan(self, candidate: ArtifactCandidate) -> VerificationPlan:
        require_supported(self, candidate)
        notes = [
            "no required check: PowerShell can only be parsed by pwsh, which "
            "soloctl does not depend on; treat as cannot-auto-verify",
        ]
        requires = self.requires(candidate)
        if requires:
            notes.append("declares #Requires " + "; ".join(requires)
                         + " (not checked by parsing)")
        return VerificationPlan(
            emitter=self.name,
            artifact_type=self.artifact_type,
            checks=(
                VerificationCheck(
                    name="pwsh-parse", kind="external", required=False,
                    description="parse with the PowerShell language parser "
                                "(no execution); needs pwsh 7.4+ for "
                                "-CommandWithArgs; advisory because pwsh is "
                                "not a soloctl dependency",
                    tool="pwsh",
                    argv=(*_PWSH_PREFIX, PWSH_PARSE_SCRIPT, ARTIFACT_PATH)),
                VerificationCheck(
                    name="psscriptanalyzer", kind="external", required=False,
                    description="PSScriptAnalyzer at warning severity; needs "
                                "pwsh 7.4+ and the PSScriptAnalyzer module; "
                                "advisory",
                    tool="pwsh",
                    argv=(*_PWSH_PREFIX, PSSA_SCRIPT, ARTIFACT_PATH)),
            ),
            complete=False,
            notes=(*notes, *risk_notes(candidate)),
        )

    def executable(self, candidate: ArtifactCandidate) -> bool:
        require_supported(self, candidate)
        return False    # run via `pwsh -File`, even when a shebang is present
