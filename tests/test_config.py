import json
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


def test_load_target_and_input_dir(tmp_path):
    path = tmp_path / ".obfusconfig.json"
    path.write_text('{"targetDir":"./dist_custom","inputDir":"./src_custom"}')
    cfg = load(path)
    assert cfg.target_dir == "./dist_custom"
    assert cfg.input_dir == "./src_custom"


def test_load_json_array_config_file(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]))
    cfg = load(path)
    assert cfg.patterns == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]
    assert cfg.all_patterns() == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]


def test_load_tokens_and_patterns_object(tmp_path):
    path = tmp_path / ".obfusconfig.json"
    path.write_text(json.dumps({
        "tokens": ["John Smith", "ABC12345"],
        "patterns": [r"app-[dev|qa|prod]-\d{3}"],
    }))
    cfg = load(path)
    assert cfg.tokens == ["John Smith", "ABC12345"]
    assert cfg.patterns == [r"app-[dev|qa|prod]-\d{3}"]
    assert cfg.all_patterns() == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]


def test_load_config_with_external_patterns_file(tmp_path):
    pfile = tmp_path / "custom_patterns.json"
    pfile.write_text(json.dumps(["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]))

    cfg_file = tmp_path / ".obfusconfig.json"
    cfg_file.write_text(json.dumps({"patternsFile": "custom_patterns.json"}))

    cfg = load(cfg_file)
    assert cfg.all_patterns() == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]


def test_load_optional_finds_default_tokens_file(tmp_path):
    # If .obfusconfig.json is absent, load_optional checks for tokens.json
    pfile = tmp_path / "tokens.json"
    pfile.write_text(json.dumps(["John Smith", "ABC12345"]))

    cfg = load_optional(tmp_path / ".obfusconfig.json")
    assert cfg.all_patterns() == ["John Smith", "ABC12345"]
