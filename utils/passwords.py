from __future__ import annotations

import base64
import hashlib
import os
import secrets


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    encoded_salt = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"scrypt$16384$8$1${encoded_salt}${encoded_digest}"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password_hash(password: str, encoded: str) -> bool:
    if not encoded.startswith("scrypt$"):
        # Backward-compatible verification for databases created by older releases.
        return secrets.compare_digest(hashlib.sha256(password.encode()).hexdigest(), encoded)
    try:
        _, n, r, p, salt, expected = encoded.split("$", 5)
        expected_raw = _b64decode(expected)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(expected_raw),
        )
        return secrets.compare_digest(actual, expected_raw)
    except Exception:
        return False
