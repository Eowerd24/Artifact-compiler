"""Extractor — pure function, no I/O. Implements EXTRACTOR_BLUEPRINT.md v1,
generalized from Bash-only to language-neutral `ArtifactCandidate`s (Phase 6).

Signed-off behaviors preserved from the soloctl-0.1.0 prototype:
  1. Secret hit aborts the ENTIRE extract (SecretDetected), zero output —
     every fence is scanned, including ones that would be skipped.
  2. Supersede: within-document revisions collapse, last wins (name match or
     difflib ratio >= 0.70 on normalized bodies). Deterministic, no AI.
     Revisions only ever group within one language.
  3. Transcript mode: assistant-turn fences only by default; the preceding
     user question is the preferred description source.

Invariant (self-checked): every input fence lands in blocks or skipped.

Recognized fence labels live in `classify.LABELS` (bash, python, powershell,
sql + dialects, prompt, markdown/runbook). `only` still defaults to
`{"bash"}` so callers that never passed it see the WP1 behavior unchanged;
pass `only=SUPPORTED_LANGUAGES` to extract every recognized language.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Collection
from difflib import SequenceMatcher

from markdown_it import MarkdownIt

from ..errors import SecretDetected, UnknownLanguageError
from ..ledger import load_scrub_patterns, scan_text_for_secret
from .classify import CONSOLE_LABELS, SUPPORTED_LANGUAGES, classify_label
from .models import ArtifactCandidate, Block, ExtractResult, SkipRecord, SourceRef

__all__ = [
    "SourceRef", "ArtifactCandidate", "Block", "SkipRecord", "ExtractResult",
    "SecretDetected", "SUPPORTED_LANGUAGES", "DEFAULT_ONLY",
    "extract", "load_risk_patterns",
]

SIMILARITY_THRESHOLD = 0.70
DEFAULT_ONLY: frozenset[str] = frozenset({"bash"})
CONSOLE_LANGS = CONSOLE_LABELS


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
_SQL_COMMENT_NAME_RX = re.compile(r"^--\s*([A-Za-z][^\n]{2,})$")
# Line-comment syntax per language, used only for the name fallback. Prompts
# have no comment syntax; a markdown runbook's "# Title" heading reads the same
# way as a shell comment, which is exactly the name we want.
_COMMENT_RX_BY_LANG: dict[str, re.Pattern[str]] = {
    "bash": _COMMENT_NAME_RX, "python": _COMMENT_NAME_RX,
    "powershell": _COMMENT_NAME_RX, "markdown": _COMMENT_NAME_RX,
    "sql": _SQL_COMMENT_NAME_RX,
}


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


def _name_from_comment(body: str, lang: str = "bash") -> str | None:
    rx = _COMMENT_RX_BY_LANG.get(lang)
    if rx is None:
        return None
    for line in body.splitlines()[:6]:
        line = line.strip()
        if line.startswith("#!"):
            continue
        m = rx.match(line)
        if m and not m.group(1).lower().startswith(("set ", "shellcheck")):
            return _slugify(m.group(1))
    return None


# --------------------------------------------------------------------------
# extract()
# --------------------------------------------------------------------------
def extract(text: str, *, source: str = "-",
            library_hashes: frozenset[str] = frozenset(),
            only: Collection[str] | None = None,
            include_user: bool = False,
            all_revisions: bool = False,
            scrub_patterns=None,
            risk_patterns=None) -> ExtractResult:
    only = frozenset(only or DEFAULT_ONLY)
    unknown = only - SUPPORTED_LANGUAGES
    if unknown:
        raise UnknownLanguageError(sorted(unknown), sorted(SUPPORTED_LANGUAGES))
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
        if lang_raw in CONSOLE_LABELS:
            skipped.append(SkipRecord("console", lang_raw, srcref(f)))
            continue
        cls = classify_label(lang_raw)
        if cls is None:
            skipped.append(SkipRecord("non-target-lang", lang_raw, srcref(f),
                                      detail="unrecognized label"))
            continue
        lang = cls.language
        if lang not in only:
            skipped.append(SkipRecord("non-target-lang", lang_raw, srcref(f),
                                      detail=f"{lang} not selected"))
            continue
        if f["role"] == "user" and not include_user:
            skipped.append(SkipRecord("user-turn", lang_raw, srcref(f)))
            continue

        # name: heading -> first comment line -> block-NN
        name = (_slugify(f["heading_path"][-1]) if f["heading_path"] else "") \
            or _name_from_comment(f["body"], lang) or f"block-{n:02d}"

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
            "src": srcref(f), "artifact_type": cls.artifact_type,
            "lang_raw": lang_raw, "dialect": cls.dialect,
        })

    # -- supersede (within-document, last wins) ------------------------------
    groups: list[list[dict]] = []
    if not all_revisions:
        for b in blocks_wip:
            placed = False
            for g in groups:
                rep = g[-1]
                if b["lang"] != rep["lang"]:
                    continue          # a bash and a python block never revise each other
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
    final: list[ArtifactCandidate] = []
    for b in survivors:
        if b["sha256"] in library_hashes:
            skipped.append(SkipRecord("dupe-in-library", b["lang"], b["src"],
                                      detail=b["name_proposal"]))
            continue
        final.append(ArtifactCandidate(
            lang=b["lang"], body=b["body"], body_norm=b["body_norm"],
            sha256=b["sha256"], name_proposal=b["name_proposal"],
            description=b["description"], heading_path=b["heading_path"],
            flags=b["flags"], src=b["src"],
            artifact_type=b["artifact_type"], lang_raw=b["lang_raw"],
            supersedes=b.get("supersedes"),
            superseded_count=b.get("superseded_count", 0),
            dialect=b["dialect"]))

    stats = {"fences_seen": fences_seen,
             "turns": max((t for _, t, _ in markers), default=0),
             "transcript_mode": transcript_mode,
             "by_lang": dict(by_lang),
             "by_artifact_type": dict(Counter(b.artifact_type for b in final))}

    # invariant (blueprint rule 2): nothing disappears silently
    if fences_seen != len(final) + len(skipped):
        raise AssertionError(
            f"extractor invariant broken: {fences_seen} fences != "
            f"{len(final)} blocks + {len(skipped)} skips")

    return ExtractResult(tuple(final), tuple(skipped), stats)
