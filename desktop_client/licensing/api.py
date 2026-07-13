from __future__ import annotations

from typing import Any

import httpx

from .config import LicenseClientConfig
from .device import DeviceIdentity


class LicenseServerUnavailable(RuntimeError):
    pass


class LicenseRejected(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        if isinstance(detail, dict):
            self.reason_code = str(detail.get("code") or "license_rejected")
            message = str(detail.get("message") or detail.get("code") or detail)
        else:
            self.reason_code = "license_rejected"
            message = str(detail)
        super().__init__(message)


class LicenseApiClient:
    def __init__(
        self,
        config: LicenseClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        timeout = httpx.Timeout(
            config.read_timeout_seconds,
            connect=config.connect_timeout_seconds,
            write=config.read_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self.config = config
        self.client = httpx.Client(
            base_url=config.api_base_url.rstrip("/"), timeout=timeout,
            transport=transport, follow_redirects=False,
            headers={"User-Agent": f"xianyuxian/{config.app_version}"},
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise LicenseServerUnavailable("license server is unreachable") from exc
        if 500 <= response.status_code <= 599:
            raise LicenseServerUnavailable(f"license server returned {response.status_code}")
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            except Exception:
                detail = response.text or f"HTTP {response.status_code}"
            raise LicenseRejected(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise LicenseServerUnavailable("license server returned an invalid response")
        return payload

    def activate(self, license_code: str, device: DeviceIdentity) -> dict[str, Any]:
        return self._request("POST", "/v1/licenses/activate", json={
            "license_code": license_code,
            "device_id": device.device_id,
            "device_name": device.device_name,
            "app_version": self.config.app_version,
            "os_version": device.os_version,
            "architecture": device.architecture,
            "channel": self.config.channel,
        })

    def refresh(self, refresh_token: str, device: DeviceIdentity) -> dict[str, Any]:
        return self._request("POST", "/v1/licenses/refresh", json={
            "refresh_token": refresh_token,
            "device_id": device.device_id,
            "app_version": self.config.app_version,
            "channel": self.config.channel,
        })

    def heartbeat(self, access_token: str) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/licenses/heartbeat",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"app_version": self.config.app_version, "channel": self.config.channel},
        )

    def deactivate(self, access_token: str) -> None:
        self._request(
            "POST", "/v1/licenses/deactivate",
            headers={"Authorization": f"Bearer {access_token}"},
        )

