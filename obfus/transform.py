"""Obfuscate, restore and irreversible AI-safe token transforms."""

from __future__ import annotations

from typing import Callable, Iterable

from obfus.mapping import Mapping
from obfus.tokenizer import Token, TokenType, reconstruct
from obfus.tokenizer.helpers import detect_quote


def obfuscate_tokens(tokens: Iterable[Token], m: Mapping) -> list[Token]:
    return [_replace(token, m.forward) for token in tokens]


def restore_tokens(tokens: Iterable[Token], m: Mapping) -> list[Token]:
    return [_replace(token, m.reverse) for token in tokens]


def restore_source(
    obfuscated_source: str,
    tokenize: Callable[[str], list[Token]],
    m: Mapping,
) -> str:
    return reconstruct(restore_tokens(tokenize(obfuscated_source), m))


def ai_safe_tokens(tokens: Iterable[Token]) -> list[Token]:
    safe: list[Token] = []
    id_index = str_index = comment_index = 1

    for token in tokens:
        if token.type is TokenType.IDENTIFIER:
            safe.append(Token(token.type, f"REDACTED_ID_{id_index}"))
            id_index += 1
        elif token.type is TokenType.STRING:
            safe.append(Token(token.type, _redact_string_literal(token.raw, str_index)))
            str_index += 1
        elif token.type is TokenType.COMMENT:
            safe.append(Token(token.type, _redact_comment(token.raw, comment_index)))
            comment_index += 1
        else:
            safe.append(token)

    return safe


def _replace(token: Token, table: dict[str, str]) -> Token:
    replacement = table.get(token.raw)
    return token if replacement is None else Token(token.type, replacement)


def _redact_string_literal(raw: str, index: int) -> str:
    label = f"REDACTED_STR_{index}"
    quote_start, quote_delim = detect_quote(raw)
    if not quote_delim:
        return label
    return raw[:quote_start] + quote_delim + label + quote_delim


def _redact_comment(raw: str, index: int) -> str:
    if raw.startswith("#"):
        return f"# REDACTED_COMMENT_{index}"
    if raw.startswith("//"):
        return f"// REDACTED_COMMENT_{index}"
    if raw.startswith("/*"):
        return f"/* REDACTED_COMMENT_{index} */"
    return f"REDACTED_COMMENT_{index}"
