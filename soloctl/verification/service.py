"""`soloctl verify`: verify one library artifact and record the result.

    artifact arg -> ref + stamp (library.refs) -> emitter + plan -> engine
                 -> library/verification/<kind>/<filename>.json

Plans aren't stored at compile time, so the plan is rebuilt by asking the
emitter that produced the file. The emitter is chosen by the artifact's
kind directory and extension, among *all* built-in emitters: which emitters
are enabled governs compile, not whether an existing artifact can be
checked. The emitter's `verification_plan()` needs a candidate; the inputs
the built-in plans read are the language, the artifact type, the SQL
dialect, the risk flags and the body, and each is recovered from the file
(its header/front matter and text). `tests/test_verification.py` checks that
the rebuilt plan equals the one the emitter returned at compile time.

The result file is keyed by the same `<kind>/<filename>` reference as tags
and collections, so it survives approval moving the file. It records the
`compiled:` stamp and the sha256 of the bytes checked, so a reader can tell
whether it still describes the file on disk. Only the latest run is kept.
Writes are atomic (`library.atomic`) and paths go through
`LibraryPaths.resolve`.

Nothing here approves anything, appends a ledger line or emits a
`ucc.event`; approval, manifest/index and events are later steps.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .. import __version__
from ..compiler.compile import KIND_DIRS
from ..compiler.models import ArtifactCandidate, SourceRef
from ..config import SoloctlConfig
from ..emitters.base import ArtifactEmitter, VerificationPlan
from ..emitters.registry import BUILTIN_EMITTERS
from ..errors import LibraryError, UnknownArtifactError, VerificationError
from ..ledger import now_iso
from ..library.paths import VERIFICATION, LibraryPaths
from ..library.refs import capture, locate, write_json_doc
from .engine import DEFAULT_TIMEOUT, run_plan
from .markdown import parse_front_matter
from .models import MANUAL_NOTE, VerificationReport
from .sql import header_dialect

__all__ = [
    "RECORD_SCHEMA", "EMITTER_LANGUAGES", "VerifyOutcome", "emitter_for",
    "plan_for", "record_path", "verify_artifact",
]

RECORD_SCHEMA = "soloctl.verification/1"

# Emitter name -> the normalized language its candidates carry (classify.py).
EMITTER_LANGUAGES: dict[str, str] = {
    "bash": "bash", "python": "python", "powershell": "powershell",
    "sql": "sql", "prompt": "prompt", "runbook": "markdown",
}

_SCRIPT_FLAGS_RX = re.compile(r"^(?:#|--)[ \t]+risk-flags:[ \t]+(.*?)[ \t]*$")


@dataclass(frozen=True)
class VerifyOutcome:
    ref: str                                   # "<kind>/<filename>"
    state: Literal["draft", "approved"]
    compiled: str                              # the artifact's generation stamp
    verified_at: str
    report: VerificationReport
    record_path: Path                          # absolute
    relative_record_path: Path                 # relative to the library root


def emitter_for(ref: str) -> ArtifactEmitter:
    """The one built-in emitter whose kind directory and extension produce
    `ref`. SQL is built with no default dialect: the header already records
    the dialect the emitter resolved at compile time."""
    kind, filename = ref.split("/")
    suffix = Path(filename).suffix
    matches = [e for e in (factory(None) for factory in BUILTIN_EMITTERS.values())
               if KIND_DIRS[e.artifact_type] == kind and e.extension == suffix]
    if len(matches) != 1:
        raise UnknownArtifactError(
            f"no built-in emitter produces {kind}/*{suffix} artifacts, so "
            f"{ref} has no verification plan")
    return matches[0]


def _risk_flags(emitter: ArtifactEmitter, text: str) -> tuple[str, ...]:
    if emitter.extension == ".md":
        flags = parse_front_matter(text).fields.get("risk-flags")
        if isinstance(flags, list) and all(isinstance(f, str) for f in flags):
            return tuple(flags)
        return ()
    for line in text.split("\n"):
        if line.startswith("#!"):
            continue
        if not line.startswith(("#", "--")):
            break
        m = _SCRIPT_FLAGS_RX.match(line)
        if m:
            value = m.group(1)
            return () if value == "none" else tuple(v.strip() for v in value.split(","))
    return ()


def plan_for(ref: str, text: str) -> tuple[ArtifactEmitter, VerificationPlan]:
    """Rebuild the plan the emitter returned when it rendered `text`."""
    emitter = emitter_for(ref)
    lang = EMITTER_LANGUAGES[emitter.name]
    # A transient value for `verification_plan()` only, never stored. The
    # hash fields stay empty rather than invented; plans don't read them.
    candidate = ArtifactCandidate(
        lang=lang, body=text, body_norm="", sha256="",
        name_proposal=Path(ref).stem, description="", heading_path=(),
        flags=_risk_flags(emitter, text),
        src=SourceRef(path=ref, line_start=1, line_end=text.count("\n") + 1),
        artifact_type=emitter.artifact_type, lang_raw=lang,
        dialect=header_dialect(text) if emitter.name == "sql" else None)
    return emitter, emitter.verification_plan(candidate)


def record_path(paths: LibraryPaths, ref: str) -> Path:
    kind, filename = ref.split("/")
    return paths.resolve(VERIFICATION, kind, f"{filename}.json")


def verify_artifact(config: SoloctlConfig, artifact: str, *,
                    timeout: float = DEFAULT_TIMEOUT,
                    verified_at: str | None = None) -> VerifyOutcome:
    """Verify one draft or approved artifact and record the result.

    `artifact` takes the same forms as `soloctl tag`. Refusals (unknown or
    uncompiled artifact, no plan, unreadable or changed file) raise before
    anything is written."""
    paths = LibraryPaths(config.library_root)
    if not paths.verification.is_dir():
        raise LibraryError(
            f"no verification directory at {paths.verification}; run 'soloctl "
            f"init --library {paths.root}' first")
    item = capture(paths, artifact)
    where = locate(paths, item.ref)
    if where is None:       # removed between capture() and here
        raise UnknownArtifactError(f"{item.ref} disappeared while verify started")
    state, path = where
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise VerificationError(f"cannot read artifact {path}: {exc}") from exc

    _, plan = plan_for(item.ref, text)
    report = run_plan(plan, path, timeout=timeout)
    if report.sha256 != hashlib.sha256(data).hexdigest():
        raise VerificationError(
            f"{path} changed between planning and checking; nothing was "
            f"recorded — re-run `soloctl verify`")

    when = verified_at or now_iso()
    dest = record_path(paths, item.ref)
    write_json_doc(dest, _record(item.ref, state, item.compiled, when, report))
    return VerifyOutcome(
        ref=item.ref, state=state, compiled=item.compiled, verified_at=when,
        report=report, record_path=dest,
        relative_record_path=dest.relative_to(paths.root.resolve()))


def _record(ref: str, state: str, compiled: str, verified_at: str,
            report: VerificationReport) -> dict[str, Any]:
    return {
        "schema": RECORD_SCHEMA,
        "ref": ref,
        "state": state,
        "compiled": compiled,
        "sha256": report.sha256,
        "emitter": report.emitter,
        "artifact_type": report.artifact_type,
        "verified_at": verified_at,
        "tool_version": f"soloctl {__version__}",
        "scope": "automatic",
        "note": MANUAL_NOTE,
        "verdict": report.verdict,
        "reasons": list(report.reasons),
        "plan": {"complete": report.plan_complete, "notes": list(report.plan_notes)},
        "checks": [
            {"name": c.name, "kind": c.kind, "required": c.required,
             "description": c.description, "status": c.status, "detail": c.detail,
             "tool": c.tool, "argv": list(c.argv), "returncode": c.returncode,
             "output": c.output}
            for c in report.checks
        ],
    }
