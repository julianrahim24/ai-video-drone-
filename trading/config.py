"""
Central configuration and safety limits.

SAFETY NOTE: TradingMode always starts each process at PAPER, regardless of
what was used in a previous run. Live trading must be re-enabled explicitly
every session via the CLI's /live command - it is never silently persisted
as the startup mode. This is intentional and must not be "fixed".

Secrets (Robinhood crypto API key / private key) are read from environment
variables only. Nothing that can authenticate to a real account is ever
written into source code, config files checked into git, or logs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from trading.models import TradingMode


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class RiskLevelProfile:
    level_range: tuple[int, int]
    label: str
    max_trade_risk_pct: float          # max % of portfolio that can be lost on a single trade
    default_max_position_pct: float    # soft default cap on notional per position
    max_open_positions: int
    stop_loss_atr_multiple: float      # wider stop = more room for volatility
    volatility_ceiling_annualized: float  # reject symbols historically more volatile than this
    min_avg_dollar_volume: float       # liquidity floor
    options_allowed_ceiling: bool      # can options ever be enabled at this band (still requires explicit opt-in)
    leverage_allowed_ceiling: bool      # can leverage ever be enabled at this band (still requires explicit opt-in)


# Risk level table, directly encoding the bands specified by the user.
RISK_LEVEL_PROFILES: list[RiskLevelProfile] = [
    RiskLevelProfile((1, 2), "Very Conservative", 1.0, 0.06, 4, 1.5, 0.25, 5_000_000, False, False),
    RiskLevelProfile((3, 4), "Conservative", 1.5, 0.08, 5, 2.0, 0.35, 3_000_000, False, False),
    RiskLevelProfile((5, 6), "Moderate", 2.0, 0.10, 6, 2.5, 0.55, 1_500_000, True, False),
    RiskLevelProfile((7, 8), "Aggressive", 3.0, 0.15, 8, 3.0, 0.90, 750_000, True, False),
    RiskLevelProfile((9, 10), "Very Aggressive", 5.0, 0.20, 10, 3.5, 999.0, 300_000, True, True),
]


def profile_for_level(level: int) -> RiskLevelProfile:
    if not 1 <= level <= 10:
        raise ValueError(f"risk level must be 1-10, got {level}")
    for profile in RISK_LEVEL_PROFILES:
        lo, hi = profile.level_range
        if lo <= level <= hi:
            return profile
    raise AssertionError("unreachable - table above covers 1-10")


@dataclass
class PortfolioLimits:
    """Configurable, account-wide limits. Independent of risk level so a user
    can never accidentally loosen them just by raising risk level."""
    max_position_percent: float = _env_float("MAX_POSITION_PERCENT", 0.15)
    max_portfolio_exposure: float = _env_float("MAX_PORTFOLIO_EXPOSURE", 0.65)
    max_daily_loss_percent: float = _env_float("MAX_DAILY_LOSS_PERCENT", 0.03)
    max_open_positions: int = _env_int("MAX_OPEN_POSITIONS", 8)
    max_symbol_concentration_pct: float = _env_float("MAX_SYMBOL_CONCENTRATION_PCT", 0.15)
    max_sector_concentration_pct: float = _env_float("MAX_SECTOR_CONCENTRATION_PCT", 0.30)
    quote_staleness_seconds: float = _env_float("QUOTE_STALENESS_SECONDS", 60.0)
    min_avg_dollar_volume_floor: float = _env_float("MIN_AVG_DOLLAR_VOLUME", 250_000.0)


@dataclass
class AppConfig:
    mode: TradingMode = TradingMode.PAPER   # ALWAYS starts PAPER - see module docstring
    risk_level: int = _env_int("DEFAULT_RISK_LEVEL", 3)
    allow_options: bool = False             # never true on startup; only via explicit /options on command
    allow_leverage: bool = False            # never true on startup; only via explicit /leverage on command
    auto_execute_live: bool = False         # if False (default/required), live orders always wait for /approve
    limits: PortfolioLimits = field(default_factory=PortfolioLimits)

    # Robinhood Crypto Trading API (official, documented). Never hard-coded.
    crypto_api_key: str | None = field(default_factory=lambda: os.environ.get("ROBINHOOD_CRYPTO_API_KEY"))
    crypto_private_key_b64: str | None = field(
        default_factory=lambda: os.environ.get("ROBINHOOD_CRYPTO_PRIVATE_KEY_B64")
    )

    # Market data (official, documented, free-tier third-party provider - see trading/data)
    finnhub_api_key: str | None = field(default_factory=lambda: os.environ.get("FINNHUB_API_KEY"))

    state_dir: str = os.environ.get("TRADING_STATE_DIR", "logs")

    def risk_profile(self) -> RiskLevelProfile:
        return profile_for_level(self.risk_level)
