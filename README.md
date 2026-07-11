# soloctl — Artifact Compiler backend (Work Package 1)

Local-first backend that imports chat transcripts, extracts reusable
artifacts, and (in later work packages) emits them into a filesystem
library with draft/approved/verified states. Single operator, no database,
no frontend, no network calls.

This cut (Work Package 1) delivers: package scaffolding, configuration
loading, filesystem library initialization, the canonical Transcript IR
with its renderer/parser, the importer protocol/registry, a Markdown
passthrough importer, and the stabilized extractor. It does **not** emit
compiled artifacts, run verification/approval, or parse ChatGPT/Claude
exports — those are later work packages.

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

## `soloctl init`

Creates the filesystem library layout. Safe to run repeatedly.

```bash
soloctl init --library ./library
```

Creates:

```
library/
├── transcripts/
├── artifacts/
│   ├── drafts/{scripts,prompts,runbooks}/
│   ├── approved/{scripts,prompts,runbooks}/
│   ├── revoked/
│   └── superseded/
├── collections/
├── verification/
└── events.jsonl
```

`--library` defaults to `./library` (or `library_root` from `soloctl.toml`
if present). All writes are constrained to the resolved library root —
resolving a path outside it raises `PathEscapesLibraryError`.

## `soloctl import`

Imports a markdown file (plain, or an already-canonical transcript) as a
canonical transcript under `library/transcripts/YYYY/MM/<slug>.md`.

```bash
soloctl import chat.md --library ./library
soloctl import chat.md --library ./library --title "Forge provisioning"
soloctl import chat.md --library ./library --dry-run
soloctl import chat.md --library ./library --adapter markdown-v1
```

- Plain markdown becomes one anonymous assistant turn.
- An existing canonical transcript is recognized and re-saved with its
  original `source`/`adapter`/`conversation_id` intact (passthrough).
- The rendered transcript is secret-scanned before anything is written; a
  match refuses the entire import (exit code 2), nothing is saved.
- `--dry-run` prints the proposed destination and turn count; it never
  writes.
- Filenames never collide silently: a second import with the same title
  gets `-2`, `-3`, ... appended.

## Canonical transcript format

```markdown
---
kind: transcript
schema: 1
source: markdown
adapter: markdown-v1
conversation_id: null
title: Example conversation
exported_at: null
turns: 2
---

<!-- turn 1 role=user -->
Create a backup script.

<!-- turn 2 role=assistant -->
```bash
echo backup
```
```

Front matter fields are always present in this order. `render_transcript`
(the one canonical renderer) and `parse_transcript` round-trip every
required `Transcript`/`Turn` field, with one documented normalization:
per-turn content is stripped of leading/trailing blank lines. Internal
content — including fenced code blocks — is preserved exactly.

## Running tests

```bash
python3 -m pytest tests/ -v
```

45 tests across configuration, library initialization, transcript
render/parse round-tripping, the markdown importer, and extractor
regression (converted from the original `selftest.py` bare-assert suite).
