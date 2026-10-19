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
