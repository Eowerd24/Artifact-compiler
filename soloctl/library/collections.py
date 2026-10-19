"""Collections (WP4 item 5): named, ordered sets of compiled artifacts.

One file per collection, `library/collections/<name>.json`:

    {"schema": "soloctl.collection/1", "name": "<name>", "title": "...",
     "description": "...", "members": [{"ref": "scripts/foo.sh", "compiled": "<stamp>"}]}

Members keep insertion order (a collection can be a sequence, e.g. the
scripts a runbook walks through). References and their generation stamps
work as for tags (see refs.py). Every operation is idempotent and a real
change is one atomic write. Contract-free, and no ledger event.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import SoloctlConfig
from ..errors import (
    CollectionConflictError, StaleReferenceError, UnknownArtifactError,
    UnknownCollectionError,
)
from .paths import LibraryPaths
from .refs import (
    NAME_RX, REF_RX, ArtifactRef, Status, capture, corrupt, load_json_doc,
    parse_artifact_arg, require_library, status_of, validate_name,
    write_json_doc,
)

__all__ = [
    "COLLECTION_SCHEMA", "Collection", "CollectionChange", "MemberChange",
    "MemberView", "CollectionView", "create_collection", "add_members",
    "remove_members", "show_collection", "list_collections",
]

COLLECTION_SCHEMA = "soloctl.collection/1"


@dataclass(frozen=True)
class Collection:
    name: str
    title: str
    description: str
    members: tuple[ArtifactRef, ...]


@dataclass(frozen=True)
class CollectionChange:
    collection: Collection
    created: bool


@dataclass(frozen=True)
class MemberChange:
    collection: Collection
    changed: tuple[str, ...]      # refs actually added (or removed)
    unchanged: tuple[str, ...]    # already members (add) / not members (remove)
    written: bool


@dataclass(frozen=True)
class MemberView:
    ref: str
    status: Status


@dataclass(frozen=True)
class CollectionView:
    collection: Collection
    members: tuple[MemberView, ...]


def _path(paths: LibraryPaths, name: str) -> Path:
    validate_name("collection", name)
    require_library(paths)
    return paths.collection_file(name)


def _parse(path: Path, name: str) -> Collection | None:
    doc = load_json_doc(path, COLLECTION_SCHEMA)
    if doc is None:
        return None
    if doc.get("name") != name:
        raise corrupt(path, f"`name` is {doc.get('name')!r}, expected {name!r} "
                            f"(the file name)")
    title, description, members = doc.get("title"), doc.get("description"), doc.get("members")
    if not isinstance(title, str) or not isinstance(description, str):
        raise corrupt(path, "`title` and `description` must be strings")
    if not isinstance(members, list):
        raise corrupt(path, "`members` must be a list")
    parsed: list[ArtifactRef] = []
    for m in members:
        if not (isinstance(m, dict) and isinstance(m.get("ref"), str)
                and REF_RX.match(m["ref"]) and isinstance(m.get("compiled"), str)
                and m["compiled"]):
            raise corrupt(path, f"malformed member {m!r}")
        parsed.append(ArtifactRef(m["ref"], m["compiled"]))
    if len({m.ref for m in parsed}) != len(parsed):
        raise corrupt(path, "a member is listed twice")
    return Collection(name, title, description, tuple(parsed))


def _load(paths: LibraryPaths, name: str) -> tuple[Path, Collection]:
    path = _path(paths, name)
    found = _parse(path, name)
    if found is None:
        raise UnknownCollectionError(
            f"no collection {name!r} at {path}; create it with "
            f"soloctl collection create {name}")
    return path, found


def _save(path: Path, c: Collection, *, exist_ok: bool = True) -> None:
    write_json_doc(path, {
        "schema": COLLECTION_SCHEMA, "name": c.name, "title": c.title,
        "description": c.description,
        "members": [{"ref": m.ref, "compiled": m.compiled} for m in c.members],
    }, exist_ok=exist_ok)


def _same_or_conflict(existing: Collection, title: str | None,
                      description: str | None) -> CollectionChange:
    for field, given in (("title", title), ("description", description)):
        stored = getattr(existing, field)
        if given is not None and given != stored:
            raise CollectionConflictError(
                f"collection {existing.name!r} already exists with {field} "
                f"{stored!r}, not {given!r}; it was left unchanged")
    return CollectionChange(existing, False)


def create_collection(config: SoloctlConfig, name: str, *, title: str | None = None,
                      description: str | None = None) -> CollectionChange:
    """Create an empty collection. Re-creating an existing one is a no-op
    unless the given title/description differ from what's stored."""
    paths = LibraryPaths(config.library_root)
    path = _path(paths, name)
    existing = _parse(path, name)
    if existing is not None:
        return _same_or_conflict(existing, title, description)
    new = Collection(name, title or "", description or "", ())
    try:
        _save(path, new, exist_ok=False)
    except FileExistsError:
        # Created between the check and the write: never clobber it.
        raced = _parse(path, name)
        if raced is None:
            raise
        return _same_or_conflict(raced, title, description)
    return CollectionChange(new, True)


