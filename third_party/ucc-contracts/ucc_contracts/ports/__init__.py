"""Exact port contracts: ArtifactPort and FactoryPort.

These are contract-only Protocols plus request/response DTOs. The shared
package contains NO domain services (Roadmap WS3). nodectl accesses Artifact
Compiler only through ArtifactPort and VM-Factory only through FactoryPort
(UCC-Remaining-Baseline §4-5). Adapters (in-process or CLI) implement these;
neither port may expose arbitrary shell execution or direct cross-module
canonical writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from .refusal_codes import (
    RefusalCode,
    ARTIFACT_PORT_CODES,
    FACTORY_PORT_CODES,
)

__all__ = [
    "RefusalCode", "ARTIFACT_PORT_CODES", "FACTORY_PORT_CODES",
    "ArtifactPort", "FactoryPort",
    "RevisionRef", "PublicationRef", "EligibilityRequest", "EligibilityResult",
    "ReserveNodeRequest", "ExecutionRequestEnvelope", "CollectHandbackRequest",
    "PortResult",
]


# --- Shared value objects -------------------------------------------------

@dataclass(frozen=True)
class RevisionRef:
    artifact_id: str
    revision_id: str
    content_hash: str


@dataclass(frozen=True)
class PublicationRef:
    publication_id: str
    revision_id: str
    channel: str  # only "execution" in Phase 1


@dataclass(frozen=True)
class PortResult:
    """Uniform port return. Either ok with a value, or a typed refusal.

    Refusals map onto ucc.problem (kind="refusal"); errors are raised, not
    returned. `retryable` never authorizes blind execution replay.
    """
    ok: bool
    disposition: str  # accepted|completed|refused|failed|partial|cancelled|unknown
    value: Optional[dict] = None
    refusal_code: Optional[RefusalCode] = None
    message: str = ""
    retryable: bool = False


# --- ArtifactPort ---------------------------------------------------------

@dataclass(frozen=True)
class EligibilityRequest:
    revision_id: str
    content_hash: str
    channel: str
    entrypoint: str


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    revision: Optional[RevisionRef] = None
    publication: Optional[PublicationRef] = None
    refusal_code: Optional[RefusalCode] = None


@runtime_checkable
class ArtifactPort(Protocol):
    """SPEC-001 §4 / UCC-Remaining-Baseline §4. Content handoff is always an
    immutable store-relative reference, never a live Workspace path."""

    def get_revision(self, request: dict) -> PortResult: ...
    def resolve_publication(self, request: dict) -> PortResult: ...
    def verify_execution_eligibility(self, request: EligibilityRequest) -> EligibilityResult: ...
    def create_script_revision(self, request: dict) -> PortResult: ...
    def approve_revision(self, request: dict) -> PortResult: ...
    def publish_revision(self, request: dict) -> PortResult: ...
    def withdraw_publication(self, request: dict) -> PortResult: ...


# --- FactoryPort ----------------------------------------------------------

@dataclass(frozen=True)
class ReserveNodeRequest:
    assignment_id: str
    capability_requirements: list[str]
    freshness_limit_seconds: int
    idempotency_key: str
    reservation_ttl_seconds: int = 600
    preferred_node_id: Optional[str] = None


@dataclass(frozen=True)
class ExecutionRequestEnvelope:
    """Wraps a validated ucc.execution-request document (validated against the
    schema before it reaches the port)."""
    document: dict
    idempotency_key: str


@dataclass(frozen=True)
class CollectHandbackRequest:
    execution_id: str
    idempotency_key: str


@runtime_checkable
class FactoryPort(Protocol):
    """SPEC-001 §5 / UCC-Remaining-Baseline §5. Public staging is not exposed
    in Phase 1; request_execution validates the allocation + exact input,
    creates the Execution, and stages internally. cancel_execution never
    claims termination before observation."""

    def list_eligible_nodes(self, request: dict) -> PortResult: ...
    def reserve_node(self, request: ReserveNodeRequest) -> PortResult: ...
    def release_node(self, request: dict) -> PortResult: ...
    def request_execution(self, request: ExecutionRequestEnvelope) -> PortResult: ...
    def get_execution(self, request: dict) -> PortResult: ...
    def collect_handback(self, request: CollectHandbackRequest) -> PortResult: ...
    def cancel_execution(self, request: dict) -> PortResult: ...
    def reset_node(self, request: dict) -> PortResult: ...
    def quarantine_node(self, request: dict) -> PortResult: ...
    def get_node_health(self, request: dict) -> PortResult: ...
