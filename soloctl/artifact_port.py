"""Real in-process ArtifactPort over Artifact Compiler canonical records (S2-1)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ucc_contracts import is_valid_id
from ucc_contracts.idempotency import IdempotencyOutcome, evaluate_idempotency
from ucc_contracts.ports import (
    ArtifactPort,
    EligibilityRequest,
    EligibilityResult,
    PortResult,
    PublicationRef,
    RefusalCode,
    RevisionRef,
)

from .artifact_store import ArtifactRecordStore, ArtifactStoreRefusal, now_iso
from .idempotency_store import IdempotencyStore, request_fingerprint
from .library.paths import LibraryPaths
from .ucc_events import emit_event


def _refusal(
    code: RefusalCode, message: str, *, retryable: bool = False
) -> PortResult:
    return PortResult(
        ok=False,
        disposition="refused",
        refusal_code=code,
        message=message,
        retryable=retryable,
    )


def _serialize_result(result: PortResult) -> dict:
    return {
        "ok": result.ok,
        "disposition": result.disposition,
        "value": result.value,
        "refusal_code": (
            result.refusal_code.value if result.refusal_code is not None else None
        ),
        "message": result.message,
        "retryable": result.retryable,
    }


def _deserialize_result(value: dict) -> PortResult:
    code = value.get("refusal_code")
    return PortResult(
        ok=bool(value["ok"]),
        disposition=value["disposition"],
        value=value.get("value"),
        refusal_code=RefusalCode(code) if code else None,
        message=value.get("message", ""),
        retryable=bool(value.get("retryable", False)),
    )


class SoloctlArtifactPort:
    """ArtifactPort backed by one configured Artifact Compiler owner root."""

    def __init__(
        self,
        library_root: Path | None = None,
        *,
        canonical_root: Path | None = None,
    ):
        root = (library_root or (Path.cwd() / "library")).resolve()
        self.paths = LibraryPaths(root)
        owner_root = canonical_root or self.paths.resolve(
            "canonical", "artifact-compiler"
        )
        self.records = ArtifactRecordStore(owner_root)

    def _read(self, action: Callable[[], dict]) -> PortResult:
        try:
            value = action()
        except ArtifactStoreRefusal as exc:
            return _refusal(exc.code, str(exc), retryable=exc.retryable)
        return PortResult(ok=True, disposition="completed", value=value)

    def _mutation(
        self,
        request: dict,
        *,
        operation_type: str,
        action: Callable[[], dict],
        event_type: str,
        subject_kind: str,
        subject_id: Callable[[dict], str],
        event_payload: Callable[[dict], dict],
    ) -> PortResult:
        for field, prefix in (("created_by", "act"), ("operation_id", "op"),
                              ("request_id", "req"), ("correlation_id", "corr")):
            value = request.get(field)
            if field == "created_by" or value is not None:
                if not isinstance(value, str) or not is_valid_id(value, expected_prefix=prefix):
                    return _refusal(
                        RefusalCode.VALIDATION_ERROR,
                        f"{field} must be a canonical {prefix}_ identifier",
                    )

        key = request.get("idempotency_key")
        if not isinstance(key, str) or not key:
            return _refusal(
                RefusalCode.VALIDATION_ERROR,
                "idempotency_key must be a non-empty string",
            )

        payload = {name: value for name, value in request.items() if name != "idempotency_key"}
        fingerprint = request_fingerprint(
            {"operation_type": operation_type, "payload": payload}
        )
        store = IdempotencyStore(self.paths.idempotency_db)
        try:
            stored = store.get(key)
            outcome = evaluate_idempotency(key, fingerprint, stored)
            if outcome == IdempotencyOutcome.CONFLICT:
                return _refusal(
                    RefusalCode.IDEMPOTENCY_CONFLICT,
                    "idempotency_key was already used with different inputs",
                )
            if outcome == IdempotencyOutcome.REPLAY:
                if stored is not None and stored.disposition == "unknown":
                    return _refusal(
                        RefusalCode.OUTCOME_UNKNOWN,
                        "a prior mutation has an unknown outcome; reconcile before retrying",
                    )
                assert stored is not None
                return _deserialize_result(stored.result)

            store.put_in_flight(
                idempotency_key=key,
                fingerprint=fingerprint,
                operation_type=operation_type,
                created_at=now_iso(),
            )
            try:
                value = action()
            except ArtifactStoreRefusal as exc:
                store.delete(key)
                return _refusal(exc.code, str(exc), retryable=exc.retryable)

            result = PortResult(ok=True, disposition="completed", value=value)
            actor_id = request["created_by"]
            emit_event(
                self.paths.ucc_events_file,
                event_type=event_type,
                payload=event_payload(value),
                actor_id=actor_id,
                subject={"kind": subject_kind, "id": subject_id(value)},
                operation_id=request.get("operation_id"),
                request_id=request.get("request_id"),
                correlation_id=request.get("correlation_id"),
            )
            store.complete(idempotency_key=key, result=_serialize_result(result))
            return result
        finally:
            store.close()

    def get_revision(self, request: dict) -> PortResult:
        revision_id = request.get("revision_id")
        return self._read(
            lambda: self._revision_value(revision_id)
        )

    def _revision_value(self, revision_id: object) -> dict:
        revision, manifest = self.records.revision_with_manifest(revision_id)
        return {"revision": revision, "manifest": manifest}

    def resolve_publication(self, request: dict) -> PortResult:
        publication_id = request.get("publication_id")

        def resolve() -> dict:
            publication = self.records.get_publication(publication_id)
            if publication["publication_state"] == "withdrawn":
                raise ArtifactStoreRefusal(
                    RefusalCode.PUBLICATION_WITHDRAWN,
                    f"publication {publication_id} is withdrawn",
                )
            revision, manifest = self.records.revision_with_manifest(
                publication["revision_id"]
            )
            if revision["content_hash"] != publication["content_hash"]:
                raise ArtifactStoreRefusal(
                    RefusalCode.CONTENT_HASH_MISMATCH,
                    "publication content hash does not match its revision",
                )
            return {
                "publication": publication,
                "revision": revision,
                "manifest": manifest,
            }

        return self._read(resolve)

    def verify_execution_eligibility(
        self, request: EligibilityRequest
    ) -> EligibilityResult:
        try:
            revision, manifest = self.records.revision_with_manifest(
                request.revision_id
            )
            if revision["content_hash"] != request.content_hash:
                raise ArtifactStoreRefusal(
                    RefusalCode.CONTENT_HASH_MISMATCH,
                    "requested content hash does not match the revision",
                )
            publication = self.records.publication_for(
                request.revision_id, request.channel
            )
            if publication is None:
                raise ArtifactStoreRefusal(
                    RefusalCode.ARTIFACT_NOT_PUBLISHED,
                    "revision is not published for the requested channel",
                )
            if publication["publication_state"] == "withdrawn":
                raise ArtifactStoreRefusal(
                    RefusalCode.PUBLICATION_WITHDRAWN,
                    "the publication is withdrawn",
                )
            if publication["content_hash"] != revision["content_hash"]:
                raise ArtifactStoreRefusal(
                    RefusalCode.CONTENT_HASH_MISMATCH,
                    "publication content hash does not match the revision",
                )
            verification, approval = self.records.governance(
                request.revision_id, revision["content_hash"]
            )
            if verification is None or verification["verification_state"] not in {
                "not_required", "passed"
            }:
                raise ArtifactStoreRefusal(
                    RefusalCode.VERIFICATION_FAILED,
                    "revision verification is not eligible for execution",
                )
            if approval is None or approval["approval_state"] != "approved":
                raise ArtifactStoreRefusal(
                    RefusalCode.APPROVAL_REVOKED,
                    "revision has no active approval",
                )
            if revision["artifact_type"] != "script":
                raise ArtifactStoreRefusal(
                    RefusalCode.UNSUPPORTED_ARTIFACT_TYPE,
                    "only script artifacts are supported in S2-1",
                )
            entries = {
                item["path"]: item for item in manifest["entries"]
            }
            entry = entries.get(request.entrypoint)
            if entry is None or not entry.get("executable", False):
                raise ArtifactStoreRefusal(
                    RefusalCode.ENTRYPOINT_NOT_IN_MANIFEST,
                    "entrypoint is absent from the executable manifest entries",
                )
        except ArtifactStoreRefusal as exc:
            return EligibilityResult(eligible=False, refusal_code=exc.code)

        return EligibilityResult(
            eligible=True,
            revision=RevisionRef(
                artifact_id=revision["artifact_id"],
                revision_id=revision["id"],
                content_hash=revision["content_hash"],
            ),
            publication=PublicationRef(
                publication_id=publication["id"],
                revision_id=revision["id"],
                channel=publication["channel"],
            ),
        )

    def create_script_revision(self, request: dict) -> PortResult:
        return self._mutation(
            request,
            operation_type="artifact.create_script_revision",
            action=lambda: self.records.create_script_revision(request),
            event_type="artifact.revision_created",
            subject_kind="artifact_revision",
            subject_id=lambda value: value["revision"]["id"],
            event_payload=lambda value: {
                "artifact_id": value["artifact"]["id"],
                "revision_id": value["revision"]["id"],
                "content_hash": value["revision"]["content_hash"],
            },
        )

    def approve_revision(self, request: dict) -> PortResult:
        return self._mutation(
            request,
            operation_type="artifact.approve_revision",
            action=lambda: self.records.approve_revision(request),
            event_type="artifact.revision_approval_recorded",
            subject_kind="artifact_revision",
            subject_id=lambda value: value["revision_id"],
            event_payload=lambda value: {
                "revision_id": value["revision_id"],
                "approval_id": value["id"],
                "approval_state": value["approval_state"],
            },
        )

    def publish_revision(self, request: dict) -> PortResult:
        return self._mutation(
            request,
            operation_type="artifact.publish_revision",
            action=lambda: self.records.publish_revision(request),
            event_type="artifact.revision_published",
            subject_kind="publication",
            subject_id=lambda value: value["id"],
            event_payload=lambda value: {
                "publication_id": value["id"],
                "revision_id": value["revision_id"],
                "content_hash": value["content_hash"],
                "channel": value["channel"],
            },
        )

    def withdraw_publication(self, request: dict) -> PortResult:
        return self._mutation(
            request,
            operation_type="artifact.withdraw_publication",
            action=lambda: self.records.withdraw_publication(request),
            event_type="artifact.publication_withdrawn",
            subject_kind="publication",
            subject_id=lambda value: value["id"],
            event_payload=lambda value: {
                "publication_id": value["id"],
                "revision_id": value["revision_id"],
                "content_hash": value["content_hash"],
                "channel": value["channel"],
            },
        )


def build_artifact_port(
    library_root: Path | None = None,
    *,
    canonical_root: Path | None = None,
) -> ArtifactPort:
    return SoloctlArtifactPort(library_root, canonical_root=canonical_root)
