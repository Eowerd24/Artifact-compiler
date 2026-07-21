# UCC Standards & Layout Reference

**Status:** Active digest. Companion to `UCC-Shared-Roadmap-To-Fork.md`.
**Purpose:** One condensed, precedence-resolved reference for everything being standardized now — formats, IDs, envelopes, lifecycles, layouts, permissions, retention, security floor. Vendored identically into all three repos.
**Precedence:** 1-of-2 → 2-of-2 → Part-G → UCC-Remaining-Baseline → roadmap → SPEC-001 → drafts. Where an older doc shows a different tree or field name, the version here is the locked one.

> This is a lookup sheet, not a spec. Rationale, edge cases, and evidence live in the source docs. `ucc-contracts` is the executable form of everything below; if code and this sheet disagree, the pinned `ucc-contracts` version wins.

---

## 1. Formats & serialization

| Use | Format | Rule |
|---|---|---|
| Canonical machine state | JSON | UTF-8; one document per entity |
| Append-only events | JSONL | one event per line; producer owns sequence |
| Human config | TOML | secret **references** only, never values |
| Timestamps | RFC 3339 UTC | fractional seconds, `Z` (`2026-07-12T12:00:00.000Z`) |
| Hashes | `sha256:<64 lowercase hex>` | content-addressed for immutable records |

Every canonical document carries: `schema`, `schema_version` (integer major), `id` (prefixed ULID), `created_at`, `created_by`, `record_version`. Immutable records stay at `record_version: 1`; mutable records increment it. Unsupported `schema_version` fails explicitly — never guessed. Security-sensitive requests reject unknown fields.

---

## 2. Identifiers

Form: `<lowercase-prefix>_<26-char uppercase Crockford ULID>` (e.g. `job_01K0A6R4V8W6E3M4M8Y0R9J2QX`). Generated once by the canonical owner; case-sensitive; never encode names, paths, hostnames, or business meaning. Display names are mutable, non-unique, non-identifying. Legacy names survive as aliases.

| act_ actor | art_ artifact | rev_ artifact revision | col_ collection | pub_ publication |
|---|---|---|---|---|
| **host_** host | **img_** image | **snap_** snapshot | **node_** node | **nalloc_** node allocation |
| **prj_** project | **job_** job | **asn_** assignment | **exec_** execution | **xfer_** transfer |
| **hb_** handback | **rpt_** report | **cred_** credential lease | **evt_** event | **op_** operation |
| **req_** request | **res_** result | **corr_** correlation | | |

References are `{ "kind": "job", "id": "job_..." }`; immutable-content references add `"content_hash": "sha256:..."`.

---

## 3. Paths & hashing

Relative POSIX only. Rejected everywhere: absolute paths, `.`, `..`, empty components, backslashes, NULs, control characters. No symlinks / devices / FIFOs / sockets / hardlink aliases in executable bundles. Manifest entries sorted by UTF-8 byte order of `path`; duplicate paths refused. A revision's `content_hash` is SHA-256 over the canonical serialized `content-manifest.json` bytes; mutable metadata (title, tags, approval, publication) is **not** in the content hash. Entrypoint + interpreter come from the execution request, never inferred from a filename.

---

## 4. Shared envelopes (condensed)

All from `ucc-contracts`. Field lists are the minimum required set.

**Request** `ucc.request` — `request_id, operation_id, correlation_id, causation_id?, idempotency_key, request_fingerprint, requested_at, requested_by, operation_type, payload`. `additionalProperties: false`.

**Result** `ucc.result` — `result_id, request_id, operation_id, correlation_id, completed_at, disposition, resource, warnings[]`.
`disposition ∈ { accepted | completed | refused | failed | partial | cancelled | unknown }`.

**Problem** `ucc.problem` — `kind, code, message, retryable, details, remediation, request_id, operation_id, correlation_id`. No stack traces in refusals; details redacted + size-bounded.
`kind ∈ { refusal | validation_error | conflict | dependency_unavailable | operation_failed | outcome_unknown | security_violation }`.

**Event** `ucc.event` — `event_id, event_type (past-tense fact), occurred_at, recorded_at, producer.module_id, actor, subject, operation_id, request_id, correlation_id, causation_id, producer_sequence, payload`. No global ordering; no secrets/large bodies in payloads; corrections are new events.

**Module registration** `ucc.module-registration` — `module_id, display_name, module_version, adapter_kind, enabled, supported contract versions, capabilities, canonical root, health timeout`.
`health ∈ { healthy | degraded | unavailable | incompatible | disabled }`.

