import pytest

from obfus.config import load, load_optional


def test_load_optional_returns_defaults_when_missing(tmp_path):
    cfg = load_optional(tmp_path / ".obfusconfig.json")
    assert cfg.encryption.enabled is False
    assert cfg.encryption.password_env == "OBFUS_PASSWORD"


def test_load_invalid_config_fails(tmp_path):
    path = tmp_path / ".obfusconfig.json"
    path.write_text('{"encryption":{"enabled":true,"passwordEnv":""}}')
    with pytest.raises(ValueError, match="passwordEnv must not be empty"):
        load(path)


def test_load_partial_config_keeps_defaults(tmp_path):
    path = tmp_path / ".obfusconfig.json"
    path.write_text('{"encryption":{"enabled":true}}')
    cfg = load(path)
    assert cfg.encryption.enabled is True
    assert cfg.encryption.password_env == "OBFUS_PASSWORD"


def test_load_malformed_json_fails(tmp_path):
    path = tmp_path / ".obfusconfig.json"
    path.write_text("{nope")
    with pytest.raises(ValueError, match="parse config"):
        load(path)
