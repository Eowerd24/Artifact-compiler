from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.config import SoloctlConfig
from soloctl.errors import LibraryError, PathEscapesLibraryError
from soloctl.library.paths import LibraryPaths
from soloctl.library.repository import init_library


def _config(tmp_path: Path) -> SoloctlConfig:
    return SoloctlConfig(library_root=tmp_path / "library")


def test_init_creates_all_required_directories(tmp_path: Path):
    config = _config(tmp_path)
    result = init_library(config)

    paths = LibraryPaths(config.library_root)
    for directory in paths.required_directories():
        assert directory.is_dir(), f"missing {directory}"
    assert paths.events_file.is_file()
    assert result.already_initialized is False
    assert len(result.created_directories) > 0


def test_init_is_idempotent(tmp_path: Path):
    config = _config(tmp_path)
    first = init_library(config)
    second = init_library(config)

    assert first.created_directories
    assert second.created_directories == ()
    assert second.created_files == ()
    assert second.already_initialized is True

    paths = LibraryPaths(config.library_root)
    for directory in paths.required_directories():
        assert directory.is_dir()


def test_file_where_directory_expected_raises_clear_error(tmp_path: Path):
    config = _config(tmp_path)
    config.library_root.mkdir(parents=True)
    # Pre-create a plain file where artifacts/ (a directory) must go.
    (config.library_root / "artifacts").write_text("oops", encoding="utf-8")

    with pytest.raises(LibraryError) as exc_info:
        init_library(config)
    assert "artifacts" in str(exc_info.value)


def test_library_root_itself_is_a_file(tmp_path: Path):
    root = tmp_path / "library"
    root.write_text("not a directory", encoding="utf-8")
    config = SoloctlConfig(library_root=root)

    with pytest.raises(LibraryError):
        init_library(config)


def test_resolved_paths_cannot_escape_library_root(tmp_path: Path):
    paths = LibraryPaths(tmp_path / "library")
    with pytest.raises(PathEscapesLibraryError):
        paths.resolve("..", "..", "etc", "passwd")


def test_resolve_within_root_is_fine(tmp_path: Path):
    paths = LibraryPaths(tmp_path / "library")
    resolved = paths.resolve("transcripts", "2026", "07")
    assert resolved == (tmp_path / "library" / "transcripts" / "2026" / "07").resolve()