CLI exit codes: `0` ok/accepted · `1` unexpected failure · `2` typed refusal / invalid request · `3` conflict/idempotency mismatch · `4` dependency unavailable / outcome unknown · `130` cancelled.

---

## 5. Lifecycle axes (never one global `status`)

Phase and outcome are always separate axes. Health is an observation with timestamp + freshness, never a lifecycle state.

**The nine machines** (owner in brackets; full tables in `ucc-contracts/transitions/`):

```text
Job [UCC]            created → queued → dispatching → running → collecting → terminal
Assignment [UCC]     requested → accepted|refused → active → releasing → released
NodeAllocation [VMF] reserved → active → releasing → released      (exc: refused|expired|lost)
Execution [VMF]      accepted → staging → ready → running → finalizing → completed
Transfer [VMF]       created → receiving|sending → validating → validated → semantic_review
                       → accepted|rejected|quarantined → promoted → closed
Handback [VMF]       candidate → committed_on_node → collecting → collected → validating
                       → verified|rejected → acknowledged
CredentialLease[VMF] requested → active → cleanup_pending → closed
                       (exc: refused|expired_unverified|cleanup_failed|quarantined)
Publication [AC]     published → withdrawn
Quarantine           not_quarantined → quarantined → release_requested
                       → released|reset_required|destroyed
```

Outcomes: Job `succeeded|failed|cancelled|partial|unknown`; Execution `succeeded|failed|cancelled|timed_out|lost|refused|unknown`. After `execution_started`, a retry creates a **new** execution ID (`retry_of`). `unknown` is reconciled only by a new event — never auto-replayed.

**Artifact-revision governance** is four independent projections, not one field:
`verification: not_required|pending|passed|failed|expired` · `review: not_requested|pending|changes_requested|accepted` · `approval: unapproved|approved|revoked` · `publication: unpublished|published|withdrawn`.

**Node axes:** `provisioning_phase · runtime_state · readiness · allocation_phase · health · lifecycle` (all separate).

---

## 6. Naming — overloaded terms → standard terms

| Don't use | Use |
|---|---|
| `state` / `status` (generic) | named axes: `provisioning_phase`, `runtime_state`, `readiness`, `allocation_phase`, `health`, `outcome` |
| `approved` (directory/tier) | `ApprovalRecord` + separate `PublicationRecord` |
| `payload` (ambiguous) | `ArtifactRevision`, `ExecutionBundle`, or `TransferItem` |
| `assignment` (overloaded) | UCC `Assignment` (intent) + VM-Factory `NodeAllocation` (realization) |
| `node` (domain name) | stable `node_id`; display name + provider ref are separate mutable fields |
| `manifest` (unqualified) | qualify it: artifact-content / node / handback / image manifest |
| `ledger` (3 formats) | shared `event stream`; diagnostic logs stay separate |
| `source of truth` (both) | VM-Factory canonical **declaration** vs timestamped hypervisor **observation** |
| `scrub` / `nuke` | `cleanup_requested`, `cleanup_verified`, `provider_revoked`, `closed` |
| `result` (string) | typed `OperationResult` / `ExecutionResult` / `Handback` |

---

## 7. Host dataplane layout (locked — 2-of-2 §F)

```text
UCC_ROOT/
├── config/
├── canonical/          ← module-owned; no cross-writes
│   ├── ucc/                  [UCC]
│   ├── artifact-compiler/    [AC]
│   └── vm-factory/           [VMF]
├── materials/          [UCC]   sources/ repositories/ workspaces/ checkpoints/ collections/
├── exchange/           [UCC]   raw/ validated/ rejected/ quarantine/ staging/ receipts/ promotions/
├── catalog/            [UCC]   commands/ command-collections/ aliases/
├── module-assets/
│   └── vm-factory/     [VMF]   provisioners/ bootstrap/ cloud-init/ image-templates/
│                               domain-templates/ network-templates/ node-helper/ maintenance/
├── large-data/                 vm-images/ snapshots/ repository-mirrors/ object-store/
├── projections/        [UCC]   disposable (SQLite)
├── events/                     per-producer JSONL, rotated monthly
├── logs/  recovery/  cache/  run/  tmp/
```

