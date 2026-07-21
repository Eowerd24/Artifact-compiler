"""M-c: atomic_write_bytes must fsync both the temp file and the containing
directory after os.replace — durability testing is inherently indirect
(you can't unit-test a real power loss), so this asserts fsync is actually
called on both file descriptors, not just the file's."""
import os
from pathlib import Path
from unittest.mock import patch

from soloctl.library.atomic import atomic_write_bytes, atomic_write_text


def test_write_creates_file_with_correct_content(tmp_path):
    target = tmp_path / "sub" / "file.txt"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_fsync_called_on_both_file_and_parent_dir(tmp_path):
    target = tmp_path / "file.txt"
    fsynced_fds = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        fsynced_fds.append(fd)
        return real_fsync(fd)

    with patch("soloctl.library.atomic.os.fsync", side_effect=spy_fsync) as mock_fsync:
        atomic_write_bytes(target, b"data")
        assert mock_fsync.call_count == 2  # file fd, then dir fd


def test_no_dir_fsync_on_failure_before_replace(tmp_path):
    """If exist_ok=False and the target already exists, atomic_write_bytes
    raises before ever calling os.replace — the dir fsync (which only makes
    sense after a real rename) must not fire either."""
    target = tmp_path / "file.txt"
    target.write_bytes(b"original")

    import pytest
    from contextlib import suppress
    with patch("soloctl.library.atomic._fsync_dir") as mock_dir_fsync:
        with pytest.raises(FileExistsError):
            atomic_write_bytes(target, b"new", exist_ok=False)
        mock_dir_fsync.assert_not_called()
    assert target.read_bytes() == b"original"


def test_atomic_write_text_round_trips(tmp_path):
    target = tmp_path / "file.txt"
    atomic_write_text(target, "héllo")
    assert target.read_text(encoding="utf-8") == "héllo"


def test_no_leftover_tmp_files_after_success(tmp_path):
    target = tmp_path / "file.txt"
    atomic_write_bytes(target, b"data")
    leftovers = [p for p in tmp_path.iterdir() if p.name != "file.txt"]
    assert leftovers == []
