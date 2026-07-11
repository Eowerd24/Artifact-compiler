from .chatgpt import ChatGPTImporter
from .claude import ClaudeImporter
from .markdown import MarkdownImporter
from .registry import ImporterRegistry

__all__ = [
    "ImporterRegistry", "MarkdownImporter", "ChatGPTImporter", "ClaudeImporter",
    "build_default_registry",
]


def build_default_registry() -> ImporterRegistry:
    """Registry of the importers enabled in this work package."""
    return ImporterRegistry((MarkdownImporter(), ChatGPTImporter(), ClaudeImporter()))
