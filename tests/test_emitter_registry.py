"""Emitter registry tests (WP3): exactly-one-match rule, unsupported-emitter,
overlap as a configuration error, and config-driven enablement."""
from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.compiler.classify import SUPPORTED_LANGUAGES
from soloctl.compiler.extract import extract
from soloctl.config import DEFAULT_ENABLED_EMITTERS, load_config
from soloctl.emitters import (
    BUILTIN_EMITTERS, EmitterRegistry, default_registry, registry_from_config,
)
from soloctl.emitters.bash import BashEmitter
from soloctl.emitters.sql import SqlEmitter
from soloctl.errors import EmitterConfigurationError, UnsupportedEmitterError

FIX = Path(__file__).parent / "fixtures"


def polyglot():
    return extract((FIX / "transcript-polyglot.md").read_text(encoding="utf-8"),
                   source="polyglot", only=SUPPORTED_LANGUAGES)


def one(label: str, body: str = "x"):
    return extract(f"```{label}\n{body}\n```", source="inline",
                   only=SUPPORTED_LANGUAGES).candidates[0]


def test_builtin_names_match_config_defaults():
    assert tuple(BUILTIN_EMITTERS) == DEFAULT_ENABLED_EMITTERS
    assert default_registry().names == DEFAULT_ENABLED_EMITTERS


@pytest.mark.parametrize("label,emitter", [
    ("bash", "bash"), ("zsh", "bash"), ("py", "python"), ("pwsh", "powershell"),
    ("ps1", "powershell"), ("sql", "sql"), ("mysql", "sql"), ("prompt", "prompt"),
    ("markdown", "runbook"), ("md", "runbook"), ("runbook", "runbook"),
])
def test_label_to_type_to_emitter_mapping(label, emitter):
    assert default_registry().resolve(one(label)).name == emitter


def test_every_supported_language_has_exactly_one_default_emitter():
    reg = default_registry()
    for c in polyglot().candidates:
        matches = [n for n in reg.names if reg.get(n).supports(c)]
        assert len(matches) == 1, (c.lang, matches)


def test_zero_matches_is_unsupported_emitter():
    reg = default_registry(["bash"])
    with pytest.raises(UnsupportedEmitterError) as exc_info:
        reg.resolve(one("python", "print(1)"))
    exc = exc_info.value
    assert exc.reason == "unsupported-emitter"
    assert (exc.lang, exc.artifact_type) == ("python", "script")
    assert "enabled_emitters" in str(exc) and "inline:1" in str(exc)


def test_empty_registry_rejects_everything_as_unsupported():
    with pytest.raises(UnsupportedEmitterError):
        EmitterRegistry([]).resolve(one("bash", "echo hi"))


def test_multiple_matches_is_a_configuration_error_not_a_pick():
    class GreedyEmitter(BashEmitter):
        name = "greedy"

        def supports(self, candidate):
            return True

    reg = EmitterRegistry([BashEmitter(), GreedyEmitter()])
    with pytest.raises(EmitterConfigurationError, match=r"\['bash', 'greedy'\]"):
        reg.resolve(one("bash", "echo hi"))
    # order must not matter either — no first-registered-wins fallback
    with pytest.raises(EmitterConfigurationError):
        EmitterRegistry([GreedyEmitter(), BashEmitter()]).resolve(one("bash", "echo hi"))
    # and assign() must propagate it rather than turning it into a skip
    with pytest.raises(EmitterConfigurationError):
        reg.assign([one("bash", "echo hi")])


def test_duplicate_emitter_names_rejected():
    with pytest.raises(EmitterConfigurationError, match="unique"):
        EmitterRegistry([BashEmitter(), BashEmitter()])


def test_non_protocol_object_rejected():
    with pytest.raises(EmitterConfigurationError, match="ArtifactEmitter protocol"):
        EmitterRegistry([object()])


def test_unknown_or_repeated_enabled_names_rejected():
    with pytest.raises(EmitterConfigurationError, match="valid names"):
        default_registry(["bash", "javascript"])
    with pytest.raises(EmitterConfigurationError, match="more than once"):
        default_registry(["bash", "bash"])


def test_get_unknown_name():
    with pytest.raises(EmitterConfigurationError, match="registered"):
        default_registry(["bash"]).get("python")


def test_assign_keeps_fence_accounting_intact():
    r = polyglot()
    a = default_registry(["bash", "python", "sql"]).assign(r.candidates)
    assert [e.name for _, e in a.assigned] == ["bash", "python", "sql"]
    assert [(s.reason, s.lang) for s in a.unsupported] == [
        ("unsupported-emitter", "powershell"),
        ("unsupported-emitter", "prompt"),
        ("unsupported-emitter", "markdown"),
    ]
    assert r.stats["fences_seen"] == (
        len(a.assigned) + len(a.unsupported) + len(r.skipped))


def test_registry_from_config(tmp_path):
    (tmp_path / "soloctl.toml").write_text(
        'enabled_emitters = ["sql", "bash"]\ndefault_sql_dialect = "sqlite"\n',
        encoding="utf-8")
    reg = registry_from_config(load_config(base_dir=tmp_path))
    assert reg.names == ("sql", "bash")
    sql = reg.get("sql")
    assert isinstance(sql, SqlEmitter) and sql.dialect(one("sql", "SELECT 1;")) == "sqlite"
    with pytest.raises(UnsupportedEmitterError):
        reg.resolve(one("py", "print(1)"))


def test_registry_from_default_config_enables_all_six(tmp_path):
    reg = registry_from_config(load_config(base_dir=tmp_path))
    a = reg.assign(polyglot().candidates)
    assert a.unsupported == () and len(a.assigned) == 6
