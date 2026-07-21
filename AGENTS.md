# AGENTS.md

Guidance for any coding agent (Codex, Claude Code, etc.) working in this repository.
This is one of three UCC Stage-1 repos: **`nodectl`**, **`Artifact-compiler`**, **`VM-Factory`**.
This copy is trimmed to Artifact-compiler's own block — see the shared `/UCC/AGENTS.md` template
(one directory up from the three repo clones) for the other two repos' blocks and for what to
re-sync here if the shared core changes.

> **M-c note:** this repo had no `AGENTS.md`/`CLAUDE.md` before this change — only
> `HANDOFF_NOTES.md` (WP1/WP2 handoff record for the extractor/importer feature work, predates
> and is orthogonal to the UCC conformance work below — reviewed for contradictions with the
> locked baseline and found to have none; it's accurate as historical record and doesn't touch
> ports/fences/envelopes at all). Both files added fresh, not reconciled from a stale prior
> version, unlike nodectl's.

---

## 0. What this repo is

A **UCC Stage-1 conformant standalone tool.** It runs and is tested on its own, and it
conforms to a shared contract layer so three repos can later integrate. The fork onto the
UCC line has **not** been cut yet. Pinned shared-contract version: **`ucc-contracts v0.2.0`**
(vendored under `third_party/ucc-contracts/`).

Two documents outrank this file and each other in this order — read them before non-trivial work:

1. `docs/roadmap/UCC-Shared-Roadmap-To-Fork.md` — the plan, gates, and the path to fork (§8).
2. `docs/reference/UCC-Standards-and-Layout-Reference.md` — the conventions everything conforms to.

**If this file disagrees with those, they win.** If the vendored `ucc-contracts` disagrees with
any prose, the code wins. Do not re-litigate decisions already locked in the roadmap's decisions
table (D1–D6) or its conflict-resolution table.

---

## 1. Shared core — non-negotiable rules (identical in all three repos)

1. **Fork scope is NARROW.** Do **not**: build the UCC product, merge repos, add a broker /
   network service / canonical database, or wire real cross-module adapters. Those are Stage 2
   (post-fork). Port adapters here may stay honest stubs.
2. **Fail closed over fabricate.** If you lack a real ID, hash, token, publication state, or
   record, refuse with a typed `ucc.problem` — never invent one. This is the same principle
   behind the vault and dry-run fixes; apply it everywhere, especially in port methods.
3. **No trusted-path arbitrary shell. No cross-module canonical writes.** Legacy raw-command and
   direct-infra paths survive only as **fenced, standalone-only diagnostics** and must never be
   reachable from a port. See §3 below for the exact fenced symbols.
4. **Fences are enforced by AST call-site tests, not substrings.** Mentioning a fenced symbol in a
   docstring is fine; adding a real call to it will (correctly) fail the guard. **Never "fix" a
   failing fence test by weakening it to text matching** — that regression already happened once
   and was reverted. If a fence test fails, you added a real forbidden call; remove it.
5. **`ucc-contracts` is vendored and pinned.** Never hand-edit schemas, ID rules, lifecycle
   tables, or refusal codes locally. If the contract needs to change, it changes upstream, gets a
   new tag, and is re-vendored — then this repo bumps its pinned version.
6. **Standalone stays usable.** Every change is additive or a fenced relocation. Never remove this
   repo's independent CLI/run path or its existing tests.
7. **Six-field format for every change**, in the PR/patch description:
   current evidence / target contract / smallest conforming change / compatibility impact /
   tests / migration or fallback.
8. **Delivery is via patches.** Clones are read-only (no push creds). Produce `.patch`/diffs and
   files; do not assume you can push. Patches are cumulative and order-sensitive per repo.
9. **Keep the docs in lockstep.** If you change the schema set or a gate's state, update the
   roadmap (§2/§8) and standards reference (§17) in the same change.

### Event / envelope conventions

- Each repo **dual-writes**: the legacy ledger/audit line **and** a schema-conformant `ucc.event`,
  never one instead of the other. The legacy writer stays byte-for-byte as-is.
