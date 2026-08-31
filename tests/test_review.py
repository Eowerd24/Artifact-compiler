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
        "created_by": new_id("act"),
        "verification_state": verification_state,
        "idempotency_key": key,
    })

def _approve(port: SoloctlArtifactPort, rev_id: str, *, key="app-1", state="approved"):
    return port.approve_revision({
        "revision_id": rev_id,
        "created_by": new_id("act"),
        "approval_state": state,
        "reason": f"record {state}",
        "idempotency_key": key,
    })

def _publish(port: SoloctlArtifactPort, rev_id: str, *, key="pub-1"):
    return port.publish_revision({
        "revision_id": rev_id,
        "channel": "execution",
        "created_by": new_id("act"),
        "idempotency_key": key,
    })


def test_record_review_roundtrip(tmp_path: Path):
    port = build_artifact_port(tmp_path)
    # create revision
    created = _create(port)
    assert created.ok
    rev_id = created.value["revision"]["id"]
    content_hash = created.value["revision"]["content_hash"]
    act_id = new_id("act")
    
    # Record review
    res = port.record_review({
        "operation_id": new_id("op"),
        "idempotency_key": new_id("op"),
        "revision_id": rev_id,
        "created_by": act_id,
        "review_state": "pending"
    })
    assert res.ok, res.message
    assert res.value.get("id") is not None
    assert res.value["review_state"] == "pending"
    
    # Verify it doesn't break eligibility when not required
    _approve(port, rev_id)
    _publish(port, rev_id)
    
    req = EligibilityRequest(revision_id=rev_id, content_hash=content_hash, channel="execution", entrypoint="bin/inventory.sh")
    elig = port.verify_execution_eligibility(req)
    assert elig.eligible
    
    # Require review -> fails because it is pending
    req_req = EligibilityRequest(revision_id=rev_id, content_hash=content_hash, channel="execution", entrypoint="bin/inventory.sh", require_review=True)
    elig = port.verify_execution_eligibility(req_req)
    assert not elig.eligible
    assert elig.refusal_code == RefusalCode.VERIFICATION_FAILED
    
    # Record accepted review
    port.record_review({
        "operation_id": new_id("op"),
        "idempotency_key": new_id("op"),
        "revision_id": rev_id,
        "created_by": act_id,
        "review_state": "accepted"
    })
    
    # Now it should be eligible
    elig = port.verify_execution_eligibility(req_req)
    assert elig.eligible
