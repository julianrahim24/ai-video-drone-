"""
Risk-based position sizing.

The core idea: decide how many shares to buy from how much money you're
willing to LOSE (risk_amount = portfolio_value * max_trade_risk_pct), not
from how much you want to spend. The stop-loss distance converts that dollar
risk into a share count. The result is then hard-capped by the account's
absolute position-size and cash limits, which can only shrink the size,
never grow it beyond the risk-based number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from trading.config import PortfolioLimits, RiskLevelProfile


@dataclass
class SizingResult:
    quantity: float
    position_value: float
    dollar_risk: float
    capped_by: list[str]


def size_position(
    portfolio_value: float,
    available_cash: float,
    entry_price: float,
    stop_loss: float,
    risk_profile: RiskLevelProfile,
    limits: PortfolioLimits,
) -> SizingResult:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        raise ValueError("stop_loss must differ from entry_price")

    capped_by: list[str] = []

    max_dollar_risk = portfolio_value * (risk_profile.max_trade_risk_pct / 100)
    risk_based_qty = math.floor(max_dollar_risk / risk_per_share)

    max_position_value = portfolio_value * min(risk_profile.default_max_position_pct, limits.max_position_percent)
    position_value = risk_based_qty * entry_price
    if position_value > max_position_value:
        capped_by.append("max_position_percent")
        risk_based_qty = math.floor(max_position_value / entry_price)
        position_value = risk_based_qty * entry_price

    if position_value > available_cash:
        capped_by.append("available_cash")
        risk_based_qty = math.floor(available_cash / entry_price)
        position_value = risk_based_qty * entry_price

    quantity = max(risk_based_qty, 0)
    position_value = quantity * entry_price
    dollar_risk = quantity * risk_per_share

    return SizingResult(
        quantity=quantity,
        position_value=round(position_value, 2),
        dollar_risk=round(dollar_risk, 2),
        capped_by=capped_by,
    )
