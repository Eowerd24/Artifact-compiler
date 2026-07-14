"""M-b: perform_import_idempotent — the §5 idempotent-replay and
idempotency-conflict fixtures, wired against a real AC operation."""
from pathlib import Path

import pytest

from soloctl.config import SoloctlConfig
from soloctl.errors import IdempotencyConflict, SecretDetected
from soloctl.idempotent_import import perform_import_idempotent
from soloctl.idempotency_store import IdempotencyStore
from soloctl.library.repository import init_library
from ucc_contracts import validate_document

PLAIN = "# t\n\nuser: hello\n\nassistant: hi\n"
PLAIN_2 = "# t2\n\nuser: bye\n\nassistant: bye\n"


def _config(tmp_path: Path) -> SoloctlConfig:
    config = SoloctlConfig(library_root=tmp_path / "library")
    init_library(config)
    return config


def test_new_key_proceeds_and_returns_a_validated_result(tmp_path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    result = perform_import_idempotent(config, src, idempotency_key="k1")

    validate_document("result", result)
    assert result["disposition"] == "completed"


def test_identical_replay_returns_the_same_stored_result(tmp_path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    first = perform_import_idempotent(config, src, idempotency_key="k1")
    second = perform_import_idempotent(config, src, idempotency_key="k1")

    assert first == second
    assert first["result_id"] == second["result_id"]


def test_replay_does_not_reimport(tmp_path):
    """A replay must not touch the filesystem again — only one transcript
    file should exist even after two calls with the same key."""
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    perform_import_idempotent(config, src, idempotency_key="k1")
    perform_import_idempotent(config, src, idempotency_key="k1")

    transcripts = list((config.library_root / "transcripts").rglob("*.md"))
    assert len(transcripts) == 1


def test_same_key_different_inputs_is_a_conflict(tmp_path):
    src1 = tmp_path / "plain.md"
    src1.write_text(PLAIN, encoding="utf-8")
    src2 = tmp_path / "plain2.md"
    src2.write_text(PLAIN_2, encoding="utf-8")
    config = _config(tmp_path)

    perform_import_idempotent(config, src1, idempotency_key="k1")
    with pytest.raises(IdempotencyConflict) as exc_info:
        perform_import_idempotent(config, src2, idempotency_key="k1")

    problem = exc_info.value.problem
    validate_document("problem", problem)
    assert problem["code"] == "idempotency_conflict"
    assert problem["kind"] == "conflict"


def test_different_keys_both_proceed(tmp_path):
    src1 = tmp_path / "plain.md"
    src1.write_text(PLAIN, encoding="utf-8")
    src2 = tmp_path / "plain2.md"
    src2.write_text(PLAIN_2, encoding="utf-8")
    config = _config(tmp_path)

    r1 = perform_import_idempotent(config, src1, idempotency_key="k1")
    r2 = perform_import_idempotent(config, src2, idempotency_key="k2")

    assert r1["result_id"] != r2["result_id"]
    transcripts = list((config.library_root / "transcripts").rglob("*.md"))
    assert len(transcripts) == 2


def test_dry_run_bypasses_the_store_entirely(tmp_path):
    src = tmp_path / "plain.md"
    src.write_text(PLAIN, encoding="utf-8")
    config = _config(tmp_path)

    outcome = perform_import_idempotent(config, src, idempotency_key="k1", dry_run=True)

    assert outcome.dry_run is True
    store = IdempotencyStore(config.library_root / "idempotency.db")
    assert store.get("k1") is None
    assert list((config.library_root / "transcripts").rglob("*.md")) == []


def test_refusal_is_not_stored_and_may_be_retried(tmp_path):
    src = tmp_path / "secret.md"
    src.write_text(
        "```bash\nexport GITHUB_TOKEN=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n```\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)

    with pytest.raises(SecretDetected):
        perform_import_idempotent(config, src, idempotency_key="k1")

    store = IdempotencyStore(config.library_root / "idempotency.db")
    assert store.get("k1") is None

    # retrying the same key is safe — it re-scans and refuses the same way,
    # not a conflict (nothing was ever stored for this key).
    with pytest.raises(SecretDetected):
        perform_import_idempotent(config, src, idempotency_key="k1")


def test_request_fingerprint_is_stable_for_identical_payloads(tmp_path):
    from soloctl.idempotency_store import request_fingerprint
    a = request_fingerprint({"path": "x", "adapter": None, "conversation_id": None, "title": None})
    b = request_fingerprint({"path": "x", "adapter": None, "conversation_id": None, "title": None})
    assert a == b
    assert a.startswith("sha256:")
