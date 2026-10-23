from __future__ import annotations

from obfus.tokenizer.helpers import (
    is_identifier_part,
    is_identifier_start,
    is_whitespace,
    scan_block_comment,
    scan_line_comment,
    scan_quoted,
)
from obfus.tokenizer.token import Token, TokenType

JS_KEYWORDS = frozenset(
    """break case catch class const continue debugger default delete do else export
    extends finally for function if import in instanceof let new return super switch
    this throw try typeof var void while with yield await enum implements interface
    package private protected public static null true false""".split()
)


def tokenize_javascript(source: str) -> list[Token]:
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

        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            end = scan_line_comment(source, i, 2)
            tokens.append(Token(TokenType.COMMENT, source[i:end]))
            i = end
            continue

        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            end = scan_block_comment(source, i)
            tokens.append(Token(TokenType.COMMENT, source[i:end]))
            i = end
            continue

        if ch in "'\"`":
            end = scan_quoted(source, i, ch, True)
            tokens.append(Token(TokenType.STRING, source[i:end]))
            i = end
            continue

        if is_identifier_start(ch, True):
            start = i
            i += 1
            while i < n and is_identifier_part(source[i], True):
                i += 1
            value = source[start:i]
            kind = TokenType.KEYWORD if value in JS_KEYWORDS else TokenType.IDENTIFIER
            tokens.append(Token(kind, value))
            continue

        tokens.append(Token(TokenType.OTHER, ch))
        i += 1

    return tokens
