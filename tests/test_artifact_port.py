"""G3: ArtifactPort adapter conformance. Every method must exist, be
Protocol-structural (isinstance holds), and return a PortResult/
EligibilityResult with a disposition/refusal_code that would validate
against the shared ucc.problem/ucc.result vocabulary — even though every
method refuses today (no Artifact/ArtifactRevision/Publication store yet)."""
import pytest

from soloctl.artifact_port import SoloctlArtifactPort, build_artifact_port
from ucc_contracts.ports import ArtifactPort, EligibilityRequest, EligibilityResult, PortResult, RefusalCode

VALID_DISPOSITIONS = {"accepted", "completed", "refused", "failed", "partial", "cancelled", "unknown"}


def test_adapter_satisfies_artifact_port_protocol():
    port = build_artifact_port()
    assert isinstance(port, ArtifactPort)


def test_all_seven_methods_present_and_callable():
    port = SoloctlArtifactPort()
    result = port.get_revision({"revision_id": "rev_x"})
    assert isinstance(result, PortResult)
    result = port.resolve_publication({"publication_id": "pub_x"})
    assert isinstance(result, PortResult)
    result = port.verify_execution_eligibility(
        EligibilityRequest(revision_id="rev_x", content_hash="sha256:" + "a" * 64,
                           channel="execution", entrypoint="run.sh"))
    assert isinstance(result, EligibilityResult)
    result = port.create_script_revision({"artifact_id": "art_x", "content": "echo hi"})
    assert isinstance(result, PortResult)
    result = port.approve_revision({"revision_id": "rev_x"})
    assert isinstance(result, PortResult)
    result = port.publish_revision({"revision_id": "rev_x", "channel": "execution"})
    assert isinstance(result, PortResult)
    result = port.withdraw_publication({"publication_id": "pub_x"})
    assert isinstance(result, PortResult)


@pytest.mark.parametrize("method,request_payload", [
    ("get_revision", {"revision_id": "rev_x"}),
    ("resolve_publication", {"publication_id": "pub_x"}),
    ("create_script_revision", {"artifact_id": "art_x", "content": "echo hi"}),
    ("approve_revision", {"revision_id": "rev_x"}),
    ("publish_revision", {"revision_id": "rev_x", "channel": "execution"}),
    ("withdraw_publication", {"publication_id": "pub_x"}),
])
def test_well_formed_request_refuses_dependency_unavailable_not_a_crash(method, request_payload):
    port = SoloctlArtifactPort()
    result = getattr(port, method)(request_payload)
    assert result.ok is False
    assert result.disposition in VALID_DISPOSITIONS
    assert result.disposition == "refused"
    assert result.refusal_code == RefusalCode.DEPENDENCY_UNAVAILABLE
    assert result.retryable is True  # not a permanent no — the record model just doesn't exist yet


def test_verify_execution_eligibility_refuses_honestly():
    port = SoloctlArtifactPort()
    result = port.verify_execution_eligibility(
        EligibilityRequest(revision_id="rev_x", content_hash="sha256:" + "a" * 64,
                           channel="execution", entrypoint="run.sh"))
    assert result.eligible is False
    assert result.refusal_code == RefusalCode.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize("method,bad_payload", [
    ("get_revision", {}),
    ("resolve_publication", {}),
    ("create_script_revision", {"artifact_id": "art_x"}),  # missing content
    ("approve_revision", {}),
    ("publish_revision", {"revision_id": "rev_x"}),  # missing channel
    ("withdraw_publication", {}),
])
def test_malformed_request_gets_validation_error_not_dependency_unavailable(method, bad_payload):
    port = SoloctlArtifactPort()
    result = getattr(port, method)(bad_payload)
    assert result.refusal_code == RefusalCode.VALIDATION_ERROR
    assert result.retryable is False  # a fixed request would still fail the same way
