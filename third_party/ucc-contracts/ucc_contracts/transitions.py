"""Lifecycle transition tables and the shared legality check.

Authority (precedence): UCC-Remaining-Baseline §3 and Part-G/G-Context over
older SPEC-001 §E.6 wording where they differ. Tables live as machine-readable
JSON under transitions/ so all three repos evaluate the same rules.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent.parent / "transitions"


class TransitionError(Exception):
    pass


def load_transitions(machine: str) -> dict[str, Any]:
    path = _DIR / f"{machine}.json"
    if not path.exists():
        raise TransitionError(f"No transition table for {machine!r}.")
    return json.loads(path.read_text(encoding="utf-8"))


def is_legal_transition(machine: str, from_state: str, to_state: str) -> bool:
    table = load_transitions(machine)
    allowed = {row["to"] for row in table["transitions"] if row["from"] == from_state}
    return to_state in allowed


def refusal_code_for(machine: str, from_state: str, to_state: str) -> str | None:
    """Return the declared refusal code if this transition is illegal, else None."""
    if is_legal_transition(machine, from_state, to_state):
        return None
    table = load_transitions(machine)
    return table.get("illegal_transition_refusal_code", "illegal_lifecycle_transition")