- `ucc.event.causation_id` is **omitted when absent, never `null`** (unlike `ucc.request`, the event
  schema's `causation_id` is not nullable).
- `producer_sequence` is per-producer, not globally ordered; it is not race-safe under concurrent
  writers (matches the legacy ledgers — do not claim otherwise).
- Real canonical IDs (`art_`, `node_`, …) do not exist yet. Current `subject.id`s are **documented
  placeholders** (deterministic sha256-derived). Do not build logic that assumes they are the final
  canonical IDs; they are replaced in Stage 2.

---

## 2. Making a change here

- Start from the current HEAD; run the full suite **before** touching anything and report the count.
- Make the smallest conforming change. Prefer additive files (new test, new module) over edits to
  load-bearing or vendored code — and verify a "this is vendored, don't touch it" comment is
  actually still true before trusting it.
- Re-run the full suite in an **independent fresh clone** before delivering — not just the working
  copy you edited.
- Write the six-field description. State compatibility impact honestly (operational changes count,
  e.g. "connecting to an un-pinned host now hard-fails").

---

## 3. This repo — Artifact-compiler

- **Shape:** package `soloctl` + Typer CLI; thin service layer; transcript IR / importers /
  extractor. Vendored `third_party/ucc-contracts/`. See `HANDOFF_NOTES.md` for the WP1/WP2 feature
  history (extractor, ChatGPT/Claude importers) — that work is independent of, and unaffected by,
  everything below.
- **Dry-run invariant (never regress):** a dry run performs **no** canonical mutation and appends
  **no** event — including the secret-refusal path (the `_log_import_event` call stays behind
  `if not dry_run:`). A real (non-dry) refusal must still audit.
- **Ports:** `soloctl/artifact_port.py` — 7 `ArtifactPort` methods; each validates its request
  (→ `VALIDATION_ERROR`) then refuses `DEPENDENCY_UNAVAILABLE` (no Artifact/Revision/Publication
  record store exists yet — that's Stage 2). Never fabricate a revision id, hash, or publication.
- **Events:** dual-write via `soloctl/ucc_events.py`, alongside `_log_import_event`.
- **Idempotency (M-b, D2, done):** `soloctl/idempotent_import.py` wraps `perform_import` — opt in via
  `import --idempotency-key <key>`. Builds+validates `ucc.request`/`ucc.result`; replay returns the
  stored result verbatim (no re-import); same key + different inputs refuses with `IdempotencyConflict`
  (CLI exit `3`). Store: `library/idempotency.db` (`soloctl/idempotency_store.py`). It commits
  `unknown` before dispatch; success replaces it, definite refusal removes it, and ambiguity retains
  it so retry exits `4` with `outcome_unknown` until reconciliation. No auto-expiry. `--dry-run`
  bypasses the wrapper entirely (dry-run needs no dedup guarantee).
- **Atomic writes (M-c, done):** `soloctl/library/atomic.py` — fsyncs the file, then `os.replace`, then
  fsyncs the containing directory (the rename's directory-entry update is only durable once the
  directory recording it is flushed too — `tests/test_atomic.py` spies on `os.fsync` to confirm both
  calls actually happen, not just proximity-tested).
- **`soloctl/ledger.py` provenance:** its own header says it's adapted from an older, separately-
  vendored `soloctl-0.1.0` archive's ledger module (see `HANDOFF_NOTES.md`'s WP1 section) — a
  historical claim about where the scrub-policy code originated, not a live "keep this in sync with
  another repo" contract. Distinct from nodectl's now-corrected `backend/ledger.py`, whose header
  used to (falsely) claim exactly that kind of live sync with this file.
- **Tests:** `pytest`.
- **Pending:** promote `main` to the default branch before peers pin a dep (GitHub repo-settings
  action, not a file change — needs push/admin access this session didn't have).

---

## 4. Out of scope (do not do here)

Real cross-module adapters; canonical record stores; the ~26 domain schemas; projection builder;
UCC application services; broker / network API / server DB; repo merges; multi-operator auth; any
general remote terminal in a trusted path; frontend or deployment-topology decisions. All of these
are Stage 2 or a later roadmap. If a task seems to require one, stop and flag it against the roadmap.
