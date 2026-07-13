from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=256)


class AdminSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    role: str


class SubadminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    active_license_limit: int = Field(default=100, ge=1, le=10000)


class SubadminResponse(BaseModel):
    id: str
    username: str
    role: str
    active_license_limit: int
    enabled: bool
    created_at: datetime


class LicenseCreateRequest(BaseModel):
    expiry_type: Literal["permanent", "days", "calendar_months"] = "permanent"
    duration_value: int | None = Field(default=None, ge=1, le=3650)
    max_accounts: int | None = Field(default=None, ge=1, le=1000)
    note: str = Field(default="", max_length=1000)
    entitlements: dict[str, Any] = Field(default_factory=dict)
    assigned_admin_id: str | None = None

    @field_validator("duration_value")
    @classmethod
    def validate_duration(cls, value: int | None, info):
        expiry_type = info.data.get("expiry_type")
        if expiry_type in {"days", "calendar_months"} and value is None:
            raise ValueError("duration_value is required for timed licenses")
        if expiry_type == "permanent" and value is not None:
            raise ValueError("duration_value must be omitted for permanent licenses")
        return value


class LicenseCreatedResponse(BaseModel):
    id: str
    license_code: str
    expiry_type: str
    duration_value: int | None
    max_devices: int
    max_accounts: int | None
    created_at: datetime


class LicenseResponse(BaseModel):
    id: str
    masked_code: str
    status: str
    expiry_type: str
    duration_value: int | None
    starts_at: datetime | None
    expires_at: datetime | None
    max_devices: int
    max_accounts: int | None
    note: str
    created_by: str
    created_at: datetime


class ActivationRequest(BaseModel):
    license_code: str = Field(min_length=20, max_length=80)
    device_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    device_name: str = Field(default="", max_length=160)
    app_version: str = Field(min_length=1, max_length=40)
    os_version: str = Field(default="", max_length=100)
    architecture: str = Field(default="x64", max_length=40)
    channel: str = Field(default="stable", max_length=24)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)
    device_id: str = Field(min_length=16, max_length=128)
    app_version: str = Field(min_length=1, max_length=40)
    channel: str = Field(default="stable", max_length=24)


class TokenBundleResponse(BaseModel):
    activation_id: str
    license_status: str
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    offline_ticket: str
    offline_expires_at: datetime
    license_expires_at: datetime | None
    entitlements: dict[str, Any]
    heartbeat_seconds: int
    minimum_version: str | None
    latest_version: str | None
    update_required: bool
    server_time: datetime


class HeartbeatRequest(BaseModel):
    app_version: str = Field(min_length=1, max_length=40)
    channel: str = Field(default="stable", max_length=24)


class HeartbeatResponse(BaseModel):
    status: str
    license_expires_at: datetime | None
    offline_ticket: str
    offline_expires_at: datetime
    heartbeat_seconds: int
    minimum_version: str | None
    latest_version: str | None
    update_required: bool
    server_time: datetime


class ActivationResponse(BaseModel):
    id: str
    license_id: str
    device_id: str
    device_name: str
    app_version: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


class ReleaseCreateRequest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    channel: Literal["stable", "test"] = "stable"
    download_url: str = Field(min_length=8, max_length=2000)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    signature: str = ""
    notes: str = Field(default="", max_length=10000)
    minimum: bool = False
    mandatory: bool = False
    blocked: bool = False
    published: bool = True


class ReleaseResponse(BaseModel):
    version: str
    channel: str
    download_url: str
    sha256: str
    signature: str
    notes: str
    minimum: bool
    mandatory: bool
    blocked: bool
    published: bool
    created_at: datetime


class ReleaseManifestResponse(BaseModel):
    release: ReleaseResponse
    manifest_ticket: str
