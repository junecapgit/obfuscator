from obfus.mapping import generate
from obfus.tokenizer import reconstruct, tokenize_javascript
from obfus.transform import ai_safe_tokens, obfuscate_tokens, restore_tokens


def test_obfuscate_and_restore_round_trip():
    source = 'const customerId = "ABC123";'
    tokens = tokenize_javascript(source)

    m = generate(tokens)
    obfuscated_source = reconstruct(obfuscate_tokens(tokens, m))
    assert obfuscated_source != source

    restored = restore_tokens(tokenize_javascript(obfuscated_source), m)
    assert reconstruct(restored) == source


def test_ai_safe_redacts_sensitive_values():
    source = 'const customerId = "ABC123"; // user comment'
    safe = reconstruct(ai_safe_tokens(tokenize_javascript(source)))

    assert "customerId" not in safe
    assert "ABC123" not in safe
    assert "user comment" not in safe
    assert "REDACTED_STR_1" in safe


def test_ai_safe_preserves_comment_style():
    source = "# a\n// b\n/* c */\n"
    from obfus.tokenizer import tokenize_terraform

    safe = reconstruct(ai_safe_tokens(tokenize_terraform(source)))
    assert safe == "# REDACTED_COMMENT_1\n// REDACTED_COMMENT_2\n/* REDACTED_COMMENT_3 */\n"
