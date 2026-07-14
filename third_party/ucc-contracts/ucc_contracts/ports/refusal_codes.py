"""Shared refusal codes for ArtifactPort and FactoryPort.

Authority: UCC-Remaining-Baseline §4-5, §13 (mandatory failure matrix),
SPEC-001 §E.8, and the locked idempotency rules (1-of-2 Decisions §1.25-28).
Refusals are expected, typed, stack-trace-free (ucc.problem kind="refusal").
Codes are stable strings; readers switch on them, not on prose.
"""
from __future__ import annotations

from enum import Enum


class RefusalCode(str, Enum):
    # Cross-cutting
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNKNOWN_FIELD = "unknown_field"
    VALIDATION_ERROR = "validation_error"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SECURITY_VIOLATION = "security_violation"
    ILLEGAL_LIFECYCLE_TRANSITION = "illegal_lifecycle_transition"

    # ArtifactPort
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    REVISION_NOT_FOUND = "revision_not_found"
    ARTIFACT_NOT_PUBLISHED = "artifact_not_published"
    PUBLICATION_WITHDRAWN = "publication_withdrawn"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"
    VERIFICATION_FAILED = "verification_failed"
    APPROVAL_REVOKED = "approval_revoked"
    UNSUPPORTED_ARTIFACT_TYPE = "unsupported_artifact_type"
    ENTRYPOINT_NOT_IN_MANIFEST = "entrypoint_not_in_manifest"

    # FactoryPort
    NO_ELIGIBLE_NODE = "no_eligible_node"
    WRONG_NODE_GENERATION = "wrong_node_generation"
    RESERVATION_EXPIRED = "reservation_expired"
    NODE_QUARANTINED = "node_quarantined"
    NODE_NOT_READY = "node_not_ready"
    UNSAFE_HANDBACK_PATH = "unsafe_handback_path"
    EXECUTION_NOT_FOUND = "execution_not_found"
    ALLOCATION_NOT_FOUND = "allocation_not_found"
    NODE_NOT_FOUND = "node_not_found"


ARTIFACT_PORT_CODES = frozenset({
    RefusalCode.ARTIFACT_NOT_FOUND, RefusalCode.REVISION_NOT_FOUND,
    RefusalCode.ARTIFACT_NOT_PUBLISHED, RefusalCode.PUBLICATION_WITHDRAWN,
    RefusalCode.CONTENT_HASH_MISMATCH, RefusalCode.VERIFICATION_FAILED,
    RefusalCode.APPROVAL_REVOKED, RefusalCode.UNSUPPORTED_ARTIFACT_TYPE,
    RefusalCode.ENTRYPOINT_NOT_IN_MANIFEST,
})

FACTORY_PORT_CODES = frozenset({
    RefusalCode.NO_ELIGIBLE_NODE, RefusalCode.WRONG_NODE_GENERATION,
    RefusalCode.RESERVATION_EXPIRED, RefusalCode.NODE_QUARANTINED,
    RefusalCode.NODE_NOT_READY, RefusalCode.UNSAFE_HANDBACK_PATH,
    RefusalCode.EXECUTION_NOT_FOUND, RefusalCode.ALLOCATION_NOT_FOUND,
    RefusalCode.NODE_NOT_FOUND,
})
