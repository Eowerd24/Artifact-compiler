"""Atomic file writes: write to a temp file in the same directory, fsync,
then os.replace. A crash mid-write leaves the original file (or nothing)
intact — never a truncated or partial file at the final path.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes, *, exist_ok: bool = True) -> None:
    """Write data to path atomically. If exist_ok is False and path already
    exists, raises FileExistsError without touching it."""
    if not exist_ok and path.exists():
        raise FileExistsError(f"refusing to overwrite existing file {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if not exist_ok and path.exists():
            raise FileExistsError(f"refusing to overwrite existing file {path}")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, exist_ok: bool = True) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), exist_ok=exist_ok)
