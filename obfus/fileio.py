"""Byte-faithful file IO.

Files are decoded as UTF-8 with ``surrogateescape`` so arbitrary bytes survive
a read/write round trip unchanged, and no newline translation occurs.
"""

from __future__ import annotations

import os
from pathlib import Path

_ERRORS = "surrogateescape"


def read_text(path: str | os.PathLike[str]) -> str:
    return Path(path).read_bytes().decode("utf-8", _ERRORS)


def write_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """Write ``data`` creating the file with owner-only permissions (0o600)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def write_text(path: str | os.PathLike[str], text: str) -> None:
    write_bytes(path, text.encode("utf-8", _ERRORS))
