# soloctl — Artifact Compiler backend (Work Packages 1-4, 5a)

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

Work Package 3 adds: a language-neutral extractor (`ArtifactCandidate`
model; Bash, Python, PowerShell, SQL, prompt, and Markdown runbook fence
labels), the emitter protocol and registry, full Bash and Python emitters,
and scaffolded PowerShell/SQL/prompt/runbook emitters.

Work Package 4 (items 1-3) adds: the compilation coordinator
(`soloctl/compiler/compile.py`) and `soloctl compile`, which turns a
canonical transcript into draft artifacts under
`artifacts/drafts/{scripts,prompts,runbooks}/`, with collision resolution
against the library and per-fence accounting.

Work Package 4 (items 4-5) adds: real verification plans for the
PowerShell, SQL, prompt and runbook emitters, language-specific risk flags
(PowerShell, SQL, Python), and tags and collections (`soloctl tag`,
`soloctl collection`).

Work Package 5a adds: the verification engine (`soloctl/verification/`)
and `soloctl verify`, which runs an artifact's verification plan and
records the result under `library/verification/`.

Still **not** implemented: a compile ledger/`ucc.event`, approval of drafts, manifest/index, or rich review workflow. S2-1 provides only the minimal explicit create → approve → publish path needed by `ArtifactPort`.

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pip install -e third_party/ucc-contracts   # vendored contracts; tests import it
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

## `soloctl compile`

Compiles one canonical transcript (the output of `soloctl import`) into
draft artifacts.

```bash
soloctl compile library/transcripts/2026/10/forge-provisioning.md --library ./library
soloctl compile library/transcripts/2026/10/forge-provisioning.md --library ./library --dry-run
soloctl compile library/transcripts/2026/10/forge-provisioning.md --library ./library --include-user  # also user-turn fences
```

- Pipeline: parse the canonical transcript → `extract()` every recognized
  language → `EmitterRegistry.assign()` (from `enabled_emitters`) → render
  every draft in memory → atomic writes (`library/atomic.py`). The draft
  directory comes from the artifact type: `script` → `scripts/`, `prompt`
  → `prompts/`, `runbook` → `runbooks/`.
- The whole transcript, then every fence, is secret-scanned (built-ins plus
  `library/scrub-patterns.toml`) before anything is written; a match
  refuses the entire compile (exit code 2), nothing is saved.
- Drafts never overwrite anything. If `drafts/<kind>/<name>` or
  `approved/<kind>/<name>` exists, the draft becomes `<name>-2`, `-3`, ...
  (Python: `_2`), and its header names the file it is actually in.
- Every fence is accounted for: `fences: N = drafts + skipped +
  unsupported`. A fence whose emitter is disabled in `soloctl.toml` shows
  as `unsupported-emitter`, not as missing.
- `--dry-run` prints the same plan (same names) and writes nothing.
- Drafts are written non-executable (mode `0600`).
- No ledger event is appended yet, in either mode (see `HANDOFF_NOTES.md`,
  WP4 open decision).
- No library-level dedup yet: there is no hash index until manifest/index
  lands, so compiling the same transcript twice writes `-2` drafts.

## `soloctl tag` and `soloctl collection`

Tag compiled artifacts and group them into ordered collections. Both work
on drafts and approved artifacts, and never change an artifact file.

```bash
soloctl tag add scripts/disk-audit.sh disk linux --library ./library
soloctl tag add artifacts/drafts/scripts/disk-audit.sh disk --library ./library   # the path compile prints works too
soloctl tag remove scripts/disk-audit.sh linux --library ./library
soloctl tag list --library ./library                          # every tag, with counts
soloctl tag list scripts/disk-audit.sh --library ./library    # one artifact's tags
soloctl tag list --tag disk --library ./library               # artifacts carrying a tag

soloctl collection create disk-kit --title "Disk triage" --description "..." --library ./library
soloctl collection add disk-kit scripts/disk-audit.sh runbooks/disk-full-runbook.md --library ./library
soloctl collection remove disk-kit scripts/disk-audit.sh --library ./library
soloctl collection show disk-kit --library ./library
soloctl collection list --library ./library
```

