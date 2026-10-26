import json
import pytest

from obfus.mapping import Mapping
from obfus.patterns import (
    ai_safe_text,
    compile_pattern,
    load_patterns_file,
    normalize_pattern,
    obfuscate_text,
    restore_text,
)


def test_normalize_pattern_bracket_alternation():
    pat = r"app-[dev|qa|prod]-\d{3}"
    normalized = normalize_pattern(pat)
    assert normalized == r"app-(?:dev|qa|prod)-\d{3}"


def test_compile_pattern_and_matching():
    cp = compile_pattern(r"app-[dev|qa|prod]-\d{3}")
    assert cp.search("server: app-dev-001") is not None
    assert cp.search("server: app-qa-999") is not None
    assert cp.search("server: app-prod-123") is not None
    assert cp.search("server: app-other-123") is None

    # Literal token compilation
    cp_literal = compile_pattern("John Smith")
    assert cp_literal.search("Hello John Smith!") is not None
    assert cp_literal.search("Hello John Smithson!") is None


def test_obfuscate_and_restore_text():
    text = (
        '# Created by John Smith\n'
        'account_id = "ABC12345"\n'
        'dev_server = "app-dev-001"\n'
        'prod_server = "app-prod-999"\n'
        'note = "Contact John Smith for ABC12345"\n'
    )
    patterns = ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]

    safe, m = obfuscate_text(text, patterns)

    # Verify sensitive tokens are replaced
    assert "John Smith" not in safe
    assert "ABC12345" not in safe
    assert "app-dev-001" not in safe
    assert "app-prod-999" not in safe

    # Verify placeholder consistency (John Smith and ABC12345 appeared multiple times)
    placeholder_john = m.forward["John Smith"]
    placeholder_abc = m.forward["ABC12345"]
    assert safe.count(placeholder_john) == 2
    assert safe.count(placeholder_abc) == 2

    # Restore and verify round trip
    restored = restore_text(safe, m)
    assert restored == text


def test_load_patterns_file_json_array(tmp_path):
    pfile = tmp_path / "tokens.json"
    pfile.write_text(json.dumps(["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]))

    loaded = load_patterns_file(pfile)
    assert loaded == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]


def test_load_patterns_file_json_object(tmp_path):
    pfile = tmp_path / "patterns.json"
    pfile.write_text(
        json.dumps({
            "tokens": ["John Smith", "ABC12345"],
            "patterns": [r"app-[dev|qa|prod]-\d{3}"],
        })
    )

    loaded = load_patterns_file(pfile)
    assert "John Smith" in loaded
    assert "ABC12345" in loaded
    assert r"app-[dev|qa|prod]-\d{3}" in loaded


def test_load_patterns_file_with_raw_unescaped_backslashes(tmp_path):
    # Standard json.loads would fail on raw \d
    pfile = tmp_path / "patterns_raw.json"
    pfile.write_bytes(b'["John Smith", "ABC12345", "app-[dev|qa|prod]-\\d{3}"]')

    loaded = load_patterns_file(pfile)
    assert "John Smith" in loaded
    assert "ABC12345" in loaded
    assert any("app-" in p for p in loaded)


def test_load_patterns_file_plaintext_lines(tmp_path):
    pfile = tmp_path / "patterns.txt"
    pfile.write_text(
        "# Comment line\n"
        "John Smith\n"
        "ABC12345\n"
        "\n"
        r"app-[dev|qa|prod]-\d{3}" + "\n"
    )

    loaded = load_patterns_file(pfile)
    assert loaded == ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]


def test_ai_safe_text_redacts_patterns():
    text = "User John Smith deployed app-dev-123 with key ABC12345."
    patterns = ["John Smith", "ABC12345", r"app-[dev|qa|prod]-\d{3}"]

    safe = ai_safe_text(text, patterns)
    assert "John Smith" not in safe
    assert "app-dev-123" not in safe
    assert "ABC12345" not in safe
    assert "REDACTED_TOKEN_1" in safe
