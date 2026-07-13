from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def format_datetime(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class LicenseState(str, Enum):
    NEEDS_ACTIVATION = "needs_activation"
    ALLOWED_ONLINE = "allowed_online"
    ALLOWED_OFFLINE = "allowed_offline"
    DENIED = "denied"
    UPDATE_REQUIRED = "update_required"


@dataclass
class LicenseCredential:
    activation_id: str
    device_id: str
    refresh_token: str
    refresh_expires_at: datetime
    offline_ticket: str
    offline_expires_at: datetime
    license_expires_at: datetime | None
    entitlements: dict[str, Any]
    last_server_time: datetime
    last_local_time: datetime
    latest_version: str | None = None
    minimum_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "activation_id": self.activation_id,
            "device_id": self.device_id,
            "refresh_token": self.refresh_token,
            "refresh_expires_at": format_datetime(self.refresh_expires_at),
            "offline_ticket": self.offline_ticket,
            "offline_expires_at": format_datetime(self.offline_expires_at),
            "license_expires_at": format_datetime(self.license_expires_at),
            "entitlements": self.entitlements,
            "last_server_time": format_datetime(self.last_server_time),
            "last_local_time": format_datetime(self.last_local_time),
            "latest_version": self.latest_version,
            "minimum_version": self.minimum_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LicenseCredential":
        required_dates = {
            name: parse_datetime(data.get(name))
            for name in ("refresh_expires_at", "offline_expires_at", "last_server_time", "last_local_time")
        }
        if any(value is None for value in required_dates.values()):
            raise ValueError("credential contains missing timestamps")
        return cls(
            activation_id=str(data["activation_id"]),
            device_id=str(data["device_id"]),
            refresh_token=str(data["refresh_token"]),
            refresh_expires_at=required_dates["refresh_expires_at"],  # type: ignore[arg-type]
            offline_ticket=str(data["offline_ticket"]),
            offline_expires_at=required_dates["offline_expires_at"],  # type: ignore[arg-type]
            license_expires_at=parse_datetime(data.get("license_expires_at")),
            entitlements=dict(data.get("entitlements") or {}),
            last_server_time=required_dates["last_server_time"],  # type: ignore[arg-type]
            last_local_time=required_dates["last_local_time"],  # type: ignore[arg-type]
            latest_version=data.get("latest_version"),
            minimum_version=data.get("minimum_version"),
        )


@dataclass(frozen=True)
class LicenseDecision:
    state: LicenseState
    message: str
    entitlements: dict[str, Any] = field(default_factory=dict)
    offline_until: datetime | None = None
    license_expires_at: datetime | None = None
    latest_version: str | None = None
    minimum_version: str | None = None
    download_url: str | None = None
    reason_code: str | None = None

    @property
    def allows_automation(self) -> bool:
        return self.state in {LicenseState.ALLOWED_ONLINE, LicenseState.ALLOWED_OFFLINE}
