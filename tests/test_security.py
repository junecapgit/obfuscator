import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from obfus.security import decrypt, encrypt


def test_encrypt_decrypt_symmetric():
    plaintext = b'{"forward":{"a":"b"}}'
    password = "correct-horse-battery-staple"

    encrypted = encrypt(plaintext, password)

    assert plaintext not in encrypted
    assert decrypt(encrypted, password) == plaintext


def test_decrypt_wrong_password_fails():
    encrypted = encrypt(b"sensitive mapping content", "right-password")
    with pytest.raises(ValueError, match="decrypt failed"):
        decrypt(encrypted, "wrong-password")


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        encrypt(b"x", "")
    with pytest.raises(ValueError):
        decrypt(b"{}", "")


def test_decrypts_envelope_in_go_wire_format():
    # Envelope built per the Go spec: key = SHA-256(password || salt), AES-256-GCM, no AAD.
    password, salt, nonce = "pw", bytes(range(32)), bytes(range(12))
    key = hashlib.sha256(password.encode() + salt).digest()
    ciphertext = AESGCM(key).encrypt(nonce, b"hello", None)
    envelope = {
        "version": "1",
        "algorithm": "AES-256-GCM",
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    assert decrypt(json.dumps(envelope).encode(), password) == b"hello"


def test_unsupported_algorithm_rejected():
    payload = json.dumps({"algorithm": "ROT13"}).encode()
    with pytest.raises(ValueError, match="unsupported algorithm"):
        decrypt(payload, "pw")
