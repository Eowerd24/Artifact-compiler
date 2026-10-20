# STAGE-3-UCC-SCOPE.md: truthful integration and the first real proof

**Status:** Authorized by the owner on 2026-10-20 (`DECISION-REGISTER.md` D12–D14).
**Facts this scope builds on:** `BASELINE.md` in the UCC workspace (2026-10-20): pinned SHAs, contract pins,
owner roots, and missing proof M1–M8.
**Why it exists:** Stage 2 closed on 2026-08-30. Its instructions exclude the real-VM proof, and
no later scope existed, so the audit's next actions had no authorization on any line.

> In-repo copy of the workspace `Documents and reference/STAGE-3-UCC-SCOPE.md`; the workspace copy is
> authoritative if they differ.

**Precedence:** `DECISION-REGISTER.md` → this file → `UCC-Standards-and-Layout-Reference.md` →
`BASELINE.md` (facts only). Locked decisions D1–D11 and the pinned contract resolutions are
unchanged.

---

## 0. Scope boundary

**Stage 3 IS** the 2026-10-18 audit's next actions 2–5, delivered as bounded, ordered steps:

| Step | Audit action | Objective | Done when |
|---|---|---|---|
| **S3-0** | (prerequisite) | Each active line's `AGENTS.md`/`CLAUDE.md` describes this scope; stale pins and status facts are corrected | Docs-only patch per line; suites unchanged |
| **S3-1** | 2 | Installed owner boundary: AC, VMF and the shell co-install outside checkouts on **one** contracts release (`v0.3.4`, D13); explicit roots and backends; no sibling `sys.path` discovery, no implicit mock | A repeatable non-editable smoke prints module origins and versions, loads packaged schemas, builds each owner on explicit isolated roots, and shows a missing peer refusing clearly. Full suites green in fresh clones (BASELINE M1) |
| **S3-2** | 3 | Trusted boundaries tell the truth: no fixture success, accepted ≠ completed, strict request, version and identity checks, replay-safe execution and handback, AC `IN_FLIGHT` → `OUTCOME_UNKNOWN`, minimal canonical controller journal for one Project/Job/Assignment | The audit's reproduced failure cases refuse or stay nonterminal; unknown never reruns (M2–M5). Delivered as sequential bounded patches |
| **S3-3** | 4 | One bounded real node path to the locked Part-G helper contract | One disposable node runs the expected bytes; tampering and interruption give truthful evidence (M6–M7) |
| **S3-4** | 5 | One correlated vertical proof with selected failure evidence | Another operator reproduces happy and failure paths; owners and UI agree on IDs and outcomes (M8) |

**Stage 3 IS NOT:** a broker, message bus, socket/HTTP module API, or canonical server database;
a repo merge or monorepo; multi-operator auth; a frontend replacement; a persistent node agent or
daemon; a general remote terminal in any trusted path (`terminal.py` stays permanently fenced);
credentialed execution in the first proof; every payload kind; multi-host; snapshot expansion;
production deployment; AC catalog features (emitters, tags, collections, provenance graph).
**AC's independent `main` line (past `46b1e96`) is out of scope (D14).** AC will be adapted to
UCC later, not the reverse.

Work outside this boundary stops and gets written up as a proposed expansion before any
implementation.

## 1. Lines, pins, delivery

| Repo | Stage 3 line cut from | Contracts |
|---|---|---|
| `Eo-org24/nodectl` | `ucc-integration` @ `ed0f35e` | `v0.3.4` (already) |
| `Eowerd24/VM-Factory` | `main` @ `d04607f` | `v0.3.0` → `v0.3.4` in S3-1 |
| `Eowerd24/Artifact-compiler` | `46b1e96` (**not** current `main`) | `v0.3.0` → `v0.3.4` in S3-1 |
| `Eowerd24/ucc-contracts` | tag `v0.3.5` (= v0.3.4 + optional `ReserveNodeRequest` caller context, OQ-12) | — |

- Each line is a local `stage3-ucc` branch. Delivery is cumulative, order-sensitive
  `git format-patch` series under `outputs/patches/stage3/<repo>/`, each with the six-field
  description (shared rule 1.7–1.8). Pushing branches or opening PRs needs explicit owner
  approval per push.
- Contracts are re-vendored only as the exact `v0.3.4` export set (D8: package + `pyproject.toml`
  + `README.md` + `VENDOR-MANIFEST.md`). That excludes `tests/`, `venv/`, `dist/`, `*.egg-info`
  and stale root `schemas/`. Never hand-edit.
- Full suites run before and after every step, with final verification in fresh clones that have
  the patch series applied.
- When a step's gate closes, update `BASELINE.md` (§7/§8) and the register's open threads in the
  same change.

## 2. Rules carried forward verbatim

Fail closed over fabricate. No trusted-path arbitrary shell and no cross-module canonical writes.
AST fences are never weakened to substring matches. `ucc-contracts` is vendored and pinned, never
hand-edited. Standalone stays usable (additive or fenced relocation only). Six-field format.
Docs stay in lockstep (schema set or gate changes update roadmap and standards in the same change).
