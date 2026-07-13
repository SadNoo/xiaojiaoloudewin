from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from datetime import UTC, datetime
from typing import Awaitable, Callable

from .licensing.factory import create_windows_license_manager
from .licensing.manager import HeartbeatWorker, LicenseManager
from .licensing.models import LicenseDecision, LicenseState


logger = logging.getLogger(__name__)
AsyncCallback = Callable[[], Awaitable[None] | None]

LICENSE_READ_ONLY_WRITE_ALLOW_EXACT = {
    '/login', '/logout', '/generate-captcha', '/verify-captcha',
    '/send-verification-code', '/register', '/change-password',
}
LICENSE_READ_ONLY_WRITE_ALLOW_PREFIXES = ('/api/license/', '/geetest/')


def request_allowed_without_license(method: str, path: str) -> bool:
    """Allow reads/exports and only the writes needed to authenticate or recover licensing."""
    if method.upper() in {'GET', 'HEAD', 'OPTIONS'}:
        return True
    return path in LICENSE_READ_ONLY_WRITE_ALLOW_EXACT or path.startswith(LICENSE_READ_ONLY_WRITE_ALLOW_PREFIXES)


class ApplicationLicenseCoordinator:
    """Thread-safe bridge between the synchronous license SDK and the main asyncio loop."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._manager: LicenseManager | None = None
        self._worker: HeartbeatWorker | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_allowed: AsyncCallback | None = None
        self._on_blocked: AsyncCallback | None = None
        self._decision = LicenseDecision(
            LicenseState.NEEDS_ACTIVATION,
            "License module has not been initialized.",
            reason_code="license_not_initialized",
        )
        self._initialization_error: str | None = None

    def initialize(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        on_allowed: AsyncCallback,
        on_blocked: AsyncCallback,
        manager: LicenseManager | None = None,
    ) -> None:
        with self._lock:
            self._loop = loop
            self._on_allowed = on_allowed
            self._on_blocked = on_blocked
            try:
                self._manager = manager or create_windows_license_manager()
                self._initialization_error = None
            except Exception as exc:
                self._manager = None
                self._initialization_error = str(exc)
                self._decision = LicenseDecision(
                    LicenseState.DENIED,
                    f"License client configuration is unavailable: {exc}",
                    reason_code="license_client_configuration_error",
                )

    def _schedule(self, callback: AsyncCallback | None) -> None:
        if not callback or not self._loop or self._loop.is_closed():
            return

        async def invoke() -> None:
            result = callback()
            if inspect.isawaitable(result):
                await result

        future = asyncio.run_coroutine_threadsafe(invoke(), self._loop)

        def report_error(done) -> None:
            try:
                done.result()
            except Exception:
                logger.exception("license state callback failed")

        future.add_done_callback(report_error)

    def _publish(self, decision: LicenseDecision) -> LicenseDecision:
        with self._lock:
            was_allowed = self._decision.allows_automation
            self._decision = decision
            is_allowed = decision.allows_automation
            if is_allowed and self._manager and (not self._worker or not self._worker.is_running):
                self._worker = HeartbeatWorker(self._manager, self._publish)
                self._worker.start(initial_interval=60 if decision.state == LicenseState.ALLOWED_OFFLINE else None)
            if is_allowed and not was_allowed:
                self._schedule(self._on_allowed)
            elif not is_allowed and was_allowed:
                self._schedule(self._on_blocked)
            return decision

    def startup_check(self) -> LicenseDecision:
        with self._lock:
            manager = self._manager
        if not manager:
            return self._decision
        return self._publish(manager.startup_check())

    def activate(self, license_code: str) -> LicenseDecision:
        with self._lock:
            manager = self._manager
        if not manager:
            return self._decision
        return self._publish(manager.activate(license_code))

    def retry_online(self) -> LicenseDecision:
        return self.startup_check()

    def deactivate(self) -> LicenseDecision:
        with self._lock:
            manager = self._manager
        if not manager:
            return self._decision
        return self._publish(manager.deactivate())

    def status(self) -> dict:
        with self._lock:
            decision = self._decision
            manager = self._manager
            device = manager.device if manager else None

        def iso(value: datetime | None) -> str | None:
            return value.astimezone(UTC).isoformat() if value else None

        return {
            "state": decision.state.value,
            "allows_automation": decision.allows_automation,
            "message": decision.message,
            "reason_code": decision.reason_code,
            "offline_until": iso(decision.offline_until),
            "license_expires_at": iso(decision.license_expires_at),
            "latest_version": decision.latest_version,
            "minimum_version": decision.minimum_version,
            "download_url": decision.download_url,
            "entitlements": decision.entitlements,
            "device_id": f"…{device.device_id[-12:]}" if device else None,
            "device_name": device.device_name if device else None,
            "initialized": manager is not None,
            "initialization_error": self._initialization_error,
        }

    def shutdown(self) -> None:
        with self._lock:
            worker = self._worker
            self._worker = None
        if worker:
            worker.stop()


application_license = ApplicationLicenseCoordinator()
