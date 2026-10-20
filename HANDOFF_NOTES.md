# Work Packages 1-2 — Handoff Notes

## What was reused from the supplied prototypes

- **`extract.py`** — moved into `soloctl/compiler/extract.py` essentially
  unchanged. Same dataclasses (`SourceRef`, `Block`, `SkipRecord`,
  `ExtractResult`), same pipeline, same behaviors: whole-input secret
  refusal, within-document supersession (last wins, difflib ≥ 0.70 or name
  match), exact-hash dedup via injected `library_hashes`, risk-flag
  annotation, deterministic naming fallback (heading → comment → `block-NN`),
  and the `fences_seen == blocks + skipped` invariant, self-checked at the
  end of `extract()`.
- **`selftest.py`** — every `test_*` function converted 1:1 into pytest
  assertions in `tests/test_extractor.py` (plus one added invariant check
  for a mixed-language document). No behavior was weakened to make the port
  pass.
- **Fixtures** — `paste-simple.md`, `paste-secret.md`, `transcript-forge.md`
  copied verbatim into `tests/fixtures/`.
- **`ledger.py`** — kept the scrub-pattern loading, the kv-secret
  literal-vs-reference heuristic, and redaction helpers (`scrub_text`,
  `scrub_obj`). These now live in `soloctl/ledger.py` and are shared by both
  the extractor (per-fence scan) and the new import command (whole-rendered-
  transcript scan) — previously the kv-literal check was duplicated inline
  in `extract.py`; it's now one function (`scan_text_for_secret`).
- **`cli.py`** — the dry-run presentation concept (proposed name/path,
  turn/stat summary, colored refusal message, distinct exit codes) carried
  over, but the architecture didn't: WP1's `cli.py` separates Typer command
  functions (thin) from service functions (`perform_init`, `perform_import`)
  that return dataclasses (`InitResult`, `ImportOutcome`) instead of
  printing.

## What was changed

- **Extractor's `_scan_secrets`** was renamed/moved to
  `ledger.scan_text_for_secret` so it's reusable outside fenced-block
  context (the import command scans the whole rendered transcript, not
  per-fence).
- **Import secret-scan line numbers** are offsets into the *rendered*
  canonical transcript (front matter shifts everything), not the original
  source file. `SecretDetected.path` says `"rendered transcript of
  <path>"` rather than implying a false-precision match against the
  source file's own lines — worth knowing if this surfaces in scripts that
  parse the error text.
- **Transcript front matter** is hand-rolled YAML (no PyYAML dependency):
  bare scalars when safe, JSON-quoted (valid YAML) when a value contains a
  colon, is empty, or collides with a reserved word (`null`, `true`, ...).
  This was a deliberate call to avoid adding a dependency for a fixed, flat,
  7-key front matter block; if front matter ever needs lists/nesting
  (tags, collections), reconsider and pull in a real YAML library then.
- **`--adapter` matches `Importer.version`** (e.g. `markdown-v1`), not
  `Importer.name` (`markdown`). The task's `Importer` protocol has both
  fields; the blueprint's CLI examples (`--adapter chatgpt-v1`) only make
  sense against the versioned string, so that's the lookup key in
  `ImporterRegistry`.

## What was found in `soloctl-0.1.0.tar.gz`

Diffed byte-for-byte against the uploaded `extract.py`/`cli.py`/
`selftest.py` — **identical**, so the archive added no new behavior over
the loose files. It did add three things not otherwise supplied:
`pyproject.toml` (pinned `typer>=0.12`, `markdown-it-py>=3.0`), the vendored
`ledger.py` (scrub patterns *and* a full ULID-based JSONL audit-event writer
— `Ledger` class, monotonic ULIDs, `lib.*` event envelope), and the test
fixtures. The `Ledger`/ULID/event-writer machinery was **not** carried
into WP1 — that's Phase 20 (ledger & auditability) work, not this package.
Only the scrub-policy half of the vendored module survived.

## Known limitations after WP1 (resolved or superseded by WP2 — kept for history)

- ~~Only `markdown-v1` is registered~~ — resolved, see WP2 section below.
- ~~`events.jsonl` is created empty by `init`; nothing appends to it~~ —
  resolved for `transcript.import`, see WP2 section below.
- The extractor still only recognizes Bash-family fences (`bash`, `sh`,
  `shell`, `zsh`); the language-neutral `ArtifactCandidate` model and the
  other five emitters are not implemented. Still true after WP2 — untouched
  by design (see below).
- No compilation: `extract()` is wired up and tested, but nothing calls it
  from the CLI yet, and no artifacts are ever written to `artifacts/drafts/`.
- No manifest.json / index.json generation (explicitly deferred).
- No approval, verification, tags, or collections.
- Filename-collision resolution (`slug.md`, `slug-2.md`, ...) has a
  TOCTOU race between checking and writing — acceptable for a single-
  operator local tool, not safe for concurrent writers.
- `soloctl.toml`'s `enabled_emitters`/`enabled_validators`/
  `default_sql_dialect` fields are parsed and validated but unused until
  the emitter and verification work packages exist.

---

# Work Package 2 — ChatGPT/Claude adapters, selection UX, import ledger event

## What was added

- **`soloctl/importers/chatgpt.py`** (`chatgpt-v1`) — walks the `mapping`
  tree backward from `current_node` to the root and reverses it. That walk
  *is* the entire "only the active branch" policy — there is no separate
  check anywhere for "is this a regenerated/edited-away message?". Content
  type `"text"` is fully supported (`parts` joined with blank lines);
  anything else (`image_asset_pointer`, missing `content`, missing `parts`)
  is recorded non-fatally as `turn.metadata["unsupported_content_type"]` or
  `["missing_content"]`, never dropped silently and never a hard failure.
  A missing `mapping`, a missing `current_node` key, a `current_node`
  pointing at a node absent from `mapping`, or a cycle in the parent chain
  all raise `ImporterSchemaError` naming the conversation and the offending
  key.
