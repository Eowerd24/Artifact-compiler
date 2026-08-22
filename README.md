# soloctl — Artifact Compiler backend (Work Packages 1-2)

Local-first backend that imports chat transcripts, extracts reusable
artifacts, and now stores minimal canonical script Artifact/Revision/Verification/Approval/Publication records with hash-addressed content. Single operator, no database,
no frontend, no network calls.

Work Package 1 delivered: package scaffolding, configuration loading,
filesystem library initialization, the canonical Transcript IR with its
renderer/parser, the importer protocol/registry, a Markdown passthrough
importer, and the stabilized extractor.

Work Package 2 adds: ChatGPT (`chatgpt-v1`) and Claude (`claude-v1`)
import adapters, conversation listing/selection (`--list`,
`--conversation`), and a `transcript.import` ledger event appended to
`library/events.jsonl` on every real import (success or secret refusal).

Still **not** implemented: the full emitter catalog, tags, collections, or rich review workflow. S2-1 provides only the minimal explicit create → approve → publish path needed by `ArtifactPort`.

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
├── canonical/artifact-compiler/  # authoritative S2-1 records + immutable content
├── events/artifact-compiler.jsonl
└── events.jsonl
```

`--library` defaults to `./library` (or `library_root` from `soloctl.toml`
if present). All writes are constrained to the resolved library root —
resolving a path outside it raises `PathEscapesLibraryError`.

## `soloctl import`

Imports a markdown file, ChatGPT export, or Claude export as a canonical
transcript under `library/transcripts/YYYY/MM/<slug>.md`.

```bash
soloctl import chat.md --library ./library
soloctl import chat.md --library ./library --title "Forge provisioning"
soloctl import chat.md --library ./library --dry-run
soloctl import chat.md --library ./library --adapter markdown-v1

# ChatGPT / Claude exports (a conversations.json file, a directory
# containing one, or a .zip archive containing one)
soloctl import export.zip --library ./library --list
soloctl import export.zip --library ./library --conversation "forge prov"
soloctl import export.zip --library ./library --conversation conv-abc123 --dry-run
```

- Plain markdown becomes one anonymous assistant turn.
- An existing canonical transcript is recognized and re-saved with its
  original `source`/`adapter`/`conversation_id` intact (passthrough).
- ChatGPT exports are tree-shaped (`mapping` + `current_node`): only the
  active conversation path is imported. Edited messages and regenerated
  responses on abandoned branches never appear.
- Claude exports are a flat `chat_messages` list: no branches to resolve.
- `--conversation <id-or-title>` selects one conversation out of an export
  containing several: exact id match, then exact title match, then an
  unambiguous case-insensitive title substring. A tie at any stage is
  rejected rather than guessed.
- `--list` prints every conversation found (id, turn count, exported-at,
  title) and exits without importing anything.
- The rendered transcript is secret-scanned before anything is written; a
  match refuses the entire import (exit code 2), nothing is saved.
- `--dry-run` prints the proposed destination and turn count; it never
  writes, and never appends a ledger event.
- Filenames never collide silently: a second import with the same title
  gets `-2`, `-3`, ... appended.
- Every real (non-dry-run) import attempt appends one `transcript.import`
  event to `library/events.jsonl` — `"result": "ok"` on success,
  `"result": "refused"` if a secret was found.

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

## UCC conformance

Uses the immutable **ucc-contracts v0.2.0** release baseline plus the additive S2-1 contract development pin **56e2efc6024d9de032350fa061d2ec9a6cedb9a8**. The exact D8 export set is vendored at
`third_party/ucc-contracts/` (schemas, lifecycle transition tables, ID/hash/path
primitives — no domain code). `tests/contracts/` asserts this repo's own
(de)serialization and validation matches the pinned contracts exactly;
bumping the vendored copy is deliberate and version-gated, never silent.
Every real import also dual-writes a `ucc.event` to `library/events/` alongside
the legacy `transcript.import` ledger event in `library/events.jsonl`.

## Standalone status and limitations

This remains a standalone-usable Artifact Compiler, now carrying the additive S2-1 owner-side record store and real in-process `ArtifactPort`. It is *not* the UCC product, a network service, or a cross-owner canonical writer.

- **Shared contracts:** release baseline `v0.2.0`; S2-1 development pin `56e2efc6024d9de032350fa061d2ec9a6cedb9a8` pending the deliberate `v0.3.0` release. The vendor is copied only from upstream, never hand-edited.
- **Entity IDs:** S2-1 Artifact mutations and events use real `art_`/`rev_`/`ver_`/`apr_`/`pub_` ULIDs. Legacy transcript-import events still use the documented operation subject until S2-5 completes the remaining D4 cutover.
- **Events are dual-written:** the legacy ledger *and* a schema-conformant `ucc.event`
  stream. Neither replaces the other yet.
- **`producer_sequence`** is per-producer, not globally ordered, and not race-safe under
  concurrent writers (matching the legacy ledgers).
- **Fenced paths:** direct-infrastructure and shell paths are retained for standalone use
  only, unreachable from any port (AST call-site tests). Not an integration surface.
- **Domain schemas:** `artifact`, `artifact-revision`, `verification`, and `approval` are now authored with fixtures; the remaining Stage 2 set stays queued in standards §17.
- **`ArtifactPort` is real for S2-1:** create/approve/publish/withdraw mutations are idempotent; reads return canonical records; eligibility fails closed on publication, verification, approval, entrypoint, and hash evidence.
- **Governance authority is record-based.** `drafts/approved/revoked/superseded` remain projection/export directories only.

## Running tests

```bash
python3 -m pytest tests/ -v
```

176 tests across configuration, library initialization, transcript
render/parse round-tripping, the markdown/ChatGPT/Claude importers, the
importer registry, and extractor regression (converted from the original
`selftest.py` bare-assert suite). Versioned fixtures live under
`tests/fixtures/{chatgpt,claude}/v1/`.
