from __future__ import annotations

import base64
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop_client.licensing.api import LicenseApiClient, LicenseRejected, LicenseServerUnavailable
from desktop_client.app_license import ApplicationLicenseCoordinator, request_allowed_without_license
from desktop_client.licensing.config import LicenseClientConfig
from desktop_client.licensing.device import DeviceIdentity, derive_device_id
from desktop_client.licensing.manager import LicenseManager
from desktop_client.licensing.models import LicenseState
from desktop_client.licensing.models import LicenseDecision
from desktop_client.licensing.storage import CredentialStore, DPAPIProtector
from desktop_client.licensing.ticket import OfflineTicketError, OfflineTicketVerifier


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class TestProtector:
    prefix = b"test-protected:"

    def protect(self, plaintext: bytes) -> bytes:
        return self.prefix + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(self.prefix):
            raise ValueError("invalid test ciphertext")
        return ciphertext[len(self.prefix):][::-1]


def sign_ticket(private_key: Ed25519PrivateKey, payload: dict) -> str:
    header = {"alg": "EdDSA", "typ": "JWT", "kid": "license-v1"}
    encoded_header = b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_payload = b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    message = f"{encoded_header}.{encoded_payload}".encode("ascii")
    return f"{encoded_header}.{encoded_payload}.{b64url(private_key.sign(message))}"


class FakeApi:
    def __init__(self, bundle: dict):
        self.bundle = bundle
        self.refresh_error: Exception | None = None
        self.heartbeat_error: Exception | None = None
        self.deactivated = False

    def activate(self, license_code: str, device: DeviceIdentity) -> dict:
        if license_code != "XY-VALID-LICENSE-CODE-12345":
            raise LicenseRejected(401, "invalid license")
        return dict(self.bundle)

    def refresh(self, refresh_token: str, device: DeviceIdentity) -> dict:
        if self.refresh_error:
            raise self.refresh_error
        result = dict(self.bundle)
        result["refresh_token"] = "rotated-refresh-token-abcdefghijklmnopqrstuvwxyz"
        return result

    def heartbeat(self, access_token: str) -> dict:
        if self.heartbeat_error:
            raise self.heartbeat_error
        return {
            key: self.bundle[key]
            for key in (
                "license_expires_at", "offline_ticket", "offline_expires_at", "heartbeat_seconds",
                "minimum_version", "latest_version", "server_time",
            )
        } | {"status": "active", "update_required": False}

    def deactivate(self, access_token: str) -> None:
        self.deactivated = True


@pytest.fixture()
def licensing_fixture(tmp_path):
    now = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    device = DeviceIdentity(
        device_id=derive_device_id("01234567-89ab-cdef-0123-456789abcdef"),
        device_name="Test PC", os_version="Windows 11", architecture="AMD64",
    )
    offline_expires = now + timedelta(hours=72)
    ticket = sign_ticket(private, {
        "purpose": "offline",
        "activation_id": "activation-1",
        "license_id": "license-1",
        "device_id": device.device_id,
        "iat": int(now.timestamp()),
        "exp": int(offline_expires.timestamp()),
        "license_expires_at": None,
        "entitlements": {"max_accounts": None},
        "minimum_version": "1.0.0",
    })
    bundle = {
        "activation_id": "activation-1",
        "license_status": "active",
        "access_token": "access-token",
        "access_expires_at": (now + timedelta(hours=1)).isoformat(),
        "refresh_token": "refresh-token-abcdefghijklmnopqrstuvwxyz",
        "refresh_expires_at": (now + timedelta(days=30)).isoformat(),
        "offline_ticket": ticket,
        "offline_expires_at": offline_expires.isoformat(),
        "license_expires_at": None,
        "entitlements": {"max_accounts": None},
        "heartbeat_seconds": 900,
        "minimum_version": "1.0.0",
        "latest_version": "1.2.0",
        "update_required": False,
        "server_time": now.isoformat(),
    }
    config = LicenseClientConfig(
        api_base_url="http://license.test",
        public_key_base64=b64url(public_raw),
        app_version="1.0.0",
        allow_insecure_http=True,
    )
    store = CredentialStore(tmp_path / "credential.bin", TestProtector())
    api = FakeApi(bundle)
    return now, private, device, bundle, config, store, api


