"""One permission vocabulary; paid access and developer authority are independent."""
import json
from datetime import UTC, datetime

from marketgraph_platform.repository import PlatformError

FEATURES = {
    "professional_evidence": "PRO", "research_chat": "FREE", "discovery": "PRO",
    "opportunity_alerts": "FREE", "stock_connections": "FREE", "monitoring": "FREE",
    "market_monitoring": "PRO",
}


def effective_plan(user, now=None):
    if user is None:
        return "FREE"
    if user.is_developer:
        return "PRO"
    expires = user.plan_expires_at
    return "PRO" if user.plan == "PRO" and (expires is None or expires > (now or datetime.now(UTC))) else "FREE"


def require_permission(user, permission):
    if user.is_developer:
        return
    allowed = {
        "author": "PROFESSIONAL" in user.roles and user.professional_verified,
        "review": "REVIEWER" in user.roles,
        "admin": False,
    }
    if not allowed.get(permission, False):
        raise PlatformError(403, "Permission required: " + permission)


def access_policy(user=None, policy=None):
    developer = bool(user and user.is_developer)
    plan = effective_plan(user)
    configured = policy or {}
    features = configured.get("features") or {
        name: plan == "PRO" or tier == "FREE" for name, tier in FEATURES.items()
    }
    if isinstance(features, str):
        features = json.loads(features)
    return {
        "phase": 2, "billing_enabled": False, "rbac_enabled": True, "quota_enforcement": not developer,
        "plan": plan, "developer": developer,
        "features": {name: {"allowed": developer or bool(features.get(name, False)), "tier": tier}
                     for name, tier in FEATURES.items()},
        "limits": {
            "active_stocks": None if developer else configured.get("active_stock_limit", 10 if plan == "FREE" else None),
            "opportunity_alerts_per_month": None if developer else configured.get("monthly_alert_limit", 10 if plan == "FREE" else None),
            "reset_timezone": "Asia/Kolkata",
        },
        "policy_revision": configured.get("revision", 1),
    }
