"""Automatic verification (WP5a): run the `VerificationPlan` an emitter
returned against an artifact file and record the result. Separate from
emission (roadmap rule 8); never implies manual verification (rule 10)."""
from __future__ import annotations

from .engine import DEFAULT_TIMEOUT, IN_PROCESS_CHECKS, decide, run_plan, substitute_path
from .models import CheckOutcome, CheckResult, CheckStatus, Verdict, VerificationReport

__all__ = [
    "DEFAULT_TIMEOUT", "IN_PROCESS_CHECKS", "decide", "run_plan", "substitute_path",
    "CheckOutcome", "CheckResult", "CheckStatus", "Verdict", "VerificationReport",
]