def test_activation_online_refresh_and_encrypted_storage(licensing_fixture):
    now, _, device, _, config, store, api = licensing_fixture
    manager = LicenseManager(config, device, store, api=api, clock=lambda: now)
    activated = manager.activate("XY-VALID-LICENSE-CODE-12345")
    assert activated.state == LicenseState.ALLOWED_ONLINE
    assert manager.heartbeat_seconds == 900
    assert store.load().activation_id == "activation-1"
    assert b"refresh-token" not in store.path.read_bytes()

    refreshed = LicenseManager(config, device, store, api=api, clock=lambda: now + timedelta(minutes=1))
    decision = refreshed.startup_check()
    assert decision.state == LicenseState.ALLOWED_ONLINE
    assert store.load().refresh_token.startswith("rotated-refresh")

    assert refreshed.heartbeat().state == LicenseState.ALLOWED_ONLINE
    api.heartbeat_error = LicenseRejected(403, "license revoked")
    assert refreshed.heartbeat().state == LicenseState.DENIED


def test_network_failure_uses_offline_ticket_but_rejection_does_not(licensing_fixture):
    now, _, device, _, config, store, api = licensing_fixture
    manager = LicenseManager(config, device, store, api=api, clock=lambda: now)
    assert manager.activate("XY-VALID-LICENSE-CODE-12345").allows_automation

    api.refresh_error = LicenseServerUnavailable("offline")
    offline_manager = LicenseManager(config, device, store, api=api, clock=lambda: now + timedelta(hours=1))
    offline = offline_manager.startup_check()
    assert offline.state == LicenseState.ALLOWED_OFFLINE

    api.refresh_error = LicenseRejected(403, "license revoked")
    denied = LicenseManager(config, device, store, api=api, clock=lambda: now + timedelta(hours=2)).startup_check()
    assert denied.state == LicenseState.DENIED
    assert denied.state != LicenseState.ALLOWED_OFFLINE


def test_clock_rollback_blocks_offline_mode(licensing_fixture):
    now, _, device, _, config, store, api = licensing_fixture
    manager = LicenseManager(config, device, store, api=api, clock=lambda: now)
    assert manager.activate("XY-VALID-LICENSE-CODE-12345").allows_automation
    api.refresh_error = LicenseServerUnavailable("offline")
    rollback = LicenseManager(config, device, store, api=api, clock=lambda: now - timedelta(hours=1)).startup_check()
    assert rollback.state == LicenseState.DENIED
    assert rollback.reason_code == "clock_rollback"


def test_offline_grace_expiry_blocks_automation(licensing_fixture):
    now, _, device, _, config, store, api = licensing_fixture
    manager = LicenseManager(config, device, store, api=api, clock=lambda: now)
    assert manager.activate("XY-VALID-LICENSE-CODE-12345").allows_automation
    api.refresh_error = LicenseServerUnavailable("offline")
    expired = LicenseManager(
        config, device, store, api=api, clock=lambda: now + timedelta(hours=73),
    ).startup_check()
    assert expired.state == LicenseState.DENIED
    assert "expired" in expired.message


def test_ticket_rejects_other_device_and_old_version(licensing_fixture):
    now, _, device, bundle, config, _, _ = licensing_fixture
    verifier = OfflineTicketVerifier(config.public_key_base64)
    with pytest.raises(OfflineTicketError, match="different device"):
        verifier.verify(bundle["offline_ticket"], device_id="win-other", app_version="1.0.0", now=now)
    with pytest.raises(OfflineTicketError, match="update required"):
        verifier.verify(bundle["offline_ticket"], device_id=device.device_id, app_version="0.9.0", now=now)


