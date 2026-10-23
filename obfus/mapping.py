"""Deterministic forward/reverse identifier and string mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from obfus.tokenizer import Token, TokenType
from obfus.tokenizer.helpers import detect_quote


@dataclass
class Mapping:
    forward: dict[str, str] = field(default_factory=dict)
    reverse: dict[str, str] = field(default_factory=dict)


def generate(tokens: Iterable[Token]) -> Mapping:
    result = Mapping()
    identifier_index = 1
    string_index = 1

    for token in tokens:
        if token.type is TokenType.IDENTIFIER:
            if token.raw in result.forward:
                continue
            replacement = _next_available_identifier(result, identifier_index)
            identifier_index += 1
        elif token.type is TokenType.STRING:
            if token.raw in result.forward:
                continue
            replacement = _placeholder_string_literal(token.raw, string_index)
            while _has_conflict(result, replacement):
                string_index += 1
                replacement = _placeholder_string_literal(token.raw, string_index)
            string_index += 1
        else:
            continue
        result.forward[token.raw] = replacement
        result.reverse[replacement] = token.raw

    return result


def invert(forward: dict[str, str]) -> dict[str, str]:
    reverse: dict[str, str] = {}
    for original, replacement in forward.items():
        if replacement in reverse:
            raise ValueError(
                f"duplicate replacement {replacement!r} for originals "
                f"{reverse[replacement]!r} and {original!r}"
            )
        reverse[replacement] = original
    return reverse


def build_from_forward(forward: dict[str, str]) -> Mapping:
    return Mapping(forward=forward, reverse=invert(forward))


def _has_conflict(current: Mapping, replacement: str) -> bool:
    return replacement in current.reverse or replacement in current.forward


def _next_available_identifier(current: Mapping, start: int) -> str:
    index = start
    while True:
        candidate = f"obf_var_{index}"
        if not _has_conflict(current, candidate):
            return candidate
        index += 1


def _placeholder_string_literal(raw: str, index: int) -> str:
    payload = f"obf_str_{index}"
    quote_start, quote_delim = detect_quote(raw)
    if not quote_delim:
        return payload
    return raw[:quote_start] + quote_delim + payload + quote_delim