Ownership: UCC writes `canonical/ucc`, `materials`, `exchange`, `catalog`, projections, its event stream. AC writes only `canonical/artifact-compiler` + its stream. VMF writes `canonical/vm-factory`, `module-assets/vm-factory`, node-transfer state, large-data metadata + its stream. Cross-boundary movement is by immutable reference, validated transfer, explicit promotion, or typed request only. Large objects are referenced by typed store-relative records (`store_id`, `object_kind`, `object_id`, `relative_path`, `size`, `sha256`, `availability`) — never absolute paths; missing storage is `offline`/`degraded`, never deletion.

*(SPEC-001 §F.2 shows an older `data/{controller,artifacts,factory}` tree — superseded by the above.)*

---

## 8. Node dataplane layout (locked — Part-G)

```text
NODE_ROOT/
├── identity/  control/  assignments/  payloads/  executions/
├── inbox/  outbox/  reports/  receipts/  credentials/
├── health/  logs/  recovery/  quarantine/  tmp/  run/

executions/<exec_id>/
├── request.json  request.sha256  state.json
├── work/  outputs/  stdout.log  stderr.log
├── result.partial.json  result.json  COMPLETE
```

Allowed execution input kinds (exactly one): `published_artifact_revision` | `workspace_checkpoint` | `vm_factory_operational_asset`. Explicit interpreter + argv; no controller shell interpolation; non-root by default; bounded env/cwd/runtime/logs/outputs/processes/tmp.

**Receipts (append-only, node lifetime):** `assignment_received, assignment_accepted, payload_received, payload_verified, execution_received, execution_validated, execution_starting, execution_started, execution_finished, result_committed, handback_committed, credential_cleanup_verified`.

Snapshot revert that can roll back control state → **new node ID** in Phase 1 (never silently continue). Uncertain credential cleanup → quarantine. Destruction preserves node tombstone + history.

---

## 9. Path mappings

| Category | Dev (`nodectl/.ucc-dev/`, git-ignored) | XDG user install | Future system |
|---|---|---|---|
| config | `.ucc-dev/config/` | `~/.config/ucc/` | `/etc/ucc/` |
| canonical/materials/catalog | `.ucc-dev/canonical` … | `~/.local/share/ucc/` | `/var/lib/ucc/` |
| state (exchange/events/logs/recovery) | `.ucc-dev/…` | `~/.local/state/ucc/` | `/var/lib/ucc/state/`, `/var/log/ucc/` |
| cache | `.ucc-dev/cache/` | `~/.cache/ucc/` | `/var/cache/ucc/` |
| runtime | `.ucc-dev/run/` | `$XDG_RUNTIME_DIR/ucc/` | `/run/ucc/` |

Node install (dedicated `ucc-worker` account): `/etc/ucc-node/`, `/var/lib/ucc-node/`, `/var/log/ucc-node/`, `/run/ucc-node/`. Large data redirects independently via `large_data_root`. Domain code resolves logical categories through a path resolver — never hard-codes XDG or `/var`. Tests always get an isolated root; never the shared dev root or real XDG paths.

---

## 10. Permissions (defaults)

```text
config dirs 0750 · canonical dirs 0750 · canonical files 0640 · events/logs 0640
exchange/raw 0700 · exchange/quarantine 0700 · runtime dirs 0700 · secret material 0600
```

The web process gets no direct handle to secret values, hypervisor sockets, or personal SSH keys. Public artifact publication is an explicit separate export, never implicitly world-readable.

---

## 11. Retention (defaults, reference-aware)

| Host data | Retention | Node data | Retention |
|---|---|---|---|
| successful raw transfer | 24 h | Handback awaiting ack | indefinite |
| failed/rejected raw | 7 d | acknowledged Handback | 14 d |
| validated but unpromoted | 7 d | execution logs | 14 d |
| workspace checkpoints | while referenced | successful payload staging | assignment lifetime |
| repository mirrors | while registered | failed/rejected input | 12 d / quarantine |
| VM images/snapshots | VMF policy | receipts | node lifetime |
| logs | 14 d / size cap | credential material | immediate cleanup |
| quarantine | manual review | tmp | disposable |
| canonical + tombstones + audit | indefinite | | |

Nothing is removed while a retained Project/Job/Execution/Material/Artifact/Handback references it. Every deletion writes a receipt.

---

## 12. Configuration & secrets

