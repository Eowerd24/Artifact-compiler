"""Shared secret-scrub policy.

Adapted from the vendored soloctl-0.1.0 ledger module: this keeps only the
scrub-pattern loading, whole-text secret scanning, and log-time redaction
that the extractor and the import command both need today. The append-only
JSONL audit event writer (ULID ids, actor/action/target envelope) from the
0.1.0 archive is intentionally not carried over yet — that belongs to the
ledger-and-auditability work package, not this one.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Scrub patterns: refusal (extractor, import) and redaction (future logging)
# share one table so a new pattern lands everywhere at once.
# --------------------------------------------------------------------------
_DEFAULT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL)),
    ("gh-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("gh-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("ts-key", re.compile(r"tskey-[a-z]+-[A-Za-z0-9-]{16,}")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    # value-only: keep the key name, redact the value after = or :
    ("kv-secret", re.compile(
        r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b(\s*[=:]\s*)(\S+)")),
]


def load_scrub_patterns(toml_path: str | os.PathLike[str]
                        ) -> list[tuple[str, re.Pattern[str]]]:
    """Load [patterns] label = regex from a shared scrub-patterns.toml.
    Falls back to built-ins if the file is missing so scanning never breaks."""
    try:
        import tomllib
        data = tomllib.loads(Path(toml_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, ModuleNotFoundError):
        return list(_DEFAULT_PATTERNS)
    pats: list[tuple[str, re.Pattern[str]]] = []
    for label, rx in (data.get("patterns") or {}).items():
        try:
            pats.append((label, re.compile(rx, re.IGNORECASE | re.DOTALL)))
        except re.error:
            continue  # a bad pattern must not disable the whole scanner
    return pats or list(_DEFAULT_PATTERNS)


# --------------------------------------------------------------------------
# Refusal scan (D4: whole-input abort on any hit).
#
# The ledger's kv-secret pattern is tuned for LOGGING (over-redacting is
# safe). For REFUSAL it would false-positive on legitimate scripts
# (`TOKEN=$(cat …)`, `password="$1"`). So: high-confidence token shapes
# refuse on any match; kv-secret refuses only when the value is a
# literal-looking credential, not a variable reference, substitution, or
# placeholder.
# --------------------------------------------------------------------------
_KV_REFERENCE_PREFIXES = ("$", "(", "{", "<", "`", '"$', "'$")
_KV_PLACEHOLDER_HINTS = ("xxx", "your", "changeme", "change_me", "example",
                         "placeholder", "redacted", "dummy", "todo", "...")
_KV_LITERAL = re.compile(r"[A-Za-z0-9+/_.=-]{12,}")


def _kv_value_is_literal_secret(value: str) -> bool:
    v = value.strip().strip('"').strip("'")
    if not v or v.startswith(_KV_REFERENCE_PREFIXES):
        return False
    low = v.lower()
    if any(h in low for h in _KV_PLACEHOLDER_HINTS):
        return False
    return bool(_KV_LITERAL.fullmatch(v))


def scan_text_for_secret(
    text: str,
    patterns: list[tuple[str, re.Pattern[str]]] | None = None,
) -> tuple[str, int] | None:
    """Return (label, 1-based line number of the first match) or None."""
    pats = patterns if patterns is not None else _DEFAULT_PATTERNS
    for label, rx in pats:
        for m in rx.finditer(text):
            if label == "kv-secret" and not _kv_value_is_literal_secret(m.group(3)):
                continue
            return label, text.count("\n", 0, m.start()) + 1
    return None


# --------------------------------------------------------------------------
# Redaction — not wired into any command yet (no logging exists in WP1), but
# kept alongside the patterns table since future ledger events must scrub
# their params with the exact same table.
# --------------------------------------------------------------------------
def _last4(s: str) -> str:
    s = s.strip()
    return s[-4:] if len(s) >= 4 else "----"


def scrub_text(text: str,
               patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> str:
    """Replace secrets with [REDACTED:<label>:<last4>]. Correlatable, useless
    to replay. kv-secret keeps the key name and redacts only the value."""
    pats = patterns if patterns is not None else _DEFAULT_PATTERNS
    for label, rx in pats:
        if label == "kv-secret":
            text = rx.sub(
                lambda m: f"{m.group(1)}{m.group(2)}"
                          f"[REDACTED:{label}:{_last4(m.group(3))}]",
                text)
        else:
            text = rx.sub(
                lambda m, _l=label: f"[REDACTED:{_l}:{_last4(m.group(0))}]", text)
    return text


def scrub_obj(obj: Any,
              patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> Any:
    """Recursively scrub every string leaf in a JSON-serializable structure.
    Dict keys are left intact (they are field names, not values)."""
    if isinstance(obj, str):
        return scrub_text(obj, patterns)
    if isinstance(obj, dict):
        return {k: scrub_obj(v, patterns) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v, patterns) for v in obj]
    return obj
