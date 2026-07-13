from __future__ import annotations

from desktop_client import build_config

from .config import LicenseClientConfig
from .device import get_windows_device_identity
from .manager import LicenseManager
from .storage import CredentialStore


def create_windows_license_manager() -> LicenseManager:
    """Build the production manager from values embedded by the release pipeline."""
    config = LicenseClientConfig(
        api_base_url=build_config.LICENSE_API_BASE_URL,
        public_key_base64=build_config.LICENSE_PUBLIC_KEY_BASE64,
        app_version=build_config.APP_VERSION,
        channel=build_config.RELEASE_CHANNEL,
    )
    return LicenseManager(
        config,
        get_windows_device_identity(),
        CredentialStore.windows_default(),
    )
