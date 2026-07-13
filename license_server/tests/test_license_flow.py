from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import AdminUser
from app.main import _add_calendar_months, create_app
from app.security import hash_secret


@pytest.fixture()
def client(tmp_path):
    private = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        hmac_secret=b"h" * 32,
        signing_private_key=private,
        environment="test",
        offline_grace_hours=72,
        heartbeat_seconds=900,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        with app.state.database.session() as session:
            session.add(AdminUser(
                id=str(uuid.uuid4()), username="owner", password_hash=hash_secret("correct horse battery"),
                role="owner", active_license_limit=0,
            ))
        test_client.app_state = app.state
        yield test_client


def admin_headers(client: TestClient, username: str = "owner", password: str = "correct horse battery") -> dict[str, str]:
    response = client.post("/admin/v1/session", json={
        "username": username, "password": password,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_license(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {"expiry_type": "permanent", "note": "test license"}
    payload.update(overrides)
    response = client.post("/admin/v1/licenses", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def activation_payload(code: str, device_id: str = "device-0123456789abcdef", version: str = "1.0.0") -> dict:
    return {
        "license_code": code,
        "device_id": device_id,
        "device_name": "Test PC",
        "app_version": version,
        "os_version": "Windows 11",
        "architecture": "x64",
        "channel": "stable",
    }


def test_owner_subadmin_and_scope(client: TestClient):
    headers = admin_headers(client)
    response = client.post("/admin/v1/admins", headers=headers, json={
        "username": "helper", "password": "a secure helper password", "active_license_limit": 1,
    })
    assert response.status_code == 201, response.text
    assert response.json()["active_license_limit"] == 1
    listed = client.get("/admin/v1/admins", headers=headers)
    assert listed.status_code == 200
    assert [item["username"] for item in listed.json()] == ["helper"]

    helper_headers = admin_headers(client, "helper", "a secure helper password")
    first = client.post("/admin/v1/licenses", headers=helper_headers, json={"expiry_type": "permanent"})
    assert first.status_code == 201, first.text
    over_limit = client.post("/admin/v1/licenses", headers=helper_headers, json={"expiry_type": "permanent"})
    assert over_limit.status_code == 409
    helper_list = client.get("/admin/v1/licenses", headers=helper_headers)
    assert len(helper_list.json()) == 1


def test_activation_refresh_heartbeat_device_limit_and_revoke(client: TestClient):
    headers = admin_headers(client)
    license_data = create_license(client, headers)

    activated = client.post("/v1/licenses/activate", json=activation_payload(license_data["license_code"]))
    assert activated.status_code == 200, activated.text
    bundle = activated.json()
    assert bundle["heartbeat_seconds"] == 900
    assert bundle["offline_expires_at"] is not None

    offline = client.app_state.signer.verify(bundle["offline_ticket"], purpose="offline")
    assert offline["device_id"] == "device-0123456789abcdef"

    second_device = client.post("/v1/licenses/activate", json=activation_payload(
        license_data["license_code"], "device-fedcba9876543210",
    ))
    assert second_device.status_code == 409

    refreshed = client.post("/v1/licenses/refresh", json={
        "refresh_token": bundle["refresh_token"],
        "device_id": "device-0123456789abcdef",
        "app_version": "1.0.0",
        "channel": "stable",
    })
    assert refreshed.status_code == 200, refreshed.text
    rotated = refreshed.json()

    reused = client.post("/v1/licenses/refresh", json={
        "refresh_token": bundle["refresh_token"],
        "device_id": "device-0123456789abcdef",
        "app_version": "1.0.0",
    })
    assert reused.status_code == 401

    access_headers = {"Authorization": f"Bearer {rotated['access_token']}"}
    heartbeat = client.post("/v1/licenses/heartbeat", headers=access_headers, json={"app_version": "1.0.0"})
    assert heartbeat.status_code == 200, heartbeat.text

    revoked = client.post(f"/admin/v1/licenses/{license_data['id']}/revoke", headers=headers)
    assert revoked.status_code == 204, revoked.text
    denied = client.post("/v1/licenses/heartbeat", headers=access_headers, json={"app_version": "1.0.0"})
    assert denied.status_code == 403


def test_timed_license_and_minimum_version(client: TestClient):
    headers = admin_headers(client)
    license_data = create_license(client, headers, expiry_type="calendar_months", duration_value=1)
    release = client.post("/admin/v1/releases", headers=headers, json={
        "version": "2.0.0",
        "channel": "stable",
        "download_url": "https://license.example.com/downloads/xianyuxian-2.0.0.exe",
        "sha256": "a" * 64,
        "minimum": True,
        "mandatory": True,
    })
    assert release.status_code == 201, release.text
    manifest = client.get("/v1/releases/latest?channel=stable")
    assert manifest.status_code == 200, manifest.text
    signed_manifest = client.app_state.signer.verify(
        manifest.json()["manifest_ticket"], purpose="release_manifest",
    )
    assert signed_manifest["release"]["version"] == "2.0.0"

    blocked = client.post("/v1/licenses/activate", json=activation_payload(license_data["license_code"], version="1.0.0"))
    assert blocked.status_code == 426
    assert blocked.json()["detail"]["download_url"] == "https://license.example.com/downloads/xianyuxian-2.0.0.exe"
    allowed = client.post("/v1/licenses/activate", json=activation_payload(license_data["license_code"], version="2.0.0"))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["license_expires_at"] is not None


def test_calendar_month_uses_server_creation_time_and_does_not_restart(client: TestClient):
    headers = admin_headers(client)
    preview = client.get("/admin/v1/server-time?calendar_months=1", headers=headers)
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    preview_start = datetime.fromisoformat(preview_data["server_time"])
    preview_expiry = datetime.fromisoformat(preview_data["calendar_month_expires_at"])
    assert preview_expiry == _add_calendar_months(preview_start, 1)
    assert _add_calendar_months(datetime(2024, 1, 31, 12, 30), 1) == datetime(2024, 2, 29, 12, 30)

    before = datetime.now(UTC).replace(tzinfo=None)
    license_data = create_license(client, headers, expiry_type="calendar_months", duration_value=1)
    after = datetime.now(UTC).replace(tzinfo=None)
    starts_at = datetime.fromisoformat(license_data["starts_at"])
    expires_at = datetime.fromisoformat(license_data["expires_at"])
    assert before <= starts_at <= after
    assert expires_at == _add_calendar_months(starts_at, 1)

    activated = client.post("/v1/licenses/activate", json=activation_payload(license_data["license_code"]))
    assert activated.status_code == 200, activated.text
    assert datetime.fromisoformat(activated.json()["license_expires_at"]) == expires_at


def test_license_code_reveal_is_scoped_audited_and_not_cached(client: TestClient):
    owner_headers = admin_headers(client)
    license_data = create_license(client, owner_headers)
    listed = client.get("/admin/v1/licenses", headers=owner_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["can_reveal"] is True
    assert license_data["license_code"] not in listed.text

    revealed = client.get(f"/admin/v1/licenses/{license_data['id']}/code", headers=owner_headers)
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["license_code"] == license_data["license_code"]
    assert "no-store" in revealed.headers["cache-control"]

    created_subadmin = client.post("/admin/v1/admins", headers=owner_headers, json={
        "username": "viewer", "password": "a secure viewer password", "active_license_limit": 100,
    })
    assert created_subadmin.status_code == 201
    viewer_headers = admin_headers(client, "viewer", "a secure viewer password")
    forbidden = client.get(f"/admin/v1/licenses/{license_data['id']}/code", headers=viewer_headers)
    assert forbidden.status_code == 404


def test_self_service_deactivation_limit(client: TestClient):
    headers = admin_headers(client)
    license_data = create_license(client, headers)
    payload = activation_payload(license_data["license_code"])

    for _ in range(2):
        activated = client.post("/v1/licenses/activate", json=payload)
        assert activated.status_code == 200, activated.text
        access = {"Authorization": f"Bearer {activated.json()['access_token']}"}
        stopped = client.post("/v1/licenses/deactivate", headers=access)
        assert stopped.status_code == 204, stopped.text

    activated = client.post("/v1/licenses/activate", json=payload)
    assert activated.status_code == 200, activated.text
    access = {"Authorization": f"Bearer {activated.json()['access_token']}"}
    blocked = client.post("/v1/licenses/deactivate", headers=access)
    assert blocked.status_code == 429