Precedence: `CLI option > operation env var > module env var > user config > system config > built-in default`. Env prefixes: `UCC_`, `ARTIFACT_COMPILER_`, `VM_FACTORY_`, `UCC_NODE_`. `config show --effective --redacted` reports each value + its source. Unknown keys fail startup unless under an explicit `extensions` table. Secrets are never read from ordinary config fields — config holds references; values come from an external provider into a protected path, `0600`, deleted after use. Diagnostic output is redacted.

---

## 13. Ports (the only cross-module seam)

**ArtifactPort** — `get_revision · resolve_publication · verify_execution_eligibility · create_script_revision · approve_revision · publish_revision · withdraw_publication`.

**FactoryPort** — `list_eligible_nodes · reserve_node · release_node · request_execution · get_execution · collect_handback · cancel_execution · reset_node · quarantine_node · get_node_health`.

In-process adapter by default; tested CLI adapter is the fallback and must satisfy the same DTO contract. Content handoff is an immutable store-relative reference, never a live workspace path. Cancellation reports `cancel_requested | already_terminal | refused | unknown` and never claims termination before observation. Refusal codes are partitioned per port in `ucc-contracts` (`ARTIFACT_PORT_CODES` / `FACTORY_PORT_CODES`).

---

## 14. Catalog & asset kinds

Command implementation kinds: `ucc_builtin | published_artifact_revision | vm_factory_operation | external_adapter`. Catalog entries never hold arbitrary shell strings; artifact-backed commands pin Artifact + Revision + Publication + content hash + entrypoint; parameters validated by JSON Schema.

VM-Factory asset source kinds: `packaged | operator_material | repository_snapshot | generated`. Every operation records the exact asset ID + version + content hash used. General workload scripts do not belong in the factory catalog.

---

## 15. Security floor (non-negotiable invariants)

- Dedicated UCC/VM-Factory SSH identity; host keys explicitly pinned. **No** personal `~/.ssh` mount, `AutoAddPolicy`/`accept-new`, or `UserKnownHostsFile=/dev/null`.
- Typed operations only in trusted paths. **No** `run(command: str)` or `fire_script(path, args)` reachable by automation. Any terminal is operator-only, separately audited, never port-reachable.
- Credentials are time- and purpose-bounded leases; secret values stay external; cleanup requires evidence; uncertain cleanup quarantines the node.
- **Fail-closed:** never fabricate tokens or fall back to ambient env for unknown references (refuse instead).
- Dry run mutates no canonical state and appends no canonical audit event.
- Every mutation carries request ID + idempotency key + fingerprint + correlation (+ optional causation) and a durable result; reused key with a different body is refused; identical replay returns the stored result.
- No automatic replay under ambiguous outcomes (`unknown`).
- Filesystem writes: path containment + atomic commit (temp → fsync → replace → fsync parent) + locking + explicit recovery. Archive extraction rejects traversal, links, devices, sockets, and unsafe size/count.
- Destruction preserves tombstones and audit evidence.

---

## 16. Locked conflict resolutions (pinned in `ucc-contracts`)

| Point | Chosen |
|---|---|
| Result envelope | `ucc.result` (not `ucc.operation-result`) |
| Event producer key | `producer.module_id` (not `producer.module`) |
| Project prefix | `prj_` (not `proj_`) |
| ID scheme | prefixed Crockford ULID (not UUIDv7) |
| Transfer lifecycle | UCC-Remaining-Baseline §3 state set |
| Host layout | 2-of-2 §F tree (not SPEC-001 §F.2) |
| Node layout | Part-G tree (not SPEC-001 §G.2) |

---

## 17. Required schemas (Phase 0 close)

**Present in `ucc-contracts`:** `common, request, result, problem, event, module-health, artifact-content-manifest, publication, execution-request`.

**Queued (each needs valid + invalid fixtures):** `ucc.transfer, ucc.transfer-receipt, ucc.promotion, ucc.material, ucc.repository, ucc.repository-snapshot, ucc.workspace, ucc.workspace-checkpoint, ucc.material-collection, ucc.command-definition, ucc.vm-factory-asset, ucc.large-data-reference`, plus domain records `ucc.project, ucc.job, ucc.assignment, ucc.node, ucc.node-manifest, ucc.node-allocation, ucc.execution, ucc.handback, ucc.report, ucc.credential-lease, ucc.health-observation, ucc.quarantine, ucc.artifact, ucc.artifact-revision, ucc.verification, ucc.approval`.

Every schema ships with valid, invalid, path-traversal, hash-mismatch, and unsupported-version fixtures, plus contract tests in each repo where relevant.
