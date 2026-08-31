from pathlib import Path
from soloctl.artifact_port import build_artifact_port, SoloctlArtifactPort
from ucc_contracts.ports import EligibilityRequest, RefusalCode, PortResult
from ucc_contracts import new_id

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
        "executable": True,
        "created_by": "act_01H123456789ABCDEFGHJKMNPQ",
        "verification_state": verification_state,
        "idempotency_key": key,
    })

def _approve(port: SoloctlArtifactPort, rev_id: str, *, key="app-1", state="approved"):
    return port.approve_revision({
        "revision_id": rev_id,
        "created_by": "act_01H123456789ABCDEFGHJKMNPQ",
        "approval_state": state,
        "reason": f"record {state}",
        "idempotency_key": key,
    })

def _publish(port: SoloctlArtifactPort, rev_id: str, *, key="pub-1"):
    return port.publish_revision({
        "revision_id": rev_id,
        "channel": "execution",
        "created_by": "act_01H123456789ABCDEFGHJKMNPQ",
        "idempotency_key": key,
    })


def test_revoke_approval_and_eligibility(tmp_path: Path):
    port = build_artifact_port(tmp_path)
    created = _create(port)
    rev_id = created.value["revision"]["id"]
    content_hash = created.value["revision"]["content_hash"]
    
    _approve(port, rev_id)
    _publish(port, rev_id)
    
    req = EligibilityRequest(revision_id=rev_id, content_hash=content_hash, channel="execution", entrypoint="bin/inventory.sh")
    elig = port.verify_execution_eligibility(req)
    assert elig.eligible
    
    # Revoke
    res = port.revoke_approval({
        "operation_id": "op_01H123456789ABCDEFGHJKMNPQ",
        "idempotency_key": "revoke-1",
        "revision_id": rev_id,
        "created_by": "act_01H123456789ABCDEFGHJKMNPQ",
        "reason": "testing revocation"
    })
    assert res.ok, res.message
    assert res.value["approval_state"] == "revoked"
    
    # Eligibility refused
    elig = port.verify_execution_eligibility(req)
    assert not elig.eligible
    assert elig.refusal_code == RefusalCode.APPROVAL_REVOKED
    
    # History preserved: there should be 2 approval records
    records = list((port.records.approvals / rev_id).glob("*.json"))
    assert len(records) == 2
    
    # Idempotent revoke
    res2 = port.revoke_approval({
        "operation_id": "op_01H123456789ABCDEFGHJKMNPQ",
        "idempotency_key": "revoke-1",
        "revision_id": rev_id,
        "created_by": "act_01H123456789ABCDEFGHJKMNPQ",
        "reason": "testing revocation"
    })
    assert res2.ok
    assert res2.value["id"] == res.value["id"]
