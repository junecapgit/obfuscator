from __future__ import annotations

_WHITESPACE = frozenset(" \t\n\r\f\v")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_ASCII_DIGITS = frozenset("0123456789")


def is_ascii_letter(ch: str) -> bool:
    return ch in _ASCII_LETTERS


def is_ascii_digit(ch: str) -> bool:
    return ch in _ASCII_DIGITS


def is_identifier_start(ch: str, allow_dollar: bool) -> bool:
    if ch == "_":
        return True
    if allow_dollar and ch == "$":
        return True
    return is_ascii_letter(ch)


def is_identifier_part(ch: str, allow_dollar: bool) -> bool:
    return is_identifier_start(ch, allow_dollar) or is_ascii_digit(ch)


def is_whitespace(ch: str) -> bool:
    return ch in _WHITESPACE


def scan_quoted(src: str, start: int, quote: str, allow_escapes: bool) -> int:
    """Return the end index (exclusive) of a quoted literal starting at ``start``."""
    i = start + 1
    n = len(src)
    while i < n:
        ch = src[i]
        if allow_escapes and ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return n


def scan_triple_quoted(src: str, start: int, quote: str) -> int:
    i = start + 3
    n = len(src)
    triple = quote * 3
    while i + 2 < n:
        if src.startswith(triple, i):
            return i + 3
        i += 1
    return n


def detect_quote(raw: str) -> tuple[int, str]:
    """Locate the opening quote of a string literal; returns ``(index, delimiter)``.

    ``delimiter`` is empty when ``raw`` contains no quote (e.g. a heredoc).
    """
    for i, ch in enumerate(raw):
        if ch not in "'\"`":
            continue
        if ch == "`":
            return i, "`"
        if raw[i + 1 : i + 3] == ch * 2:
            return i, ch * 3
        return i, ch
    return 0, ""


def scan_line_comment(src: str, start: int, prefix_len: int) -> int:
    """Return the index of the terminating newline (or end of input)."""
    i = start + prefix_len
    n = len(src)
    while i < n and src[i] != "\n":
        i += 1
    return i


def scan_block_comment(src: str, start: int) -> int:
    """Return the end index of a ``/* ... */`` comment (mirrors the Go scanner)."""
    i = start + 2
    n = len(src)
    while i + 1 < n:
        if src[i] == "*" and src[i + 1] == "/":
            i += 2
            break
        i += 1
    return min(i, n)
