"""Mapping persistence: plain JSON and AES-256-GCM encrypted."""

from __future__ import annotations

import json
from pathlib import Path

from obfus import security
from obfus.fileio import write_bytes
from obfus.mapping import Mapping


def save_mapping(path: str | Path, m: Mapping) -> None:
    _validate(m)
    data = json.dumps(_to_dict(m), indent=2, sort_keys=True)
    write_bytes(path, data.encode("utf-8"))


def load_mapping(path: str | Path) -> Mapping:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"read mapping file: {exc}") from exc
    return _parse(data, "parse mapping JSON")


def save_mapping_encrypted(path: str | Path, m: Mapping, password: str) -> None:
    _validate(m)
    data = json.dumps(_to_dict(m), sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        encrypted = security.encrypt(data, password)
    except ValueError as exc:
        raise ValueError(f"encrypt mapping: {exc}") from exc
    write_bytes(path, encrypted)


def load_mapping_encrypted(path: str | Path, password: str) -> Mapping:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"read encrypted mapping file: {exc}") from exc
    try:
        plaintext = security.decrypt(data, password)
    except ValueError as exc:
        raise ValueError(f"decrypt mapping: {exc}") from exc
    return _parse(plaintext, "parse decrypted mapping JSON")


def _to_dict(m: Mapping) -> dict[str, dict[str, str]]:
    return {"forward": m.forward, "reverse": m.reverse}


def _parse(data: bytes, context: str) -> Mapping:
    try:
        raw = json.loads(data)
    except ValueError as exc:
        raise ValueError(f"{context}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{context}: top-level value must be an object")
    forward, reverse = raw.get("forward"), raw.get("reverse")
    for name, table in (("forward", forward), ("reverse", reverse)):
        if table is not None and not (
            isinstance(table, dict) and all(isinstance(v, str) for v in table.values())
        ):
            raise ValueError(f"{context}: '{name}' must be an object of strings")

    m = Mapping(forward=forward, reverse=reverse)  # type: ignore[arg-type]
    _validate(m)
    return m


def _validate(m: Mapping) -> None:
    if m.forward is None or m.reverse is None:
        raise ValueError("mapping must include forward and reverse maps")
    if len(m.forward) != len(m.reverse):
        raise ValueError("mapping forward/reverse size mismatch")

    for original, replacement in m.forward.items():
        if replacement not in m.reverse:
            raise ValueError(f"missing reverse entry for replacement {replacement!r}")
        if m.reverse[replacement] != original:
            raise ValueError(f"reverse mismatch for replacement {replacement!r}")
