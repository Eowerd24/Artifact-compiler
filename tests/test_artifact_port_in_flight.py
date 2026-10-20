"""S3-2: a retained `unknown` idempotency row refuses typed OUTCOME_UNKNOWN on retry.

The shared evaluator reports such a row as IN_FLIGHT. The mutation wrapper must
refuse without entering the action again, inserting another row, or appending an
event (UCC-Standards §15; DC-001). Before this fix the retry raised
sqlite3.IntegrityError from a second put_in_flight (2026-10-18 audit probe).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from soloctl import artifact_port as artifact_port_module
from soloctl.artifact_port import SoloctlArtifactPort
from soloctl.idempotency_store import IdempotencyStore, request_fingerprint
from ucc_contracts import new_id
from ucc_contracts.ports import RefusalCode


def _port(tmp_path: Path) -> SoloctlArtifactPort:
    return SoloctlArtifactPort(tmp_path / "library")


def _create_request(key: str = "create-unknown") -> dict:
    return {
        "title": "Unknown outcome",
        "content": "#!/bin/sh\nprintf unknown\n",
        "content_path": "bin/unknown.sh",
        "created_by": new_id("act"),
        "idempotency_key": key,
    }


def _preseed_unknown(port: SoloctlArtifactPort, operation_type: str, request: dict) -> None:
    """Commit the same `unknown` row the wrapper writes before dispatch."""
    payload = {k: v for k, v in request.items() if k != "idempotency_key"}
    store = IdempotencyStore(port.paths.idempotency_db)
    try:
        store.put_in_flight(
            idempotency_key=request["idempotency_key"],
            fingerprint=request_fingerprint({"operation_type": operation_type, "payload": payload}),
            operation_type=operation_type,
            created_at="2026-10-20T00:00:00.000Z",
        )
    finally:
        store.close()


def _row(port: SoloctlArtifactPort, key: str):
    store = IdempotencyStore(port.paths.idempotency_db)
    try:
        return store.get(key)
    finally:
        store.close()


def _event_lines(port: SoloctlArtifactPort) -> list[str]:
    path = port.paths.ucc_events_file
    return [line for line in path.read_text().splitlines() if line] if path.exists() else []


def _revisions(port: SoloctlArtifactPort) -> list[Path]:
    return sorted(port.records.revisions.glob("rev_*"))


def _assert_outcome_unknown(result) -> None:
    assert result.ok is False
    assert result.disposition == "refused"
    assert result.refusal_code == RefusalCode.OUTCOME_UNKNOWN
    assert result.retryable is False


def _count_action_calls(monkeypatch, port: SoloctlArtifactPort, method: str) -> list:
    calls = []
    original = getattr(port.records, method)

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(port.records, method, spy)
    return calls


def test_preseeded_unknown_create_refuses_without_dispatch(tmp_path: Path, monkeypatch):
    port = _port(tmp_path)
    request = _create_request()
    _preseed_unknown(port, "artifact.create_script_revision", request)
    calls = _count_action_calls(monkeypatch, port, "create_script_revision")

    result = port.create_script_revision(request)

    _assert_outcome_unknown(result)
    assert calls == []
    assert _revisions(port) == []
    assert _event_lines(port) == []
    assert _row(port, request["idempotency_key"]).disposition == "unknown"


def test_retry_after_post_mutation_event_failure_preserves_single_revision(tmp_path: Path, monkeypatch):
    port = _port(tmp_path)
    request = _create_request("create-event-failure")

    with monkeypatch.context() as patched:
        patched.setattr(artifact_port_module, "emit_event",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("simulated event fs failure")))
        with pytest.raises(OSError):
            port.create_script_revision(request)

    revisions_before = _revisions(port)
    bytes_before = {p.name: sorted(f.read_bytes() for f in p.rglob("*") if f.is_file())
                    for p in revisions_before}
    events_before = _event_lines(port)
    assert len(revisions_before) == 1
    assert _row(port, request["idempotency_key"]).disposition == "unknown"

    calls = _count_action_calls(monkeypatch, port, "create_script_revision")
    retry = port.create_script_revision(request)
    again = port.create_script_revision(request)

    _assert_outcome_unknown(retry)
    _assert_outcome_unknown(again)
    assert calls == []
    assert _revisions(port) == revisions_before
    assert {p.name: sorted(f.read_bytes() for f in p.rglob("*") if f.is_file())
            for p in _revisions(port)} == bytes_before
    assert _event_lines(port) == events_before
    assert _row(port, request["idempotency_key"]).disposition == "unknown"


def test_different_input_on_an_unknown_key_is_still_a_conflict(tmp_path: Path):
    port = _port(tmp_path)
    request = _create_request("unknown-then-different")
    _preseed_unknown(port, "artifact.create_script_revision", request)

    different = dict(request, content="#!/bin/sh\nprintf other\n")
    result = port.create_script_revision(different)

    assert result.ok is False
    assert result.refusal_code == RefusalCode.IDEMPOTENCY_CONFLICT
    assert _revisions(port) == []


@pytest.mark.parametrize(
    "method, operation_type, request_body",
    [
        ("approve_revision", "artifact.approve_revision",
         {"revision_id": "rev_01J8ABCDEFGHJKMNPQRSTV0006", "approval_state": "approved",
          "reason": "record approved"}),
        ("publish_revision", "artifact.publish_revision",
         {"revision_id": "rev_01J8ABCDEFGHJKMNPQRSTV0006", "channel": "execution"}),
        ("withdraw_publication", "artifact.withdraw_publication",
         {"publication_id": "pub_01J8ABCDEFGHJKMNPQRSTV0007", "reason": "withdraw"}),
    ],
)
def test_every_mutation_refuses_on_a_retained_unknown_row(tmp_path: Path, monkeypatch,
                                                          method, operation_type, request_body):
    port = _port(tmp_path)
    request = dict(request_body, created_by=new_id("act"), idempotency_key=f"unknown-{method}")
    _preseed_unknown(port, operation_type, request)
    calls = _count_action_calls(monkeypatch, port, method)

    result = getattr(port, method)(request)

    _assert_outcome_unknown(result)
    assert calls == []
    assert _event_lines(port) == []
    assert _row(port, request["idempotency_key"]).disposition == "unknown"
