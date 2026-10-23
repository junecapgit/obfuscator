from __future__ import annotations

from obfus.tokenizer.helpers import (
    is_identifier_part,
    is_identifier_start,
    is_whitespace,
    scan_line_comment,
    scan_quoted,
    scan_triple_quoted,
)
from obfus.tokenizer.token import Token, TokenType

PY_KEYWORDS = frozenset(
    """False None True and as assert async await break class continue def del elif else
    except finally for from global if import in is lambda nonlocal not or pass raise
    return try while with yield""".split()
)

_STRING_PREFIX_CHARS = frozenset("rRbBfFuU")


def tokenize_python(source: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(source)
    i = 0
    while i < n:
        ch = source[i]

        if is_whitespace(ch):
            start = i
            while i < n and is_whitespace(source[i]):
                i += 1
            tokens.append(Token(TokenType.WHITESPACE, source[start:i]))
            continue

        if ch == "#":
            end = scan_line_comment(source, i, 0)
            tokens.append(Token(TokenType.COMMENT, source[i:end]))
            i = end
            continue

        end = _scan_python_string(source, i)
        if end is not None:
            tokens.append(Token(TokenType.STRING, source[i:end]))
            i = end
            continue

        if is_identifier_start(ch, False):
            start = i
            i += 1
            while i < n and is_identifier_part(source[i], False):
                i += 1
            value = source[start:i]
            kind = TokenType.KEYWORD if value in PY_KEYWORDS else TokenType.IDENTIFIER
            tokens.append(Token(kind, value))
            continue

        tokens.append(Token(TokenType.OTHER, ch))
        i += 1

    return tokens


def _scan_python_string(src: str, start: int) -> int | None:
    n = len(src)
    prefix_end = start
    while prefix_end < n and src[prefix_end] in _STRING_PREFIX_CHARS:
        prefix_end += 1

    if prefix_end >= n:
        return None

    quote = src[prefix_end]
    if quote not in "'\"":
        return None

    if prefix_end + 2 < n and src[prefix_end + 1] == quote and src[prefix_end + 2] == quote:
        return scan_triple_quoted(src, prefix_end, quote)

    is_raw = any(c in "rR" for c in src[start:prefix_end])
    return scan_quoted(src, prefix_end, quote, not is_raw)
