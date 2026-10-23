import json

import pytest

from obfus.mapping import Mapping
from obfus.storage import (
    load_mapping,
    load_mapping_encrypted,
    save_mapping,
    save_mapping_encrypted,
)

MAPPING = Mapping(
    forward={"customerId": "obf_var_1", '"ABC123"': '"obf_str_1"'},
    reverse={"obf_var_1": "customerId", '"obf_str_1"': '"ABC123"'},
)


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "mapping.json"
    save_mapping(path, MAPPING)

    out = load_mapping(path)

    assert out == MAPPING


def test_load_corrupted_json_fails(tmp_path):
    path = tmp_path / "mapping.json"
    path.write_text("{invalid-json")
    with pytest.raises(ValueError, match="parse mapping JSON"):
        load_mapping(path)


def test_load_missing_file_fails(tmp_path):
    with pytest.raises(ValueError, match="read mapping file"):
        load_mapping(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "payload",
    [
        {"forward": {"a": "x"}},
        {"forward": {"a": "x"}, "reverse": {}},
        {"forward": {"a": "x"}, "reverse": {"x": "b"}},
        {"forward": {"a": "x"}, "reverse": {"y": "a"}},
        {"forward": None, "reverse": None},
    ],
)
def test_load_rejects_inconsistent_mapping(tmp_path, payload):
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_mapping(path)


def test_encrypted_round_trip_and_wrong_password(tmp_path):
    path = tmp_path / "map.enc"
    save_mapping_encrypted(path, MAPPING, "secret")

    assert b"customerId" not in path.read_bytes()
    assert load_mapping_encrypted(path, "secret") == MAPPING
    with pytest.raises(ValueError, match="decrypt mapping"):
        load_mapping_encrypted(path, "nope")
