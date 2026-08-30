# ARTIFACT-COMPILER-BUILDOUT.md — grounded roadmap

**Based on:** the uploaded `artifact-compiler-stage2.bundle`, `main` @ `46b1e96`, **263 tests
passing** in a fresh clone. Read, not assumed.
**Context:** develops on the **org line** (D10 — org is upstream; `Eowerd24/Artifact-compiler` is
frozen downstream, harvested from this later). AC is consumed by the UCC line's `ArtifactPort`.

---

## 0. What's actually there (correcting the plan)

I assumed the pivot target was "build AC's governance slice." **That's already done, and done
well.** Verified in the tree:

- `soloctl/artifact_store.py` — a real `ArtifactRecordStore`: hash-addressed immutable revisions
  (`content_hash` = sha256 over the canonical `ucc.artifact-content-manifest`), per-entry size +
  sha256 verification, content-path containment, `flock` locking, validated `ucc.artifact` /
  `ucc.artifact-revision` / `ucc.verification` / `ucc.approval` / `ucc.publication` records.
- `soloctl/artifact_port.py` — all seven `ArtifactPort` methods **real** over the store, with a
  full `verify_execution_eligibility` chain (existence → hash → publication → verification →
  approval) and idempotency incl. `IN_FLIGHT`.
- The **full ~26 domain schemas are authored** and vendored (37 schemas). The Stage 2 "deferred
  schemas" and the `v0.3.1` IN_FLIGHT/contracts work (register PA-4) are effectively complete on
  this line — the register's `v0.2.0` pin is now behind reality.
- Stage 1 base intact: transcript IR, importers (markdown/chatgpt/claude), the extractor (whole-
  input secret refusal, dedup, supersession), dry-run invariant.

So this is not "make AC real." It's **finish AC's authority set, then build the capability the
tool is named for.** That reframing is the whole value of reading the code first.

This also confirms `AUDIT-STAGE2.md` S2-F-001 is purely a *packaging* gap: AC genuinely has real
records behind its port (263 tests prove it); the UCC line just doesn't declare/install it as a
dependency. Fixing AC's packaging (§AC-0) directly closes the deciding Stage 2 finding.

---

## 1. Gap analysis — AC's authority set vs. what exists

SPEC-001 §A.2 makes AC "sole authority for artifact identity, immutable revisions, **provenance,
verification, review, approval, publication, tags, and collections**" — plus the emitter/compiled-
artifact path. Against the tree:

| Authority | State | Evidence |
|---|---|---|
| Artifact identity + immutable revisions | ✅ real | `artifact_store.create_script_revision`, hash-addressed |
| Verification | ✅ real | `_record_verification_unlocked`, `ucc.verification` |
| Approval | ✅ real (no revoke) | `approve_revision`; **no revocation** — `approval_state: revoked` unreachable |
| Publication | ✅ real | `publish_revision` / `withdraw_publication` |
| Eligibility | ✅ real (no review gate) | full chain **except** review |
| **Review** | ❌ absent | no method; only `preview_transcript_destination` matched the grep |
| **Provenance** (first-class) | ❌ absent | source hash is recorded on the revision, but no `provenance` record/chain |
| **Tags** | ❌ absent | nothing |
| **Collections** | ❌ absent | `library/paths.collections` dir exists; `material-collection` schema vendored; **no CRUD** |
| **The compiler (emit)** | ❌ absent | `compiler/` holds only `extract.py`; no path from a transcript/extracted blocks → an artifact revision |
| Directory governance retirement | ⚠️ vestigial | `drafts/approved/revoked/collections/` dirs remain as "export views" beside the real records |

Two buckets: **(A) the missing governance axes** (review, revocation, provenance, tags,
collections) that complete AC's authority set, and **(B) the compiler proper** — the emit path,
which is the capability "Artifact **Compiler**" is named for and still doesn't exist.

---

## 2. Scope & order

Do the packaging fix first (it unblocks the UCC line today), then close the governance axes
(small, they slot into the existing store pattern), then build the compiler (the real depth).