- **`soloctl/importers/claude.py`** (`claude-v1`) — maps the flat
  `chat_messages` list directly to `Turn`s in order (no tree, no branch
  logic needed). `sender: "human"|"assistant"` maps to canonical
  `user`/`assistant`; anything else maps to `"unknown"` (non-fatal, matches
  ChatGPT's unknown-role handling). `attachments`/`files`/`artifacts` on a
  message, if present and non-empty, are copied verbatim into
  `turn.metadata` — referenced, never read from disk or fetched.
- **`soloctl/importers/_json_export.py`** — new shared module, not
  anticipated as its own file in the required structure but justified by
  DRY: both adapters need to (a) load a JSON array of conversations from a
  bare file / directory / zip archive, and (b) resolve `--conversation
  <id-or-title>` (exact id → exact title → unambiguous substring → reject).
  Neither function knows either adapter's conversation schema — it only
  takes a filename and a set of required top-level keys — so this doesn't
  create the kind of cross-adapter coupling the "adapters only parse their
  own format" rule is meant to prevent.
- **`ledger.append_event()` / `ledger.now_iso()`** — a deliberately small
  JSONL appender (`os.O_APPEND`, one `write()` call), *not* the vendored
  0.1.0 `Ledger` class (ULID ids, actor/action/target schema). WP2 only
  needed one event type (`transcript.import`); the fuller schema from the
  archive is still deferred to the ledger-and-auditability work package,
  where the richer field set (command invocation id, before/after state,
  event types for compile/approve/verify/revoke/tag/collection) actually
  gets used. `perform_import` in `cli.py` appends one event per real
  (non-dry-run) import attempt: `"result": "ok"` on success, `"result":
  "refused"` if the secret scan aborted it. Dry runs never append — they
  don't change state, so there's nothing to audit.
- **CLI**: `soloctl import <path> --list` prints every conversation found
  (delegates to the new `perform_list` service function) and exits without
  importing; `--conversation <id-or-title>` (alias `--conv`) is threaded
  through to `Importer.parse()`.
- **Fixtures**: `tests/fixtures/chatgpt/v1/` (9 files: simple, regenerated
  response, edited message, tool calls, missing `current_node`, missing
  message content, unknown content type, duplicate titles, empty
  conversation, plus a malformed-not-a-list case) and
  `tests/fixtures/claude/v1/` (7 files: basic, with-artifacts,
  with-attachments, missing timestamps, unknown sender, empty content,
  multiple conversations, plus a malformed-not-a-list case) — matching the
  roadmap's Phase 4/5 fixture lists.

## What was verified, not just asserted

- `test_extractor.py::test_extractor_contains_no_importer_specific_logic`
  reads `compiler/extract.py`'s own source and asserts it contains none of
  `chatgpt`, `claude`, `mapping`, `current_node`, `chat_messages` — an
  automated, permanent check of the "extractor/compiler contain no
  source-specific logic" completion criterion, not just a claim in prose.
- `test_chatgpt_importer.py`/`test_claude_importer.py` each include a
  round-trip test: parse a fixture, `render_transcript()` it, `parse_
  transcript()` it back, and assert the content matches — proving both
  adapters flow through the *same* canonical renderer/parser the markdown
  importer uses, rather than a parallel code path.
- Manually smoke-tested end-to-end: `soloctl import --list` against a
  duplicate-title export, `--conversation <id>` disambiguation, a real
  (non-dry-run) import, and confirmed the resulting `events.jsonl` line and
  the written canonical transcript by hand (see commands-run summary).

## Known limitations / assumptions (WP2 scope)

- Claude's `attachments`/`files`/`artifacts` message shape is **inferred**
  from `IMPORTER_BLUEPRINT.md`'s one-line description ("noted in meta,
  content not fetched"), not captured from a real Claude data export. If a
  real export's field names or nesting differ, only `claude.py` and its
  fixtures should need to change — the Transcript IR and everything
  downstream is unaffected either way.
- ChatGPT `content_type` handling covers `"text"` fully; other real-world
  content types (`multimodal_text`, `code`, tether-browsing quotes, etc.)
  all fall into the generic `unsupported_content_type` metadata bucket
  rather than being individually modeled. Revisit if compiling from
  image/tool-heavy conversations turns out to matter.
- `--conversation` selection is case-insensitive for substring matching but
  case-sensitive for exact-title matching (mirrors "exact title" meaning
  exactly, not "exact modulo case"). Worth confirming this matches
  operator expectations once used against real exports.
- No `--since` filtering or bulk import — explicitly out of scope per
  `IMPORTER_BLUEPRINT.md` §9, unchanged from WP1.
- The `transcript.import` ledger event schema (flat dict: schema, event,
  ts, result, detail, source_path, adapter, conversation_id, turns,
  dry_run) is intentionally minimal and specific to this one event type —
  it is not yet the general envelope Phase 20 describes (no command
  invocation id, no before/after state). Don't extend it ad hoc for a new
  event type in WP3; design the general envelope once, in the ledger work
  package.

## Next steps for Work Package 3

1. Generalize `compiler/extract.py` per `ARTIFACT_COMPILER_ROADMAP.md`
   Phase 6: introduce the language-neutral `ArtifactCandidate` model,
   recognize `python`/`powershell`/`sql`/`prompt`/`runbook` fence labels
   alongside the existing Bash family, and keep the
   `fences_seen == candidates + skips` invariant intact. The new
   architectural-boundary test
   (`test_extractor_contains_no_importer_specific_logic`) should keep
   passing unchanged — Phase 6 work never needs importer knowledge.
2. Add the emitter protocol/registry (`ArtifactEmitter` per
   `COMPILER_PLAN.md`/roadmap Phase 7) with Bash and Python emitters
   first; remaining four scaffolded with tests, per the Third Work
   Package scope.
3. Do not wire compilation into the CLI yet, and do not write to
   `artifacts/drafts/` — that's the compilation coordinator, Phase 14 /
   Fourth Work Package, later than emitters.
4. When the ledger-and-auditability work package is eventually scoped,
   replace `ledger.append_event`'s ad hoc dict shape with the general
   envelope (command invocation id, previous/new state, hashes) and adapt
   the one existing call site in `cli.perform_import` — don't let a new
   event type reintroduce a second, differently-shaped envelope.

---

# Work Package 3 — generalized extractor, candidate model, emitter framework

Built on `main` at `46b1e96` (WP1/WP2 plus the merged S2-1/Stage-2 UCC
work), not on the older `claude/artifact-compiler-wp1-yrb05f` branch — the
operator chose `main` so WP3 doesn't fork away from the UCC changes. Nothing
in WP3 touches ports, fences, events, or `third_party/`; it's in-process
compiler code only, so AGENTS.md's Stage-2 guardrails aren't engaged.

## What was added

- **`soloctl/compiler/models.py`** — the data model moved out of
  `extract.py`. `ArtifactCandidate` keeps every `Block` field (same names,
  types, meanings) and adds `artifact_type` (`script|prompt|runbook`),
  `lang_raw` (the fence label as written, e.g. `pwsh`), and `dialect` (SQL
  dialect from the label, else `None`). `Block` is an alias of
  `ArtifactCandidate`, the same class rather than a subclass, so
  `from soloctl.compiler.extract import Block` and `r.blocks` keep working.
  `ExtractResult.candidates` is a property that returns the same tuple as
  `blocks`.
- **`soloctl/compiler/classify.py`** — one static label table
  (`LABELS`) mapping label → `LabelClass(language, artifact_type, dialect)`,
  plus `CONSOLE_LABELS` and `SUPPORTED_LANGUAGES`. This is the whole
  "language label vs artifact type" policy; the emitter is *not* stored
  on the candidate. The registry resolves it, so the extractor stays
  ignorant of which emitters exist or are enabled.
- **`soloctl/compiler/extract.py`** — now classifies via the table; the
  pipeline, ordering, hashing, naming, description harvesting, risk
  flagging, and invariant self-check are otherwise unchanged.
- **`soloctl/emitters/`** — `base.py` (the `ArtifactEmitter` protocol,
  `EmitContext`, `VerificationCheck`, `VerificationPlan`, shared header/
  front-matter helpers), `registry.py` (`EmitterRegistry`,
  `default_registry`, `registry_from_config`), full `bash.py` and
  `python.py`, scaffolded `powershell.py`, `sql.py`, `prompt.py`,
  `runbook.py`.
- **`soloctl/errors.py`** — `CompilerError` → `UnknownLanguageError`;
  `EmitterError` → `UnsupportedEmitterError` (carries
  `reason = "unsupported-emitter"`) and `EmitterConfigurationError`.
- **Tests** — `tests/test_extractor.py` extended (+44 tests, 200 lines
  added, 0 removed or modified), new `tests/test_emitters.py` (46),
  `tests/test_emitter_registry.py` (23), new fixture
  `tests/fixtures/transcript-polyglot.md` (one fence per supported language
  plus console/unlabeled/yaml/user-turn fences). Suite: 263 → 376.

## Decisions made where the docs were silent or in tension

- **Governing docs.** `ARTIFACT_COMPILER_ROADMAP.md`, `COMPILER_PLAN.md`,
  and `EXTRACTOR_BLUEPRINT.md` are not in the repo root; the operator's
  handoff bundle (`artifact_compiler_handoff/`, untracked) has them. None
  of them defines "Phase 6/7", `ArtifactCandidate`, or the
  `ArtifactEmitter` method list; the roadmap's WP3 entry is five bullets.
  The WP3 prompt (source-of-truth #1) supplied the method names and label
  sets; `COMPILER_PLAN.md` §2 supplied the script header template and D3
  supplied "YAML front matter for `.md` artifacts". Everything else below is
  a judgment call, recorded so WP4 can revisit it.
- **`only` still defaults to `{"bash"}`.** `test_paste_simple` asserts that
  a `python` fence is skipped `non-target-lang` with no `only` argument, and
  WP3 must not weaken existing assertions. So every language is recognized
  and classified, but a caller opts in with `only=SUPPORTED_LANGUAGES` (or a
  subset). The WP4 coordinator should derive `only` from the enabled
  emitters, not rely on the default.
- **`only` must name normalized languages** (`bash python powershell sql
  prompt markdown`); anything else raises `UnknownLanguageError`. This is a
  deliberate narrowing: before WP3, `only={"json"}` would have extracted
  JSON fences as `lang="json"` blocks. That path was untested and has no
  artifact type or emitter, so it now fails clearly instead of producing
  candidates nothing can emit. Emitter names (`runbook`) and raw labels
  (`pwsh`) are the likely mistakes, and the error lists the valid names.
- **Supersession only groups within one language.** Previously moot
  (bash only). Now a Bash and a PowerShell block under the same heading
  would share a `name_proposal` and collapse into one "revision". They
  don't anymore. Exact-content hashing stays content-only (the `sha256`
  semantics are unchanged, so existing library hashes stay valid), which
  means two identical bodies in different languages share a hash. See
  limitations.
- **Comment-name fallback is per language.** `#` for bash, python,
  powershell, and markdown (a runbook's `# Title` is the name you want),
  `--` for SQL, none for prompts (a leading `#` in a prompt is prompt text).
  Bash behavior is byte-identical.
- **Skip details.** `non-target-lang` skips now carry `detail="unrecognized
  label"` or `"<language> not selected"`. The reason codes are unchanged.
  `unsupported-emitter` is a new reason, produced only by
  `EmitterRegistry.assign()`, never by the extractor.
- **`executable()` is a method**, answered per candidate: bash and python
  return True; powershell, sql, prompt, and runbook return False. It means
  "should be executable once approved"; drafts are never written `+x`
  (COMPILER_PLAN S3).
- **Python filenames use underscores** (`disk_audit.py`), so a compiled
  script is also importable. Other emitters keep the hyphenated slug.
- **Verification plans are data.** External checks carry an argv tuple
  (never a shell string), with the `ARTIFACT_PATH` (`"{artifact}"`) token
  where the path goes. Bash: `bash -n` and `shellcheck --severity=warning`,
  both required. Python: in-process `ast` parse (required) and
  `ruff check --select E9,F63,F7,F82` (advisory, because ruff isn't a
  soloctl dependency). Scaffolds return `checks=()` with `complete=False`,
  and the verifier must read that as "cannot auto-verify", never as a pass.
- **Every artifact gets a `verify-with` placeholder**, `.md` front matter
  included, so the COMPILER_PLAN "approve refuses while verify-with is the
  placeholder" gate works uniformly across types.

## What was verified, not just asserted

- **Mutation-checked**: each guarantee was deliberately broken and the
  suite confirmed to fail, then restored:
  1. an emitter importing `subprocess`
  2. an emitter calling `open()`
  3. supersession crossing languages
  4. the registry picking the first of several matches
  5. the secret scan skipping non-bash fences
  6. a newline in a header value injecting a header line
  7. a scaffold plan claiming `complete=True`

  All 7 were caught.
- **Emitter purity is AST-checked**, per AGENTS.md §1.4's "AST, not
  substring" rule. `test_emitter_modules_do_no_io_and_run_nothing` walks
  every module in `soloctl/emitters/` and fails on imports of
  `os/subprocess/shutil/pathlib/datetime/time/tempfile/socket/urllib/http`
  or on calls such as `open`/`exec`/`eval`/`write_text`/`chmod`/`now`.
- **The architectural boundary check was extended, not edited.**
  `test_extractor_contains_no_importer_specific_logic` is untouched, and a
  sibling test applies the same forbidden-word check to `classify.py` and
  `models.py`.
- **End to end at the library level**, the polyglot fixture runs through
  extract → `registry_from_config(load_config())` → `assign()` and gets 6/6
  candidates assigned under the default config. With 3 emitters enabled,
  `fences_seen == assigned + unsupported + skipped` holds.
- **The rendered Python output is `ast.parse`d** in tests, including a body
  that starts with `from __future__ import annotations`, so the header can't
  break the future-import rule.
- **README's API sample was executed** against the polyglot fixture and
  printed all six proposed filenames.
- **Full suite run in an independent fresh clone** of the pushed branch
  (AGENTS.md §2), not only in the working copy.

## Known limitations / assumptions (WP3 scope)

- **Same-body, different-language dedup**: `sha256` hashes content only, so
  an `echo hello` fenced as `bash` and as `powershell` share a hash, and
  `library_hashes` dedup would skip the second. This is harmless in
  practice and was kept for hash stability. If WP4 needs per-type dedup,
  key the library index on `(artifact_type, sha256)` rather than changing
  the hash.
- **Risk patterns are still the Bash-centric table**, applied to every
  language (annotation only, never blocking). PowerShell (`Remove-Item
  -Recurse -Force`, `Set-ExecutionPolicy`), SQL (`DROP`, `TRUNCATE`,
  `DELETE` without `WHERE`), and Python (`os.system`, `subprocess` with
  `shell=True`) have no specific patterns yet.
- **`markdown`/`md` fences always classify as runbooks.** Chat assistants
  also use them for README drafts, sample docs, and similar, so expect some
  false-positive runbook candidates. Classification is a static table by
  design (no content sniffing); a narrower label policy, e.g. only
  `runbook`, is a one-line change in `LABELS` if this proves noisy.
- **A ```` ```markdown ```` fence containing its own triple-backtick
  fences** is split by the CommonMark parser at the first inner fence. The
  standard workaround (4-backtick or `~~~` outer fences) works. This is a
  parser property, not something the extractor can fix.
- **Bash rendering imposes `set -euo pipefail` / `IFS=$'\n\t'`**, per the
  COMPILER_PLAN template, on bodies that weren't written for strict mode.
  Verification (WP5) is where a body that breaks under it should surface.
- **Scaffolded renders are real but minimal.** PowerShell has no
  `#Requires`/shebang handling. SQL has no statement splitting. Prompt has
  no variable/placeholder extraction. Runbook has no embedded-fence
  awareness.
- **`EmitContext` is caller-supplied** (source, timestamp, version), so
  rendering is deterministic, but nothing yet validates that `compiled_at`
  is ISO-8601.
- **Setup gap on `main` (pre-existing, not WP3)**: `pyproject.toml` doesn't
  declare the vendored `ucc-contracts`, so `pip install -e ".[dev]"` alone
  leaves 6 test modules failing to collect with `ModuleNotFoundError`. The
  README now documents `pip install -e third_party/ucc-contracts`. I didn't
  add it to `pyproject.toml`, since how the vendored dependency is declared
  is a UCC packaging decision (AGENTS.md §1.5).

## Next steps for Work Package 4

1. **Compilation coordinator** (`compiler/compile.py` + thin `soloctl
   compile`): parse the canonical transcript → `extract(only=<languages of
   enabled emitters>, library_hashes=<from library>)` →
   `registry.assign()` → render → **atomic draft writes** under
   `artifacts/drafts/{scripts,prompts,runbooks}/` via
   `library/atomic.py`. Map `artifact_type` to the directory there, not in
   emitters. Secret refusal must still precede any write, and dry-run must
   still write nothing and append no event (AGENTS.md §3 invariant).
2. **Collision resolution** against the library (`slug.sh`, `slug-2.sh`,
   ...) in the coordinator, using `propose_filename()` as the starting
   point. Emitters stay unaware of library state.
3. **Fence accounting in compile output**: report
   `fences_seen == written + skipped + unsupported`, the same nothing-
   disappears rule extended through emission.
4. **Finish the four scaffolded emitters**: real verification plans
   (`complete=True`), language-specific risk patterns, and the render
   refinements listed above.
5. **Tags and collections** (roadmap WP4).
6. Decide whether `compile` emits a `lib.compile` ledger event now or waits
   for the general envelope. HANDOFF WP2 says not to add an ad-hoc,
   differently-shaped event, and AGENTS.md requires dual-writing a
   `ucc.event`. Resolve that before writing any compile event.
7. Out of scope until WP5: executing `VerificationPlan`s,
   approval/manual verification, and manifest/index.

---

# Work Package 4 (items 1-3) — compilation coordinator, collisions, accounting

Built on `main` at `28219e4` (WP3 merged). Covers WP3's "Next steps for
Work Package 4" items 1-3. Items 4-5 (finishing the scaffolded emitters,
tags/collections) are not started. Item 6 (compile event) is deliberately
deferred: see the open decision below.

## What was added

- **`soloctl/compiler/compile.py`**: `compile_transcript(config, path, *,
  dry_run, registry, library_hashes, include_user, compiled_at)` returns a
  `CompileOutcome` (`drafts`, `skipped`, `unsupported`, `fences_seen`,
  `accounting`). Each `DraftOutcome` carries the resolved candidate, the
  emitter name, the absolute and library-relative path, the emitter's
  original `proposed_filename`, and `written`. The pipeline:
  1. whole-text secret scan;
  2. parse the canonical transcript (`parse_transcript`; non-canonical
     input raises `TranscriptParseError`), then
     `extract(only=SUPPORTED_LANGUAGES, ...)`, which scans every fence
     again;
  3. `registry.assign()`;
  4. resolve names and render **every** draft in memory;
  5. accounting self-check;
  6. write (skipped entirely on dry run).
  `KIND_DIRS` maps `artifact_type` → `scripts|prompts|runbooks`, here and
  not in the emitters.
- **`soloctl compile <transcript> [--dry-run] [--include-user]
  [--library]`** in `cli.py`: thin, renders the outcome. Exit `2` on a
  secret, `1` on any other `SoloctlError` (uninitialized library, parse
  error, emitter configuration error).
- **`tests/test_compile.py`** (46 tests): coordinator, collisions,
  accounting, the dry-run/secret/no-event invariants, the contract-free
  boundary, and the CLI. Suite: 376 → 422.

## Decisions made where the docs were silent or in tension

- **`only=SUPPORTED_LANGUAGES`, not "languages of the enabled emitters".**
  WP3's notes suggested deriving `only` from the enabled emitters. I didn't,
  because a fence whose emitter is disabled would then show up as
  `non-target-lang` ("python not selected"), which hides the cause.
  Extracting everything and letting `registry.assign()` decide puts those
  fences in the `unsupported` bucket as `unsupported-emitter` ("enable it
  in `enabled_emitters`"). It also avoids a hand-kept emitter → language
  table, since emitters only expose `supports()`. Without this, the
  `unsupported` term in the accounting would always be zero with the
  built-in emitters.
- **Collision resolution goes through the emitter, not around it.** On a
  collision the coordinator hands the emitter
  `replace(candidate, name_proposal=f"{name}-{n}")` and asks again. So the
  emitter keeps its naming rules (Python gives `disk_audit_2.py`), and the
  header's `name:` line always matches the file it is in. Emitters still
  know nothing about library state.
- **A name is "taken" if it exists in `drafts/<kind>/` or
  `approved/<kind>/`, or was claimed earlier in the same run.** Names are
  per kind directory: a prompt and a runbook may both be `foo.md`.
  `revoked/` and `superseded/` are flat and not consulted, since nothing
  writes there yet. Revisit when approval/revocation lands.
- **TOCTOU is handled, not just documented.** Writes use
  `atomic_write_text(..., exist_ok=False)`. If a file appears between
  planning and writing, the coordinator moves to the next free suffix and
  re-renders, so another writer's file is never clobbered. Suffixes are
  capped at `MAX_COLLISION_SUFFIX = 1000`; past that it refuses
  (`LibraryError`) instead of spinning.
- **Whole-text secret scan before extraction.** The extractor already
  refuses on any fence. The coordinator also scans the whole transcript
  (prose included), like `import` does: D4 is whole-input abort, and
  descriptions harvested from prose end up in draft headers. It uses the
  same `library/scrub-patterns.toml` that `import` uses. The scan runs
  before parsing, because `TranscriptParseError` messages quote the
  offending front-matter line, and that line could hold the secret.
- **Render everything, then write.** An emitter error, a secret, an
  accounting mismatch, or collision exhaustion all leave `artifacts/`
  byte-identical. A mid-batch I/O failure (disk full) can still leave the
  earlier drafts in place; they're complete files, never partial, thanks
  to the atomic writes.
- **Source strings.** `SourceRef.path` (and the refusal location) is the
  transcript path relative to the library root when the transcript is
  inside the library, otherwise the path as given. The header's
  `source:` is `<transcript.source> [<exported_at>] "<title>"`.
- **Uninitialized library refuses** (`LibraryError`, "run soloctl init")
  instead of creating `artifacts/drafts/` on the fly. That holds for dry
  run too.

## Invariants and how they're enforced

- **Secret refusal before any write**: parametrized over assistant fence,
  user-turn fence, prose, and unsupported (`yaml`) fence × real/dry. Each
  asserts the library tree is byte-identical afterwards. A secret in
  malformed front matter is refused before the parser can quote it.
- **Dry run writes nothing and appends no event**: whole-tree snapshot
  before/after. Dry and real runs propose identical paths.
- **No compile event in either mode**: `events.jsonl` unchanged and
  `events/artifact-compiler.jsonl` not created after a real compile.
- **Contract-free core**: an AST check that `compile.py` imports neither
  `ucc_contracts` nor any edge module (`ucc_events`, `artifact_store`,
  `artifact_port`, `idempotency_store`, `idempotent_import`), plus a
  subprocess check that importing `soloctl.compiler.compile` loads none of
  them transitively. `cli.py` is the edge and still imports `ucc_events`
  for `import`; that's fine.
- **Mutation-checked**: each of these was deliberately broken and the
  suite confirmed to fail, then restored:
  1. dropping the whole-text scan
  2. a dry run that writes
  3. not checking `approved/`
  4. `exist_ok=True`
  5. dropping the accounting check
  6. importing `ucc_events` from `compile.py`
  7. not tracking intra-run claims
  8. no race retry
  9. falling back to the extractor's default `only`

  All 9 were caught.

## Open decision: compile ledger event (WP3 next-step 6) — still open

`compile` appends **no** event, on purpose. Writing one now forces one of
two bad options:
- an ad-hoc `lib.compile` legacy-ledger line, which HANDOFF WP2 says not to
  add before the general envelope exists;
- or a legacy line *plus* a `ucc.event` dual-write (AGENTS.md §1 event
  conventions), which couples this path to `ucc_events`/`ucc_contracts`
  while the event contract is still moving.

So the core pipeline stays contract-free and silent for now. To resolve it,
someone has to decide:
1. Does compile get audited before the Phase 20 general ledger envelope,
   or only after?
2. If before, what is the `ucc.event` type and subject? Compile creates
   drafts, which are not S2-1 Artifact records, so there is no real
   `art_`/`rev_` ID to use, and fail-closed forbids inventing one. The
   subject would have to be an operation placeholder like the
   transcript-import one.
3. Should a real (non-dry) secret refusal during compile be audited, as it
   is for import (AGENTS.md §3)? Today it isn't, because there's no event
   at all.

When it's decided, the event call belongs in the CLI/edge layer, or in an
injected callback, not in `compile.py`, so the core stays contract-free.
Dry run must keep appending nothing.

## Known limitations (WP4 items 1-3 scope)

- **No library-level dedup.** No hash index exists until manifest/index
  (WP5). `compile_transcript` accepts `library_hashes` (it's passed to
  `extract()`), but the CLI passes an empty set. Compiling the same
  transcript twice therefore writes `-2` drafts. It never overwrites, but
  it does duplicate. Recovering hashes from rendered drafts would mean
  stripping emitter-specific headers and preambles, which is fragile, and
  embedding a hash line would change every emitter's output. Either belongs
  with the manifest work. Per WP3's limitation, key the index on
  `(artifact_type, sha256)`.
- **Drafts are `0600`**, inherited from `tempfile.mkstemp` in
  `library/atomic.py`, the same as transcripts. They're never executable,
  as COMPILER_PLAN S3 requires. Approval decides the final mode.
- **No `--only`/per-emitter CLI selection**; use `enabled_emitters` in
  `soloctl.toml`. No `--all-revisions` either. The coordinator still
  handles intra-run name clashes, so adding it later is safe.
- **Concurrency**: TOCTOU-safe per file, but two concurrent compiles of the
  same transcript simply produce interleaved suffixes. Single-operator
  tool; no locking.

## Next steps

1. Resolve the open decision above, then wire the compile event at the
   edge (real runs only; refusals per the decision).
2. WP3 next-steps 4-5 are unchanged: finish the scaffolded emitters (real
   verification plans, language risk patterns), then tags/collections.
3. WP5: manifest/index, which gives library-level dedup and the
   `library_hashes` source; verification execution; approval of drafts
   (and its `revoked/`/`superseded/` collision namespace).

---

# Work Package 4 (items 4-5) — finished emitters, risk patterns, tags and collections

Built on `main` at `1e8ba10` (WP4 items 1-3 merged). Covers WP3's "Next
steps for Work Package 4" items 4 and 5. Item 6 (compile event) is still the
open decision recorded above; nothing here appends an event. Baseline 422
passed; now 583.

## What was added

- **Verification plans** (data only; execution is WP5) for the four
  scaffolded emitters:
  - `powershell.py`: `pwsh-parse` (`[Parser]::ParseFile`, which parses
    without executing) and `psscriptanalyzer`. Both advisory, so
    `complete=False`.
  - `sql.py`: `sql-lexical` (in-process, required) and `sqlfluff parse
    --dialect <mapped>` (advisory). `complete=True`.
  - `prompt.py`: `prompt-front-matter`, `prompt-body`, `prompt-placeholders`
    (in-process, required). `complete=True`.
  - `runbook.py`: `runbook-front-matter`, `runbook-title`,
    `runbook-fences-labeled` (markdown-it, required). `complete=True`.
- **Language risk patterns** in `compiler/extract.py`: `_LANG_RISK` (public
  as `LANG_RISK_PATTERNS`) for `powershell` (5), `sql` (5) and `python` (4),
  applied after the generic table, to fences of that language only.
  `extract(lang_risk_patterns=...)` overrides them.
- **Render refinements**: a PowerShell body shebang is hoisted to line 1
  (never added); `#Requires` lines stay in place, are listed in the plan
  notes (`PowerShellEmitter.requires()`), and are skipped by the PowerShell
  comment-name fallback. Prompt front matter gains `placeholders: [...]`
  (`find_placeholders()`), just before `verify-with`.
- **`emitters/base.py`**: `VerificationPlan.complete` now documents its WP4
  meaning (below); new helpers `risk_notes()` (Bash/Python switched to it,
  same output) and `leading_shebang()`; `markdown_front_matter(extra=...)`.
  The unused `scaffold_plan()` helper was removed.
- **Tags and collections** (approved design: library-level registries):
  - `library/refs.py`: references, the generation stamp, containment,
    and deterministic JSON I/O.
  - `library/tags.py`: `library/tags.json`.
  - `library/collections.py`: `library/collections/<name>.json`.
  - `library/paths.py`: `tags_file`, `collection_file()`.
  - `errors.py`: `InvalidNameError`, `UnknownArtifactError`,
    `AmbiguousArtifactError`, `StaleReferenceError`,
    `UnknownCollectionError`, `CollectionConflictError`,
    `RegistryCorruptError`, all `LibraryError` subclasses.
- **CLI**: `soloctl tag add|remove|list` and `soloctl collection
  create|add|remove|show|list`, thin over the service functions. Every
  refusal exits `1`.
- **Tests**: `tests/test_emitter_plans.py` (42), `tests/test_risk_patterns.py`
  (41), `tests/test_tags_collections.py` (78). In `tests/test_emitters.py`,
  five assertions that pinned the scaffold state were updated to the new
  truth: `complete is False and checks == ()` (PowerShell: still
  incomplete, now with advisory checks), `complete is False` → `True` for
  SQL/prompt/runbook (runbook's "not designed yet" note → its risk note),
  and the hostile-front-matter line count 8 → 9 (the `placeholders` line).
  The scaffold tests were renamed `*_basics`; nothing else in them changed.

## Decisions made where the docs were silent or in tension

- **What `complete` means now.** `complete=True` iff the plan has at least
  one *required* check, and for these four emitters that check is one
  soloctl runs in-process. A tool soloctl doesn't depend on is advisory
  (`required=False`). WP3's Bash plan (`bash -n` + `shellcheck`, both
  required, external) predates this rule and was left unchanged; WP5
  should decide whether Bash is held to it too.
- **PowerShell stays `complete=False`.** Its only real parser is pwsh, so
  there's no honest in-process check. A brace-balancing "parser" would
  claim more than it checks. WP5 can promote `pwsh-parse` to required where
  pwsh is present, which would make the plan complete.
- **PowerShell argv carries a fixed script.** `pwsh -Command` joins
  trailing arguments into the command text, so the path would become code.
  `-CommandWithArgs` (pwsh 7.4+) passes it as `$args[0]` instead. The two
  scripts are the module constants `PWSH_PARSE_SCRIPT` and `PSSA_SCRIPT`.
  No artifact content is interpolated into them, and a test proves argv is
  identical for a benign and a hostile body. `-NoProfile` keeps a user
  profile from running code.
- **`ARTIFACT_PATH` is a whole argv element.** The PowerShell scripts
  contain `{ }`, so WP5 must substitute by element equality, never
  `str.format`. A test checks every emitter's plan for this.
- **SQL `sql-lexical` is required although it is not a parse.** The brief
  asked for an in-process sanity check, and this one catches truncated
  pastes, which is the common failure. Its description says "Not a parse"
  so no one reads it as more. The sqlfluff dialect comes from a fixed table
  (`postgresql|postgres → postgres`, `mysql`, `sqlite`, `tsql`, `ansi`);
  anything else falls back to `ansi` with a plan note, so a config string
  never becomes an unvetted argv value.
- **"No leftover placeholders" vs. prompt templates.** `{input}` in a
  prompt is intentional, so the lint can't ban placeholders. The emitter
  declares them in front matter, and the lint fails on any undeclared
  `{name}`/`{{ name }}`, any declared-but-unused one, or editorial
  fill-ins (TODO, TBD, FIXME, `[insert …]`, `<insert …>`). JSON
  examples, `{0}`, and shell `${HOME}` are not placeholders. The key is
  always present (`[]` = none found).
- **Risk-pattern scope.** The Bash table keeps applying to every language
  (unchanged behavior); language tables are additive. `run-as-admin`
  (`#Requires -RunAsAdministrator`, `-Verb RunAs`) wasn't in the brief; I
  added it as PowerShell's `sudo`. DELETE/UPDATE "without WHERE" means no
  `WHERE` from a statement start (line start or `;`) to the next `;`, which
  keeps `ON DELETE CASCADE` from flagging.
- **Tags/collections: registry files** (operator-approved). D3 governs an
  artifact's compile-time metadata (header/front matter, no per-artifact
  sidecars), and §6 forbids in-place edits; library-level `tags.json` and
  `collections/<name>.json` are neither, and tagging never changes an
  artifact's bytes (tested).
- **References are `<kind>/<filename>` + the `compiled:` header value.**
  Collision resolution already makes a name unique across `drafts/<kind>/`
  and `approved/<kind>/`, so the ref survives approval moving the file.
  All artifacts from one compile run share one stamp (the run timestamp),
  so the stamp identifies the run; with the ref, that is unique. A stamp
  mismatch is `stale`: never re-attached, `add` refuses, `remove` still
  works. No `art_`/`col_` ID is invented (AGENTS.md §1.2). Only the header
  is read for the stamp; a `compiled:` line in the body never counts.
- **Idempotence rules.** Duplicate add, absent remove and re-create with
  the same (or no) metadata are no-ops that write nothing. `remove` refuses
  only if the artifact is unknown to both the registry and the disk.
  `collection add` checks every argument before writing (all-or-nothing).
  Invalid names are refused with a suggested slug, never rewritten.
- **Files in `collections/` that aren't `<valid-name>.json`** (READMEs,
  crash-left `.tmp` files) are ignored by `list`; a corrupt collection file
  is refused, and corrupt registries are never overwritten.
