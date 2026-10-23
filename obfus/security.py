"""AES-256-GCM envelope encryption (wire-compatible with the Go implementation)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT_SIZE = 32
NONCE_SIZE = 12
ALGORITHM = "AES-256-GCM"


def encrypt(plaintext: bytes, password: str) -> bytes:
    if not password:
        raise ValueError("password is required")

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(_derive_key(password, salt)).encrypt(nonce, plaintext, None)

    envelope = {
        "version": "1",
        "algorithm": ALGORITHM,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def decrypt(payload: bytes, password: str) -> bytes:
    if not password:
        raise ValueError("password is required")

    try:
        env = json.loads(payload)
    except ValueError as exc:
        raise ValueError(f"parse encrypted envelope: {exc}") from exc
    if not isinstance(env, dict):
        raise ValueError("parse encrypted envelope: top-level value must be an object")

    algorithm = env.get("algorithm", "")
    if algorithm != ALGORITHM:
        raise ValueError(f"unsupported algorithm {algorithm!r}")

    salt = _b64(env, "salt")
    nonce = _b64(env, "nonce")
    ciphertext = _b64(env, "ciphertext")

    try:
        return AESGCM(_derive_key(password, salt)).decrypt(nonce, ciphertext, None)
    except (InvalidTag, ValueError) as exc:
        raise ValueError("decrypt failed: invalid password or corrupted payload") from exc


def _b64(env: dict, name: str) -> bytes:
    value = env.get(name, "")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise ValueError(f"decode {name}: {exc}") from exc


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.sha256(password.encode("utf-8") + salt).digest()
