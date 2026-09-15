"""Test-only helpers for building fixtures quickly. Not part of the app."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading.analysis.engine import AnalysisResult
from trading.config import AppConfig, PortfolioLimits
from trading.models import AccountSnapshot, Position, Quote


def make_quote(symbol: str = "AAPL", price: float = 100.0, age_seconds: float = 0.0) -> Quote:
    return Quote(
        symbol=symbol,
        price=price,
        bid=price - 0.05,
        ask=price + 0.05,
        volume=1_000_000,
        as_of=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        source="test",
    )


def make_analysis(**overrides) -> AnalysisResult:
    defaults = dict(
        symbol="AAPL",
        signal="BUY",
        confidence=80,
        risk_label="Low",
        entry_price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        atr_value=2.5,
        annualized_volatility=0.20,
        avg_dollar_volume=2_000_000.0,
        trend="up",
        market_trend="up",
        rsi_value=55.0,
        relative_strength_value=0.03,
        support=90.0,
        resistance=120.0,
        days_to_earnings=None,
        reasons=["uptrend", "healthy RSI"],
        warnings=[],
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def make_account(cash: float = 25_000.0, portfolio_value: float | None = None, positions: list[Position] | None = None) -> AccountSnapshot:
    positions = positions or []
    if portfolio_value is None:
        portfolio_value = cash + sum(p.cost_basis for p in positions)
    return AccountSnapshot(cash=cash, portfolio_value=portfolio_value, positions=positions)


def make_config(risk_level: int = 5, **limit_overrides) -> AppConfig:
    config = AppConfig(risk_level=risk_level)
    if limit_overrides:
        config.limits = PortfolioLimits(**{**vars(PortfolioLimits()), **limit_overrides})
    return config
