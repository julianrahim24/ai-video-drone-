"""Account-wide guardrails that apply regardless of risk level: exposure,
concentration, open-position count, and daily loss. Each check returns a
reason string on failure, or None on pass, so the risk engine can report a
concrete, human-readable reason for any refusal."""
from __future__ import annotations

from trading.config import PortfolioLimits
from trading.models import AccountSnapshot, OrderSide


def check_open_positions_limit(account: AccountSnapshot, limits: PortfolioLimits, max_open_positions_for_level: int) -> str | None:
    cap = min(limits.max_open_positions, max_open_positions_for_level)
    if len(account.positions) >= cap:
        return f"already at the maximum of {cap} open positions for this account/risk level"
    return None


def check_portfolio_exposure(account: AccountSnapshot, new_position_value: float, limits: PortfolioLimits) -> str | None:
    if account.portfolio_value <= 0:
        return "portfolio value is zero or negative - cannot evaluate exposure"
    projected_exposure = (account.exposure_value() + new_position_value) / account.portfolio_value
    if projected_exposure > limits.max_portfolio_exposure:
        return (
            f"trade would bring total exposure to {projected_exposure:.0%}, "
            f"above the {limits.max_portfolio_exposure:.0%} limit"
        )
    return None


def check_symbol_concentration(
    account: AccountSnapshot, symbol: str, new_position_value: float, limits: PortfolioLimits
) -> str | None:
    existing = account.position_for(symbol)
    existing_value = existing.cost_basis if existing else 0.0
    projected_pct = (existing_value + new_position_value) / account.portfolio_value
    if projected_pct > limits.max_symbol_concentration_pct:
        return (
            f"you already have exposure to {symbol}; this trade would bring it to "
            f"{projected_pct:.0%} of the portfolio, above the {limits.max_symbol_concentration_pct:.0%} limit"
        )
    return None


def check_sector_concentration(
    account: AccountSnapshot, sector: str | None, new_position_value: float, limits: PortfolioLimits
) -> str | None:
    if not sector:
        return None
    existing_sector_value = sum(p.cost_basis for p in account.positions if p.sector == sector)
    projected_pct = (existing_sector_value + new_position_value) / account.portfolio_value
    if projected_pct > limits.max_sector_concentration_pct:
        return (
            f"this trade would bring {sector} sector exposure to {projected_pct:.0%}, "
            f"above the {limits.max_sector_concentration_pct:.0%} limit"
        )
    return None


def check_daily_loss_limit(daily_start_value: float, current_portfolio_value: float, limits: PortfolioLimits) -> str | None:
    if daily_start_value <= 0:
        return None
    daily_pnl_pct = (current_portfolio_value - daily_start_value) / daily_start_value
    if daily_pnl_pct <= -limits.max_daily_loss_percent:
        return (
            f"daily loss limit reached ({daily_pnl_pct:.1%} today, "
            f"limit is -{limits.max_daily_loss_percent:.0%}) - no new trades until tomorrow"
        )
    return None


def check_sufficient_cash(account: AccountSnapshot, order_value: float, side: OrderSide) -> str | None:
    if side == OrderSide.BUY and order_value > account.cash + 1e-6:
        return f"insufficient cash: need ${order_value:,.2f}, have ${account.cash:,.2f}"
    return None