```
AC-0  Package AC as an installable pinned dependency        ← unblocks AUDIT-STAGE2 S2-F-001
AC-1  Review records + eligibility gate                     ┐
AC-2  Approval revocation (close the approval axis)         │ governance axes
AC-3  Provenance as a first-class record                    │ (complete SPEC-001 authority)
AC-4  Tags                                                  │
AC-5  Collections                                           ┘
AC-6  The compiler: transcript/material → artifact revision ← the headline capability
AC-7  Retire directory-shaped governance to projections
AC-8  CLI surface for the new verbs
```

Each keeps AC **green and standalone**; the UCC line adopts any of it by bumping the pinned SHA.

---

## 3. Workstreams

### AC-0 — Installable pinned package (closes Stage 2 S2-F-001)

**This is packaging work, not version reconciliation.** The reconciliation (all three repos
vendor v0.3.1/37 schemas, byte-identical) is already confirmed and done. AC-0 is the separate
job of making AC a real, installable dependency so the UCC line stops sibling-importing it.

- *Evidence:* AC has `pyproject.toml` and is `pip install -e .`-able (263 tests ran that way), but
  the UCC line reaches it via a `sys.path` sibling dir, not as an installed dependency
  (`AUDIT-STAGE2.md` S2-F-001).
- *The real problem to solve — install-time collision, not content:* AC and nodectl each vendor
  their own `third_party/ucc-contracts`. Both being byte-identical means a collision is *harmless
  if it happens* — but two distributions of the same top-level package `ucc_contracts` still
  collide **at install time** regardless of content. So "byte-equal" does not make the co-install
  clean; the install mechanics must be resolved.
- *Change (two contexts, both must work):*
  1. **Standalone AC:** unchanged — `pip install -e .` uses AC's vendored `third_party/ucc-contracts`.
     Standalone independence (D3/D8) is preserved.
  2. **Integrated UCC context:** exactly **one** `ucc_contracts` is installed — the hosted
     `Eowerd24/ucc-contracts@v0.3.1` (this is what D9 hosted it for). AC is installed as
     `pip install git+https://github.com/Eowerd24/Artifact-compiler@<AC-sha>` and must import
     `soloctl.artifact_port.build_artifact_port` against that single shared contracts install —
     **without** its vendored copy shadowing or double-installing it. Achieve this by declaring
     `ucc-contracts==0.3.0` as a normal dependency in AC's `pyproject.toml` (so pip resolves one
     copy) and keeping the vendored tree as a standalone-only fallback, not an install artifact.
- *Note on SHAs:* the **contracts** pin is `v0.3.1` (tag `4051a35` on `Eowerd24/ucc-contracts`).
  The **AC** pin is AC's own commit (`46b1e96` today, or the new SHA this AC-0 change produces) —
  don't conflate them.
- *Tests:*
  - a **non-editable** install-and-import test: `pip install .` into a clean venv, then
    `from soloctl.artifact_port import build_artifact_port` works and returns a port over a temp root;
  - a co-install test: install AC **and** nodectl (from `Eo-org24/nodectl@ucc-integration`) into one
    venv and assert exactly one `ucc_contracts` distribution is present (`pip show ucc-contracts`),
    v0.3.1, and both ports import.
- *Why first:* this is the exact dependency `FIX-STAGE2.md` §1 needs. Doing the AC half here means
  the UCC line's Dockerfile can `pip install` AC instead of sibling-importing it — closing the
  deciding Stage 2 finding.

### AC-1 — Review records + eligibility gate
- *Evidence:* eligibility checks verification+approval+publication but **not** review; the lifecycle
  model has `review_state: not_requested|pending|changes_requested|accepted`.
- *Change:* add `request_review` / `record_review` producing a `ucc.review` record (author the
  schema if absent), and add an optional review gate to `verify_execution_eligibility` (policy:
  review not required for the first proof, but the record and state must exist). Follow the exact
  `_write_document` + `locked()` pattern already in the store.
- *Tests:* review record round-trips; eligibility with review-required refuses until accepted.

### AC-2 — Approval revocation
- *Evidence:* `approve_revision` exists; `approval_state: revoked` is unreachable; a `revoked/` dir
  exists as a vestige.
