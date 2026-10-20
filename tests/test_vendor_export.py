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
    # Export set as declared by the pinned release's own VENDOR-MANIFEST.md (v0.3.4):
    # resources live inside the package since the v0.3.1 packaging fix.
    expected = {
        "ucc_contracts", "ucc_contracts/schemas", "ucc_contracts/fixtures",
        "ucc_contracts/transitions", "pyproject.toml", "README.md", "VENDOR-MANIFEST.md",
    }
    assert all((root / prefix / item).exists() for item in expected)
    # Pre-v0.3.1 root resource copies are stale duplicates, not part of the export set.
    top_level = {path.parts[0] for path in relative}
    assert top_level == {"ucc_contracts", "pyproject.toml", "README.md", "VENDOR-MANIFEST.md"}
    assert all(
        not any(part in {"tests", ".git", "__pycache__"} or part.endswith(".egg-info")
                for part in path.parts)
        for path in relative
    )
