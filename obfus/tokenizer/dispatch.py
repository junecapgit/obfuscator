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
    ".tfvars": tokenize_terraform,
    ".hcl": tokenize_terraform,
    ".tfbackend": tokenize_terraform,
}

_SPECIAL_TERRAFORM_SUFFIXES = (".tf.json", ".tfvars.json")
_SPECIAL_TERRAFORM_NAMES = frozenset({".terraformrc", "terraform.rc", ".tofurc"})


def for_file(path: str) -> Tokenizer:
    p = PurePath(path)
    lower_name = p.name.lower()
    for suffix in _SPECIAL_TERRAFORM_SUFFIXES:
        if lower_name.endswith(suffix):
            return tokenize_terraform
    if lower_name in _SPECIAL_TERRAFORM_NAMES:
        return tokenize_terraform

    ext = p.suffix.lower()
    try:
        return _BY_EXTENSION[ext]
    except KeyError:
        raise ValueError(f"unsupported file extension {ext!r}") from None


def is_supported_file(path: str) -> bool:
    try:
        for_file(path)
        return True
    except ValueError:
        return False
