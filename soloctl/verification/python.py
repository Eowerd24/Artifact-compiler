"""`python-ast-parse`: parse with the stdlib `ast` module (no execution).

`ast.parse` builds a syntax tree and runs nothing: no import, no top-level
statement, no decorator. It catches what the parser catches; errors that only
the bytecode compiler reports (e.g. `return` outside a function) are not in
scope, matching the check's description.
"""
from __future__ import annotations

import ast

from .models import CheckOutcome

__all__ = ["check_python_ast_parse"]


def check_python_ast_parse(text: str) -> CheckOutcome:
    try:
        ast.parse(text, filename="<artifact>")
    except SyntaxError as exc:     # includes IndentationError / TabError
        where = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return CheckOutcome(False, f"syntax error at {where}: {exc.msg}")
    except ValueError as exc:      # e.g. "source code string cannot contain null bytes"
        return CheckOutcome(False, f"cannot parse: {exc}")
    except RecursionError:
        return CheckOutcome(False, "cannot parse: nesting too deep for the parser")
    return CheckOutcome(True, "parsed with ast (nothing executed)")