- **Not a UCC schema change.** `soloctl.tags/1` and `soloctl.collection/1`
  are local file formats, not `ucc-contracts` schemas, so CLAUDE.md's
  "update the roadmap §2/§8 and standards §17" rule isn't engaged.

## What was verified, not just asserted

- **Mutation-checked, Part A (23/23 caught)**:
  1. Bash given a language table
  2. language tables applied to every language
  3. DELETE ignoring WHERE
  4. DELETE not anchored to a statement start
  5. eval/exec lookbehind dropped
  6. remove-recurse-force needing only `-Recurse`
  7. flag dedupe removed
  8. `#Requires` name skip removed
  9. that skip leaking into Bash
  10. `pwsh-parse` made required
  11. PowerShell plan claiming complete
  12. artifact content interpolated into the pwsh script
  13. the path token embedded in a script
  14. shebang not hoisted
  15. shebang left in the body
  16. `#Requires` not noted
  17. `sql-lexical` not required
  18. unknown dialect passed through to sqlfluff
  19. SQL risk notes dropped
  20. placeholders missing from front matter
  21. `${x}` treated as a placeholder
  22. placeholder dedupe removed
  23. runbook complete with no required check
- **Mutation-checked, Part B (18/18 caught)**:
  1. stamp guard skipped
  2. status ignoring the stamp
  3. a no-op that writes
  4. ref regex letting paths through
  5. `locate` bypassing `LibraryPaths.resolve` (symlink escape)
  6. names accepting upper case
  7. `collection add` skipping unknown artifacts
  8. ambiguity check removed
  9. `create` clobbering a concurrent create
  10. create conflict ignored
  11. corrupt registry read as empty
  12. `tag remove` accepting unknown artifacts
  13. stamp read beyond the header
  14. member dedupe removed
  15. `tags.py` importing `ucc_events`
  16. `list` not filtering invalid names
  17. bad tag names tolerated in `tags.json`
  18. registry bytes depending on operation order

  One honest note on item 18: mutating only `sorted()` in `_save`, or only
  `sort_keys` in `write_json_doc`, is not caught, because each alone keeps
  the order. Breaking both is caught.
