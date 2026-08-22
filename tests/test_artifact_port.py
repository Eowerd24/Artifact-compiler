"""S2-1 ArtifactPort acceptance tests over isolated canonical roots."""
from __future__ import annotations

import json
from pathlib import Path

from soloctl.artifact_port import SoloctlArtifactPort, build_artifact_port
from ucc_contracts import new_id
from ucc_contracts.ports import (
    ArtifactPort,
    EligibilityRequest,
    EligibilityResult,
    PortResult,
    RefusalCode,
)


def _port(tmp_path: Path) -> SoloctlArtifactPort:
    return SoloctlArtifactPort(tmp_path / "library")


def _create(
    port: SoloctlArtifactPort,
    *,
    key: str = "create-1",
    verification_state: str = "not_required",
) -> PortResult:
    return port.create_script_revision({
        "title": "Inventory",
        "content": "#!/bin/sh\nprintf inventory\n",
        "content_path": "bin/inventory.sh",
        "created_by": new_id("act"),
        "verification_state": verification_state,
        "idempotency_key": key,
    })


def _approve(port: SoloctlArtifactPort, revision_id: str, *, key: str = "approve-1",
             state: str = "approved") -> PortResult:
    return port.approve_revision({
        "revision_id": revision_id,
        "created_by": new_id("act"),
        "approval_state": state,
        "reason": f"record {state}",
        "idempotency_key": key,
    })


def _publish(port: SoloctlArtifactPort, revision_id: str, *, key: str = "publish-1") -> PortResult:
    return port.publish_revision({
        "revision_id": revision_id,
        "channel": "execution",
        "created_by": new_id("act"),
        "idempotency_key": key,
    })


def _eligible(port: SoloctlArtifactPort, revision: dict, *,
              content_hash: str | None = None,
              entrypoint: str = "bin/inventory.sh") -> EligibilityResult:
    return port.verify_execution_eligibility(EligibilityRequest(
        revision_id=revision["id"],
        content_hash=content_hash or revision["content_hash"],
        channel="execution",
        entrypoint=entrypoint,
    ))


def test_adapter_satisfies_artifact_port_protocol(tmp_path: Path):
    port = build_artifact_port(tmp_path / "library")
    assert isinstance(port, ArtifactPort)


def test_create_approve_publish_and_real_reads(tmp_path: Path):
    port = _port(tmp_path)

    created = _create(port)
    assert created.ok is True
    artifact = created.value["artifact"]
    revision = created.value["revision"]
    assert artifact["id"].startswith("art_")
    assert revision["id"].startswith("rev_")
    assert revision["artifact_id"] == artifact["id"]
    assert revision["content_hash"].startswith("sha256:")

    revision_result = port.get_revision({"revision_id": revision["id"]})
    assert revision_result.ok is True
    assert revision_result.value["revision"] == revision
    assert revision_result.value["manifest"]["entries"][0]["path"] == "bin/inventory.sh"

    unpublished = _eligible(port, revision)
    assert unpublished.eligible is False
    assert unpublished.refusal_code == RefusalCode.ARTIFACT_NOT_PUBLISHED

    approved = _approve(port, revision["id"])
    assert approved.ok is True
    assert approved.value["id"].startswith("apr_")

    published = _publish(port, revision["id"])
    assert published.ok is True
    publication = published.value
    assert publication["id"].startswith("pub_")

    resolved = port.resolve_publication({"publication_id": publication["id"]})
    assert resolved.ok is True
    assert resolved.value["revision"]["id"] == revision["id"]

    eligible = _eligible(port, revision)
    assert eligible.eligible is True
    assert eligible.revision.revision_id == revision["id"]
    assert eligible.publication.publication_id == publication["id"]


def test_create_replay_returns_same_records_and_does_not_duplicate_event(tmp_path: Path):
    port = _port(tmp_path)
    actor = new_id("act")
    request = {
        "title": "Replay",
        "content": "echo replay\n",
        "content_path": "bin/replay.sh",
        "created_by": actor,
        "idempotency_key": "same-create",
    }
    first = port.create_script_revision(request)
    second = port.create_script_revision(request)

    assert first.ok is True
    assert second == first
    assert list(port.records.revisions.glob("rev_*")) == [
        port.records.revisions / first.value["revision"]["id"]
    ]
    event_lines = [
        line for line in port.paths.ucc_events_file.read_text().splitlines() if line
    ]
    assert len(event_lines) == 1
    event = json.loads(event_lines[0])
    assert event["subject"] == {
        "kind": "artifact_revision",
        "id": first.value["revision"]["id"],
    }
    assert event["actor"]["id"] == actor