def add_members(config: SoloctlConfig, name: str,
                artifacts: Sequence[str]) -> MemberChange:
    """Append artifacts in the given order. All of them are checked before
    anything is written; one unknown or stale artifact refuses the batch."""
    paths = LibraryPaths(config.library_root)
    path, c = _load(paths, name)
    if not artifacts:
        raise UnknownArtifactError("no artifacts given: name at least one")
    items = list({i.ref: i for i in (capture(paths, a) for a in artifacts)}.values())
    current = {m.ref: m for m in c.members}
    for item in items:
        held = current.get(item.ref)
        if held is not None and held.compiled != item.compiled:
            raise StaleReferenceError(
                f"collection {name!r} holds an earlier artifact named {item.ref} "
                f"(compiled {held.compiled}); the file there now was compiled "
                f"{item.compiled}. Remove it first: "
                f"soloctl collection remove {name} {item.ref}")
    added = tuple(i for i in items if i.ref not in current)
    if added:
        c = Collection(c.name, c.title, c.description, (*c.members, *added))
        _save(path, c)
    return MemberChange(c, tuple(i.ref for i in added),
                        tuple(i.ref for i in items if i.ref in current), bool(added))


def remove_members(config: SoloctlConfig, name: str,
                   artifacts: Sequence[str]) -> MemberChange:
    """Remove members; stale and missing ones can always be removed. An
    argument that is neither a member nor an artifact on disk is refused."""
    paths = LibraryPaths(config.library_root)
    path, c = _load(paths, name)
    if not artifacts:
        raise UnknownArtifactError("no artifacts given: name at least one")
    members = {m.ref for m in c.members}
    refs: dict[str, None] = {}
    for arg in artifacts:
        ref = parse_artifact_arg(paths, arg)
        if ref not in members:
            capture(paths, arg)            # raises if the artifact is unknown
        refs[ref] = None
    removed = tuple(r for r in refs if r in members)
    if removed:
        c = Collection(c.name, c.title, c.description,
                       tuple(m for m in c.members if m.ref not in removed))
        _save(path, c)
    return MemberChange(c, removed, tuple(r for r in refs if r not in members),
                        bool(removed))


def show_collection(config: SoloctlConfig, name: str) -> CollectionView:
    paths = LibraryPaths(config.library_root)
    _, c = _load(paths, name)
    return CollectionView(c, tuple(MemberView(m.ref, status_of(paths, m))
                                   for m in c.members))


def list_collections(config: SoloctlConfig) -> tuple[Collection, ...]:
    """Every collection, by name. Files that aren't `<valid-name>.json`
    (e.g. an atomic-write temp file left by a crash) are not collections
    and are ignored; a corrupt collection file is refused."""
    paths = LibraryPaths(config.library_root)
    require_library(paths)
    found: list[Collection] = []
    for p in sorted(paths.collections.glob("*.json")):
        if not NAME_RX.match(p.stem):
            continue
        c = _parse(paths.collection_file(p.stem), p.stem)
        if c is not None:
            found.append(c)
    return tuple(found)
