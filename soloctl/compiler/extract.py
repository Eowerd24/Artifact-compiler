"""Extractor — pure function, no I/O. Implements EXTRACTOR_BLUEPRINT.md v1.

Signed-off behaviors preserved from the soloctl-0.1.0 prototype:
  1. Secret hit aborts the ENTIRE extract (SecretDetected), zero output.
  2. Supersede: within-document revisions collapse, last wins (name match or
     difflib ratio >= 0.70 on normalized bodies). Deterministic, no AI.
  3. Transcript mode: assistant-turn fences only by default; the preceding
     user question is the preferred description source.

Invariant (self-checked): every input fence lands in blocks or skipped.

This module still generalizes only to Bash-family fences (WP1 scope keeps
the extractor's current behavior; expanding to all emitter languages and
introducing the ArtifactCandidate model is Phase 6 / a later work package).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from markdown_it import MarkdownIt

from ..errors import SecretDetected
from ..ledger import load_scrub_patterns, scan_text_for_secret

__all__ = [
    "SourceRef", "Block", "SkipRecord", "ExtractResult", "SecretDetected",
    "extract", "load_risk_patterns",
]

SIMILARITY_THRESHOLD = 0.70
TARGET_LANGS = {"bash", "sh", "shell", "zsh"}          # all normalize to "bash"
CONSOLE_LANGS = {"console", "terminal", "shell-session", "shellsession"}


# --------------------------------------------------------------------------
# Data model (blueprint §2)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceRef:
    path: str
    line_start: int
    line_end: int
    turn: int | None = None
    role: str | None = None


@dataclass(frozen=True)
class Block:
    lang: str
    body: str
    body_norm: str
    sha256: str
    name_proposal: str
    description: str
    heading_path: tuple[str, ...]
    flags: tuple[str, ...]
    src: SourceRef
    supersedes: str | None = None       # sha256 of the latest prior revision
    superseded_count: int = 0


@dataclass(frozen=True)
class SkipRecord:
    reason: str   # unlabeled | non-target-lang | console | user-turn |
                  # dupe-in-library | superseded | empty
    lang: str | None
    src: SourceRef
    detail: str = ""


@dataclass(frozen=True)
class ExtractResult:
    blocks: tuple[Block, ...]
    skipped: tuple[SkipRecord, ...]
    stats: dict


# --------------------------------------------------------------------------
# Risk patterns (flag list — annotate, never block). Same TOML convention as
# scrub patterns; dumb regex by design, whole table readable in one screen.
# --------------------------------------------------------------------------
_DEFAULT_RISK: list[tuple[str, re.Pattern[str]]] = [
    ("sudo", re.compile(r"\bsudo\b")),
    ("rm-rf", re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*[rf]\b")),
    ("pipe-to-shell", re.compile(r"\b(?:curl|wget)\b[^|\n]*\|\s*(?:ba|z)?sh\b")),
    ("disk", re.compile(r"\b(?:dd|mkfs\.\w+|parted|sgdisk|wipefs)\b")),
    ("chmod-777", re.compile(r"\bchmod\s+-?\w*\s*777\b")),
    ("pkg-install", re.compile(r"\b(?:apt(?:-get)?|pip3?|npm|dnf|pacman|snap)\s+(?:install|add|-S)\b")),
    ("firewall", re.compile(r"\b(?:ufw|iptables|nft|firewall-cmd)\b")),
    ("systemd", re.compile(r"\bsystemctl\b")),
    ("etc-write", re.compile(r"(?:>>?\s*/etc/|\btee\s+(?:-a\s+)?/etc/)")),
]


def load_risk_patterns(toml_path=None) -> list[tuple[str, re.Pattern[str]]]:
    if not toml_path:
        return list(_DEFAULT_RISK)
    try:
        import tomllib
        from pathlib import Path
        data = tomllib.loads(Path(toml_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return list(_DEFAULT_RISK)
    pats = []
    for label, rx in (data.get("patterns") or {}).items():
        try:
            pats.append((label, re.compile(rx)))
        except re.error:
            continue
    return pats or list(_DEFAULT_RISK)


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
_TURN_RX = re.compile(
    r"<!--\s*turn\s+(\d+)\s+role=(\w+)(?:\s+ts=(\S+))?\s*-->")
_FRONT_MATTER_RX = re.compile(r"\A---\n(.*?)\n(?:---|\.\.\.)\n", re.DOTALL)
_LEADIN_RX = re.compile(
    r"^\s*(?:sure[,.!]?\s+)?here(?:'s| is)\s+(?:a |an |the )?"
    r"(?:\w+ ){0,2}?(?:that|to|which)\s+", re.IGNORECASE)
_COMMENT_NAME_RX = re.compile(r"^#\s*(?!!)([A-Za-z][^\n]{2,})$")


def _slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


def _normalize(body: str) -> str:
    lines = body.replace("\r\n", "\n").split("\n")
    out = "\n".join(l.rstrip() for l in lines).rstrip("\n")
    return out + "\n"


def _first_sentence(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    sent = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return sent[:limit].rstrip()


def _strip_leadin(text: str) -> str:
    t = _LEADIN_RX.sub("", text).strip().rstrip(":").strip()
    return (t[:1].upper() + t[1:]) if t else ""


def _name_from_comment(body: str) -> str | None:
    for line in body.splitlines()[:6]:
        line = line.strip()
        if line.startswith("#!"):
            continue
        m = _COMMENT_NAME_RX.match(line)
        if m and not m.group(1).lower().startswith(("set ", "shellcheck")):
            return _slugify(m.group(1))
    return None


# --------------------------------------------------------------------------
# extract()
# --------------------------------------------------------------------------
def extract(text: str, *, source: str = "-",
            library_hashes: frozenset[str] = frozenset(),
            only: set[str] | None = None,
            include_user: bool = False,
            all_revisions: bool = False,
            scrub_patterns=None,
            risk_patterns=None) -> ExtractResult:
    only = only or {"bash"}
    scrub = scrub_patterns if scrub_patterns is not None \
        else load_scrub_patterns("/nonexistent")          # -> built-in defaults
    risk = risk_patterns if risk_patterns is not None else list(_DEFAULT_RISK)

    # -- front matter (strip, keep line offset so src lines match the file) --
    offset = 0
    fm = _FRONT_MATTER_RX.match(text)
    if fm:
        offset = text[:fm.end()].count("\n")
        text = text[fm.end():]

    # -- turn markers from raw lines ----------------------------------------
    markers: list[tuple[int, int, str]] = []           # (line0, turn, role)
    for i, line in enumerate(text.split("\n")):
        m = _TURN_RX.search(line)
        if m:
            markers.append((i, int(m.group(1)), m.group(2).lower()))
    transcript_mode = bool(markers)

    def turn_at(line0: int) -> tuple[int | None, str | None]:
        cur: tuple[int | None, str | None] = (None, None)
        for ln, t, r in markers:
            if ln <= line0:
                cur = (t, r)
            else:
                break
        return cur

    # -- token walk: headings, paragraphs, fences ---------------------------
    md = MarkdownIt("commonmark")
    tokens = md.parse(text)

    heading_stack: list[tuple[int, str]] = []
    last_para: tuple[str, int | None] | None = None     # (text, turn)
    paras_by_turn: dict[int, list[str]] = {}
    raw: list[dict] = []
    fences_seen = 0
    by_lang: Counter = Counter()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            level = int(tok.tag[1])
            content = tokens[i + 1].content if i + 1 < len(tokens) else ""
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, content))
            last_para = None          # a heading breaks para→fence association
            i += 3
            continue
        if tok.type == "paragraph_open":
            content = tokens[i + 1].content if i + 1 < len(tokens) else ""
            line0 = tok.map[0] if tok.map else 0
            t, r = turn_at(line0)
            last_para = (content, t)
            if t is not None:
                paras_by_turn.setdefault(t, []).append(content)
            i += 3
            continue
        if tok.type == "fence":
            fences_seen += 1
            line0, line1 = (tok.map or (0, 0))
            t, role = turn_at(line0)
            info = (tok.info or "").strip().split()
            lang_raw = info[0].lower() if info else None
            by_lang[lang_raw or "(unlabeled)"] += 1
            raw.append({
                "lang_raw": lang_raw, "body": tok.content,
                "line0": line0, "line1": line1, "turn": t, "role": role,
                "heading_path": tuple(h for _, h in heading_stack),
                "para": last_para,
            })
            last_para = None          # consumed: it described this fence
            i += 1
            continue
        i += 1

    # -- secret scan FIRST, across ALL fences: abort before building output --
    for f in raw:
        hit = scan_text_for_secret(f["body"], scrub)
        if hit:
            label, rel = hit
            raise SecretDetected(label, offset + f["line0"] + 1 + rel, source)

    # -- classify / name / describe -----------------------------------------
    blocks_wip: list[dict] = []
    skipped: list[SkipRecord] = []

    def srcref(f) -> SourceRef:
        return SourceRef(source, offset + f["line0"] + 1,
                         offset + f["line1"], f["turn"], f["role"])

    for n, f in enumerate(raw, 1):
        lang_raw = f["lang_raw"]
        if not f["body"].strip():
            skipped.append(SkipRecord("empty", lang_raw, srcref(f)))
            continue
        if lang_raw is None:
            skipped.append(SkipRecord("unlabeled", None, srcref(f)))
            continue
        if lang_raw in CONSOLE_LANGS:
            skipped.append(SkipRecord("console", lang_raw, srcref(f)))
            continue
        lang = "bash" if lang_raw in TARGET_LANGS else lang_raw
        if lang not in only:
            skipped.append(SkipRecord("non-target-lang", lang_raw, srcref(f)))
            continue
        if f["role"] == "user" and not include_user:
            skipped.append(SkipRecord("user-turn", lang_raw, srcref(f)))
            continue

        # name: heading -> first comment line -> block-NN
        name = (_slugify(f["heading_path"][-1]) if f["heading_path"] else "") \
            or _name_from_comment(f["body"]) or f"block-{n:02d}"

        # description: preceding user turn -> same-turn para -> heading path
        desc = ""
        if transcript_mode and f["turn"] is not None:
            user_turns = [t for t, r in
                          {ln_t_r[1]: ln_t_r[2] for ln_t_r in markers}.items()
                          if r == "user" and t < f["turn"] and t in paras_by_turn]
            if user_turns:
                desc = _first_sentence(paras_by_turn[max(user_turns)][0])
        if not desc and f["para"] and f["para"][1] == f["turn"]:
            desc = _strip_leadin(_first_sentence(f["para"][0]))
        if not desc and f["heading_path"]:
            desc = " / ".join(f["heading_path"])

        body_norm = _normalize(f["body"])
        flags = tuple(l for l, rx in risk if rx.search(f["body"]))
        blocks_wip.append({
            "lang": lang, "body": f["body"], "body_norm": body_norm,
            "sha256": hashlib.sha256(body_norm.encode()).hexdigest(),
            "name_proposal": name, "description": desc,
            "heading_path": f["heading_path"], "flags": flags,
            "src": srcref(f),
        })

    # -- supersede (within-document, last wins) ------------------------------
    groups: list[list[dict]] = []
    if not all_revisions:
        for b in blocks_wip:
            placed = False
            for g in groups:
                rep = g[-1]
                if (b["name_proposal"] == rep["name_proposal"]
                        or SequenceMatcher(None, rep["body_norm"],
                                           b["body_norm"]).ratio()
                        >= SIMILARITY_THRESHOLD):
                    g.append(b)
                    placed = True
                    break
            if not placed:
                groups.append([b])
    else:
        groups = [[b] for b in blocks_wip]

    survivors: list[dict] = []
    for g in groups:
        for earlier in g[:-1]:
            skipped.append(SkipRecord(
                "superseded", earlier["lang"],
                earlier["src"],
                detail=f"→ {g[-1]['name_proposal']}"))
        last = dict(g[-1])
        if len(g) > 1:
            last["supersedes"] = g[-2]["sha256"]
            last["superseded_count"] = len(g) - 1
        survivors.append(last)

    # -- library dedup on survivors ------------------------------------------
    final: list[Block] = []
    for b in survivors:
        if b["sha256"] in library_hashes:
            skipped.append(SkipRecord("dupe-in-library", b["lang"], b["src"],
                                      detail=b["name_proposal"]))
            continue
        final.append(Block(
            lang=b["lang"], body=b["body"], body_norm=b["body_norm"],
            sha256=b["sha256"], name_proposal=b["name_proposal"],
            description=b["description"], heading_path=b["heading_path"],
            flags=b["flags"], src=b["src"],
            supersedes=b.get("supersedes"),
            superseded_count=b.get("superseded_count", 0)))

    stats = {"fences_seen": fences_seen,
             "turns": max((t for _, t, _ in markers), default=0),
             "transcript_mode": transcript_mode,
             "by_lang": dict(by_lang)}

    # invariant (blueprint rule 2): nothing disappears silently
    if fences_seen != len(final) + len(skipped):
        raise AssertionError(
            f"extractor invariant broken: {fences_seen} fences != "
            f"{len(final)} blocks + {len(skipped)} skips")

    return ExtractResult(tuple(final), tuple(skipped), stats)
