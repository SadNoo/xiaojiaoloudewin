from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from .api import LicenseApiClient, LicenseRejected, LicenseServerUnavailable
from .config import LicenseClientConfig
from .device import DeviceIdentity
from .models import LicenseCredential, LicenseDecision, LicenseState, parse_datetime, utc_now
from .storage import CredentialStore, CredentialStoreError
from .ticket import OfflineTicketError, OfflineTicketVerifier


class LicenseApi(Protocol):
    def activate(self, license_code: str, device: DeviceIdentity) -> dict[str, Any]: ...
    def refresh(self, refresh_token: str, device: DeviceIdentity) -> dict[str, Any]: ...
    def heartbeat(self, access_token: str) -> dict[str, Any]: ...
    def deactivate(self, access_token: str) -> None: ...


class LicenseManager:
    def __init__(
        self,
        config: LicenseClientConfig,
        device: DeviceIdentity,
        store: CredentialStore,
        *,
        api: LicenseApi | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.config = config
        self.device = device
        self.store = store
        self.api = api or LicenseApiClient(config)
        self.verifier = OfflineTicketVerifier(config.public_key_base64)
        self.clock = clock
        self._access_token: str | None = None
        self._heartbeat_seconds = 900
        self._lock = threading.RLock()

    @property
    def heartbeat_seconds(self) -> int:
        return self._heartbeat_seconds

    def _now(self) -> datetime:
        current = self.clock()
        return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)

    def _rejected_decision(self, error: LicenseRejected) -> LicenseDecision:
        if error.status_code == 426:
            detail = error.detail if isinstance(error.detail, dict) else {}
            return LicenseDecision(
                LicenseState.UPDATE_REQUIRED,
                "Client update is required before automation can start.",
                latest_version=detail.get("latest_version"),
                minimum_version=detail.get("minimum_version"),
                download_url=detail.get("download_url"),
                reason_code=error.reason_code,
            )
        return LicenseDecision(
            LicenseState.DENIED,
            str(error) or "License was rejected by the server.",
            reason_code=error.reason_code,
        )

    def _verified_ticket(self, token: str, now: datetime) -> dict[str, Any]:
        return self.verifier.verify(
            token,
            device_id=self.device.device_id,
            app_version=self.config.app_version,
            now=now,
        )

    def _accept_bundle(self, payload: dict[str, Any]) -> LicenseDecision:
        now = self._now()
        ticket_payload = self._verified_ticket(str(payload["offline_ticket"]), now)
        activation_id = str(payload["activation_id"])
        if ticket_payload.get("activation_id") != activation_id:
            raise OfflineTicketError("ticket activation does not match the online response")
        server_time = parse_datetime(payload.get("server_time"))
        refresh_expires_at = parse_datetime(payload.get("refresh_expires_at"))
        offline_expires_at = parse_datetime(payload.get("offline_expires_at"))
        if not server_time or not refresh_expires_at or not offline_expires_at:
            raise ValueError("license server omitted required timestamps")
        entitlements = dict(payload.get("entitlements") or ticket_payload.get("entitlements") or {})
        credential = LicenseCredential(
            activation_id=activation_id,
            device_id=self.device.device_id,
            refresh_token=str(payload["refresh_token"]),
            refresh_expires_at=refresh_expires_at,
            offline_ticket=str(payload["offline_ticket"]),
            offline_expires_at=offline_expires_at,
            license_expires_at=parse_datetime(payload.get("license_expires_at")),
            entitlements=entitlements,
            last_server_time=server_time,
            last_local_time=now,
            latest_version=payload.get("latest_version"),
            minimum_version=payload.get("minimum_version"),
        )
        self.store.save(credential)
        self._access_token = str(payload["access_token"])
        self._heartbeat_seconds = max(60, int(payload.get("heartbeat_seconds") or 900))
        return LicenseDecision(
            LicenseState.ALLOWED_ONLINE,
            "License validated online.",
            entitlements=entitlements,
            offline_until=offline_expires_at,
            license_expires_at=credential.license_expires_at,
            latest_version=credential.latest_version,
            minimum_version=credential.minimum_version,
        )

    def _accept_heartbeat(self, payload: dict[str, Any], credential: LicenseCredential) -> LicenseDecision:
        now = self._now()
        ticket_payload = self._verified_ticket(str(payload["offline_ticket"]), now)
        if ticket_payload.get("activation_id") != credential.activation_id:
            raise OfflineTicketError("heartbeat ticket activation mismatch")
        server_time = parse_datetime(payload.get("server_time"))
        offline_expires_at = parse_datetime(payload.get("offline_expires_at"))
        if not server_time or not offline_expires_at:
            raise ValueError("heartbeat omitted required timestamps")
        credential.offline_ticket = str(payload["offline_ticket"])
        credential.offline_expires_at = offline_expires_at
        credential.license_expires_at = parse_datetime(payload.get("license_expires_at"))
        credential.entitlements = dict(ticket_payload.get("entitlements") or credential.entitlements)
        credential.last_server_time = server_time
        credential.last_local_time = now
        credential.latest_version = payload.get("latest_version")
        credential.minimum_version = payload.get("minimum_version")
        self.store.save(credential)
        self._heartbeat_seconds = max(60, int(payload.get("heartbeat_seconds") or 900))
        return LicenseDecision(
            LicenseState.ALLOWED_ONLINE,
            "License heartbeat accepted.",
            entitlements=credential.entitlements,
            offline_until=credential.offline_expires_at,
            license_expires_at=credential.license_expires_at,
            latest_version=credential.latest_version,
            minimum_version=credential.minimum_version,
        )

    def _offline_decision(self, credential: LicenseCredential) -> LicenseDecision:
        now = self._now()
        tolerance = timedelta(seconds=self.config.clock_rollback_tolerance_seconds)
        checkpoint = max(credential.last_server_time, credential.last_local_time)
        if now + tolerance < checkpoint:
            return LicenseDecision(
                LicenseState.DENIED,
                "System clock moved backwards; online validation is required.",
                reason_code="clock_rollback",
            )
        try:
            payload = self._verified_ticket(credential.offline_ticket, now)
        except OfflineTicketError as exc:
            state = LicenseState.UPDATE_REQUIRED if "update required" in str(exc) else LicenseState.DENIED
            return LicenseDecision(state, str(exc), reason_code="offline_ticket_invalid")
        if payload.get("activation_id") != credential.activation_id:
            return LicenseDecision(
                LicenseState.DENIED, "Offline ticket activation mismatch.",
                reason_code="offline_activation_mismatch",
            )
        credential.last_local_time = now
        try:
            self.store.save(credential)
        except CredentialStoreError:
            return LicenseDecision(
                LicenseState.DENIED, "Could not persist the offline clock checkpoint.",
                reason_code="credential_write_failed",
            )
        return LicenseDecision(
            LicenseState.ALLOWED_OFFLINE,
            "License server is unreachable; running within the offline grace period.",
            entitlements=dict(payload.get("entitlements") or credential.entitlements),
            offline_until=credential.offline_expires_at,
            license_expires_at=credential.license_expires_at,
            latest_version=credential.latest_version,
            minimum_version=payload.get("minimum_version") or credential.minimum_version,
            reason_code="server_unreachable",
        )

    def _load_credential(self) -> LicenseCredential | LicenseDecision | None:
        try:
            credential = self.store.load()
        except CredentialStoreError:
            return LicenseDecision(
                LicenseState.DENIED,
                "Stored license credential is corrupted or belongs to another Windows user.",
                reason_code="credential_unreadable",
            )
        if credential and credential.device_id != self.device.device_id:
            return LicenseDecision(
                LicenseState.DENIED,
                "Stored license credential belongs to a different device.",
                reason_code="device_mismatch",
            )
        return credential

    def activate(self, license_code: str) -> LicenseDecision:
        with self._lock:
            try:
                return self._accept_bundle(self.api.activate(license_code, self.device))
            except LicenseServerUnavailable:
                return LicenseDecision(
                    LicenseState.DENIED,
                    "First activation requires an online connection to the license server.",
                    reason_code="activation_requires_network",
                )
            except LicenseRejected as exc:
                return self._rejected_decision(exc)
            except (OfflineTicketError, KeyError, TypeError, ValueError, CredentialStoreError) as exc:
                return LicenseDecision(
                    LicenseState.DENIED, f"License response validation failed: {exc}",
                    reason_code="invalid_server_response",
                )

    def startup_check(self) -> LicenseDecision:
        with self._lock:
            loaded = self._load_credential()
            if isinstance(loaded, LicenseDecision):
                return loaded
            if loaded is None:
                return LicenseDecision(
                    LicenseState.NEEDS_ACTIVATION,
                    "Enter a license code to activate this device.",
                    reason_code="not_activated",
                )
            try:
                return self._accept_bundle(self.api.refresh(loaded.refresh_token, self.device))
            except LicenseServerUnavailable:
                return self._offline_decision(loaded)
            except LicenseRejected as exc:
                return self._rejected_decision(exc)
            except (OfflineTicketError, KeyError, TypeError, ValueError, CredentialStoreError) as exc:
                return LicenseDecision(
                    LicenseState.DENIED, f"License response validation failed: {exc}",
                    reason_code="invalid_server_response",
                )

    def heartbeat(self) -> LicenseDecision:
        with self._lock:
            loaded = self._load_credential()
            if isinstance(loaded, LicenseDecision):
                return loaded
            if loaded is None:
                return LicenseDecision(LicenseState.NEEDS_ACTIVATION, "License is not activated.")
            if not self._access_token:
                return self.startup_check()
            try:
                return self._accept_heartbeat(self.api.heartbeat(self._access_token), loaded)
            except LicenseServerUnavailable:
                return self._offline_decision(loaded)
            except LicenseRejected as exc:
                if exc.status_code == 401:
                    self._access_token = None
                    return self.startup_check()
                return self._rejected_decision(exc)
            except (OfflineTicketError, KeyError, TypeError, ValueError, CredentialStoreError) as exc:
                return LicenseDecision(
                    LicenseState.DENIED, f"Heartbeat validation failed: {exc}",
                    reason_code="invalid_heartbeat_response",
                )

    def deactivate(self) -> LicenseDecision:
        with self._lock:
            if not self._access_token:
                decision = self.startup_check()
                if not decision.allows_automation or not self._access_token:
                    return decision
            try:
                self.api.deactivate(self._access_token)
            except LicenseServerUnavailable:
                return LicenseDecision(
                    LicenseState.DENIED, "Device deactivation requires an online connection.",
                    reason_code="deactivation_requires_network",
                )
            except LicenseRejected as exc:
                return self._rejected_decision(exc)
            self._access_token = None
            self.store.clear()
            return LicenseDecision(
                LicenseState.NEEDS_ACTIVATION, "This device has been deactivated.",
                reason_code="deactivated",
            )


class HeartbeatWorker:
    def __init__(
        self,
        manager: LicenseManager,
        callback: Callable[[LicenseDecision], None],
    ):
        self.manager = manager
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._initial_interval: int | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, *, initial_interval: int | None = None) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._initial_interval = initial_interval
        self._thread = threading.Thread(target=self._run, name="license-heartbeat", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self.is_running:
            self._thread.join(timeout)

    def _run(self) -> None:
        interval = self._initial_interval or self.manager.heartbeat_seconds
        while not self._stop.wait(interval):
            decision = self.manager.heartbeat()
            self.callback(decision)
            if decision.state in {LicenseState.DENIED, LicenseState.UPDATE_REQUIRED, LicenseState.NEEDS_ACTIVATION}:
                return
            interval = 60 if decision.state == LicenseState.ALLOWED_OFFLINE else self.manager.heartbeat_seconds
