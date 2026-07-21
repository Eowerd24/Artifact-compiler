"""D8: the tracked vendored contract tree is exactly the declared export set."""
from pathlib import Path, PurePosixPath
import subprocess


def test_tracked_vendor_export_set_is_exact():
    root = Path(__file__).resolve().parents[1]
    prefix = "third_party/ucc-contracts/"
    tracked = subprocess.run(
        ["git", "ls-files", prefix], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.splitlines()
    relative = [PurePosixPath(path.removeprefix(prefix)) for path in tracked]
    expected = {
        "ucc_contracts", "schemas", "fixtures", "transitions",
        "pyproject.toml", "README.md", "VENDOR-MANIFEST.md",
    }
    assert all((root / prefix / item).exists() for item in expected)
    assert all(
        not any(part in {"tests", ".git", "__pycache__"} or part.endswith(".egg-info")
                for part in path.parts)
        for path in relative
    )
