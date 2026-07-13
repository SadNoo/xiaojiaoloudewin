from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _decode_secret(name: str, value: str | None, *, minimum: int = 32) -> bytes:
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(f"{name} must be URL-safe base64") from exc
    if len(decoded) < minimum:
        raise RuntimeError(f"{name} must decode to at least {minimum} bytes")
    return decoded


@dataclass(frozen=True)
class Settings:
    database_url: str
    hmac_secret: bytes
    signing_private_key: bytes
    environment: str = "development"
    offline_grace_hours: int = 72
    heartbeat_seconds: int = 900
    access_token_seconds: int = 3600
    refresh_token_days: int = 30
    admin_session_hours: int = 12
    default_subadmin_license_limit: int = 100
    public_base_url: str = "http://127.0.0.1:8090"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        signing_key = _decode_secret(
            "LICENSE_SIGNING_PRIVATE_KEY",
            os.getenv("LICENSE_SIGNING_PRIVATE_KEY"),
            minimum=32,
        )
        if len(signing_key) != 32:
            raise RuntimeError("LICENSE_SIGNING_PRIVATE_KEY must decode to exactly 32 bytes")
        return cls(
            database_url=os.getenv("LICENSE_DATABASE_URL", "sqlite:///./data/license.db"),
            hmac_secret=_decode_secret("LICENSE_HMAC_SECRET", os.getenv("LICENSE_HMAC_SECRET")),
            signing_private_key=signing_key,
            environment=os.getenv("LICENSE_ENV", "development"),
            offline_grace_hours=int(os.getenv("LICENSE_OFFLINE_GRACE_HOURS", "72")),
            heartbeat_seconds=int(os.getenv("LICENSE_HEARTBEAT_SECONDS", "900")),
            access_token_seconds=int(os.getenv("LICENSE_ACCESS_TOKEN_SECONDS", "3600")),
            refresh_token_days=int(os.getenv("LICENSE_REFRESH_TOKEN_DAYS", "30")),
            admin_session_hours=int(os.getenv("LICENSE_ADMIN_SESSION_HOURS", "12")),
            default_subadmin_license_limit=int(os.getenv("LICENSE_SUBADMIN_LIMIT", "100")),
            public_base_url=os.getenv("LICENSE_PUBLIC_BASE_URL", "http://127.0.0.1:8090").rstrip("/"),
        )
