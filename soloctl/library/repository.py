"""Library initialization: create the full filesystem layout, idempotently."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import SoloctlConfig
from ..errors import LibraryError
from .atomic import atomic_write_bytes
from .paths import LibraryPaths


@dataclass(frozen=True)
class InitResult:
    library_root: Path
    created_directories: tuple[Path, ...]
    created_files: tuple[Path, ...]
    already_initialized: bool


def init_library(config: SoloctlConfig) -> InitResult:
    """Create the library directory layout under config.library_root.

    Safe to call repeatedly: existing directories/files are left untouched,
    only missing pieces are created. A regular file where a required
    directory belongs raises LibraryError rather than being silently
    replaced.
    """
    paths = LibraryPaths(config.library_root)
    root = paths.root

    if root.exists() and not root.is_dir():
        raise LibraryError(
            f"library root {root} exists and is not a directory; "
            f"remove it or choose a different --library path"
        )

    already_initialized = root.is_dir() and any(root.iterdir())

    created_dirs: list[Path] = []
    for directory in paths.required_directories():
        if directory.exists() and not directory.is_dir():
            raise LibraryError(
                f"cannot create library directory {directory}: a file already "
                f"exists at that path; remove it and re-run 'soloctl init'"
            )
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_dirs.append(directory)

    created_files: list[Path] = []
    events_path = paths.events_file
    if events_path.exists() and not events_path.is_file():
        raise LibraryError(
            f"cannot create {events_path}: a directory already exists at that "
            f"path; remove it and re-run 'soloctl init'"
        )
    if not events_path.exists():
        atomic_write_bytes(events_path, b"")
        created_files.append(events_path)

    return InitResult(
        library_root=root,
        created_directories=tuple(created_dirs),
        created_files=tuple(created_files),
        already_initialized=already_initialized,
    )
