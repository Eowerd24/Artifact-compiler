from .markdown import MarkdownImporter
from .registry import ImporterRegistry

__all__ = ["ImporterRegistry", "MarkdownImporter", "build_default_registry"]


def build_default_registry() -> ImporterRegistry:
    """Registry of the importers enabled in this work package. ChatGPT and
    Claude adapters register here once implemented — nothing else changes."""
    return ImporterRegistry((MarkdownImporter(),))
