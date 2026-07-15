# UCC Shared Roadmap — Standalone Conformity to First Fork

**Status:** Active. Shared by `nodectl`, `Artifact-compiler`, and `VM-Factory`.
**Supersedes:** Roadmap 1 (Phase 0 Contracts and Conformity) — folds it in and extends it through the fork gate.
**Evidence cutoff:** 2026-07-13 (re-verified against each repo's HEAD).
**Precedence for any conflict:** 1-of-2-Decisions → 2-of-2-Decisions → Part-G/G-Context → UCC-Remaining-Baseline → this roadmap → SPEC-001 → older drafts.

This is one file, vendored identically into all three repositories (recommended path `docs/roadmap/UCC-Shared-Roadmap-To-Fork.md`). It defines a **shared spine**, three **repo lanes**, and **shared gates** the repos cross together. No repo advances a shared gate alone. Every repo stays independently runnable at every gate.

This roadmap does **not** build the UCC product. It gets all three repos to a conformant standalone baseline, tags the preserved line, and takes the first steps onto the UCC integration line. The full vertical proof and the real-VM run (KI-001) are a later roadmap.

---

## 0. Where we are now (verified 2026-07-15, G1–G4/M-a/M-b/M-c session)

Baselines re-cloned and re-run today; all green. G0–G4 are all done; the fork gate (§6) is next:

| Repo | Tests | Notes |
|---|---|---|
| `nodectl` | **98** pass | 95 pre-audit + ambiguity/in-flight regression + vendor-export guard + governing-doc presence guard. |
| Artifact Compiler | **164** pass | 161 pre-audit + ambiguity/in-flight regression + vendor-export guard + governing-doc presence guard. |
| VM-Factory | **98** pass | 91 pre-audit + ambiguity/in-flight regression + four validation-before-refusal cases + vendor-export guard + governing-doc presence guard. |
| `ucc-contracts` | **49** pass | v0.2.0's 48 contract tests + D8 vendor-manifest packaging guard. |

**Already done and delivered:**

- `ucc-contracts` package (schemas + fixtures + 9 lifecycle tables + `ArtifactPort`/`FactoryPort` DTOs + refusal-code registry). Five priming-doc conflicts resolved and pinned by tests/fixtures (see §2).
- Two "fail-open is unacceptable" patches, applied to clones and tested, delivered as `.patch` files:
  - Artifact Compiler: dry-run no longer appends a refused audit event on secret detection; real runs still audit.
  - VM-Factory: vault refuses unknown references instead of fabricating a dummy token; explicit `mock:`/`env:` preserved.

**What inspection corrected vs SPEC-001 (so the lanes below are scoped to reality, not the stale evidence):**

- `nodepanel` is retired; `nodectl` exists and does not carry NodePanel's git lineage.
- `nodectl` already has: a real `create_app()` backend (no placeholder), paramiko `RejectPolicy()` + pinned `known_hosts` + shlex list-argv (no `AutoAddPolicy`, no `/dev/null`, no shell-string exec), deploy-key git credentials. `fire_script`/`run_terminal_command` are gone. So its lane is lighter than Roadmap 1 assumed.
- Artifact Compiler `main` now exists (same commit as the feature branch; default is still the feature branch).
- VM-Factory security findings other than the vault fix are unchanged.

---

## 0.5. Locked decisions (D1–D6)

`AGENTS.md`/`CLAUDE.md` in each repo reference this table; it is formalized here so it stops being implicit. Do not re-litigate these silently — if one needs to change, change it here first.

| # | Decision |
|---|---|
| **D1** | **Fork scope is narrow.** The fork tags a clean, envelope-aware, standalone `nodectl` with consumed port *stubs*. Real canonical records, real port behavior, and the ~26 domain schemas are Stage 2 (post-fork) — not fork blockers. No UCC product, no repo merge, no broker/network service/canonical DB, no real cross-module adapters before the fork. |
| **D2** | **Idempotency is a pure decision helper + per-owner storage**, not a shared service. `ucc-contracts` ships `evaluate_idempotency()` (new/replay/conflict given an optional stored record) and `idempotency_conflict_problem()` — no I/O. Each repo owns its SQLite table under its own state root. The owner layer extends the pinned helper with `IN_FLIGHT`: commit `disposition: unknown` before dispatch, replace it on success, remove it on definite failure, retain it under ambiguity until operator reconciliation. This is canonical evidence (backed up), not a disposable projection; there is no auto-expiry. |
| **D3** | **`ucc-contracts` is a real, independently-versioned git repo**, not a bundle of files re-copied by convention. Tagged releases (`v0.1.0` baseline, `v0.2.0`+); each consuming repo vendors a pinned tag under `third_party/ucc-contracts/` and bumps deliberately. |
| **D4** | **Placeholder subject IDs are documented, not fabricated-and-hidden.** Where a repo has no canonical `art_`/`node_`/… ID yet, event `subject.id` is a *documented placeholder* (deterministic sha256-derived from the name/actor string, matching the ID format but not the eventual real ID) — never a random ID pretending to be canonical. Every repo's README must carry this note before the fork gate closes (§6 item 5). |
| **D5** | **`nodepanel` → `ucc`/`nodectl` identifier rename ships with a dual-accept read window.** Readers keep tolerating the old `nodepanel` tool tag / paths for one transition period; writers switch immediately. No flag day, no silent breakage of anything still emitting the old identifier. |
| **D6** | **`FACTORY_PORT_CODES` gets `node_not_found`.** Landed in `ucc-contracts v0.2.0`; `FactoryPort.get_node_health` now refuses typed (`RefusalCode.NODE_NOT_FOUND`) instead of `refusal_code=None` for an unknown node name. |

---

## 1. The shared model of work

```text
        SHARED SPINE:  ucc-contracts  (authoritative; vendored by all three)
                              │
   ┌──────────────┬───────────┴───────────┬──────────────┐
   │  nodectl     │   Artifact Compiler    │  VM-Factory  │   ← three lanes
   └──────┬───────┴───────────┬────────────┴──────┬───────┘
          │                   │                   │
      ════╪═══════════════════╪═══════════════════╪════  ← shared gates G0..G4
          │                   │                   │        (crossed together)
                         FORK GATE
                              │
                    Stage 2: UCC line  (first steps only)
```

**Rules that hold across every lane and gate:**

1. `ucc-contracts` is the single source of truth for shared meaning. A repo never forks its own copy of an envelope, ID rule, or lifecycle table.
2. Standalone stays usable. Each conformity change is additive or a fenced-off relocation; no repo loses its independent CLI/run path.
3. No trusted-path arbitrary shell, no cross-module canonical writes. Legacy raw-command and direct-infra paths may survive only as clearly fenced standalone diagnostics, never reachable through a port.
4. A shared gate is met only when **all three** repos satisfy it and the shared conformance fixtures (§5) pass in each.

---

## 2. The shared spine — `ucc-contracts`

**As of v0.2.0, `ucc-contracts` is its own git repo (D3)**, tagged (`v0.1.0` baseline, `v0.2.0` current), vendored into all three repos under `third_party/ucc-contracts/` with the version pinned in each repo's README. Previously it was a bundle of files re-copied by convention with no version history of its own — that gap is closed.

**Done (load-bearing core + vertical-proof path):** `common`, `request`, `result`, `problem`, `event`, `module-health`, `artifact-content-manifest`, `publication`, `execution-request` schemas; nine lifecycle tables (job, assignment, node-allocation, execution, transfer, handback, credential-lease, publication, quarantine); `ArtifactPort` + `FactoryPort` DTOs; partitioned `RefusalCode` registry (v0.2.0 adds `node_not_found`, D6); ID/hash/path primitives; idempotency decision helper (v0.2.0, D2 — `evaluate_idempotency()` / `idempotency_conflict_problem()`, pure logic, no storage).

**Locked conflict resolutions (do not re-litigate silently — each is pinned):**

| Point | Chosen (authority) |
|---|---|
| Result envelope | `ucc.result` (not `ucc.operation-result`) |
| Event producer key | `producer.module_id` (not `producer.module`) |
| Project prefix | `prj_` (not `proj_`) |
| ID scheme | prefixed Crockford ULID (not UUIDv7) |
| Transfer lifecycle | UCC-Remaining-Baseline §3 state set |

**Remaining to author before Phase 0 artifacts fully close** (same pattern: schema + valid + invalid fixtures). These are **not** blockers for the fork of a *standalone* `nodectl`, but they are blockers for the full vertical proof:

`ucc.transfer`, `ucc.transfer-receipt`, `ucc.promotion`, `ucc.material`, `ucc.repository`, `ucc.repository-snapshot`, `ucc.workspace`, `ucc.workspace-checkpoint`, `ucc.material-collection`, `ucc.command-definition`, `ucc.vm-factory-asset`, `ucc.large-data-reference`, and the domain records `ucc.project`, `ucc.job`, `ucc.assignment`, `ucc.node`, `ucc.node-manifest`, `ucc.node-allocation`, `ucc.execution`, `ucc.handback`, `ucc.report`, `ucc.credential-lease`, `ucc.health-observation`, `ucc.quarantine`, `ucc.artifact`, `ucc.artifact-revision`, `ucc.verification`, `ucc.approval`.

**Consumption rule:** each repo vendors a pinned version (copy under `third_party/ucc-contracts/` or a path/VCS dependency pinned to a tag). Bump is deliberate and version-gated; a repo declares which `ucc-contracts` version it conforms to in its own README. `schema_version` is integer-major; unsupported versions fail explicitly, never guessed.

---

## 3. Shared gates (the synchronization points)

| Gate | Meaning | nodectl | Artifact Compiler | VM-Factory | State |
|---|---|---|---|---|---|
| **G0** | Baselines green + contracts core locked | 25 green | 86 green | 14 green | ✅ done |
| **G1** | Security floor: every fail-open / trusted-path hazard closed | route/virsh/terminal fenced ✅ (27 green) | dry-run no-write ✅ (88 green) | vault fail-closed ✅; SSH host-key pinned ✅; string-exec fenced ✅ (25 green) | ✅ done |
| **G2** | Envelope adoption: all three read/write shared request/result/problem/event; pass conformance fixtures (§5) | `ucc.event` dual-write ✅ + `ucc.request`/`result`/`problem` + idempotent replay/conflict on `node_action` ✅ (81 green) | `ucc.event` dual-write ✅ + `ucc.request`/`result`/`problem` + idempotent replay/conflict on `perform_import` ✅ (156 green) | `ucc.event` dual-write ✅ + `ucc.request`/`result`/`problem` + idempotent replay/conflict on `reset_node` ✅ (91 green) | ✅ done — all twelve §5 bullets covered (schema/ID/transition via `tests/contracts/`; idempotent-replay + idempotency-conflict via the M-b dedicated test files per repo) |
| **G3** | Port adapters exist and are the only cross-module seam | `ArtifactPort`+`FactoryPort` stubs consumed in `app.state` ✅ | `ArtifactPort` adapter ✅ (7 methods, honest refusals) | `FactoryPort` adapter ✅ (10 methods; 3 real, `node_not_found` typed as of v0.2.0) | ✅ done — structurally; most methods refuse `DEPENDENCY_UNAVAILABLE` pending record models each lane table tracks separately, that's not a G3 gap |
| **G4** | `nodectl` clean, green, taggable standalone | full §4A (M-c) | (support) | (support) | ✅ M-c complete — nested dup removed, `uploads/` untracked, VMF tombstone + AC fsync done, `nodepanel`→`ucc` rename (D5) done, `.ucc-dev` dev-root isolation + redacted-config/module-health diagnostics + `COMPONENT-MAP.md` done, agent-instruction-file reconciliation (`AGENTS.md`/`CLAUDE.md`/`RULES.md`/`MISSION.md`) done across all three repos |
| **FORK** | Fork gate (see §6) | — | — | — | ⬜ |
| **G5** | First UCC-line steps landed (see §7) | UCC line | consumed via port | consumed via port | ⬜ |

G1 is the safety gate and should be finished first across all three — it is the one gate whose omission is actively dangerous. G2 and G3 can proceed per-lane in parallel once G1 is clear, then converge at G4. G1–G4 are all done; the fork gate (§6) is next.

---

## 4. Repo lanes

Each change is stated as: current evidence / target contract / smallest change / compatibility / tests / fallback.

### 4A. `nodectl` lane (Roadmap WS4)

| Change | Current evidence | Target | Smallest change | Compatibility | Tests | Fallback |
|---|---|---|---|---|---|---|
| Remove nested duplicate | 178 files under `nodectl/nodectl/` (dirty-init copy) | single tree | `git rm -r nodectl/nodectl` | none (dead copy) | startup + route smoke stay green | revert commit |
| Untrack committed uploads | 77 `uploads/**` files incl. 8.8 MB tarball; `.gitignore` omits `uploads/` | no runtime data in Git | add `uploads/` to `.gitignore`; `git rm -r --cached uploads` | none at runtime | route smoke | files stay on disk |
| Retire `nodepanel` identifiers | `Ledger(tool="nodepanel")`, `VALID_TOOL`, `/var/lib/nodepanel`, remote `.ssh/nodepanel*` | `ucc`/`nodectl` naming | rename constants/paths; keep dual-accept read | readers already tolerate extra tools | ledger write/read test | dual-accept window |
| Isolate dev root | mixed runtime state | `.ucc-dev/` isolated, git-ignored; tests use isolated temp roots | add resolver + `.gitignore` | additive | test-isolation test | — |
| Add redacted config + health diagnostics | none surfaced | `config show --effective --redacted`; module-health view/CLI | add read-only diagnostic command/route | additive | diagnostic smoke | — |
| Classify every component | mixed | tag each: ucc-app / presentation / materials-exchange / command-catalog / artifact-adapter / factory-adapter / diagnostic-only / legacy-standalone / remove | add `COMPONENT-MAP.md` + module docstrings | documentation | map lint | — |
| Fence infra paths | `POST /nodes/{n}/action/{a}`; `factory.py` reads `virsh list`/`node.yaml`; terminal WS echo stub | unreachable from any future port; `diagnostic_only`/`legacy_standalone` | keep them out of the port stubs; assert no port imports them | standalone routes unchanged | "no port depends on route/virsh/terminal exec" test | routes remain for standalone |
| Add port + envelope stubs | none | `ArtifactPort`/`FactoryPort` from `ucc-contracts`; shared envelopes | add stub adapters + envelope (de)serialization | additive | contract fixtures run in-repo | — |

Note the two `git rm` deletions are the only destructive steps; both are pure Git-tracking changes (content stays on disk), and both are reversible by revert.

### 4B. Artifact Compiler lane (Roadmap WS5)

Preserve transcript IR, importers, extractor, thin service layer, fixtures, CLI.

| Change | Current evidence | Target | Smallest change | Compatibility | Tests | Fallback |
|---|---|---|---|---|---|---|
| Dry-run no-write | **DONE** (patch) | dry-run appends no audit event; real run still audits | applied | preserves refusal signal | +2 tests (88 total) | patch revert |
| Parent-dir fsync | `atomic.py` fsyncs file, not parent dir | crash-durable replace | add `os.fsync` on the containing dir fd after `os.replace` | none | durability test | — |
| Shared IDs/envelopes | minimal `transcript.import` ledger | emit `ucc.event`; carry request/correlation/causation/operation IDs | add envelope writer alongside legacy ledger | dual-write during transition | event conformance fixtures | keep legacy ledger readable |
| Minimal artifact records | directory-shaped `drafts/approved/...` only | `Artifact`, `ArtifactRevision`, immutable content-manifest, `Publication` records | add records + one create/approve/publish path | additive; directories become projections | hash + eligibility + revoked-publication tests | CLI-only, manual |
| Execution eligibility query | none | `verify_execution_eligibility` returns typed result/refusal | implement over the new records | additive | eligibility + refusal tests | — |
| `ArtifactPort` adapter | none | the seven port methods over service functions | thin adapter, no new transport | in-process; CLI parity kept | port contract tests | CLI adapter |
| `--json` / stable exit envelopes | prose CLI | machine-readable envelopes + documented exit codes | add `--json` and envelope emit | additive | exit-code test | prose default preserved |
| Promote real default branch | default is feature branch; `main` exists at same commit | `main` is the release/default line before anyone pins a dep | set default branch; tag | none | — | — |

### 4C. VM-Factory lane (Roadmap WS6)

Preserve hypervisor/transport interface pattern, mock backend, CLI, payload validator, report parser, lifecycle tests.

| Change | Current evidence | Target | Smallest change | Compatibility | Tests | Fallback |
|---|---|---|---|---|---|---|
| Vault fail-closed | **DONE** (patch) | unknown refs refuse; no fabricated token | applied | explicit `mock:`/`env:` kept | +4 tests (18 total) | patch revert |
| SSH host-key pinning | `transport.py`: `StrictHostKeyChecking=accept-new` + `UserKnownHostsFile=/dev/null` | `StrictHostKeyChecking=yes` + real pinned known-hosts | add a known-hosts config surface; flip the two flags | needs config value (slightly larger than vault fix) | host-key reject test | mock transport unaffected |
| Split overloaded `NodeState` | single enum `provisioned→…→retired` | external axes: provisioning / runtime / readiness / allocation / health / lifecycle | add an external contract adapter; keep internal enum behind it | legacy enum stays internal | axis-mapping test | adapter passthrough |
| Typed execution + allocation | `assign()` = credentialed git-clone; `run_cmd(cmd:str)` | `NodeAllocation` + typed execution acceptance with exact ID/hash validation | add typed ops; route clone through a typed prep op | string exec becomes legacy diagnostic only | duplicate-request + hash-mismatch + wrong-generation tests | standalone CLI keeps legacy |
| Stop owning approval | `PayloadManifest.tier/approved_by/approved_at` | consume Artifact Compiler publication as eligibility | treat tier fields as legacy adapter inputs; check publication | additive | eligibility-from-publication test | legacy fields tolerated |
| Atomic manifests + handbacks | non-atomic manifest writes; unbounded manifest path joins | atomic + locked writes; shared path containment; reject links/special files | reuse shared containment validator; `.partial`+rename | none | malicious-handback + traversal tests | — |
| Credential lease + cleanup evidence | `scrub()`/`nuke()` metadata-only | lease with cleanup receipt; uncertain cleanup → quarantine | add cleanup receipt + quarantine transition | additive | cleanup-failure + quarantine tests | — |
| Tombstone on destroy | `engine.py destroy()` `manifest_path.unlink()` | preserve node tombstone + history | replace unlink with tombstone write | none | destroy-preserves-tombstone test | — |
| `FactoryPort` adapter | none | the ten port methods over the engine | thin adapter | in-process; mock parity kept | port contract tests | CLI adapter |
| Idempotency + envelopes | none | idempotency receipts; shared envelopes | add receipt store + envelope emit | additive | idempotent-replay + conflict tests | — |
| Panel identity | panel also titled "NodePanel" with lifecycle forms | standalone diagnostic harness, not a second UCC | rename + label as diagnostic | UI-only | smoke | — |

---

## 5. Shared conformance test matrix (Roadmap WS7)

Each repo runs the **same** `ucc-contracts` fixtures for: valid serialization; unsupported version refusal; strict unknown-field rejection (security-sensitive requests); ID + hash vectors; idempotent replay; idempotency conflict; typed refusal shape; correlation + causation presence; path traversal rejection; illegal lifecycle transition rejection; unavailable module; incompatible module.

Wiring: each repo adds a `tests/contracts/` that imports the vendored fixtures and asserts its own (de)serialization + validation against them. A repo passes G2 only when this suite is green **and** it neither imports another repo's domain code nor needs a running peer.

---

## 6. Fork gate

Cross only when all of the following hold:

1. G1–G4 met across all three repos; §5 suite green in each.
2. `nodectl` is clean: no nested duplicate, no committed runtime data, no `nodepanel` identifiers in trusted paths, isolated dev root, green startup + route smoke.
3. Only contract/adapter seams were added to `nodectl`; no business logic moved into templates/routes; no trusted-path arbitrary shell; no cross-module canonical writes.
4. `COMPONENT-MAP.md` complete; every component classified; all infra/terminal paths fenced as diagnostic/legacy.
5. Standalone features and limitations documented in each repo's README, including the pinned `ucc-contracts` version.
6. Migration map recorded: current component → future UCC service/port.

**Then tag the preserved standalone line** (this is the legacy line the fork branches from):

```text
nodectl-phase0-conformant-standalone
```

Tag Artifact Compiler and VM-Factory at their conformant commits too (e.g. `phase0-conformant`) so the fork pins exact peers.

---

## 7. Stage 2 — first steps onto the UCC line (bounded)

Per locked decisions, `nodectl` *is* the UCC integration repo and application shell. The "fork" is: preserve the tag above as the standalone/legacy line, then continue UCC integration on the main line (or a `ucc-integration` branch cut from the tag). These are the **first steps only** — enough to stand up the seam, not the vertical proof.

1. **Cut the line.** Branch/continue from `nodectl-phase0-conformant-standalone`. Record the parent tag in the branch's README.
2. **Wire real in-process adapters** behind the `ArtifactPort`/`FactoryPort` stubs, pointing at the conformant Artifact Compiler and VM-Factory (in-process import by default; CLI adapter kept as the tested fallback per locked I.2). No HTTP, no socket, no daemon.
3. **Stand up the disposable SQLite projection builder** reading the three producer event streams; prove delete-and-rebuild reproduces the same view (locked: projections are derived and disposable).
4. **Add the UCC application-service skeleton** owning Project / Job / Assignment / Operation, with idempotency keys and correlation — no cross-module canonical writes; it calls ports only.
5. **One operator surface**: a single HTMX/Jinja operation view (or one CLI command) that renders a correlated, projection-backed operation from fixtures. Reuse `nodectl` presentation assets.
6. **XDG path resolver** wired so nothing hard-codes install paths.

**Explicitly out of Stage 2 (later roadmap):** the full first vertical proof end-to-end, the mandatory failure matrix, and the real disposable-VM run (KI-001). Stage 2 ends when the seam is real, the projection rebuilds, and the skeleton renders one fixture-backed operation.

---

## 8. Dependency-aware ordering

```text
NOW: G0✅ G1✅ G2✅ G3✅ G4✅   ← M-a, M-b, M-c complete
 │
 ├─ REMEDIATION (audit 2026-07-15, NOT FORK-READY)
 │    · F-002 green suites, clean pinned env      [blocker]
 │    · F-007 in-flight/unknown records           [blocks tag]
 │    · F-001 vendor manifest + A6 fix (D8)
 │    · F-003/004✅/005 · mediums · lows · remove candidates
 ├─ RE-AUDIT (AUDIT.md, fresh clones) → FORK-READY
 └─ FORK GATE (§6) → push · tag ×3 · fork nodectl → Eo_org24 (D7) → Stage 2 (§7)
```

Milestones (folded from Roadmap 1): M1 contracts ✅ · M2 lifecycles + DTOs ✅ · M3 G1 ✅ · M4 G2/G3 ✅ · M5 M-a/M-b/M-c ✅ · **M6 remediation + re-audit** · **Fork** · M7 Stage 2.

---

## 9. Guardrails (out of scope until a later roadmap)

No broker, message bus, mandatory network API, or canonical server database. No repo merge. No microservices. No multi-operator auth. No general remote terminal in any trusted/automated path. No dynamic/untrusted code loading. No full Artifact Compiler governance UI. No VM-Factory internal rewrite. Frontend and final deployment topology stay open.

---

## Appendix — current deliverables backing this roadmap

- `ucc-contracts/` — now a real git repo, tags `v0.1.0` (41 tests) and `v0.2.0` (48 tests: +`node_not_found` refusal code, +idempotency helper).
- `patches/artifact-compiler__dry-run-no-write.patch` (AC → 88 tests).
- `patches/vm-factory__vault-fail-closed.patch` (VMF → 18 tests).
- `patches/nodectl__g1-infra-fence.patch` (nodectl → 27 tests; G1 close-out).
- `patches/vm-factory__ssh-host-key-pinning.patch` (VMF → 23 tests; apply after vault patch).
- `patches/vm-factory__string-exec-fence.patch` (VMF → 25 tests; G1 close-out).
- `patches/nodectl__g2-g3-envelopes-and-ports.patch` (nodectl → 76 tests; vendors ucc-contracts, event dual-write, ArtifactPort/FactoryPort stubs).
- `patches/artifact-compiler__g2-g3-envelopes-and-artifact-port.patch` (AC → 148 tests; vendors ucc-contracts, event dual-write, ArtifactPort adapter).
- `patches/vm-factory__g2-g3-envelopes-and-factory-port.patch` (VMF → 85 tests; vendors ucc-contracts, event dual-write, FactoryPort adapter).
- `patches/nodectl__ma-ucc-contracts-v0.2.0.patch`, `patches/artifact-compiler__ma-ucc-contracts-v0.2.0.patch`, `patches/vm-factory__ma-ucc-contracts-v0.2.0.patch` — M-a: re-vendor to v0.2.0 + README version bump; VMF's also fixes `get_node_health` to use the real `NODE_NOT_FOUND` code.
- `patches/nodectl__mb-idempotency.patch` (nodectl → 81 tests; SQLite `idempotency_records` table via migration 003 in the existing `nodepanel.db`, wired into `POST /api/nodes/{node_name}/action/{action}` via an optional `X-Idempotency-Key` header).
- `patches/artifact-compiler__mb-idempotency.patch` (AC → 156 tests; `library/idempotency.db`, wired into `perform_import` via a new `--idempotency-key` CLI option).
- `patches/vm-factory__mb-idempotency.patch` (VMF → 91 tests; `<state_dir>/idempotency.db`, wired into `FactoryPort.reset_node` via an optional `idempotency_key` request field).
- `patches/vm-factory__mc-tombstone-on-destroy.patch` (VMF, still 91 tests — 2 changed in place; `engine.py::destroy()` preserves the manifest as a tombstone instead of `unlink()`-ing it; destroyed nodes now stay visible as `retired` in listings).
- `patches/artifact-compiler__mc-parent-dir-fsync.patch` (AC → 161 tests; `atomic_write_bytes` fsyncs the containing directory after `os.replace`).
- `patches/nodectl__mc-uploads-gitignore.patch` (nodectl, still 81 tests; adds `uploads/` to `.gitignore`) — **apply together with** two documented one-line commands (not patches — the deleted binary files hit the same blob-hash issue VM-Factory's `.pyc` files did): `git rm -r nodectl` (removes the confirmed-dead 178-file nested duplicate) and `git rm -r --cached uploads` (untracks 77 files/9.4MB, content stays on disk).
- `patches/nodectl__mc-nodepanel-to-ucc-rename.patch` (nodectl → 86 tests; D5 — `Ledger` writer tag switches to `"nodectl"`, `VALID_TOOL` dual-accepts `"nodepanel"` for the transition window, git-deploy-key remote paths move to `~/.ssh/nodectl/`, `scrub()` removes both the new and legacy `~/.ssh/nodepanel/` path so already-provisioned nodes still get cleaned up. Deliberately out of scope: `factory_user` (a real remote Linux username, renaming it would break already-provisioned nodes), `database_path`/`session_cookie_name`/write-probe filename/CLI `prog=` — none of these are in D5's four-item list, left for a future decision).
- `patches/nodectl__mc-dev-root-isolation-and-diagnostics.patch` (nodectl → 95 tests; the remaining three §4A rows: dev-root isolation — bare local-dev defaults for `data_root`/`staging_root`/`inbox_root`/`ledger_root`/`ucc_events_root`/`database_path`/`ssh_known_hosts_path` now live under one git-ignored `.ucc-dev/` instead of five loose repo-root directories, additive only — every deployed environment already overrides every one of these via env vars; `backend/diagnostics.py` + `cli.py` add `config show --effective --redacted` (secrets always redacted, no un-redacted mode) and `module-health` (a real `ucc.module-registration` record validated against the vendored schema, computed from the same startup check `lifespan()` runs, not a hardcoded "healthy"); `COMPONENT-MAP.md` classifies every component. Also fixed a real deployment gap found while touching these paths: `docker-compose.yml`/`DEPLOYMENT.md` never set `UCC_EVENTS_ROOT` or mounted `./events`, so a production container (`read_only: true` root fs) would fail the moment it tried to write `ucc.jsonl` — added the missing env var + volume mount + doc line alongside the dev-root change since it's the same five-paths reasoning).
- `patches/nodectl__mc-agents-claude-md-reconciliation.patch` (nodectl, still 95 tests, doc-only; final M-c item — closes G4). Replaced the repo's old, pre-UCC `AGENTS.md` (a stale single-purpose "wire the htmx frontend" manual — wrong repo name, wrong route file, `fabric`-only claim) with a trimmed copy of the shared template; added `CLAUDE.md` (didn't exist); rewrote `RULES.md` (two of six original rules were factually wrong — "no database" and "one SSH path only" — corrected, not deleted) and `MISSION.md` (phases 1–3 done, phase 4 superseded by the locked narrow-fork scope); documented all of it in `COMPONENT-MAP.md`. Also fixed the shared root `/UCC/CLAUDE.md` template itself (used nodectl's now-corrected `ledger.py` vendoring claim as its own example — reworded to be accurate for all three repos).
- `patches/artifact-compiler__mc-agents-claude-md.patch` (AC, still 161 tests, doc-only). No `AGENTS.md`/`CLAUDE.md` existed — added both (trimmed template + verbatim copy). `HANDOFF_NOTES.md` reviewed and found to need no changes — it's an accurate WP1/WP2 feature-work record, predates and doesn't touch the UCC ports/fences/envelope work.
- `patches/vm-factory__mc-agents-claude-md.patch` (VM-Factory, still 91 tests, doc-only). Existing `AGENTS.md` was purely generic agent-operating procedure (branch naming, commit hygiene, destructive-action policy) with zero UCC-specific content and several stale claims (absolute `/home/sarge/Desktop/AI-Factory/VM-Factory/...` paths that don't match any real clone location; "no runnable application wrapper exists yet", false — `panel/main.py` is a real FastAPI app) — merged the shared UCC template in front of it, corrected the stale claims in place, kept the still-valid generic-hygiene content as a clearly separated section. Flagged (not rewritten) a large pre-existing product-vision corpus (`ai-worker-factory-plan.md` 800+ lines, `factory-panel-convergence.md`) with short header notes: repo-convergence work is Stage-2-or-later under the locked roadmap, not authorization to merge repos now; `factory-panel-convergence.md`'s "nodepanel.db + uploads/ out of git" hygiene item is substantially already done on the `nodectl` side this session. Added `CLAUDE.md` (didn't exist).
- VM-Factory's 5 tracked `__pycache__/*.pyc` files: also untracked via a documented command (`git rm --cached library/__pycache__/*.pyc tests/__pycache__/*.pyc`), same reason — no reliable binary patch for stale-blob-hash deletions.

G2 closes with these three: each wraps its designated real operation in built+validated `ucc.request`/`ucc.result`/`ucc.problem` envelopes. Each owner commits an in-flight `unknown` row before dispatch; success replaces it, definite failure removes it, and ambiguity retains it. Same-key retry against that retained row refuses `outcome_unknown` without re-execution until operator reconciliation. No in-flight row auto-expires.

All patches are cumulative and order-sensitive per repo (verified against independent fresh clones — never just the working copy used to build them):

- **nodectl:** `g1-infra-fence` → `g2-g3-envelopes-and-ports` → `ma-ucc-contracts-v0.2.0` → `mb-idempotency` → `mc-uploads-gitignore` → (then `git rm -r nodectl` && `git rm -r --cached uploads`) → `mc-nodepanel-to-ucc-rename` → `mc-dev-root-isolation-and-diagnostics` → `mc-agents-claude-md-reconciliation` **(G4 complete)**
- **Artifact Compiler:** `dry-run-no-write` → `g2-g3-envelopes-and-artifact-port` → `ma-ucc-contracts-v0.2.0` → `mb-idempotency` → `mc-parent-dir-fsync` → `mc-agents-claude-md` **(G4 complete)**
- **VM-Factory:** `vault-fail-closed` (needs `--exclude='*__pycache__*'`) → `ssh-host-key-pinning` → `string-exec-fence` → `g2-g3-envelopes-and-factory-port` → `ma-ucc-contracts-v0.2.0` → `mb-idempotency` → `mc-tombstone-on-destroy` → (then `git rm --cached library/__pycache__/*.pyc tests/__pycache__/*.pyc`) → `mc-agents-claude-md` **(G4 complete)**
