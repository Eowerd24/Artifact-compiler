"""Agent guidance must never cite governing documents absent from the repo."""
from pathlib import Path


def test_governing_documents_exist_at_cited_paths():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs/roadmap/UCC-Shared-Roadmap-To-Fork.md").is_file()
    assert (root / "docs/reference/UCC-Standards-and-Layout-Reference.md").is_file()