def test_idempotency_conflict_fails_closed(tmp_path: Path):
    port = _port(tmp_path)
    actor = new_id("act")
    first = port.create_script_revision({
        "title": "One",
        "content": "echo one\n",
        "created_by": actor,
        "idempotency_key": "reused",
    })
    conflict = port.create_script_revision({
        "title": "Two",
        "content": "echo two\n",
        "created_by": actor,
        "idempotency_key": "reused",
    })

    assert first.ok is True
    assert conflict.ok is False
    assert conflict.refusal_code == RefusalCode.IDEMPOTENCY_CONFLICT


def test_hash_mismatch_refuses_eligibility(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port)
    revision = created.value["revision"]
    assert _approve(port, revision["id"]).ok
    assert _publish(port, revision["id"]).ok

    result = _eligible(port, revision, content_hash="sha256:" + "0" * 64)
    assert result.eligible is False
    assert result.refusal_code == RefusalCode.CONTENT_HASH_MISMATCH


def test_tampered_content_refuses_get_revision(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port)
    revision = created.value["revision"]
    content_root = (
        port.records.root / revision["content_reference"]["relative_path"]
    )
    (content_root / "bin/inventory.sh").write_text("tampered\n", encoding="utf-8")

    result = port.get_revision({"revision_id": revision["id"]})
    assert result.ok is False
    assert result.refusal_code == RefusalCode.CONTENT_HASH_MISMATCH


def test_failed_verification_refuses_publication(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port, verification_state="failed")
    revision = created.value["revision"]
    assert _approve(port, revision["id"]).ok

    result = _publish(port, revision["id"])
    assert result.ok is False
    assert result.refusal_code == RefusalCode.VERIFICATION_FAILED


def test_revoked_approval_refuses_eligibility(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port)
    revision = created.value["revision"]
    assert _approve(port, revision["id"], key="approve-active").ok
    assert _publish(port, revision["id"]).ok
    revoked = _approve(
        port, revision["id"], key="approve-revoked", state="revoked"
    )
    assert revoked.ok is True

    result = _eligible(port, revision)
    assert result.eligible is False
    assert result.refusal_code == RefusalCode.APPROVAL_REVOKED


def test_missing_entrypoint_refuses_eligibility(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port)
    revision = created.value["revision"]
    assert _approve(port, revision["id"]).ok
    assert _publish(port, revision["id"]).ok

    result = _eligible(port, revision, entrypoint="bin/missing.sh")
    assert result.eligible is False
    assert result.refusal_code == RefusalCode.ENTRYPOINT_NOT_IN_MANIFEST


def test_withdrawn_publication_refuses_reads_and_new_execution(tmp_path: Path):
    port = _port(tmp_path)
    created = _create(port)
    revision = created.value["revision"]
    assert _approve(port, revision["id"]).ok
    publication = _publish(port, revision["id"]).value

    withdrawn = port.withdraw_publication({
        "publication_id": publication["id"],
        "created_by": new_id("act"),
        "reason": "superseded by a later revision",
        "idempotency_key": "withdraw-1",
    })
    assert withdrawn.ok is True
    assert withdrawn.value["publication_state"] == "withdrawn"

    resolved = port.resolve_publication({"publication_id": publication["id"]})
    assert resolved.ok is False
    assert resolved.refusal_code == RefusalCode.PUBLICATION_WITHDRAWN
    eligible = _eligible(port, revision)
    assert eligible.eligible is False
    assert eligible.refusal_code == RefusalCode.PUBLICATION_WITHDRAWN


def test_unknown_and_malformed_ids_return_typed_refusals(tmp_path: Path):
    port = _port(tmp_path)

    malformed = port.get_revision({"revision_id": "rev_x"})
    assert malformed.ok is False
    assert malformed.refusal_code == RefusalCode.VALIDATION_ERROR

    missing = port.get_revision({"revision_id": new_id("rev")})
    assert missing.ok is False
    assert missing.refusal_code == RefusalCode.REVISION_NOT_FOUND

    missing_publication = port.resolve_publication({
        "publication_id": new_id("pub")
    })
    assert missing_publication.ok is False
    assert missing_publication.refusal_code == RefusalCode.ARTIFACT_NOT_PUBLISHED


def test_mutations_require_idempotency_key(tmp_path: Path):
    port = _port(tmp_path)
    result = port.create_script_revision({
        "title": "No key",
        "content": "echo no\n",
        "created_by": new_id("act"),
    })
    assert result.ok is False
    assert result.refusal_code == RefusalCode.VALIDATION_ERROR
    assert not port.records.root.exists()
