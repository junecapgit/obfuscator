import pytest

from obfus.mapping import generate, invert
from obfus.tokenizer import Token, TokenType


def test_generate_is_deterministic_and_collision_free():
    tokens = [
        Token(TokenType.KEYWORD, "const"),
        Token(TokenType.WHITESPACE, " "),
        Token(TokenType.IDENTIFIER, "customerId"),
        Token(TokenType.WHITESPACE, " "),
        Token(TokenType.OTHER, "="),
        Token(TokenType.WHITESPACE, " "),
        Token(TokenType.STRING, '"ABC123"'),
        Token(TokenType.OTHER, ";"),
        Token(TokenType.WHITESPACE, " "),
        Token(TokenType.IDENTIFIER, "customerId"),
    ]

    m1, m2 = generate(tokens), generate(tokens)

    assert len(m1.forward) == 2
    assert m1.forward == m2.forward
    assert m1.forward["customerId"] == "obf_var_1"
    assert m1.forward['"ABC123"'] == '"obf_str_1"'
    assert m1.forward["customerId"] != m1.forward['"ABC123"']


def test_generate_skips_replacement_that_collides_with_existing_name():
    tokens = [
        Token(TokenType.IDENTIFIER, "obf_var_1"),
        Token(TokenType.IDENTIFIER, "other"),
    ]
    m = generate(tokens)
    # "obf_var_1" is not yet taken when first seen, so it maps to itself; the next name must skip it.
    assert m.forward == {"obf_var_1": "obf_var_1", "other": "obf_var_2"}


def test_invert_builds_reverse_without_data_loss():
    forward = {"customerId": "obf_var_1", '"ABC123"': '"obf_str_1"'}
    reverse = invert(forward)
    assert reverse["obf_var_1"] == "customerId"
    assert reverse['"obf_str_1"'] == '"ABC123"'


def test_invert_fails_on_duplicate_replacement():
    with pytest.raises(ValueError, match="duplicate replacement"):
        invert({"a": "x", "b": "x"})