- An artifact is named `<kind>/<filename>` (`scripts/foo.sh`), the same
  name in `drafts/` and `approved/`. A path under either works too.
- Tags live in `library/tags.json`; each collection is
  `library/collections/<name>.json`. Both are deterministic JSON written
  atomically. A no-op (tag already there, member already in) writes
  nothing.
- Tag and collection names are lower-case slugs (`a-z`, `0-9`, `-`, up to
  48 characters). Anything else is refused with a suggested slug.
- Each reference also stores the artifact's `compiled:` header value. If a
  name is reused by a later compile (the old file was deleted), the old
  tags and memberships show as `STALE` and are never moved onto the new
  file; `tag add`/`collection add` refuse until you remove them. A file
  that's gone shows as `MISSING`; `remove` still cleans it up.
- A corrupt `tags.json` or collection file is refused and left as it is.
- No ledger event is written (same open decision as `compile`).

## `soloctl verify`

Runs an artifact's automatic verification plan (the checks its emitter
describes) and records the result. Works on drafts and approved artifacts,
and never changes the artifact file.

```bash
soloctl verify scripts/disk-audit.sh --library ./library
soloctl verify artifacts/drafts/prompts/summarize-audit.md --library ./library   # same forms as `tag`
soloctl verify scripts/largest-tables.sql --timeout 20 --library ./library        # seconds per external check
```

- Exit codes: `0` passed, `5` failed, `6` inconclusive, `1` refused
  (unknown or uncompiled artifact, uninitialized library, file changed
  mid-run). On a refusal nothing is recorded.
