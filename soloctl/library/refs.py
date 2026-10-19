"""Artifact references shared by tags and collections (WP4 item 5).

A reference is `<kind>/<filename>` (e.g. `scripts/foo.sh`). It doesn't name
a state directory: collision resolution already treats a name as taken in
`drafts/<kind>/` *and* `approved/<kind>/`, so the reference names at most
one live artifact and survives approval moving the file.

Each stored reference also carries the artifact's `compiled:` header value,
its *generation stamp*. If a name is reused by a later compile (the old file
was deleted or revoked), the stamp no longer matches and the reference reads
as stale. It is never silently re-attached to the new file.

No canonical ID is involved: drafts aren't S2-1 records, and an `art_` ID
must never be invented for one (AGENTS.md §1.2). This module is
contract-free: stdlib plus soloctl's library/error modules only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..errors import (
    AmbiguousArtifactError, InvalidNameError, LibraryError, RegistryCorruptError,
    UnknownArtifactError,
)
from .atomic import atomic_write_text
from .paths import APPROVED, ARTIFACT_KINDS, ARTIFACTS, DRAFTS, LibraryPaths

__all__ = [
    "NAME_RX", "REF_RX", "ArtifactRef", "Status", "validate_name",
    "parse_artifact_arg", "locate", "read_compiled_stamp", "capture",
    "status_of", "require_library", "load_json_doc", "write_json_doc", "corrupt",
]

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
REF_RX = re.compile(
    rf"^({'|'.join(ARTIFACT_KINDS)})/([a-z0-9][a-z0-9_-]*\.[a-z0-9]+)$")
_STATES = (DRAFTS, APPROVED)
_STATE_PREFIX_RX = re.compile(rf"^{ARTIFACTS}/(?:{DRAFTS}|{APPROVED})/(.+)$")

_HEADER_STAMP_RX = re.compile(r"^(?:#|--)\s+compiled:\s+(\S.*?)\s*$")
_FRONT_STAMP_RX = re.compile(r"^compiled:\s*(\S.*?)\s*$")
_HEADER_SCAN_LINES = 40

# draft / approved: the file is there with the stored stamp. stale: a file
# is there under a different stamp. missing: no file in drafts/ or approved/
# (deleted, or revoked/superseded once WP5 moves files there).
Status = Literal["draft", "approved", "stale", "missing"]


@dataclass(frozen=True)
class ArtifactRef:
    ref: str          # "<kind>/<filename>"
    compiled: str     # generation stamp: the artifact's `compiled:` value


def validate_name(what: str, name: str) -> str:
    """Return `name` if it's a lower-case slug, else refuse with the slug
    form as the suggestion."""
    if NAME_RX.match(name):
        return name
    suggestion = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].rstrip("-")
    hint = f"; try {suggestion!r}" if suggestion else ""
    raise InvalidNameError(
        f"invalid {what} name {name!r}: use 1-48 characters of a-z, 0-9 and "
        f"'-', starting with a letter or digit{hint}")


def parse_artifact_arg(paths: LibraryPaths, arg: str) -> str:
    """Normalize a user-supplied artifact to a reference. Accepts the short
    form (`scripts/foo.sh`), the library-relative path `compile` prints
    (`artifacts/drafts/scripts/foo.sh`), or a filesystem path inside
    `drafts/<kind>/` or `approved/<kind>/`. Doesn't require the file to
    exist."""
    if REF_RX.match(arg):
        return arg
    m = _STATE_PREFIX_RX.match(arg)
    if m and REF_RX.match(m.group(1)):
        return m.group(1)
    candidate = Path(arg).expanduser().resolve()
    for state in _STATES:
        try:
            rel = candidate.relative_to(paths.resolve(ARTIFACTS, state))
        except ValueError:
            continue
        if REF_RX.match(rel.as_posix()):
            return rel.as_posix()
    raise UnknownArtifactError(
        f"{arg!r} is not a soloctl artifact: give <kind>/<filename> "
        f"(kind one of {', '.join(ARTIFACT_KINDS)}), e.g. 'scripts/foo.sh', or "
        f"a path under {paths.drafts} or {paths.approved}")


def locate(paths: LibraryPaths, ref: str) -> tuple[Literal["draft", "approved"], Path] | None:
    """Where the artifact named by `ref` lives now, or None. Paths go
    through `LibraryPaths.resolve`, so a symlink out of the library is
    refused (PathEscapesLibraryError), not followed."""
    if not REF_RX.match(ref):
        raise UnknownArtifactError(f"malformed artifact reference {ref!r}")
    kind, filename = ref.split("/")
    candidates: list[tuple[Literal["draft", "approved"], Path]] = [
        ("draft", paths.resolve(ARTIFACTS, DRAFTS, kind, filename)),
        ("approved", paths.resolve(ARTIFACTS, APPROVED, kind, filename)),
    ]
    found = [(state, p) for state, p in candidates if p.is_file()]
    if len(found) > 1:
        raise AmbiguousArtifactError(
            f"{ref} exists in both {DRAFTS}/ and {APPROVED}/; the library allows "
            f"one of each name — remove or rename one copy by hand")
    return found[0] if found else None


def read_compiled_stamp(path: Path) -> str | None:
    """The `compiled:` value from an artifact's header — the `#`/`--`
    comment header of a script or the YAML front matter of a `.md` file.
    Only the header is read: a `compiled:` line in the body never counts."""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")[:_HEADER_SCAN_LINES]
    except (OSError, UnicodeDecodeError) as exc:
        raise LibraryError(f"cannot read artifact {path}: {exc}") from exc
    if lines and lines[0] == "---":
        for line in lines[1:]:
            if line in ("---", "..."):
                return None
            m = _FRONT_STAMP_RX.match(line)
            if m:
                try:
                    value = json.loads(m.group(1))
                except ValueError:
                    value = m.group(1)
                return value if isinstance(value, str) and value else None
        return None
    for line in lines:
        if not line.startswith(("#", "--")):
            return None
        m = _HEADER_STAMP_RX.match(line)
        if m:
            return m.group(1)
    return None


def capture(paths: LibraryPaths, arg: str) -> ArtifactRef:
    """Reference plus stamp for an artifact that must exist now."""
    ref = parse_artifact_arg(paths, arg)
    where = locate(paths, ref)
    if where is None:
        raise UnknownArtifactError(
            f"no artifact {ref} in {paths.drafts} or {paths.approved}; check "
            f"the name with `ls`, or compile it first")
    stamp = read_compiled_stamp(where[1])
    if stamp is None:
        raise UnknownArtifactError(
            f"{where[1]} has no `compiled:` header line, so it isn't a "
            f"soloctl-compiled artifact (or its header was edited); only "
            f"compiled artifacts can be tagged or collected")
    return ArtifactRef(ref, stamp)


def status_of(paths: LibraryPaths, item: ArtifactRef) -> Status:
    where = locate(paths, item.ref)
    if where is None:
        return "missing"
    return where[0] if read_compiled_stamp(where[1]) == item.compiled else "stale"


def require_library(paths: LibraryPaths) -> None:
    if not paths.collections.is_dir():
        raise LibraryError(
            f"no collections directory at {paths.collections}; run 'soloctl "
            f"init --library {paths.root}' first")


def load_json_doc(path: Path, schema: str) -> dict[str, Any] | None:
    """Parsed registry document, or None if the file doesn't exist. Anything
    unreadable, non-JSON, or with the wrong `schema` is refused."""
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RegistryCorruptError(
            f"cannot parse {path}: {exc}; fix or remove it by hand") from exc
    if not isinstance(doc, dict) or doc.get("schema") != schema:
        raise RegistryCorruptError(
            f"{path} is not a {schema} document (schema "
            f"{doc.get('schema') if isinstance(doc, dict) else None!r}); fix or "
            f"remove it by hand")
    return doc


def write_json_doc(path: Path, doc: dict[str, Any], *, exist_ok: bool = True) -> None:
    """Deterministic JSON (sorted keys, 2-space indent, trailing newline),
    written atomically."""
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    atomic_write_text(path, text, exist_ok=exist_ok)


def corrupt(path: Path, detail: str) -> RegistryCorruptError:
    return RegistryCorruptError(f"{path}: {detail}; fix or remove it by hand")
