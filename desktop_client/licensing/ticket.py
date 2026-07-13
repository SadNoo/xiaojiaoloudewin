from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class OfflineTicketError(ValueError):
    pass


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _semver(value: str | None) -> tuple[int, int, int]:
    if not value:
        return 0, 0, 0
    try:
        core = value.split("-", 1)[0].split("+", 1)[0]
        return tuple(int(part) for part in core.split(".", 2))  # type: ignore[return-value]
    except Exception:
        return 0, 0, 0


class OfflineTicketVerifier:
    def __init__(self, public_key_base64: str, *, key_id: str = "license-v1"):
        try:
            raw = _decode(public_key_base64)
            self.public_key = Ed25519PublicKey.from_public_bytes(raw)
        except Exception as exc:
            raise ValueError("invalid Ed25519 public key") from exc
        self.key_id = key_id

    def verify(
        self,
        token: str,
        *,
        device_id: str,
        app_version: str,
        now: datetime | None = None,
        purpose: str = "offline",
    ) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
            header = json.loads(_decode(encoded_header))
            payload = json.loads(_decode(encoded_payload))
            if header.get("alg") != "EdDSA" or header.get("kid") != self.key_id:
                raise OfflineTicketError("unsupported ticket signing key")
            self.public_key.verify(
                _decode(encoded_signature), f"{encoded_header}.{encoded_payload}".encode("ascii"),
            )
        except OfflineTicketError:
            raise
        except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise OfflineTicketError("invalid offline ticket signature or encoding") from exc
        now_ts = int(current.timestamp())
        if payload.get("purpose") != purpose:
            raise OfflineTicketError("ticket purpose mismatch")
        if payload.get("device_id") != device_id:
            raise OfflineTicketError("ticket belongs to a different device")
        if int(payload.get("exp", 0)) <= now_ts:
            raise OfflineTicketError("offline grace has expired")
        if int(payload.get("iat", 0)) > now_ts + 300:
            raise OfflineTicketError("ticket issue time is in the future")
        license_expiry = payload.get("license_expires_at")
        if license_expiry and int(license_expiry) <= now_ts:
            raise OfflineTicketError("license has expired")
        minimum_version = payload.get("minimum_version")
        if minimum_version and _semver(app_version) < _semver(str(minimum_version)):
            raise OfflineTicketError(f"client update required: minimum {minimum_version}")
        return payload

