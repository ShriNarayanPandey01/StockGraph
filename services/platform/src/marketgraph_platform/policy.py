"""All feature access is free; cost controls and ownership remain independent."""

FEATURES = {
    "professional_evidence": "PRO",
    "research_chat": "FREE",
    "discovery": "PRO",
    "opportunity_alerts": "FREE",
    "stock_connections": "FREE",
}


def access_policy() -> dict:
    return {
        "phase": 1,
        "billing_enabled": False,
        "rbac_enabled": False,
        "quota_enforcement": False,
        "features": {key: {"allowed": True, "future_access": tier} for key, tier in FEATURES.items()},
        "future_free_limits": {"active_stocks": 10, "opportunity_alerts_per_month": 10,
                               "reset_timezone": "Asia/Kolkata"},
    }
