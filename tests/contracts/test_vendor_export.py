"""D8: the tracked ucc-contracts vendor contains only the release export set."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_PREFIX = "third_party/ucc-contracts/"
ALLOWED_TOP_LEVEL = {
    "VENDOR-MANIFEST.md",
    "README.md",
    "fixtures",
    "pyproject.toml",
    "schemas",
    "transitions",
    "ucc_contracts",
}


def test_tracked_vendor_matches_d8_export_shape():
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", VENDOR_PREFIX],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tracked

    relative = [path.removeprefix(VENDOR_PREFIX) for path in tracked]
    top_level = {path.split("/", 1)[0] for path in relative}
    assert top_level == ALLOWED_TOP_LEVEL
    assert not any(
        part == ".git"
        or part == ".gitignore"
        or part == "tests"
        or part == "__pycache__"
        or part.endswith(".egg-info")
        for path in relative
        for part in path.split("/")
    )
