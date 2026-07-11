# Work Package 1 — Handoff Notes

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

## Known limitations (by design, WP1 scope)

- Only `markdown-v1` is registered; ChatGPT/Claude adapters don't exist yet.
- The extractor still only recognizes Bash-family fences (`bash`, `sh`,
  `shell`, `zsh`); the language-neutral `ArtifactCandidate` model and the
  other five emitters are not implemented.
- No compilation: `extract()` is wired up and tested, but nothing calls it
  from the CLI yet, and no artifacts are ever written to
  `artifacts/drafts/`.
- `events.jsonl` is created empty by `init`; nothing appends to it yet (no
  ledger-event writing in this work package).
- No manifest.json / index.json generation (explicitly deferred).
- No approval, verification, tags, or collections.
- Filename-collision resolution (`slug.md`, `slug-2.md`, ...) has a
  TOCTOU race between checking and writing — acceptable for a single-
  operator local tool, not safe for concurrent writers.
- `soloctl.toml`'s `enabled_emitters`/`enabled_validators`/
  `default_sql_dialect` fields are parsed and validated but unused until
  the emitter and verification work packages exist.

## Next steps for Work Package 2

1. Implement `ChatGPTImporter` and `ClaudeImporter` against
   `IMPORTER_BLUEPRINT.md` §5 (tree-walk from `current_node` to root for
   ChatGPT; flat `chat_messages` for Claude). Both must produce the same
   `Transcript` IR — no adapter-specific logic outside
   `soloctl/importers/`.
2. Add versioned fixtures per COMPILER_PLAN.md's `tests/fixtures/chatgpt/
   v1/` and `.../claude/v1/` layout: simple conversation, regenerated
   response, edited message, tool calls, missing `current_node`, missing
   content, unknown content type, duplicate titles, empty conversation.
3. Register both in `build_default_registry()`; verify the registry still
   rejects ambiguous detection and unsupported schemas without adding
   source-specific branches to `registry.py` itself.
4. Wire `--list` / `--conversation <id-or-title>` selection UX (unambiguous
   substring match) into `perform_import` and the CLI, per
   `IMPORTER_BLUEPRINT.md` §6.
5. Do not touch `compiler/extract.py`'s language set or the emitter
   framework in WP2 — that's Phase 6/7, explicitly out of scope until the
   importer surface is done.
