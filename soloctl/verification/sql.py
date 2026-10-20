"""`sql-lexical`: a lexical scan of a SQL artifact, without a database.

Not a parse. It checks, outside comments and quoted text:
  - there is at least one statement;
  - string literals, quoted identifiers and block comments are closed;
  - parentheses balance;
  - the last statement ends with ';' (tsql: or a `GO` line).

The quoting rules follow the dialect in the artifact's `-- dialect:` header
line, mapped to a family:

  every family  '...' with '' escapes, "..." with "" escapes, `--` line
                comments, /* */ block comments
  postgres      + $tag$...$tag$ dollar quoting, E'...' backslash escapes,
                nested block comments
  mysql         + backslash escapes in '...' and "...", `...` identifiers,
                `#` line comments
  sqlite        + `...` and [...] identifiers
  tsql          + [...] identifiers, nested block comments, GO separators

An unspecified or unmapped dialect gets only the common rules, so a body
that relies on dialect quoting (an unlabeled Postgres `$$` function) can
fail; the failure says so, and labelling the fence fixes it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import CheckOutcome

__all__ = ["DIALECT_FAMILIES", "check_sql_lexical", "header_dialect"]

DIALECT_FAMILIES: dict[str, str] = {
    "postgresql": "postgres", "postgres": "postgres",
    "mysql": "mysql", "sqlite": "sqlite", "tsql": "tsql",
}

_HEADER_DIALECT_RX = re.compile(r"^--[ \t]+dialect:[ \t]+(\S+)[ \t]*$")
_GO_RX = re.compile(r"[ \t]*GO(?:[ \t]+\d+)?[ \t]*(?:--[^\n]*)?(?=\n|\Z)", re.IGNORECASE)
_DOLLAR_TAG_RX = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def header_dialect(text: str) -> str | None:
    """The `-- dialect:` value from the leading comment header, or None if
    absent or `unspecified` (the SQL emitter writes that when there is none)."""
    for line in text.split("\n"):
        if not line.startswith("--"):
            break
        m = _HEADER_DIALECT_RX.match(line)
        if m:
            value = m.group(1)
            return None if value == "unspecified" else value
    return None


class _Unclosed(Exception):
    def __init__(self, what: str, line: int) -> None:
        super().__init__(f"{what} opened on line {line} is never closed")


class _Unbalanced(Exception):
    pass


@dataclass
class _Scan:
    text: str
    family: str | None
    i: int = 0
    line: int = 1

    def advance_to(self, j: int) -> None:
        self.line += self.text.count("\n", self.i, j)
        self.i = j

    def at_line_start(self) -> bool:
        return self.i == 0 or self.text[self.i - 1] == "\n"

    def is_ident_char(self, j: int) -> bool:
        return j >= 0 and (self.text[j].isalnum() or self.text[j] in "_$")

    def skip_quoted(self, close: str, what: str, *, backslash: bool) -> None:
        """From an opening quote at `i`, move past its matching close. A
        doubled closer is an escape; so is a backslash when `backslash`."""
        start_line, j, text = self.line, self.i + 1, self.text
        while j < len(text):
            c = text[j]
            if backslash and c == "\\":
                j += 2
                continue
            if c == close:
                if text.startswith(close, j + 1):
                    j += 2
                    continue
                self.advance_to(j + 1)
                return
            j += 1
        raise _Unclosed(what, start_line)

    def skip_block_comment(self, *, nested: bool) -> None:
        start_line, j, depth, text = self.line, self.i + 2, 1, self.text
        while j < len(text):
            if text.startswith("*/", j):
                depth -= 1
                j += 2
                if depth == 0:
                    self.advance_to(j)
                    return
            elif nested and text.startswith("/*", j):
                depth += 1
                j += 2
            else:
                j += 1
        raise _Unclosed("block comment", start_line)

    def skip_to_eol(self) -> None:
        end = self.text.find("\n", self.i)
        self.advance_to(len(self.text) if end < 0 else end)


def check_sql_lexical(text: str) -> CheckOutcome:
    dialect = header_dialect(text)
    family = DIALECT_FAMILIES.get((dialect or "").lower())
    hint = ("" if family else
            f" (dialect {dialect or 'unspecified'}: only standard SQL quoting is "
            f"recognized; label the fence, e.g. ```postgres, or set "
            f"default_sql_dialect)")
    try:
        statements, trailing, opens = _scan(_Scan(text, family))
    except _Unclosed as exc:
        return CheckOutcome(False, f"{exc}{hint}")
    except _Unbalanced as exc:
        return CheckOutcome(False, f"{exc}{hint}")
    if opens:
        return CheckOutcome(False, f"'(' opened on line {opens[-1]} is never "
                                   f"closed{hint}")
    if statements == 0 and trailing is None:
        return CheckOutcome(False, "no SQL statement below the header")
    if trailing is not None:
        ender = "';' or a GO line" if family == "tsql" else "';'"
        return CheckOutcome(False, f"the last statement (from line {trailing}) "
                                   f"does not end with {ender}{hint}")
    return CheckOutcome(True, f"{statements} statement(s); literals, identifiers "
                              f"and comments closed; parentheses balanced "
                              f"(lexical scan, not a parse)")


def _scan(s: _Scan) -> tuple[int, int | None, list[int]]:
    """Returns (terminated statements, line where unterminated trailing
    content starts or None, lines of '(' still open)."""
    text, family = s.text, s.family
    statements = 0
    pending: int | None = None      # line where the current statement began
    opens: list[int] = []

    def content() -> None:
        nonlocal pending
        if pending is None:
            pending = s.line

    def terminate() -> None:
        nonlocal statements, pending
        if pending is not None:
            statements += 1
            pending = None

    while s.i < len(text):
        c = text[s.i]
        if family == "tsql" and s.at_line_start():
            m = _GO_RX.match(text, s.i)
            if m:
                terminate()
                s.advance_to(m.end())
                continue
        if c in " \t\r\n":
            s.advance_to(s.i + 1)
        elif text.startswith("--", s.i) or (c == "#" and family == "mysql"):
            s.skip_to_eol()
        elif text.startswith("/*", s.i):
            s.skip_block_comment(nested=family in ("postgres", "tsql"))
        elif c == "'":
            content()
            e_string = (family == "postgres" and s.i > 0 and text[s.i - 1] in "eE"
                        and not s.is_ident_char(s.i - 2))
            s.skip_quoted("'", "string literal",
                          backslash=family == "mysql" or e_string)
        elif c == '"':
            content()
            s.skip_quoted('"', "string literal" if family == "mysql"
                          else "quoted identifier", backslash=family == "mysql")
        elif c == "`" and family in ("mysql", "sqlite"):
            content()
            s.skip_quoted("`", "quoted identifier", backslash=False)
        elif c == "[" and family in ("tsql", "sqlite"):
            content()
            s.skip_quoted("]", "bracketed identifier", backslash=False)
        elif c == "$" and family == "postgres" and not s.is_ident_char(s.i - 1) \
                and (m := _DOLLAR_TAG_RX.match(text, s.i)):
            content()
            tag, start_line = m.group(0), s.line
            end = text.find(tag, m.end())
            if end < 0:
                raise _Unclosed(f"dollar-quoted string {tag}", start_line)
            s.advance_to(end + len(tag))
        elif c == "(":
            content()
            opens.append(s.line)
            s.advance_to(s.i + 1)
        elif c == ")":
            if not opens:
                raise _Unbalanced(f"unbalanced ')' on line {s.line}")
            opens.pop()
            s.advance_to(s.i + 1)
        elif c == ";":
            terminate()
            s.advance_to(s.i + 1)
        else:
            content()
            s.advance_to(s.i + 1)
    return statements, pending, opens
