"""Thin re-export so `trading.risk.*` is self-contained per the requested
architecture, even though the level table itself lives in trading/config.py
next to the other tunables."""
from trading.config import RiskLevelProfile, RISK_LEVEL_PROFILES, profile_for_level

__all__ = ["RiskLevelProfile", "RISK_LEVEL_PROFILES", "profile_for_level"]
