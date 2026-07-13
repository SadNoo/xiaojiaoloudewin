from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


_LICENSE_CODE_AAD = b"xianyuxian/license-code/v1"


def utc_now() -> datetime:
    return datetime.now(UTC)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_opaque_token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def normalize_license_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def new_license_code() -> str:
    raw = b64url(secrets.token_bytes(20)).upper().replace("_", "X").replace("-", "Y")[:25]
    return "XY-" + "-".join(raw[i : i + 5] for i in range(0, 25, 5))


def license_lookup(code: str, secret: bytes) -> str:
    return hmac.new(secret, normalize_license_code(code).encode("ascii"), hashlib.sha256).hexdigest()


def _license_code_encryption_key(secret: bytes) -> bytes:
    return hmac.new(secret, b"xianyuxian/license-code-encryption-key/v1", hashlib.sha256).digest()


def encrypt_license_code(code: str, secret: bytes) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_license_code_encryption_key(secret)).encrypt(
        nonce,
        code.encode("ascii"),
        _LICENSE_CODE_AAD,
    )
    return f"v1.{b64url(nonce + ciphertext)}"


def decrypt_license_code(value: str, secret: bytes) -> str:
    version, encoded = value.split(".", 1)
    if version != "v1":
        raise ValueError("unsupported license code ciphertext version")
    payload = b64url_decode(encoded)
    if len(payload) <= 12:
        raise ValueError("invalid license code ciphertext")
    plaintext = AESGCM(_license_code_encryption_key(secret)).decrypt(
        payload[:12],
        payload[12:],
        _LICENSE_CODE_AAD,
    )
    return plaintext.decode("ascii")


def hash_secret(value: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(value.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${b64url(salt)}${b64url(digest)}"


def verify_secret(value: str, encoded: str) -> bool:
    try:
        name, n, r, p, salt, expected = encoded.split("$", 5)
        if name != "scrypt":
            return False
        actual = hashlib.scrypt(
            value.encode("utf-8"),
            salt=b64url_decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(b64url_decode(expected)),
        )
        return hmac.compare_digest(actual, b64url_decode(expected))
    except Exception:
        return False


class TicketSigner:
    def __init__(self, private_key_raw: bytes):
        self.private_key = Ed25519PrivateKey.from_private_bytes(private_key_raw)
        self.public_key = self.private_key.public_key()

    def sign(self, payload: dict[str, Any]) -> str:
        header = {"alg": "EdDSA", "typ": "JWT", "kid": "license-v1"}
        encoded_header = b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
        encoded_payload = b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        message = f"{encoded_header}.{encoded_payload}".encode("ascii")
        return f"{encoded_header}.{encoded_payload}.{b64url(self.private_key.sign(message))}"

    def verify(self, token: str, *, purpose: str | None = None, now: datetime | None = None) -> dict[str, Any]:
        header, payload, signature = token.split(".", 2)
        message = f"{header}.{payload}".encode("ascii")
        self.public_key.verify(b64url_decode(signature), message)
        data = json.loads(b64url_decode(payload))
        current = int((now or utc_now()).timestamp())
        if int(data.get("exp", 0)) <= current:
            raise ValueError("ticket expired")
        if purpose and data.get("purpose") != purpose:
            raise ValueError("ticket purpose mismatch")
        return data

    def public_key_base64(self) -> str:
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return b64url(raw)


def timestamp(value: datetime) -> int:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return int(normalized.timestamp())


def access_payload(activation_id: str, device_id: str, lifetime: int) -> dict[str, Any]:
    now = utc_now()
    return {
        "purpose": "access",
        "activation_id": activation_id,
        "device_id": device_id,
        "iat": timestamp(now),
        "exp": timestamp(now + timedelta(seconds=lifetime)),
        "jti": secrets.token_hex(12),
    }


def offline_payload(
    *, activation_id: str, license_id: str, device_id: str, expires_at: datetime,
    license_expires_at: datetime | None, entitlements: dict[str, Any], minimum_version: str | None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "purpose": "offline",
        "activation_id": activation_id,
        "license_id": license_id,
        "device_id": device_id,
        "iat": timestamp(now),
        "exp": timestamp(expires_at),
        "license_expires_at": timestamp(license_expires_at) if license_expires_at else None,
        "entitlements": entitlements,
        "minimum_version": minimum_version,
        "jti": secrets.token_hex(12),
    }
