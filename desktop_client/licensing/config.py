from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class LicenseClientConfig:
    api_base_url: str
    public_key_base64: str
    app_version: str
    channel: str = "stable"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    clock_rollback_tolerance_seconds: int = 300
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("api_base_url must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and not self.allow_insecure_http:
            raise ValueError("production license API must use HTTPS")
        if not self.public_key_base64:
            raise ValueError("the Ed25519 public key must be embedded in the client build")
        if not self.app_version:
            raise ValueError("app_version is required")

    @classmethod
    def from_env(cls) -> "LicenseClientConfig":
        return cls(
            api_base_url=os.environ["XIANYUXIAN_LICENSE_API"].rstrip("/"),
            public_key_base64=os.environ["XIANYUXIAN_LICENSE_PUBLIC_KEY"],
            app_version=os.getenv("XIANYUXIAN_APP_VERSION", "0.1.1"),
            channel=os.getenv("XIANYUXIAN_RELEASE_CHANNEL", "stable"),
            allow_insecure_http=os.getenv("XIANYUXIAN_LICENSE_ALLOW_HTTP", "0") == "1",
        )
