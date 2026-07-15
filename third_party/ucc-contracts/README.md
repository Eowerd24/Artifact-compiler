# ucc-contracts

Authoritative shared contracts for the Unified Control Center: JSON Schemas,
canonical envelopes, lifecycle transition tables, ID/hash/path primitives, and
the exact `ArtifactPort` / `FactoryPort` DTOs and refusal codes.

**This package contains no domain services and imports no repository's domain
code.** `nodectl`, Artifact Compiler (`soloctl`), and VM-Factory all depend on
it and must not maintain divergent copies of these primitives (SPEC-001 §E.3,
§C.5; Roadmap WS1/WS3).

## Layout

```
ucc-contracts/
├── ucc_contracts/        importable package (ids, schema, transitions, ports)
│   └── ports/            ArtifactPort, FactoryPort, RefusalCode
├── schemas/              JSON Schema Draft 2020-12
├── fixtures/valid/       one positive fixture per schema
├── fixtures/invalid/     negative fixtures + _index.json (file -> schema)
├── transitions/          nine lifecycle tables as machine-readable JSON
└── tests/                the shared contract test harness (WS7)
```

## How the three repos conform (WS7)

Each repository runs the shared harness against its own serialized output:

```python
from ucc_contracts import validate_document, is_legal_transition, is_valid_id

validate_document("event", my_emitted_event)          # raises on drift
assert is_legal_transition("execution", "ready", "running")
assert is_valid_id(rev_id, expected_prefix="rev")
```

`validate_document(name, doc)` and `is_legal_transition(machine, a, b)` are the
entire conformance surface. Security-sensitive request documents reject unknown
fields (`additionalProperties: false`), so accidental extra fields fail fast.

## Precedence conflicts resolved (verified, not assumed)

The priming set disagrees in places. Per the stated order
(1-of-2 → 2-of-2 → Part-G → UCC-Remaining-Baseline → Roadmap → SPEC-001 →
drafts), the later locked docs win. Concrete resolutions baked into these
contracts:

| Point | Older source | Chosen (authority) |
|---|---|---|
| Result envelope schema name | `ucc.operation-result` (SPEC-001 §E.8) | **`ucc.result`** (UCC-Remaining-Baseline §2.2) |
| Event producer key | `producer.module` (SPEC-001 §E.7) | **`producer.module_id`** (UCC-Remaining-Baseline §2.4). A fixture (`event__legacy_producer_module_key`) pins this. |
| Project ID prefix | `proj_` (shared-data-language draft) | **`prj_`** (SPEC-001 §E.3). Pinned by `test_project_prefix_is_prj_not_proj`. |
| ID generation | UUIDv7 "likely" (shared-data-language draft) | **Prefixed Crockford ULID** (locked Decisions 1-of-2 §1.8) |
| Transfer lifecycle | SPEC-001 §E.6 variant | **UCC-Remaining-Baseline §3** state set |

## Remaining schemas to author (same pattern)

This slice locks the load-bearing core + the vertical-proof path. The following
schemas from Roadmap WS1 / 2-of-2 §F.18 are queued and each needs valid +
invalid fixtures before Phase 0 artifacts close:

`ucc.transfer`, `ucc.transfer-receipt`, `ucc.promotion`, `ucc.material`,
`ucc.repository`, `ucc.repository-snapshot`, `ucc.workspace`,
`ucc.workspace-checkpoint`, `ucc.material-collection`, `ucc.command-definition`,
`ucc.vm-factory-asset`, `ucc.large-data-reference`, plus the domain records
`ucc.project`, `ucc.job`, `ucc.assignment`, `ucc.node`, `ucc.node-manifest`,
`ucc.node-allocation`, `ucc.execution`, `ucc.handback`, `ucc.report`,
`ucc.credential-lease`, `ucc.health-observation`, `ucc.quarantine`,
`ucc.artifact`, `ucc.artifact-revision`, `ucc.verification`, `ucc.approval`.

Already present: `common`, `request`, `result`, `problem`, `event`,
`module-health`, `artifact-content-manifest`, `publication`,
`execution-request`.

## Test

```
pip install -e ".[test]"
pytest -q          # 41 passing
```
