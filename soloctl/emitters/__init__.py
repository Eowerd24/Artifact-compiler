"""Artifact emitters: candidate -> draft content + verification plan.
Pure — no file writes, no tool execution (see base.py)."""
from .base import ArtifactEmitter, EmitContext, VerificationCheck, VerificationPlan
from .registry import (
    BUILTIN_EMITTERS, EmitterAssignment, EmitterRegistry, default_registry,
    registry_from_config,
)

__all__ = [
    "ArtifactEmitter", "EmitContext", "VerificationCheck", "VerificationPlan",
    "BUILTIN_EMITTERS", "EmitterAssignment", "EmitterRegistry",
    "default_registry", "registry_from_config",
]
