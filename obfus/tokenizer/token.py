from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class TokenType(str, Enum):
    IDENTIFIER = "identifier"
    STRING = "string"
    COMMENT = "comment"
    KEYWORD = "keyword"
    WHITESPACE = "whitespace"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    raw: str


def reconstruct(tokens: Iterable[Token]) -> str:
    return "".join(token.raw for token in tokens)
