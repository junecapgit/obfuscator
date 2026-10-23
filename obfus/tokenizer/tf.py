from __future__ import annotations

from obfus.tokenizer.helpers import (
    is_ascii_digit,
    is_ascii_letter,
    is_whitespace,
    scan_block_comment,
    scan_line_comment,
    scan_quoted,
)
from obfus.tokenizer.token import Token, TokenType

TF_KEYWORDS = frozenset(
    {"resource", "module", "variable", "output", "locals", "provider", "data", "terraform"}
)


def tokenize_terraform(source: str) -> list[Token]:
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

        if ch == "<" and i + 1 < n and source[i + 1] == "<":
            end = _scan_heredoc(source, i)
            if end is not None:
                tokens.append(Token(TokenType.STRING, source[i:end]))
                i = end
                continue

        if ch == '"':
            end = scan_quoted(source, i, ch, True)
            tokens.append(Token(TokenType.STRING, source[i:end]))
            i = end
            continue

        if _is_identifier_start(ch):
            start = i
            i += 1
            while i < n and _is_identifier_part(source[i]):
                i += 1
            value = source[start:i]
            kind = TokenType.KEYWORD if value in TF_KEYWORDS else TokenType.IDENTIFIER
            tokens.append(Token(kind, value))
            continue

        tokens.append(Token(TokenType.OTHER, ch))
        i += 1

    return tokens


def _is_identifier_start(ch: str) -> bool:
    return is_ascii_letter(ch) or ch == "_"


def _is_identifier_part(ch: str) -> bool:
    return _is_identifier_start(ch) or is_ascii_digit(ch) or ch == "-"


def _scan_heredoc(src: str, start: int) -> int | None:
    n = len(src)
    header_end = src.find("\n", start)
    if header_end == -1:
        header_end = n

    parsed = _parse_heredoc_header(src[start:header_end])
    if parsed is None:
        return None
    delimiter, allow_indent = parsed

    if header_end == n:
        return n

    i = header_end + 1
    while i <= n:
        line_start = i
        while i < n and src[i] != "\n":
            i += 1
        line = src[line_start:i]
        check = line.lstrip(" \t") if allow_indent else line
        if check == delimiter:
            return i + 1 if i < n else i
        if i >= n:
            break
        i += 1

    return n


def _parse_heredoc_header(header: str) -> tuple[str, bool] | None:
    trimmed = header.strip()
    if not trimmed.startswith("<<"):
        return None

    rest = trimmed[2:].strip()
    allow_indent = False
    if rest.startswith("-"):
        allow_indent = True
        rest = rest[1:].strip()
    if not rest:
        return None

    parts = rest.split()
    if not parts:
        return None
    delimiter = parts[0].strip("\"'")
    if not delimiter:
        return None
    for ch in delimiter:
        if not (is_ascii_letter(ch) or is_ascii_digit(ch) or ch in "_-"):
            return None

    return delimiter, allow_indent
