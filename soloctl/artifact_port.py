"""ArtifactPort adapter (G3, roadmap §4B "ArtifactPort adapter").

Thin, in-process adapter over soloctl's service functions — no new
transport, CLI parity kept (UCC-Standards §13). This is the ONLY seam a
future nodectl consumer may use to reach Artifact Compiler; nothing here
grows arbitrary shell or lets a caller reach soloctl's domain code directly.

Every method below returns a typed `DEPENDENCY_UNAVAILABLE` refusal today.
That is not a placeholder bug: AC has no Artifact/ArtifactRevision/
Publication record store yet ("Minimal artifact records" is a separate,
larger roadmap item — see soloctl's own HANDOFF_NOTES). Fabricating a fake
revision id, content hash, or publication state to make a method "succeed"
would violate the same fail-closed principle as the vault fix in VM-Factory
(never invent an answer you don't actually have). This adapter exists so
the port seam and its refusal-shape contract are exercised now, with a
real, Protocol-conformant implementation ready for nodectl to call — swap
the method bodies once the record model lands, keep the signatures.
"""
from __future__ import annotations

from typing import Any

from ucc_contracts.ports import ArtifactPort, EligibilityRequest, EligibilityResult, PortResult, RefusalCode

_NOT_YET_BUILT = (
    "Artifact Compiler has no Artifact/ArtifactRevision/Publication record "
    "store yet; this ArtifactPort method cannot be served."
)


def _validation_refusal(message: str) -> PortResult:
    return PortResult(ok=False, disposition="refused",
                      refusal_code=RefusalCode.VALIDATION_ERROR,
                      message=message, retryable=False)


def _dependency_unavailable() -> PortResult:
    return PortResult(ok=False, disposition="refused",
                      refusal_code=RefusalCode.DEPENDENCY_UNAVAILABLE,
                      message=_NOT_YET_BUILT, retryable=True)


def _require_keys(request: dict, *keys: str) -> PortResult | None:
    missing = [k for k in keys if k not in request]
    if missing:
        return _validation_refusal(f"missing required field(s): {', '.join(missing)}")
    return None


class SoloctlArtifactPort:
    """Concrete ArtifactPort. `isinstance(SoloctlArtifactPort(), ArtifactPort)`
    holds via the Protocol's structural check (see tests/test_artifact_port.py)."""

    def get_revision(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "revision_id")
        return refusal or _dependency_unavailable()

    def resolve_publication(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "publication_id")
        return refusal or _dependency_unavailable()

    def verify_execution_eligibility(self, request: EligibilityRequest) -> EligibilityResult:
        return EligibilityResult(eligible=False, refusal_code=RefusalCode.DEPENDENCY_UNAVAILABLE)

    def create_script_revision(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "artifact_id", "content")
        return refusal or _dependency_unavailable()

    def approve_revision(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "revision_id")
        return refusal or _dependency_unavailable()

    def publish_revision(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "revision_id", "channel")
        return refusal or _dependency_unavailable()

    def withdraw_publication(self, request: dict) -> PortResult:
        refusal = _require_keys(request, "publication_id")
        return refusal or _dependency_unavailable()


def build_artifact_port() -> ArtifactPort:
    return SoloctlArtifactPort()
