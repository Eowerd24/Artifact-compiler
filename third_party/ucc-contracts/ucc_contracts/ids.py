"""Identifier, hash, and path primitives.

Authority: SPEC-001 §E.3 (prefix table, ULID form), §E.4 (hash form),
locked Decisions 1-of-2 §1 items 8-10, and UCC-Remaining-Baseline §2.
Where the shared-data-language draft disagreed (e.g. `proj_`, UUIDv7),
the locked baseline wins: prefixed ULIDs, project prefix is `prj_`.
"""
from __future__ import annotations

import os
import re
import time
from typing import Tuple

# Crockford base32 alphabet (excludes I, L, O, U), as used by ULID.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# SPEC-001 §E.3 initial prefixes. This table is authoritative; repositories
# must not invent divergent prefixes.
ID_PREFIXES: frozenset[str] = frozenset({
    "act", "art", "rev", "col", "pub",
    "host", "img", "snap", "node", "nalloc",
    "prj", "job", "asn", "exec", "xfer",
    "hb", "rpt", "cred", "evt", "op", "req", "res", "corr",
})

_ID_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9]*)_(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})$")


def _encode_ulid(timestamp_ms: int, randomness: bytes) -> str:
    """Encode a 48-bit timestamp + 80-bit randomness as a 26-char Crockford ULID."""
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= int.from_bytes(randomness, "big") & ((1 << 80) - 1)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """Generate a canonical prefixed ULID. The canonical owner calls this once."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"Unknown id prefix {prefix!r}; not in the authoritative table.")
    return f"{prefix}_{_encode_ulid(int(time.time() * 1000), os.urandom(10))}"


def parse_id(value: str) -> Tuple[str, str]:
    """Return (prefix, ulid) or raise ValueError."""
    m = _ID_RE.match(value)
    if not m:
        raise ValueError(f"Malformed id {value!r}.")
    return m.group("prefix"), m.group("ulid")


def is_valid_id(value: str, *, expected_prefix: str | None = None) -> bool:
    m = _ID_RE.match(value or "")
    if not m:
        return False
    if m.group("prefix") not in ID_PREFIXES:
        return False
    if expected_prefix is not None and m.group("prefix") != expected_prefix:
        return False
    return True


def is_valid_hash(value: str) -> bool:
    """Canonical hash form is `sha256:` + 64 lowercase hex chars (SPEC-001 §E.4)."""
    return bool(_HASH_RE.match(value or ""))


def is_safe_relpath(value: str) -> bool:
    """Relative POSIX path with no traversal / absolute / control chars.

    Mirrors the canonicalization rules in SPEC-001 §E.4 and the path-security
    controls in §F.5. This is the single shared check the three repos use so
    path containment cannot drift between them.
    """
    if not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value:
        return False
    if "\x00" in value or any(ord(c) < 0x20 for c in value):
        return False
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            return False
    return True
