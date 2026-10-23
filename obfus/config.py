"""Loading and validation of ``.obfusconfig.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = ".obfusconfig.json"


@dataclass
class EncryptionConfig:
    enabled: bool = False
    password_env: str = "OBFUS_PASSWORD"


@dataclass
class Config:
    encryption: EncryptionConfig = field(default_factory=EncryptionConfig)


def default() -> Config:
    return Config()


def load(path: str | Path) -> Config:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"read config: {exc}") from exc
    try:
        raw = json.loads(data)
    except ValueError as exc:
        raise ValueError(f"parse config: {exc}") from exc

    cfg = default()
    if raw is not None:
        if not isinstance(raw, dict):
            raise ValueError("parse config: top-level value must be an object")
        enc = raw.get("encryption")
        if enc is not None:
            if not isinstance(enc, dict):
                raise ValueError("parse config: 'encryption' must be an object")
            if enc.get("enabled") is not None:
                if not isinstance(enc["enabled"], bool):
                    raise ValueError("parse config: 'encryption.enabled' must be a boolean")
                cfg.encryption.enabled = enc["enabled"]
            if enc.get("passwordEnv") is not None:
                if not isinstance(enc["passwordEnv"], str):
                    raise ValueError("parse config: 'encryption.passwordEnv' must be a string")
                cfg.encryption.password_env = enc["passwordEnv"]

    _validate(cfg)
    return cfg


def load_optional(path: str | Path) -> Config:
    if not Path(path).exists():
        return default()
    return load(path)


def resolve_config_path(working_dir: str | Path) -> Path:
    return Path(working_dir) / CONFIG_FILENAME


def _validate(cfg: Config) -> None:
    if not cfg.encryption.password_env:
        raise ValueError("encryption.passwordEnv must not be empty")
