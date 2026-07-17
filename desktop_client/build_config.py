"""Values replaced by the Windows release build pipeline.

Do not load the production trust root from a user-editable .env file.
"""

LICENSE_API_BASE_URL = "https://xianyuxian.dskjahf.xyz"
LICENSE_PUBLIC_KEY_BASE64 = "PZiG1O-uIWneaA4sYpi9SUQUhYbeA7nf9DVjyEdEwYE"
try:
    from ._generated_build import APP_VERSION
except ImportError:
    APP_VERSION = "0.1.1"
RELEASE_CHANNEL = "stable"
