"""Verification engine (WP5a, roadmap step 19).

Executes a `VerificationPlan` — data an emitter returned — against one
artifact file. Emitters only describe checks; this module is the one place
that runs them (roadmap rule 8: verification is separate from emission). It
reads the artifact, runs checks, and returns a report. It writes nothing:
persistence is `verification.service`'s job.

External checks:
  - argv is a tuple, run with `subprocess.run` and no shell; the tool is
    resolved with `shutil.which` and an absent tool makes the check
    `not-run`, never `passed`.
  - `ARTIFACT_PATH` is substituted only where a whole argv element equals
    it, with the artifact's absolute path. An element that merely contains
    the token (PowerShell scripts contain braces) is left alone, and
    artifact content never enters argv.
  - stdin is closed, output is captured, and every run has a timeout.

Every check sees the same bytes: the file is hashed before the first check
and again after the last, and a change in between refuses the whole run.

Contract-free: stdlib, the emitter value types and the check modules only
(`tests/test_verification.py` enforces it).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..emitters.base import ARTIFACT_PATH, VerificationCheck, VerificationPlan
from ..errors import VerificationError
from . import markdown, python, sql
from .models import (
    CheckOutcome, CheckResult, CheckStatus, Verdict, VerificationReport,
)

__all__ = [
    "DEFAULT_TIMEOUT", "MAX_OUTPUT_CHARS", "IN_PROCESS_CHECKS",
    "substitute_path", "run_plan", "decide",
]

DEFAULT_TIMEOUT = 60.0          # seconds per external check
MAX_OUTPUT_CHARS = 4000         # captured output kept per check

# Check name (as emitters spell it) -> implementation. An in-process check
# missing here is `not-run`, so a new emitter check can't pass by accident.
IN_PROCESS_CHECKS: dict[str, Callable[[str], CheckOutcome]] = {
    "python-ast-parse": python.check_python_ast_parse,
    "sql-lexical": sql.check_sql_lexical,
    "prompt-front-matter": markdown.check_prompt_front_matter,
    "prompt-body": markdown.check_prompt_body,
    "prompt-placeholders": markdown.check_prompt_placeholders,
    "runbook-front-matter": markdown.check_runbook_front_matter,
    "runbook-title": markdown.check_runbook_title,
    "runbook-fences-labeled": markdown.check_runbook_fences_labeled,
}


def substitute_path(argv: tuple[str, ...], artifact: Path) -> tuple[str, ...]:
    """Replace each element that *equals* `ARTIFACT_PATH` with the artifact's
    absolute path. Never `str.format`/`replace`: substrings stay as written."""
    absolute = str(artifact.resolve())
    return tuple(absolute if element == ARTIFACT_PATH else element for element in argv)


def _read(artifact: Path) -> bytes:
    try:
        return artifact.read_bytes()
    except OSError as exc:
        raise VerificationError(f"cannot read artifact {artifact}: {exc}") from exc


def run_plan(plan: VerificationPlan, artifact: Path, *,
             timeout: float = DEFAULT_TIMEOUT) -> VerificationReport:
    """Run every check in `plan`, in plan order, against `artifact`."""
    if timeout <= 0:
        raise VerificationError(f"timeout must be positive, got {timeout}")
    artifact = artifact.resolve()
    data = _read(artifact)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError(
            f"{artifact} is not UTF-8 ({exc}); soloctl only writes UTF-8 "
            f"artifacts, so this file was changed outside soloctl") from exc
    digest = hashlib.sha256(data).hexdigest()

    results = tuple(
        _run_in_process(check, text) if check.kind == "in-process"
        else _run_external(check, artifact, timeout)
        for check in plan.checks)

    if hashlib.sha256(_read(artifact)).hexdigest() != digest:
        raise VerificationError(
            f"{artifact} changed while it was being verified, so the checks "
            f"didn't all see the same content; nothing was recorded — re-run "
            f"`soloctl verify`")
    verdict, reasons = decide(plan, results)
    return VerificationReport(
        artifact=artifact, sha256=digest, emitter=plan.emitter,
        artifact_type=plan.artifact_type, plan_complete=plan.complete,
        plan_notes=plan.notes, checks=results, verdict=verdict, reasons=reasons)


def decide(plan: VerificationPlan,
           results: tuple[CheckResult, ...]) -> tuple[Verdict, tuple[str, ...]]:
    """The verdict and why. Only required checks count; advisory results are
    recorded but never move it. See `models` for the policy."""
    required = [r for r in results if r.required]
    failed = [r.name for r in required if r.status == "failed"]
    if failed:
        return "failed", tuple(f"required check {n} failed" for n in failed)
    reasons: list[str] = []
    if not plan.complete:
        reasons.append("plan is incomplete: cannot auto-verify"
                       + (f" ({plan.notes[0]})" if plan.notes else ""))
    if not required:
        reasons.append("plan has no required check")
    reasons += [f"required check {r.name} {'did not run' if r.status == 'not-run' else 'errored'}"
                f": {r.detail}" for r in required if r.status in ("not-run", "error")]
    if reasons:
        return "inconclusive", tuple(reasons)
    return "passed", (f"all {len(required)} required check(s) passed",)


def _base(check: VerificationCheck, *, status: CheckStatus, detail: str,
          argv: tuple[str, ...] = (), returncode: int | None = None,
          output: str = "") -> CheckResult:
    return CheckResult(name=check.name, kind=check.kind, required=check.required,
                       description=check.description, status=status, detail=detail,
                       tool=check.tool, argv=argv, returncode=returncode,
                       output=output)


def _run_in_process(check: VerificationCheck, text: str) -> CheckResult:
    impl = IN_PROCESS_CHECKS.get(check.name)
    if impl is None:
        return _base(check, status="not-run",
                     detail=f"soloctl has no in-process implementation of "
                            f"{check.name!r}")
    outcome = impl(text)
    return _base(check, status="passed" if outcome.passed else "failed",
                 detail=outcome.detail)


def _run_external(check: VerificationCheck, artifact: Path,
                  timeout: float) -> CheckResult:
    if not check.argv or not check.tool:
        return _base(check, status="not-run",
                     detail="the plan gives no tool/argv for this external check")
    executable = shutil.which(check.argv[0])
    if executable is None:
        return _base(check, status="not-run",
                     detail=f"{check.tool} is not installed (not found on PATH)")
    argv = (executable, *substitute_path(check.argv[1:], artifact))
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout, cwd=artifact.parent, check=False,
                              shell=False)
    except subprocess.TimeoutExpired as exc:
        return _base(check, status="error", argv=argv,
                     output=_output(exc.stdout, exc.stderr),
                     detail=f"{check.tool} timed out after {timeout:g}s")
    except OSError as exc:
        return _base(check, status="error", argv=argv,
                     detail=f"could not execute {executable}: {exc}")
    passed = proc.returncode == 0
    return _base(check, status="passed" if passed else "failed", argv=argv,
                 returncode=proc.returncode, output=_output(proc.stdout, proc.stderr),
                 detail=f"{check.tool} exited {proc.returncode}")


def _output(stdout: bytes | str | None, stderr: bytes | str | None) -> str:
    parts = []
    for stream in (stdout, stderr):
        if stream:
            parts.append(stream.decode("utf-8", errors="replace")
                         if isinstance(stream, bytes) else stream)
    text = "".join(parts)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f"\n[... truncated at {MAX_OUTPUT_CHARS} chars]"
    return text
