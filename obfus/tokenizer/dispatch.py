from __future__ import annotations

from pathlib import PurePath
from typing import Callable

from obfus.tokenizer.js import tokenize_javascript
from obfus.tokenizer.py import tokenize_python
from obfus.tokenizer.tf import tokenize_terraform
from obfus.tokenizer.token import Token

Tokenizer = Callable[[str], list[Token]]

_BY_EXTENSION: dict[str, Tokenizer] = {
    ".js": tokenize_javascript,
    ".py": tokenize_python,
    ".tf": tokenize_terraform,
}


def for_file(path: str) -> Tokenizer:
    ext = PurePath(path).suffix.lower()
    try:
        return _BY_EXTENSION[ext]
    except KeyError:
        raise ValueError(f"unsupported file extension {ext!r}") from None
