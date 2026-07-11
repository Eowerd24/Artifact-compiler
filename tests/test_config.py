from __future__ import annotations

from pathlib import Path

import pytest

from soloctl.config import SoloctlConfig, load_config
from soloctl.errors import ConfigError


def test_defaults_load_when_no_toml_present(tmp_path: Path):
    config = load_config(base_dir=tmp_path)
    assert isinstance(config, SoloctlConfig)
    assert config.library_root == (tmp_path / "library").resolve()
    assert config.default_sql_dialect is None
    assert config.manual_verification_required is True
    assert "bash" in config.enabled_emitters


def test_valid_toml_overrides_defaults(tmp_path: Path):
    (tmp_path / "soloctl.toml").write_text(
        'library_root = "custom-library"\n'
        'default_sql_dialect = "postgres"\n'
        'enabled_emitters = ["bash", "python"]\n'
        'enabled_validators = ["shellcheck"]\n'
        'manual_verification_required = false\n',
        encoding="utf-8",
    )
    config = load_config(base_dir=tmp_path)
    assert config.library_root == (tmp_path / "custom-library").resolve()
    assert config.default_sql_dialect == "postgres"
    assert config.enabled_emitters == ("bash", "python")
    assert config.enabled_validators == ("shellcheck",)
    assert config.manual_verification_required is False


def test_invalid_toml_fails_clearly(tmp_path: Path):
    bad = tmp_path / "soloctl.toml"
    bad.write_text("this is not [ valid toml", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_config(base_dir=tmp_path)
    assert str(bad) in str(exc_info.value)


def test_invalid_library_path_fails_clearly(tmp_path: Path):
    (tmp_path / "soloctl.toml").write_text('library_root = ""\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_config(base_dir=tmp_path)
    assert "library_root" in str(exc_info.value)


def test_library_root_wrong_type_fails_clearly(tmp_path: Path):
    (tmp_path / "soloctl.toml").write_text("library_root = 42\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(base_dir=tmp_path)


def test_unknown_key_fails_clearly(tmp_path: Path):
    (tmp_path / "soloctl.toml").write_text('made_up_key = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_config(base_dir=tmp_path)
    assert "made_up_key" in str(exc_info.value)


def test_explicit_config_path(tmp_path: Path):
    cfg_path = tmp_path / "elsewhere.toml"
    cfg_path.write_text('library_root = "lib"\n', encoding="utf-8")
    config = load_config(cfg_path, base_dir=tmp_path)
    assert config.library_root == (tmp_path / "lib").resolve()
