"""Tags (WP4 item 5): operator-curated labels on compiled artifacts.

Stored in one library-level registry, `library/tags.json`, never in the
artifact files. COMPILER_PLAN D3 governs where an artifact's compile-time
metadata lives (header / front matter, no per-artifact sidecars), and §6
rules out in-place editing of library files. A library-level registry is
neither, so both rules hold, and tagging never changes an artifact's bytes.

    {"schema": "soloctl.tags/1",
     "artifacts": {"scripts/foo.sh": {"compiled": "<stamp>", "tags": ["a", "b"]}}}

Every operation is idempotent: a no-op writes nothing, and a real change is
one atomic write. Contract-free, like the compile core. No ledger event:
that is the same open decision as the compile event.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..config import SoloctlConfig
from ..errors import InvalidNameError, StaleReferenceError
from .paths import LibraryPaths
from .refs import (
    NAME_RX, REF_RX, ArtifactRef, Status, capture, corrupt, load_json_doc,
    parse_artifact_arg, require_library, status_of, validate_name,
    write_json_doc,
)

__all__ = [
    "TAGS_SCHEMA", "TagChange", "TaggedArtifact", "add_tags", "remove_tags",
    "artifact_tags", "artifacts_with_tag", "all_tags",
]

TAGS_SCHEMA = "soloctl.tags/1"


@dataclass(frozen=True)
class _Entry:
    compiled: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class TagChange:
    ref: str
    changed: tuple[str, ...]      # tags actually added (or removed)
    unchanged: tuple[str, ...]    # already present (add) / already absent (remove)
    tags: tuple[str, ...]         # the artifact's tags afterwards
    written: bool


@dataclass(frozen=True)
class TaggedArtifact:
    ref: str
    tags: tuple[str, ...]
    status: Status


def _load(paths: LibraryPaths) -> dict[str, _Entry]:
    require_library(paths)
    path = paths.tags_file
    doc = load_json_doc(path, TAGS_SCHEMA)
    if doc is None:
        return {}
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, dict):
        raise corrupt(path, "`artifacts` must be an object")
    out: dict[str, _Entry] = {}
    for ref, entry in artifacts.items():
        if not REF_RX.match(ref):
            raise corrupt(path, f"malformed artifact reference {ref!r}")
        if not isinstance(entry, dict):
            raise corrupt(path, f"entry for {ref} must be an object")
        compiled, tags = entry.get("compiled"), entry.get("tags")
        if not isinstance(compiled, str) or not compiled:
            raise corrupt(path, f"entry for {ref} has no `compiled` stamp")
        if (not isinstance(tags, list) or not tags
                or not all(isinstance(t, str) for t in tags)):
            raise corrupt(path, f"entry for {ref} needs a non-empty `tags` list")
        bad = [t for t in tags if not NAME_RX.match(t)]
        if bad:
            raise corrupt(path, f"entry for {ref} has invalid tag names {bad}")
        out[ref] = _Entry(compiled, tuple(sorted(set(tags))))
    return out


def _save(paths: LibraryPaths, entries: dict[str, _Entry]) -> None:
    write_json_doc(paths.tags_file, {
        "schema": TAGS_SCHEMA,
        "artifacts": {ref: {"compiled": e.compiled, "tags": list(e.tags)}
                      for ref, e in sorted(entries.items())},
    })


def _validate_tags(tags: Sequence[str]) -> tuple[str, ...]:
    if not tags:
        raise InvalidNameError("no tags given: name at least one tag")
    return tuple(dict.fromkeys(validate_name("tag", t) for t in tags))


def add_tags(config: SoloctlConfig, artifact: str, tags: Sequence[str]) -> TagChange:
    """Tag an existing artifact. Refuses (writing nothing) on an invalid
    name, an unknown artifact, or a stale entry for a reused name."""
    paths = LibraryPaths(config.library_root)
    wanted = _validate_tags(tags)
    entries = _load(paths)
    item = capture(paths, artifact)
    current = entries.get(item.ref)
    if current is not None and current.compiled != item.compiled:
        raise StaleReferenceError(
            f"tags.json holds tags {list(current.tags)} for an earlier "
            f"artifact named {item.ref} (compiled {current.compiled}); the file "
            f"there now was compiled {item.compiled}. Clear them first: "
            f"soloctl tag remove {item.ref} {' '.join(current.tags)}")
    have = current.tags if current else ()
    added = tuple(t for t in wanted if t not in have)
    result = tuple(sorted({*have, *added}))
    if added:
        entries[item.ref] = _Entry(item.compiled, result)
        _save(paths, entries)
    return TagChange(item.ref, added, tuple(t for t in wanted if t in have),
                     result, bool(added))


def remove_tags(config: SoloctlConfig, artifact: str, tags: Sequence[str]) -> TagChange:
    """Remove tags. Works on stale and missing entries too, so a registry
    entry can always be cleaned up; refuses only if the artifact is known
    neither to the registry nor on disk."""
    paths = LibraryPaths(config.library_root)
    wanted = _validate_tags(tags)
    entries = _load(paths)
    ref = parse_artifact_arg(paths, artifact)
    current = entries.get(ref)
    if current is None:
        capture(paths, artifact)            # raises if the artifact is unknown
        return TagChange(ref, (), wanted, (), False)
    removed = tuple(t for t in wanted if t in current.tags)
    result = tuple(t for t in current.tags if t not in removed)
    if removed:
        if result:
            entries[ref] = _Entry(current.compiled, result)
        else:
            del entries[ref]
        _save(paths, entries)
    return TagChange(ref, removed, tuple(t for t in wanted if t not in current.tags),
                     result, bool(removed))


def artifact_tags(config: SoloctlConfig, artifact: str) -> TaggedArtifact:
    paths = LibraryPaths(config.library_root)
    entries = _load(paths)
    ref = parse_artifact_arg(paths, artifact)
    current = entries.get(ref)
    if current is None:
        item = capture(paths, artifact)     # raises if the artifact is unknown
        return TaggedArtifact(item.ref, (), status_of(paths, item))
    return TaggedArtifact(ref, current.tags,
                          status_of(paths, ArtifactRef(ref, current.compiled)))


def artifacts_with_tag(config: SoloctlConfig, tag: str) -> tuple[TaggedArtifact, ...]:
    paths = LibraryPaths(config.library_root)
    validate_name("tag", tag)
    return tuple(
        TaggedArtifact(ref, e.tags, status_of(paths, ArtifactRef(ref, e.compiled)))
        for ref, e in sorted(_load(paths).items()) if tag in e.tags)


def all_tags(config: SoloctlConfig) -> dict[str, tuple[str, ...]]:
    """tag -> references carrying it, both sorted."""
    index: dict[str, list[str]] = {}
    for ref, e in sorted(_load(LibraryPaths(config.library_root)).items()):
        for t in e.tags:
            index.setdefault(t, []).append(ref)
    return {t: tuple(refs) for t, refs in sorted(index.items())}