- *Change:* add `revoke_approval` writing a revocation record (append-only, preserves the approval
  history); eligibility treats a revoked approval as ineligible. No mutation of the original
  approval record.
- *Tests:* revoke → eligibility refuses; approval history preserved; idempotent revoke.

### AC-3 — Provenance as a first-class record
- *Evidence:* the revision records a source hash inline; there's no provenance entity linking
  revision → source material/transcript/import.
- *Change:* emit a `ucc.provenance` record (author schema) capturing source kind + hashes + import
  event ref, referenced by the revision. This is what lets the compiler (AC-6) prove where a
  compiled artifact came from.
- *Tests:* provenance round-trips; revision → provenance → source chain resolves.

### AC-4 — Tags
- *Change:* mutable tag records over artifacts/revisions (tags never change content identity —
  Standards: aliases don't change identity). Small CRUD in the store pattern.
- *Tests:* tag/untag; tags excluded from content hash.

### AC-5 — Collections
- *Evidence:* `material-collection` schema vendored; `collections/` dir exists; no CRUD.
- *Change:* collection records grouping artifacts/revisions (mutable named grouping, per 2-of-2
  §F.6 Material Collection semantics).
- *Tests:* create/add/remove; membership by ID not name.

### AC-6 — The compiler (the headline)
- *Evidence:* `compiler/` has only `extract.py`; `create_script_revision` takes **raw content**, not
  compiler output. There is no path from a transcript or extracted blocks to an artifact revision —
  the tool doesn't yet compile.
- *Change:* an **emitter** that takes a transcript (or selected extracted blocks) + a target artifact
  kind and produces an immutable artifact revision through the existing store, with provenance
  (AC-3) back to the transcript/import. Start with one concrete emitter (e.g. extracted shell blocks
  → a runnable script artifact) so it exercises the full extract → compile → revision → approve →
  publish path end to end.
- *Compatibility:* additive; `create_script_revision` stays as the low-level primitive the emitter
  calls.
- *Tests:* a fixture transcript compiles to a revision whose content hash is stable and whose
  provenance resolves to the source; secret-bearing input still refuses (reuse the extractor's gate).
- *Why it matters:* this is what makes AC an Artifact *Compiler* rather than an artifact *registry*.
  It's also the most valuable thing to demo — a real transcript becoming a governed, published,
  executable artifact.

### AC-7 — Retire directory-shaped governance
- *Change:* make `drafts/approved/revoked/collections/` **projections generated from records** (or
  remove them), so there's one authority (the records) and the dirs are views. Directory movement is
  never governance (SPEC-001 K.2.6).
- *Tests:* dirs rebuild from records; no code path treats a dir as authority.

### AC-8 — CLI surface
- *Change:* expose the new verbs (`review`, `revoke`, `tag`, `collect`, `compile`) as thin Typer
  commands over the service functions, matching the existing thin-command/`perform_*` split, with
  `--json` + stable exit codes.
- *Tests:* each command's exit envelope; dry-run where it mutates.

---

## 4. Out of scope

VM-Factory (its own line — note it ships **`node_modules/` committed, 626 files**, a hygiene
regression to fix there, not here); the nodectl packaging half of S2-F-001; the vertical proof and
real-VM run (Stage 3). AC does not grow a UI, a network API, or multi-operator anything.

## 5. Backport discipline (D10)

Each AC-n lands on the org line, green and standalone. Harvest back to `Eowerd24/Artifact-compiler`
at a natural boundary (governance axes as one harvest; the compiler as another). The forcing
function from the register still applies: **if an AC change can't be cleanly lifted back into the
frozen standalone repo, a boundary was crossed** — AC must import nothing from nodectl or VMF, only
`ucc-contracts`. Verify that at each harvest (`grep` AC for any nodectl/library import → must be
empty).

## 6. Gate

Every workstream: AC suite green; AC imports only `ucc-contracts`; the vendored contracts version is
the single one the whole org line shares. The UCC line adopts by bumping the pinned AC SHA (AC-0) —
never by a sibling-dir import.