- Verdict (provisional policy): **failed** if any *required* check failed;
  **inconclusive** if nothing required failed but a pass can't be
  established (the plan is incomplete, or a required check's tool isn't
  installed, timed out, or couldn't run); **passed** only if the plan is
  complete and every required check passed. Advisory checks are recorded
  but never change the verdict.
- In-process checks (soloctl runs them itself): `python-ast-parse`,
  `sql-lexical` (a lexical scan, not a parse), the prompt front-matter/body/
  placeholder lint, and the runbook front-matter/title/fence-label lint.
- External tools (`bash`, `shellcheck`, `ruff`, `sqlfluff`, `pwsh`) are
  never soloctl dependencies. They run from an argv list (no shell) with
  stdin closed and a timeout, and the artifact's absolute path is the only
  thing substituted into the argv. Without `shellcheck`, Bash artifacts are
  inconclusive. PowerShell artifacts are always inconclusive: they have no
  required check.
- The result goes to `library/verification/<kind>/<filename>.json`
  (`soloctl.verification/1`, deterministic JSON, atomic write). Only the
  latest run is kept. It records the artifact's `compiled:` stamp and the
  sha256 of the bytes checked, so you can tell whether it still describes
  the file on disk.
- Automatic verification never implies manual verification, and `verify`
  approves nothing. The result file is not an S2-1 `ucc.verification`
  record and writes no ledger line or event.

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

## Compiler: extraction and emitters (library API, WP3)

`soloctl compile` wires these together (see above). Both stages are pure:
no file writes, no tool execution — the coordinator owns all file writes.

```python
from soloctl.compiler.extract import SUPPORTED_LANGUAGES, extract
from soloctl.config import load_config
from soloctl.emitters import EmitContext, registry_from_config

result = extract(canonical_transcript_text, source="t.md",
                 only=SUPPORTED_LANGUAGES, library_hashes=known_hashes)
registry = registry_from_config(load_config())
assignment = registry.assign(result.candidates)
ctx = EmitContext(source="chat:claude ...", compiled_at="2026-10-19T12:00:00Z",
                  tool_version="0.1.0")
for candidate, emitter in assignment.assigned:
    filename = emitter.propose_filename(candidate)   # pre-collision-resolution
    text = emitter.render(candidate, ctx)            # content only, not written
    plan = emitter.verification_plan(candidate)      # described, not executed
```

Fence label → language → artifact type → emitter:

| Fence labels | Language | Type | Emitter | File | Status |
|---|---|---|---|---|---|
| `bash` `sh` `shell` `zsh` | bash | script | `bash` | `.sh` | full |
| `python` `py` | python | script | `python` | `.py` (snake_case) | full |
| `powershell` `pwsh` `ps1` | powershell | script | `powershell` | `.ps1` | full (plan incomplete: needs pwsh) |
| `sql` `postgres` `postgresql` `mysql` `sqlite` `tsql` | sql (+dialect) | script | `sql` | `.sql` | full |
| `prompt` | prompt | prompt | `prompt` | `.md` | full |
| `markdown` `md` `runbook` | markdown | runbook | `runbook` | `.md` | full |

- `console`/`terminal`/`shell-session` and unlabeled fences are always
  skipped; user-turn fences are skipped unless `include_user=True`.
- `only` defaults to `{"bash"}` (WP1 behavior); pass `SUPPORTED_LANGUAGES`
  (or a subset of normalized language names) to extract more.
- Secret refusal covers every fence, including ones that are skipped.
- Supersession (last revision wins) only groups blocks of the same language.
- The registry requires exactly one enabled emitter per candidate: none →
  `unsupported-emitter` (an error from `resolve()`, a skip record from
  `assign()`); more than one → `EmitterConfigurationError`.
- `enabled_emitters` and `default_sql_dialect` in `soloctl.toml` configure
  the registry.
- Verification plans are data (nothing runs until WP5). `complete=True`
  needs at least one required check soloctl runs itself; external tools
  soloctl doesn't depend on are advisory (`required=False`):

  | Emitter | Required | Advisory | `complete` |
  |---|---|---|---|
  | bash | `bash -n`, `shellcheck` | — | yes |
  | python | `ast` parse (in-process) | `ruff` | yes |
  | powershell | — | `pwsh-parse`, `psscriptanalyzer` (pwsh 7.4+) | **no** |
  | sql | `sql-lexical` (in-process, not a parse) | `sqlfluff parse --dialect …` | yes |
  | prompt | front matter, non-blank body, placeholders (in-process) | — | yes |
  | runbook | front matter, title, labeled fences (markdown-it) | — | yes |

  An incomplete plan means "cannot auto-verify", never an implicit pass.
- Risk flags (annotation only, never blocking): the Bash table applies to
  every language; PowerShell adds `remove-recurse-force`,
  `execution-policy`, `invoke-expression`, `download-execute`,
  `run-as-admin`; SQL adds `drop`, `truncate`, `delete-no-where`,
  `update-no-where`, `grant-all`; Python adds `os-system`, `shell-true`,
  `eval-exec`, `rmtree`.
- PowerShell: a body shebang moves to line 1; `#Requires` lines stay put
  and are listed in the plan notes. Prompt front matter lists template
  placeholders (`{name}`, `{{ name }}`) as `placeholders: [...]`.

## UCC conformance

Uses the **ucc-contracts v0.3.0** contracts release. The exact D8 export set is vendored at
`third_party/ucc-contracts/` (schemas, lifecycle transition tables, ID/hash/path
primitives — no domain code). `tests/contracts/` asserts this repo's own
(de)serialization and validation matches the pinned contracts exactly;
bumping the vendored copy is deliberate and version-gated, never silent.
Every real import also dual-writes a `ucc.event` to `library/events/` alongside
the legacy `transcript.import` ledger event in `library/events.jsonl`.

## Standalone status and limitations

This remains a standalone-usable Artifact Compiler, now carrying the additive S2-1 owner-side record store and real in-process `ArtifactPort`. It is *not* the UCC product, a network service, or a cross-owner canonical writer.

- **Shared contracts:** `ucc-contracts v0.3.0`. The vendor is copied only from upstream, never hand-edited.
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

695 tests across configuration, library initialization, transcript
render/parse round-tripping, the markdown/ChatGPT/Claude importers, the
importer registry, extractor regression (converted from the original
`selftest.py` bare-assert suite, extended for multi-language extraction),
the emitters and emitter registry, compilation, tags and collections,
the verification engine, and the UCC contracts/ports. Versioned fixtures live under
`tests/fixtures/{chatgpt,claude}/v1/`.