def test_http_client_distinguishes_unavailable_and_explicit_rejection(licensing_fixture):
    _, _, device, _, config, _, _ = licensing_fixture

    unavailable_transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "maintenance"}))
    unavailable_client = LicenseApiClient(config, transport=unavailable_transport)
    with pytest.raises(LicenseServerUnavailable):
        unavailable_client.activate("XY-VALID-LICENSE-CODE-12345", device)

    rejected_transport = httpx.MockTransport(lambda request: httpx.Response(403, json={"detail": "revoked"}))
    rejected_client = LicenseApiClient(config, transport=rejected_transport)
    with pytest.raises(LicenseRejected) as exc:
        rejected_client.activate("XY-VALID-LICENSE-CODE-12345", device)
    assert exc.value.status_code == 403


def test_update_rejection_exposes_verified_release_download(licensing_fixture):
    now, _, device, _, config, store, _ = licensing_fixture

    class UpdateApi(FakeApi):
        def refresh(self, refresh_token: str, device: DeviceIdentity) -> dict:
            raise LicenseRejected(426, {
                "code": "client_version_not_allowed",
                "minimum_version": "2.0.0",
                "latest_version": "2.1.0",
                "download_url": "https://downloads.example/xianyuxian-2.1.0.exe",
            })

    original_api = FakeApi(licensing_fixture[3])
    manager = LicenseManager(config, device, store, api=original_api, clock=lambda: now)
    assert manager.activate("XY-VALID-LICENSE-CODE-12345").allows_automation
    decision = LicenseManager(
        config, device, store, api=UpdateApi(licensing_fixture[3]), clock=lambda: now,
    ).startup_check()
    assert decision.state == LicenseState.UPDATE_REQUIRED
    assert decision.download_url == "https://downloads.example/xianyuxian-2.1.0.exe"


def test_device_id_is_deterministic_and_dpapi_is_windows_only():
    first = derive_device_id("01234567-89AB-CDEF-0123-456789ABCDEF")
    second = derive_device_id("01234567-89ab-cdef-0123-456789abcdef")
    assert first == second
    assert first.startswith("win-") and len(first) == 68
    if sys.platform != "win32":
        with pytest.raises(RuntimeError, match="only available on Windows"):
            DPAPIProtector()


def test_application_coordinator_starts_and_stops_business_callbacks(licensing_fixture):
    _, _, device, _, _, _, _ = licensing_fixture

    class FakeManager:
        heartbeat_seconds = 900

        def __init__(self):
            self.device = device
            self.decision = LicenseDecision(LicenseState.ALLOWED_ONLINE, "ok")

        def startup_check(self):
            return self.decision

        def heartbeat(self):
            return self.decision

        def activate(self, code):
            return self.decision

        def deactivate(self):
            self.decision = LicenseDecision(LicenseState.NEEDS_ACTIVATION, "stopped")
            return self.decision

    async def scenario():
        events: list[str] = []
        manager = FakeManager()
        coordinator = ApplicationLicenseCoordinator()

        async def on_allowed():
            events.append("allowed")

        async def on_blocked():
            events.append("blocked")

        coordinator.initialize(
            loop=asyncio.get_running_loop(), on_allowed=on_allowed,
            on_blocked=on_blocked, manager=manager,  # type: ignore[arg-type]
        )
        assert coordinator.startup_check().allows_automation
        await asyncio.sleep(0.05)
        assert events == ["allowed"]
        manager.decision = LicenseDecision(LicenseState.DENIED, "revoked")
        coordinator.startup_check()
        await asyncio.sleep(0.05)
        assert events == ["allowed", "blocked"]
        assert coordinator.status()["state"] == "denied"
        coordinator.shutdown()

    asyncio.run(scenario())


def test_unlicensed_read_only_request_policy():
    assert request_allowed_without_license("GET", "/backup/export")
    assert request_allowed_without_license("POST", "/api/license/activate")
    assert request_allowed_without_license("POST", "/login")
    assert not request_allowed_without_license("POST", "/api/orders/manual-ship")
    assert not request_allowed_without_license("POST", "/login-info-settings")
    assert not request_allowed_without_license("DELETE", "/cards/1")
