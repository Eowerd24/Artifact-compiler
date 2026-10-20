"""Verification result model (WP5a).

The engine executes a `VerificationPlan` (data an emitter returned) against
one artifact file and reports what each check did. Nothing here decides
approval: a verdict is evidence for the operator, and automatic
verification never implies manual verification (roadmap rule 10).

Check statuses:
  passed   the check ran and found nothing wrong
  failed   the check ran and found a problem
  not-run  the check could not run: its tool isn't on PATH, or soloctl has no
           implementation for an in-process check of that name
  error    the check started but produced no usable answer (timeout, the
           tool couldn't be executed)

Verdict (provisional policy; the operator may revise it):
  failed        some *required* check failed
  inconclusive  nothing required failed, but a pass can't be established:
                the plan is incomplete (`complete=False`), it has no required
                check, or a required check is not-run or error
  passed        the plan is complete and every required check passed

Advisory (`required=False`) results are recorded but never move the verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..compiler.models import ArtifactType

__all__ = [
    "CheckStatus", "Verdict", "CheckOutcome", "CheckResult",
    "VerificationReport", "MANUAL_NOTE",
]

CheckStatus = Literal["passed", "failed", "not-run", "error"]
Verdict = Literal["passed", "failed", "inconclusive"]

# Recorded with every result so no reader mistakes it for manual sign-off.
MANUAL_NOTE = ("automatic verification only; it never implies manual "
               "verification, which is a separate operator step")


@dataclass(frozen=True)
class CheckOutcome:
    """What an in-process check function returns."""
    passed: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    name: str
    kind: Literal["in-process", "external"]
    required: bool
    description: str
    status: CheckStatus
    detail: str
    tool: str | None = None
    argv: tuple[str, ...] = ()       # as executed (path substituted); () if not run
    returncode: int | None = None
    output: str = ""                 # captured stdout+stderr, truncated


@dataclass(frozen=True)
class VerificationReport:
    artifact: Path                   # absolute path that was verified
    sha256: str                      # of the exact bytes every check saw
    emitter: str
    artifact_type: ArtifactType
    plan_complete: bool
    plan_notes: tuple[str, ...]
    checks: tuple[CheckResult, ...]
    verdict: Verdict
    reasons: tuple[str, ...]         # why the verdict isn't (or is) "passed"
