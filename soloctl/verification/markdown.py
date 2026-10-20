"""In-process checks for the `.md` artifacts: prompts and runbooks.

Front matter. soloctl writes flat front matter: a `---` line, one
`key: <JSON value>` line per field (JSON strings and flow lists are valid
YAML), and a closing `---` line (`emitters.base.yaml_front_matter`).
soloctl has no YAML dependency, so "well-formed" means exactly that form:
every field line is `key: <JSON>`, no key repeats, the block is closed, and
the keys soloctl writes are present with the types it writes. Blank lines
and full-line `#` comments are tolerated. A hand-added plain YAML scalar
(`tags: foo`) fails — artifacts are not edited in place, and accepting what
soloctl can't parse would be a pass it can't back up.

Runbook structure is linted over the markdown-it token stream (the same
CommonMark parser the extractor uses); nothing in a runbook is executed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

from ..emitters.prompt import find_placeholders
from .models import CheckOutcome

__all__ = [
    "FRONT_MATTER_KEYS", "LIST_KEYS", "EDITORIAL_RX", "FrontMatter",
    "parse_front_matter", "check_prompt_front_matter", "check_prompt_body",
    "check_prompt_placeholders", "check_runbook_front_matter",
    "check_runbook_title", "check_runbook_fences_labeled",
]

_COMMON_KEYS = ("kind", "name", "source", "compiled", "description", "review",
                "risk-flags", "verify-with")
# The keys `emitters.base.markdown_front_matter` writes, per kind.
FRONT_MATTER_KEYS: dict[str, tuple[str, ...]] = {
    "prompt": (*_COMMON_KEYS, "placeholders"),
    "runbook": _COMMON_KEYS,
}
# Keys whose value is a list of strings; every other soloctl key is a string.
LIST_KEYS = frozenset({"risk-flags", "placeholders"})

_FENCE = "---"
_FIELD_RX = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_-]*):[ \t]*(.*?)[ \t]*$")

# Editorial fill-ins: an unfinished draft, not a template slot. Upper-case
# markers only, so prose like "a todo list" doesn't trip it.
EDITORIAL_RX = re.compile(
    r"\b(?:TODO|TBD|FIXME)\b"
    r"|(?i:\[[ \t]*insert\b[^\]\n]*\]|<[ \t]*insert\b[^>\n]*>)")


@dataclass(frozen=True)
class FrontMatter:
    """Result of splitting an artifact into front matter and body.

    `present` is False when line 1 isn't `---`; then `body` is the whole
    text. `closed` is False when the block never ends; then `body` is None
    (it can't be located). `problems` lists malformed lines and duplicates.
    `body_line` is the 1-based file line on which the body starts."""
    present: bool
    closed: bool
    fields: dict[str, Any] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    body: str | None = None
    body_line: int = 1


def parse_front_matter(text: str) -> FrontMatter:
    lines = text.split("\n")
    if lines[0] != _FENCE:
        return FrontMatter(present=False, closed=False, body=text, body_line=1)
    fields: dict[str, Any] = {}
    problems: list[str] = []
    for idx, line in enumerate(lines[1:], start=1):
        if line == _FENCE:
            return FrontMatter(present=True, closed=True, fields=fields,
                               problems=tuple(problems),
                               body="\n".join(lines[idx + 1:]), body_line=idx + 2)
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _FIELD_RX.match(line)
        if not m:
            problems.append(f"line {idx + 1} is not a `key: value` field")
            continue
        key, raw = m.groups()
        try:
            value = json.loads(raw)
        except ValueError:
            problems.append(
                f"line {idx + 1}: the value of {key!r} is not a JSON string or "
                f"list (soloctl writes flat `key: <JSON>` front matter)")
            continue
        if key in fields:
            problems.append(f"line {idx + 1}: key {key!r} appears more than once")
            continue
        fields[key] = value
    return FrontMatter(present=True, closed=False, fields=fields,
                       problems=tuple(problems))


def _check_front_matter(text: str, kind: str) -> CheckOutcome:
    fm = parse_front_matter(text)
    if not fm.present:
        return CheckOutcome(False, "no front matter: line 1 must be '---'")
    if not fm.closed:
        return CheckOutcome(False, "front matter opened on line 1 is never closed "
                                   "with a '---' line")
    problems = list(fm.problems)
    missing = [k for k in FRONT_MATTER_KEYS[kind] if k not in fm.fields]
    if missing:
        problems.append(f"missing key(s): {', '.join(missing)}")
    for key in FRONT_MATTER_KEYS[kind]:
        if key not in fm.fields:
            continue
        value = fm.fields[key]
        if key in LIST_KEYS:
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                problems.append(f"{key!r} must be a list of strings")
        elif not isinstance(value, str):
            problems.append(f"{key!r} must be a string")
    if "kind" in fm.fields and fm.fields["kind"] != kind:
        problems.append(f"kind is {fm.fields['kind']!r}, expected {kind!r}")
    if problems:
        return CheckOutcome(False, "; ".join(problems))
    return CheckOutcome(True, f"well-formed, kind {kind!r}, all "
                              f"{len(FRONT_MATTER_KEYS[kind])} soloctl keys present")


def _body_or_failure(text: str) -> tuple[FrontMatter, CheckOutcome | None]:
    fm = parse_front_matter(text)
    if fm.body is None:
        return fm, CheckOutcome(False, "cannot locate the body: the front matter "
                                       "is never closed")
    return fm, None


def _line_of(fm: FrontMatter, offset: int) -> int:
    assert fm.body is not None
    return fm.body_line + fm.body.count("\n", 0, offset)


# ---------------------------------------------------------------------- prompt
def check_prompt_front_matter(text: str) -> CheckOutcome:
    return _check_front_matter(text, "prompt")


def check_prompt_body(text: str) -> CheckOutcome:
    fm, failure = _body_or_failure(text)
    if failure:
        return failure
    assert fm.body is not None
    if not fm.body.strip():
        return CheckOutcome(False, "the body below the front matter is blank")
    return CheckOutcome(True, "body is not blank")


def check_prompt_placeholders(text: str) -> CheckOutcome:
    fm, failure = _body_or_failure(text)
    if failure:
        return failure
    assert fm.body is not None
    declared = fm.fields.get("placeholders")
    if not (isinstance(declared, list) and all(isinstance(v, str) for v in declared)):
        return CheckOutcome(False, "the front matter has no `placeholders` list of "
                                   "strings to compare the body against")
    found = find_placeholders(fm.body)
    problems: list[str] = []
    undeclared = [n for n in found if n not in declared]
    unused = [n for n in dict.fromkeys(declared) if n not in found]
    if undeclared:
        problems.append(f"undeclared placeholder(s) in the body: {', '.join(undeclared)}")
    if unused:
        problems.append(f"declared but unused placeholder(s): {', '.join(unused)}")
    fills = [f"{m.group(0)!r} (line {_line_of(fm, m.start())})"
             for m in EDITORIAL_RX.finditer(fm.body)]
    if fills:
        problems.append(f"editorial fill-in(s) remain: {', '.join(fills)}")
    if problems:
        return CheckOutcome(False, "; ".join(problems))
    return CheckOutcome(True, f"{len(found)} placeholder(s), all declared; no "
                              f"editorial fill-ins")


# --------------------------------------------------------------------- runbook
def _tokens(body: str) -> list[Any]:
    return MarkdownIt("commonmark").parse(body)


def check_runbook_front_matter(text: str) -> CheckOutcome:
    return _check_front_matter(text, "runbook")


def check_runbook_title(text: str) -> CheckOutcome:
    fm, failure = _body_or_failure(text)
    if failure:
        return failure
    assert fm.body is not None
    tokens = _tokens(fm.body)
    if not tokens:
        return CheckOutcome(False, "the body is empty, so it has no title heading")
    first = tokens[0]
    if first.type != "heading_open":
        line = fm.body_line + (first.map[0] if first.map else 0)
        return CheckOutcome(False, f"the first block of the body (line {line}) is "
                                   f"a {first.type.removesuffix('_open')}, not a "
                                   f"heading")
    title = tokens[1].content if len(tokens) > 1 else ""
    return CheckOutcome(True, f"title heading: {title!r}")


def check_runbook_fences_labeled(text: str) -> CheckOutcome:
    fm, failure = _body_or_failure(text)
    if failure:
        return failure
    assert fm.body is not None
    fences = [t for t in _tokens(fm.body) if t.type == "fence"]
    unlabeled = [fm.body_line + (t.map[0] if t.map else 0)
                 for t in fences if not t.info.strip()]
    if unlabeled:
        return CheckOutcome(False, "code fence(s) without a language label at "
                                   f"line(s) {', '.join(map(str, unlabeled))}")
    return CheckOutcome(True, f"{len(fences)} code fence(s), all labeled")
