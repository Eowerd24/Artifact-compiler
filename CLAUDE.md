# CLAUDE.md

Guidance for Claude Code in this repository. This is the standalone-usable Artifact Compiler on the UCC
**Stage 3** line, cut from `46b1e96` (`docs/roadmap/STAGE-3-UCC-SCOPE.md`), not this repo's independent `main`.

## Read these first (authoritative, in precedence order)

1. **`AGENTS.md`** (same directory) — the canonical, full agent guidance: the
   non-negotiable rules, the event/envelope conventions, and this repo's fenced
   paths, ports, and pending work. **Everything in AGENTS.md applies to you.**
   It is kept as the single source of truth so guidance can't drift between tools.
2. `docs/roadmap/STAGE-3-UCC-SCOPE.md` — the active scope and its step gates.
3. `docs/roadmap/UCC-Shared-Roadmap-To-Fork.md` — the original plan, gates, path to fork (§8).
4. `docs/reference/UCC-Standards-and-Layout-Reference.md` — the conventions.

If this file or AGENTS.md disagrees with the roadmap/standards, those win. If the
vendored `ucc-contracts` disagrees with any prose, the code wins.

## The five things to never get wrong

1. **Stage 3 scope is NARROW** — installable on contracts v0.3.5, truthful mutation boundaries, minimal exact-revision handoff; no catalog features, UCC product, repo merge, broker/network service/server DB, or cross-owner canonical writes. (AGENTS.md §1.1)
2. **Fail closed over fabricate** — refuse with a typed `ucc.problem` rather than
   invent an ID, hash, token, or state. (AGENTS.md §1.2)
3. **Don't cross the fences** — the standalone-only infra/shell paths listed in
   AGENTS.md must never be reached from a port. Fence tests are **AST-based**;
   never weaken one to a substring match to make it pass. (AGENTS.md §1.3–1.4)
4. **`ucc-contracts` is vendored + pinned** — never hand-edit it locally. This branch pins upstream development commit `56e2efc6024d9de032350fa061d2ec9a6cedb9a8`; released branches advance only by immutable tags. (AGENTS.md §1.5)
5. **Six-field format for every change**, delivered on reviewed branches with exact dependency pins. Keep the repo independently runnable and green. (AGENTS.md §1.7–1.8)

## Working notes for Claude Code

- Run the full test suite before and after any change, in an independent fresh
  clone for final verification — not just the working copy you edited.
- Prefer additive files over edits to vendored or load-bearing code — anything
  under `third_party/`, and any module whose own header claims to be synced
  from elsewhere. **Verify that claim before trusting it**, don't just take the
  comment's word for it: nodectl's `backend/ledger.py` claimed for a long time
  to be a vendored copy kept in sync with Artifact-compiler's `soloctl/ledger.py`,
  but the two had already diverged into different modules — the claim was
  stale, not a real constraint (fixed in M-c; see AGENTS.md §3).
- When you change the schema set or a gate's state, update the roadmap (§2/§8)
  and standards reference (§17) in the same change.
- Per-repo specifics (exact fenced symbols, port files, build quirks such as
  VM-Factory's no-editable-install layout) live in **AGENTS.md §3** — consult the
  block for whichever repo this is.

## Out of scope

See AGENTS.md §4 and `docs/roadmap/STAGE-3-UCC-SCOPE.md` §0. Records owned by other modules, local schema changes, the projection builder, UCC services, catalog features, and networked components remain out of scope.