- **Contract-free boundary**: AST check that `refs.py`/`tags.py`/
  `collections.py` import no edge module, plus a subprocess check that
  importing them loads none transitively (same rule as `compile.py`).
- **End to end**: `soloctl compile` on a PowerShell/SQL/prompt transcript
  produced a hoisted shebang, the `remove-recurse-force` and
  `delete-no-where` flags, and `placeholders: ["ticket", "team"]`; then
  every `tag`/`collection` command was run against those drafts, including
  refusals and a deleted member showing `MISSING`.
- **Full suite in an independent fresh clone** of the pushed branch.
- **Not verified**: `pwsh`, `sqlfluff`, `shellcheck` and `ruff` are not
  installed on the build machine, so the external argv tuples are checked
  as data only. In particular, the claim that `-CommandWithArgs` needs
  pwsh 7.4+, and the exact exit-code behavior of `sqlfluff parse`, should be
  confirmed when WP5 first runs them.

## Known limitations (WP4 items 4-5 scope)

- **The in-process checks are specified, not implemented.**
  `sql-lexical` and the prompt/runbook lints exist as names and precise
  descriptions; the code that runs them belongs to the WP5 verification
  engine (rule 8: verification is separate from emission), just like
  WP3's `python-ast-parse`.
- **Risk patterns are dumb regex by design**: SQL patterns match inside
  comments and string literals; `UPDATE … SET a = (SELECT … WHERE …)` hides
  a missing outer WHERE; PowerShell download-then-`Start-Process` isn't
  caught; the generic Bash table can still fire on other languages (e.g.
  `dd` in a SQL date format), as before.
