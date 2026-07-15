"""Agent instructions must not cite missing governing documents."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOVERNING_DOCS = (
    "docs/roadmap/UCC-Shared-Roadmap-To-Fork.md",
    "docs/reference/UCC-Standards-and-Layout-Reference.md",
)


def test_agents_governing_document_paths_exist():
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for relative_path in GOVERNING_DOCS:
        assert f"`{relative_path}`" in agents
        assert (REPO_ROOT / relative_path).is_file()
