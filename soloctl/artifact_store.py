"""Canonical Artifact records and hash-addressed revision storage for S2-1."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ucc_contracts import is_safe_relpath, is_valid_hash, is_valid_id, new_id, validate_document
from ucc_contracts.ports import RefusalCode

from .library.atomic import atomic_write_bytes, atomic_write_text


def now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json_bytes(document: dict) -> bytes:
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ArtifactStoreRefusal(Exception):
    def __init__(self, code: RefusalCode, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class ArtifactRecordStore:
    """Artifact Compiler canonical owner store.

    root is the configured canonical/artifact-compiler owner root. Existing
    artifacts/drafts and artifacts/approved directories remain export views,
    not governance authority.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.artifacts = self.root / "artifacts"
        self.revisions = self.root / "revisions"
        self.verifications = self.root / "verifications"
        self.approvals = self.root / "approvals"
        self.publications = self.root / "publications"
        self.lock_path = self.root / ".records.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o640)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _require_id(value: object, prefix: str, field: str) -> str:
        if not isinstance(value, str) or not is_valid_id(value, expected_prefix=prefix):
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR,
                f"{field} must be a canonical {prefix}_ identifier",
            )
        return value

    @staticmethod
    def _require_text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, f"{field} must be a non-empty string"
            )
        return value

    @staticmethod
    def _load(path: Path, code: RefusalCode, label: str) -> dict:
        if not path.is_file():
            raise ArtifactStoreRefusal(code, f"{label} was not found")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactStoreRefusal(
                RefusalCode.DEPENDENCY_UNAVAILABLE,
                f"{label} could not be read: {exc}",
                retryable=True,
            ) from exc
        if not isinstance(value, dict):
            raise ArtifactStoreRefusal(
                RefusalCode.DEPENDENCY_UNAVAILABLE,
                f"{label} is not a JSON object",
                retryable=True,
            )
        return value

    @staticmethod
    def _write_document(path: Path, schema: str, document: dict) -> None:
        validate_document(schema, document)
        serialized = json.dumps(
            document, ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        atomic_write_text(path, serialized)

    def _artifact_path(self, artifact_id: str) -> Path:
        return self.artifacts / f"{artifact_id}.json"

    def _revision_dir(self, revision_id: str) -> Path:
        return self.revisions / revision_id

    def _revision_path(self, revision_id: str) -> Path:
        return self._revision_dir(revision_id) / "revision.json"

    def _publication_path(self, publication_id: str) -> Path:
        return self.publications / f"{publication_id}.json"

    def get_artifact(self, artifact_id: str) -> dict:
        artifact_id = self._require_id(artifact_id, "art", "artifact_id")
        doc = self._load(
            self._artifact_path(artifact_id),
            RefusalCode.ARTIFACT_NOT_FOUND,
            f"artifact {artifact_id}",
        )
        validate_document("artifact", doc)
        if doc["id"] != artifact_id:
            raise ArtifactStoreRefusal(
                RefusalCode.SECURITY_VIOLATION,
                "artifact record identity does not match its canonical path",
            )
        return doc

    def get_revision(self, revision_id: str) -> dict:
        revision_id = self._require_id(revision_id, "rev", "revision_id")
        doc = self._load(
            self._revision_path(revision_id),
            RefusalCode.REVISION_NOT_FOUND,
            f"revision {revision_id}",
        )
        validate_document("artifact-revision", doc)
        if doc["id"] != revision_id:
            raise ArtifactStoreRefusal(
                RefusalCode.SECURITY_VIOLATION,
                "revision record identity does not match its canonical path",
            )
        return doc

    def get_publication(self, publication_id: str) -> dict:
        publication_id = self._require_id(publication_id, "pub", "publication_id")
        doc = self._load(
            self._publication_path(publication_id),
            RefusalCode.ARTIFACT_NOT_PUBLISHED,
            f"publication {publication_id}",
        )
        validate_document("publication", doc)
        if doc["id"] != publication_id:
            raise ArtifactStoreRefusal(
                RefusalCode.SECURITY_VIOLATION,
                "publication record identity does not match its canonical path",
            )
        return doc

    def revision_with_manifest(self, revision_id: str) -> tuple[dict, dict]:
        revision = self.get_revision(revision_id)
        manifest_path = self.root / revision["manifest_path"]
        try:
            manifest_path.resolve().relative_to(self.root)
        except ValueError:
            raise ArtifactStoreRefusal(
                RefusalCode.SECURITY_VIOLATION,
                "revision manifest path escapes the canonical root",
            ) from None
        if not manifest_path.is_file():
            raise ArtifactStoreRefusal(
                RefusalCode.CONTENT_HASH_MISMATCH,
                "revision content manifest is missing",
            )
        raw_manifest = manifest_path.read_bytes()
        if sha256_bytes(raw_manifest) != revision["content_hash"]:
            raise ArtifactStoreRefusal(
                RefusalCode.CONTENT_HASH_MISMATCH,
                "stored content manifest hash does not match the revision",
            )
        manifest = json.loads(raw_manifest)
        validate_document("artifact-content-manifest", manifest)
        if manifest["artifact_id"] != revision["artifact_id"] or manifest["revision_id"] != revision_id:
            raise ArtifactStoreRefusal(
                RefusalCode.CONTENT_HASH_MISMATCH,
                "content manifest identity does not match the revision",
            )

        entries = manifest["entries"]
        paths = [entry["path"] for entry in entries]
        if paths != sorted(paths, key=lambda value: value.encode("utf-8")) or len(paths) != len(set(paths)):
            raise ArtifactStoreRefusal(
                RefusalCode.CONTENT_HASH_MISMATCH,
                "content manifest paths are not unique and canonically sorted",
            )

        content_root = self.root / revision["content_reference"]["relative_path"]
        for entry in entries:
            candidate = (content_root / entry["path"]).resolve()
            try:
                candidate.relative_to(content_root.resolve())
            except ValueError:
                raise ArtifactStoreRefusal(
                    RefusalCode.SECURITY_VIOLATION,
                    "manifest content path escapes the immutable content root",
                ) from None
            if not candidate.is_file() or candidate.is_symlink():
                raise ArtifactStoreRefusal(
                    RefusalCode.CONTENT_HASH_MISMATCH,
                    f"manifest content {entry['path']} is missing or unsafe",
                )
            data = candidate.read_bytes()
            if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
                raise ArtifactStoreRefusal(
                    RefusalCode.CONTENT_HASH_MISMATCH,
                    f"manifest content hash mismatch for {entry['path']}",
                )
        return revision, manifest

    def create_script_revision(self, request: dict) -> dict:
        content = self._require_text(request.get("content"), "content")
        actor_id = self._require_id(request.get("created_by"), "act", "created_by")
        content_path = request.get("content_path", "bin/script.sh")
        if not isinstance(content_path, str) or not is_safe_relpath(content_path):
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR,
                "content_path must be a safe relative POSIX path",
            )
        content_bytes = content.encode("utf-8")
        actual_source_hash = sha256_bytes(content_bytes)
        source_hash = request.get("source_hash", actual_source_hash)
        if not is_valid_hash(source_hash):
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, "source_hash is not canonical"
            )
        if source_hash != actual_source_hash:
            raise ArtifactStoreRefusal(
                RefusalCode.CONTENT_HASH_MISMATCH,
                "source_hash does not match the supplied content",
            )
        source_kind = request.get("source_kind", "operator_input")
        if source_kind not in {"material", "workspace_checkpoint", "operator_input"}:
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, "unsupported source_kind"
            )

        verification_state = request.get("verification_state", "not_required")
        if verification_state not in {"not_required", "pending", "passed", "failed", "expired"}:
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, "unsupported verification_state"
            )
        if request.get("verification_evidence") is not None and not isinstance(
            request["verification_evidence"], dict
        ):
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, "verification_evidence must be an object"
            )
        if request.get("verification_reason") is not None:
            self._require_text(request["verification_reason"], "verification_reason")

        with self.locked():
            artifact_id = request.get("artifact_id")
            new_artifact = artifact_id is None
            if artifact_id is None:
                artifact_id = new_id("art")
                artifact = {
                    "schema": "ucc.artifact",
                    "schema_version": 1,
                    "id": artifact_id,
                    "created_at": now_iso(),
                    "created_by": actor_id,
                    "record_version": 1,
                    "artifact_type": "script",
                    "title": self._require_text(request.get("title"), "title"),
                    "lifecycle": "active",
                }
                if request.get("description") is not None:
                    artifact["description"] = self._require_text(
                        request["description"], "description"
                    )
            else:
                artifact_id = self._require_id(artifact_id, "art", "artifact_id")
                artifact = self.get_artifact(artifact_id)
                if artifact["lifecycle"] != "active":
                    raise ArtifactStoreRefusal(
                        RefusalCode.VALIDATION_ERROR,
                        f"artifact {artifact_id} is archived",
                    )

            revision_id = new_id("rev")
            relative_base = Path("revisions") / revision_id
            relative_content_root = relative_base / "content"
            relative_manifest = relative_base / "content-manifest.json"
            manifest = {
                "schema": "ucc.artifact-content-manifest",
                "schema_version": 1,
                "artifact_id": artifact_id,
                "revision_id": revision_id,
                "entries": [{
                    "path": content_path,
                    "size": len(content_bytes),
                    "sha256": sha256_bytes(content_bytes),
                    "executable": True,
                    "media_type": request.get("media_type", "text/x-shellscript"),
                }],
            }
            validate_document("artifact-content-manifest", manifest)
            manifest_bytes = canonical_json_bytes(manifest)
            content_hash = sha256_bytes(manifest_bytes)
            provenance = {"source_kind": source_kind, "source_hash": source_hash}
            if request.get("source_ref") is not None:
                provenance["source_ref"] = request["source_ref"]
            revision = {
                "schema": "ucc.artifact-revision",
                "schema_version": 1,
                "id": revision_id,
                "created_at": now_iso(),
                "created_by": actor_id,
                "record_version": 1,
                "artifact_id": artifact_id,
                "artifact_type": "script",
                "content_hash": content_hash,
                "manifest_path": relative_manifest.as_posix(),
                "content_reference": {
                    "store_id": "artifact-compiler",
                    "relative_path": relative_content_root.as_posix(),
                    "content_hash": content_hash,
                },
                "provenance": provenance,
            }
            validate_document("artifact-revision", revision)
            if new_artifact:
                validate_document("artifact", artifact)

            verification_preview = {
                "schema": "ucc.verification",
                "schema_version": 1,
                "id": new_id("ver"),
                "created_at": now_iso(),
                "created_by": actor_id,
                "record_version": 1,
                "revision_id": revision_id,
                "content_hash": content_hash,
                "verification_state": verification_state,
            }
            if request.get("verification_evidence") is not None:
                verification_preview["evidence"] = request["verification_evidence"]
            if request.get("verification_reason") is not None:
                verification_preview["reason"] = request["verification_reason"]
            validate_document("verification", verification_preview)

            if new_artifact:
                self._write_document(self._artifact_path(artifact_id), "artifact", artifact)
            revision_dir = self._revision_dir(revision_id)
            atomic_write_bytes(revision_dir / "content" / content_path, content_bytes)
            atomic_write_bytes(revision_dir / "content-manifest.json", manifest_bytes)
            self._write_document(revision_dir / "revision.json", "artifact-revision", revision)
            verification = self._record_verification_unlocked(
                revision,
                actor_id=actor_id,
                state=verification_state,
                evidence=request.get("verification_evidence"),
                reason=request.get("verification_reason"),
            )
            return {
                "artifact": artifact,
                "revision": revision,
                "manifest": manifest,
                "verification": verification,
            }

    def _record_verification_unlocked(
        self,
        revision: dict,
        *,
        actor_id: str,
        state: object,
        evidence: object = None,
        reason: object = None,
    ) -> dict:
        verification = {
            "schema": "ucc.verification",
            "schema_version": 1,
            "id": new_id("ver"),
            "created_at": now_iso(),
            "created_by": actor_id,
            "record_version": 1,
            "revision_id": revision["id"],
            "content_hash": revision["content_hash"],
            "verification_state": state,
        }
        if evidence is not None:
            if not isinstance(evidence, dict):
                raise ArtifactStoreRefusal(
                    RefusalCode.VALIDATION_ERROR, "verification_evidence must be an object"
                )
            verification["evidence"] = evidence
        if reason is not None:
            verification["reason"] = self._require_text(reason, "verification_reason")
        try:
            validate_document("verification", verification)
        except Exception as exc:
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, f"invalid verification record: {exc}"
            ) from exc
        path = self.verifications / revision["id"] / f"{verification['id']}.json"
        self._write_document(path, "verification", verification)
        return verification

    def record_verification(self, request: dict) -> dict:
        revision_id = self._require_id(request.get("revision_id"), "rev", "revision_id")
        actor_id = self._require_id(request.get("created_by"), "act", "created_by")
        with self.locked():
            revision, _ = self.revision_with_manifest(revision_id)
            return self._record_verification_unlocked(
                revision,
                actor_id=actor_id,
                state=request.get("verification_state"),
                evidence=request.get("evidence"),
                reason=request.get("reason"),
            )

    def approve_revision(self, request: dict) -> dict:
        revision_id = self._require_id(request.get("revision_id"), "rev", "revision_id")
        actor_id = self._require_id(request.get("created_by"), "act", "created_by")
        state = request.get("approval_state", "approved")
        with self.locked():
            revision, _ = self.revision_with_manifest(revision_id)
            approval = {
                "schema": "ucc.approval",
                "schema_version": 1,
                "id": new_id("apr"),
                "created_at": now_iso(),
                "created_by": actor_id,
                "record_version": 1,
                "revision_id": revision_id,
                "content_hash": revision["content_hash"],
                "approval_state": state,
            }
            if request.get("reason") is not None:
                approval["reason"] = self._require_text(request["reason"], "reason")
            try:
                validate_document("approval", approval)
            except Exception as exc:
                raise ArtifactStoreRefusal(
                    RefusalCode.VALIDATION_ERROR, f"invalid approval record: {exc}"
                ) from exc
            self._write_document(
                self.approvals / revision_id / f"{approval['id']}.json",
                "approval",
                approval,
            )
            return approval

    @staticmethod
    def _latest_record(directory: Path) -> dict | None:
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
        ]
        records = [value for value in records if isinstance(value, dict)]
        if not records:
            return None
        return max(
            records, key=lambda value: (value.get("created_at", ""), value.get("id", ""))
        )

    def governance(
        self, revision_id: str, content_hash: str
    ) -> tuple[dict | None, dict | None]:
        verification = self._latest_record(self.verifications / revision_id)
        approval = self._latest_record(self.approvals / revision_id)
        if verification is not None:
            validate_document("verification", verification)
        if approval is not None:
            validate_document("approval", approval)
        for label, record in (("verification", verification), ("approval", approval)):
            if record is not None and (
                record["revision_id"] != revision_id
                or record["content_hash"] != content_hash
            ):
                raise ArtifactStoreRefusal(
                    RefusalCode.SECURITY_VIOLATION,
                    f"{label} record is not bound to the requested revision",
                )
        return verification, approval

    def publication_for(self, revision_id: str, channel: str) -> dict | None:
        matches = []
        for path in self.publications.glob("pub_*.json"):
            doc = self._load(path, RefusalCode.DEPENDENCY_UNAVAILABLE, f"publication {path.name}")
            validate_document("publication", doc)
            if doc["id"] != path.stem:
                raise ArtifactStoreRefusal(
                    RefusalCode.SECURITY_VIOLATION,
                    "publication record identity does not match its canonical path",
                )
            if doc["revision_id"] == revision_id and doc["channel"] == channel:
                matches.append(doc)
        return sorted(matches, key=lambda item: item["id"])[-1] if matches else None

    def publish_revision(self, request: dict) -> dict:
        revision_id = self._require_id(request.get("revision_id"), "rev", "revision_id")
        actor_id = self._require_id(request.get("created_by"), "act", "created_by")
        channel = request.get("channel")
        if channel != "execution":
            raise ArtifactStoreRefusal(
                RefusalCode.VALIDATION_ERROR, "channel must be execution"
            )
        with self.locked():
            revision, _ = self.revision_with_manifest(revision_id)
            existing = self.publication_for(revision_id, channel)
            if existing is not None:
                if existing["publication_state"] == "published":
                    return existing
                raise ArtifactStoreRefusal(
                    RefusalCode.PUBLICATION_WITHDRAWN,
                    "the exact revision publication was withdrawn",
                )
            verification, approval = self.governance(revision_id, revision["content_hash"])
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
            publication = {
                "schema": "ucc.publication",
                "schema_version": 1,
                "id": new_id("pub"),
                "created_at": now_iso(),
                "created_by": actor_id,
                "record_version": 1,
                "revision_id": revision_id,
                "artifact_id": revision["artifact_id"],
                "content_hash": revision["content_hash"],
                "channel": channel,
                "publication_state": "published",
            }
            self._write_document(
                self._publication_path(publication["id"]), "publication", publication
            )
            return publication

    def withdraw_publication(self, request: dict) -> dict:
        publication_id = self._require_id(
            request.get("publication_id"), "pub", "publication_id"
        )
        self._require_id(request.get("created_by"), "act", "created_by")
        with self.locked():
            publication = self.get_publication(publication_id)
            if publication["publication_state"] == "withdrawn":
                return publication
            publication = {
                **publication,
                "record_version": publication["record_version"] + 1,
                "publication_state": "withdrawn",
                "withdrawn_at": now_iso(),
                "withdrawal_reason": self._require_text(
                    request.get("reason"), "reason"
                ),
            }
            self._write_document(
                self._publication_path(publication_id), "publication", publication
            )
            return publication