- **`library/risk-patterns.toml` still only feeds the generic table.**
  Per-language TOML tables weren't added.
- **Tags and collections are filesystem curation, not S2-1 record
  metadata.** README notes that S2-1 governance is record-based and the
  `drafts/approved/...` directories are projections. A ref names a file
  there, not an `art_` record; WP5 decides how a draft becomes a record and
  must carry curation across explicitly, never infer it.
- **Lost updates under concurrent writers**: `tags.json` is
  read-modify-replace. Each write is atomic (no torn file), but two
  simultaneous `tag add`s can drop one. Single-operator tool; no locking.
- **Revoked/superseded artifacts read as `missing`**, since nothing moves
  files there yet. No `collection delete` or rename, and no `compile --tag`.

## Next steps for WP5

1. Verification engine: execute plans; implement `sql-lexical` and the
   prompt/runbook lints to the descriptions above; substitute
   `ARTIFACT_PATH` by whole-element equality with an absolute path; treat
   `complete=False` as "cannot auto-verify". Decide whether `pwsh-parse`
   becomes required when pwsh is present, and whether Bash's required
   external checks fit the advisory rule.
2. Approval must keep `<kind>/<filename>` and rewrite only the `review:`
   line, so the `compiled:` stamp and every tag/collection ref stay valid
   without a multi-file write. If approval ever renames, it must rewrite
   `tags.json` and every collection in the same operation.
