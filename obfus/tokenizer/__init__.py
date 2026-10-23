"""Lightweight, lossless tokenizers for JavaScript, Python and Terraform."""

from obfus.tokenizer.dispatch import for_file
from obfus.tokenizer.js import tokenize_javascript
from obfus.tokenizer.py import tokenize_python
from obfus.tokenizer.tf import tokenize_terraform
from obfus.tokenizer.token import Token, TokenType, reconstruct

__all__ = [
    "Token",
    "TokenType",
    "reconstruct",
    "for_file",
    "tokenize_javascript",
    "tokenize_python",
    "tokenize_terraform",
]
