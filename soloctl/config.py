"""Typed configuration, loaded from soloctl.toml with sensible defaults.

Malformed configuration is never silently ignored: every failure mode raises
ConfigError naming the file and the offending key.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

CONFIG_FILENAME = "soloctl.toml"

# Future emitter/validator names — the config seam exists now so later work
# packages can enable/disable them without touching this module again.
DEFAULT_ENABLED_EMITTERS: tuple[str, ...] = (
    "bash", "python", "powershell", "sql", "prompt", "runbook",
)
DEFAULT_ENABLED_VALIDATORS: tuple[str, ...] = ()

_KNOWN_KEYS = {
    "library_root",
    "default_sql_dialect",
    "enabled_emitters",
    "enabled_validators",
    "manual_verification_required",
}


@dataclass(frozen=True)
class SoloctlConfig:
    library_root: Path
    default_sql_dialect: str | None = None
    enabled_emitters: tuple[str, ...] = DEFAULT_ENABLED_EMITTERS
    enabled_validators: tuple[str, ...] = DEFAULT_ENABLED_VALIDATORS
    manual_verification_required: bool = True


def default_config(base_dir: Path | None = None) -> SoloctlConfig:
    base = base_dir or Path.cwd()
    return SoloctlConfig(library_root=(base / "library").resolve())


def load_config(path: Path | None = None, *,
                 base_dir: Path | None = None) -> SoloctlConfig:
    """Load configuration from soloctl.toml. If no file exists at the
    resolved path, returns defaults rather than failing — a fresh checkout
    with no soloctl.toml is a valid starting state."""
    base = (base_dir or Path.cwd()).resolve()
    cfg_path = path if path is not None else (base / CONFIG_FILENAME)

    if not cfg_path.exists():
        return default_config(base)

    try:
        raw_text = cfg_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"cannot read configuration file {cfg_path}: {exc}. "
            f"Check the file exists and is readable, or remove --config to use defaults."
        ) from exc

    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{cfg_path} is not valid TOML: {exc}. Fix the syntax error and re-run."
        ) from exc

    return _parse(data, cfg_path, base)


def _parse(data: dict, cfg_path: Path, base: Path) -> SoloctlConfig:
    unknown = set(data) - _KNOWN_KEYS
    if unknown:
        raise ConfigError(
            f"{cfg_path}: unknown configuration key(s) {sorted(unknown)}. "
            f"Valid keys are {sorted(_KNOWN_KEYS)}."
        )

    library_root = _parse_library_root(data.get("library_root", "library"), cfg_path, base)
    default_sql_dialect = _parse_optional_str(
        data, "default_sql_dialect", cfg_path)
    enabled_emitters = _parse_str_tuple(
        data, "enabled_emitters", DEFAULT_ENABLED_EMITTERS, cfg_path)
    enabled_validators = _parse_str_tuple(
        data, "enabled_validators", DEFAULT_ENABLED_VALIDATORS, cfg_path)
    manual_verification_required = _parse_bool(
        data, "manual_verification_required", True, cfg_path)

    return SoloctlConfig(
        library_root=library_root,
        default_sql_dialect=default_sql_dialect,
        enabled_emitters=enabled_emitters,
        enabled_validators=enabled_validators,
        manual_verification_required=manual_verification_required,
    )


def _parse_library_root(raw: object, cfg_path: Path, base: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(
            f"{cfg_path}: 'library_root' must be a non-empty string path, got {raw!r}."
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _parse_optional_str(data: dict, key: str, cfg_path: Path) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"{cfg_path}: '{key}' must be a string or omitted, got {value!r}.")
    return value


def _parse_str_tuple(data: dict, key: str, default: tuple[str, ...],
                     cfg_path: Path) -> tuple[str, ...]:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(
            f"{cfg_path}: '{key}' must be a list of strings, got {value!r}."
        )
    return tuple(value)


def _parse_bool(data: dict, key: str, default: bool, cfg_path: Path) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{cfg_path}: '{key}' must be true or false, got {value!r}.")
    return value