3. Revocation/supersession: teach `refs.status_of` to report `revoked`/
   `superseded` instead of `missing`; exclude them from the manifest but
   keep the registry entries. `revoked/` and `superseded/` are flat, so
   `prompts/foo.md` and `runbooks/foo.md` collide there; fix that layout
   and add both to the collision namespace.
4. Manifest/index: read `tags.json` and `collections/*.json` as inputs (they
   are operator data, not derived). Once a hash index exists, a
   `soloctl.tags/2` can key refs on `(artifact_type, sha256)`.
5. Resolve the compile-event decision; tag/collection events follow the
   same answer.

---

# Work Package 5a — verification engine (roadmap step 19)

Built on `main` at `05bfb28` (WP4 items 4-5 merged, PR #6). Covers WP4's
"Next steps for WP5" item 1. Approval, revocation, manifest/index and
events (items 2-5) are not started. Baseline 583 passed; now 695.

## What was added

- **`soloctl/verification/`**, a new package:
  - `models.py`: `CheckOutcome`, `CheckResult`, `VerificationReport`, the
    status and verdict vocabularies, and `MANUAL_NOTE`.
  - `engine.py`: `run_plan(plan, artifact, *, timeout)` runs every check
    in plan order and returns a report. `decide()` is the verdict policy.
    `substitute_path()` does the `ARTIFACT_PATH` substitution.
    `IN_PROCESS_CHECKS` maps check names to implementations. The engine
    writes nothing.
  - `python.py` (`python-ast-parse`), `sql.py` (`sql-lexical`),
    `markdown.py` (prompt and runbook lints, plus a front-matter parser for
    soloctl's flat `key: <JSON>` form).
  - `service.py`: `verify_artifact(config, artifact, *, timeout,
    verified_at)` resolves the artifact (`library.refs`), rebuilds its plan
    (`plan_for`), runs it, and writes `verification/<kind>/<filename>.json`.
- **`soloctl verify <artifact> [--timeout S] [--library]`** in `cli.py`:
  thin. Exit `0` passed, `5` failed, `6` inconclusive, `1` refused.
- **`errors.py`**: `VerificationError(SoloctlError)`.
- **Tests**: `tests/test_verification.py` (112). No existing test changed.

## Decisions made where the docs were silent or in tension

- **Verdict policy (provisional, from the brief; the operator may revise
  it).** Statuses are `passed`, `failed`, `not-run` (tool not on PATH, or
  no implementation for an in-process name) and `error` (timeout, exec
  failure). The verdict is `failed` if a required check failed; otherwise
  `inconclusive` if the plan is `complete=False`, has no required check,
  or a required check is `not-run`/`error`; otherwise `passed`. A failure
  beats incompleteness: a real failure is evidence even in an incomplete
  plan. Advisory results are recorded and never move the verdict.
- **Plans are rebuilt, not stored** (operator-locked 2026-10-20; see
  "Locked decision" below). Compile doesn't persist plans, and
  compile.py/emitters weren't changed. `plan_for()` picks the one built-in
  emitter whose kind directory and extension produce the ref (among *all*
  built-ins: `enabled_emitters` governs compile, not checking), builds a
  transient candidate from the file (language, type, SQL dialect from
  `-- dialect:`, risk flags from the header or front matter, body = file
  text), and calls `verification_plan()`. The candidate's hash fields stay
  empty rather than invented; plans don't read them. A test compiles 12
  artifacts under three `default_sql_dialect` settings and asserts each
  rebuilt plan equals the compile-time plan. SQL is rebuilt with no
  default dialect, because the header already records the resolved one.
- **External checks.** `shutil.which(argv[0])`, then
  `subprocess.run(argv, stdin=DEVNULL, capture_output=True, timeout=…,
  cwd=<artifact dir>, shell=False)`. argv[0] becomes the resolved
  executable, so PATH isn't searched twice. `ARTIFACT_PATH` is replaced
  only in elements equal to it, with the absolute path. Exit 0 is pass and
  anything else is fail. Output (stdout+stderr) is kept up to 4000 chars.
  The environment is inherited.
- **Same bytes for every check.** The engine hashes the file before the
  first check and after the last; any change refuses the run. The service
  also refuses if the engine's hash differs from the bytes it built the
  plan from. Non-UTF-8 files are refused, since soloctl only writes UTF-8.
- **`sql-lexical` dialect families** come from the header's dialect:
  `postgres` (dollar quotes, `E''` escapes, nested comments), `mysql`
  (backslash escapes, backticks, `#` comments), `sqlite` (backticks,
  brackets), `tsql` (brackets, nested comments, `GO` lines). Unspecified or
  unmapped dialects get only the standard rules, and failures then carry a
  "label the fence" hint. Statement count, closure and paren balance are
  computed outside comments and quoted text, as the description says.
- **Front matter "well-formed"** means soloctl's own form: every field line
  is `key: <JSON>`, no duplicate keys, the block is closed, and the keys
  soloctl writes are present with the right types (strings; `risk-flags`
  and `placeholders` lists of strings). Blank and `#` comment lines are
  tolerated. A hand-added plain YAML scalar fails. There's no YAML
  dependency, and the brief forbids adding one without asking.
- **Editorial fill-ins**: `TODO`/`TBD`/`FIXME` are matched as upper-case
  words only (so "a todo list" passes); `[insert …]` and `<insert …>` are
  case-insensitive. The body is scanned, not the front matter.
  Placeholder comparison is set-based, using `emitters.prompt.find_placeholders`.
- **Runbook lints** use `MarkdownIt("commonmark")`, the extractor's parser,
  on the body below the front matter. "First block is a heading" accepts
  ATX and setext headings. Only fences are checked; indented code blocks
  aren't fences.
- **Bash and PowerShell plans unchanged.** Bash keeps its two required
  external checks, which fits the policy: without `shellcheck` a Bash
  artifact is inconclusive. `pwsh-parse` stays advisory, so PowerShell is
  always inconclusive. Promoting it "where pwsh is present" would make the
  plan depend on the machine. That is an emitter/policy change for the
  operator, not an engine change (see open decisions).
- **Result records**: `library/verification/<kind>/<filename>.json`, schema
  `soloctl.verification/1` (a local file format, not a `ucc-contracts`
  schema, so roadmap §2/§8 and standards §17 aren't engaged). Keyed by the
  same `<kind>/<filename>` ref as tags, so it survives approval moving the
  file. Each record carries `compiled`, `sha256`, `state`, `verdict`,
  `reasons`, per-check results and `scope: "automatic"` plus the
  manual-verification note. Written with `write_json_doc` (atomic,
  deterministic); the path goes through `LibraryPaths.resolve`. Only the
  latest run is kept; re-running overwrites it.

## What was verified, not just asserted

- **One focused test per check** (8 in-process checks, each with passing
  and failing cases), plus the verdict policy, external execution
  (substitution, hostile content, timeout, truncation, stdin, mid-run
  change), persistence (atomic-write spy, determinism, symlink escape,
  refusals write nothing, artifacts and `events.jsonl` byte-identical),
  plan round-trip, the CLI exit codes, and the contract-free boundary (AST
  check plus a subprocess import check, the same rule as `compile.py` and
  `library/tags.py`). AST checks also confirm that only `engine.py` imports
  `subprocess`, that it calls nothing but `subprocess.run`, with
  `shell=False`, `stdin` and `timeout`, and that `substitute_path` uses
  equality, not `format`/`replace`.
- **Mutation-checked (40/40 caught)**, each broken on purpose in a scratch
  copy, `tests/test_verification.py` confirmed to fail, then restored:
  1. substring `replace` of `ARTIFACT_PATH`
  2. relative path substituted
  3. `shell=True`
  4. missing tool counted as passed
  5. advisory checks deciding
  6. `complete=False` ignored
  7. no timeout
  8. stdin inherited
  9. unknown in-process check passing
  10. mid-run change not detected
  11. engine importing `ucc_events`
  12. `ast.parse` skipped
  13. SQL unclosed literal ignored
  14. unclosed block comment ignored
  15. open `(` ignored
  16. stray `)` ignored
  17. terminator not required
  18. no-statement accepted
  19. tsql `GO` not recognized
  20. dollar quotes ignored
  21. MySQL backslash escapes ignored
  22. undeclared placeholder ignored
  23. unused placeholder ignored
  24. fill-ins ignored
  25. fill-in words case-insensitive
  26. blank prompt body accepted
  27. missing front-matter key accepted
  28. wrong kind accepted
  29. duplicate key accepted
  30. non-JSON value accepted
  31. unclosed front matter accepted
  32. runbook title unchecked
  33. unlabeled fence ignored
  34. non-atomic record write
  35. record path bypassing `resolve`
  36. rebuilt plan ignoring the header dialect
  37. rebuilt plan dropping risk flags
  38. manual note dropped
  39. plan/check hash mismatch ignored
  40. inconclusive exiting 0

  The first run caught 38/40. Mutations 20 and 39 were missed: the
  dollar-quote test body didn't need dollar quoting (an `E''` string
  masked it), and the service-level hash guard had no test. Both tests were
  fixed and both mutations are now caught.
- **End to end**: `init` → `compile` (polyglot fixture) → `verify` on
  every draft via the CLI. Prompt, runbook, SQL and Python pass; Bash is
  inconclusive (no shellcheck); PowerShell is inconclusive.
- **Full suite in an independent fresh clone** of the pushed branch.
- **Not verified**: `shellcheck`, `ruff`, `sqlfluff` and `pwsh` are still
  not installed on the build machine. External execution is tested with
  fake `/bin/sh` tools on an isolated PATH, and with real `bash -n`. So
  WP4's open questions remain open: whether `-CommandWithArgs` needs pwsh
  7.4+ and `sqlfluff parse`'s exit codes. If sqlfluff exits 0 on a parse
  error, it would read as an advisory pass. Advisory results never decide,
  but this should be confirmed on a machine that has these tools.

## Locked decision: where `verify` gets its plan (operator, 2026-10-20)

**Approach A, rebuilding the plan at verify time, is locked.** The
operator chose it over approach B, storing the plan at compile time.

- **Why A**:
  - compile.py and the emitters stay unchanged;
  - there's no per-artifact plan file (COMPILER_PLAN D3);
  - drafts compiled before WP5a can be verified;
  - only argv from soloctl's own code is ever executed, so a tampered
    library file can't choose what `verify` runs;
  - emitter plan fixes reach existing artifacts.
- **Accepted costs**:
  - The plan depends on the header's `dialect:`/`risk-flags:` values. The
    dialect goes through a fixed table, and the flags only affect notes.
  - It needs a small kind+extension → emitter table and a transient
    candidate.
  - Checks can drift from what compile would have promised. The result
    record stores the checks that actually ran, which preserves the audit
    trail.
- **Guard**: `test_rebuilt_plan_equals_the_compile_time_plan`. Any future
  emitter whose plan reads another candidate field must extend
  `plan_for()` and that test.
- **Revisit only if** approval needs to prove the plan an artifact was
  verified against at compile time. In that case, add a plan fingerprint to
  the result record rather than storing executable plans.

## Open decisions flagged (not made here; still open after the merge)

1. **S2-1 vs. file results.** S2-1 has canonical `ucc.verification`
   records (`canonical/artifact-compiler/verifications/`, states
   `not_required|pending|passed|failed|expired`), and README says
   governance authority is record-based. WP5a's files are filesystem
   evidence about a draft's bytes, with no `ver_` ID (none is invented,
   AGENTS.md §1.2) and no bridge to those records. Whether approval reads
   these files, S2-1 records, or both, and how `inconclusive` maps onto
   the S2-1 states (there's no equivalent), belongs to the
   approval-authority decision.
2. **Verdict policy** is the brief's provisional one. In particular: should
   a missing tool for a *required* check stay inconclusive, or should Bash
   move its external checks to advisory like the WP4 rule?
3. **PowerShell**: should `pwsh-parse` become required (with
   `complete=True`)? That would make PowerShell verifiable on machines with
   pwsh 7.4+ and failed/inconclusive elsewhere.
4. **History**: only the latest run is kept. If approval needs "the
   verification this approval was based on", keep per-run records, e.g.
   `verification/<kind>/<filename>/<verified_at>.json`, or embed the sha256
   in the approval.
5. **Events**: `verify` appends nothing, by the same reasoning as the
   compile-event decision (WP4 items 1-3). A verify event would follow
   that answer.

## Known limitations (WP5a scope)

- `sql-lexical` is lexical by design: it doesn't know keywords, so `SELECT
  FROM;` passes. MySQL's `--` comments are recognized without the
  required trailing space. tsql `GO` only counts alone on its line.
- `python-ast-parse` catches parser errors only. Compiler-stage errors
  (`return` outside a function, `nonlocal` at module level) pass, as the
  check's description says.
- External tools inherit the environment and run in the artifact's
  directory, so tool config files found from there (e.g. a
  `pyproject.toml` above the library, or `.shellcheckrc`) apply. ruff's
  `exclude` could make it skip the file and exit 0. That's advisory, but
  it's an unverified pass.
- No sandbox: the roadmap lists `verification/sandbox.py`. Nothing here
  executes artifact code; every check only parses or lints. A check that
  runs the artifact would need that sandbox first.
- `verify` does one artifact per call: no `--all`, no batch over a
  collection or tag.
- Concurrent `verify` runs on the same artifact race on the record file;
  each write is atomic, and the last one wins. Single-operator tool, no
  locking.

## Next steps

1. Decide open decisions 1-3 (the plan-source question is locked, above),
   then build approval (roadmap step 20) on
   top. COMPILER_PLAN's "approve refuses while `verify-with` is the
   placeholder" gate and a "latest verification record matches the current
   sha256 and passed" gate are both available now.
2. Confirm the external tools' exit-code behavior on a machine that has
   shellcheck, ruff, sqlfluff and pwsh 7.4+.
3. Revocation/manifest/index and the event decision, as WP4's next steps
   2-5 describe.
