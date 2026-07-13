from __future__ import annotations

from .manager import LicenseManager
from .models import LicenseDecision


class LicenseGateDenied(RuntimeError):
    def __init__(self, decision: LicenseDecision):
        self.decision = decision
        super().__init__(decision.message)


def require_automation_license(manager: LicenseManager) -> LicenseDecision:
    """Run before CookieManager or any Xianyu automation task is started."""
    decision = manager.startup_check()
    if not decision.allows_automation:
        raise LicenseGateDenied(decision)
    return decision

