"""
The single place a trade is allowed or refused.

Implements, in order, the "Before placing ANY trade" checklist and the
"DO NOT TRADE" conditions from the spec. Every check that can refuse a trade
returns a specific human-readable reason - refusals are never silent and
never generic. If ANY check fails, evaluate_trade returns a Rejection and
places nothing; there is no partial/best-effort trade.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from trading.analysis.engine import AnalysisResult
from trading.config import AppConfig, PortfolioLimits, RiskLevelProfile
from trading.models import AccountSnapshot, AssetClass, OrderSide, Quote, TradeProposal
from trading.risk import portfolio_limits as limits_checks
from trading.risk import position_sizing, stop_loss

MIN_CONFIDENCE_TO_TRADE = 65


@dataclass
class Rejection:
    reason: str
    details: list[str]


def _quote_is_stale(quote: Quote, limits: PortfolioLimits) -> bool:
    return quote.age_seconds() > limits.quote_staleness_seconds


def evaluate_trade(
    *,
    account: AccountSnapshot,
    daily_start_value: float,
    symbol: str,
    side: OrderSide,
    asset_class: AssetClass,
    quote: Quote,
    analysis: AnalysisResult,
    config: AppConfig,
    sector: str | None = None,
) -> TradeProposal | Rejection:
    risk_profile: RiskLevelProfile = config.risk_profile()
    limits = config.limits

    # --- asset-class / feature gates -------------------------------------------------
    if asset_class == AssetClass.OPTION:
        if not risk_profile.options_allowed_ceiling:
            return Rejection(
                f"options are not permitted at risk level {config.risk_level} "
                f"({risk_profile.label}); options only become eligible at level 5+",
                [],
            )
        if not config.allow_options:
            return Rejection(
                "options are disabled - enable explicitly with /options on before requesting an options trade",
                [],
            )

    if asset_class != AssetClass.CRYPTO:
        # Leverage/margin is out of scope for this engine's sizing model; refuse
        # anything that isn't a plain cash-covered buy or a sell of an existing
        # long position, regardless of risk level.
        if side == OrderSide.BUY:
            pass
        elif side == OrderSide.SELL and account.position_for(symbol) is None:
            return Rejection(f"cannot sell {symbol}: no existing long position (short selling is not supported)", [])

    if config.allow_leverage and not risk_profile.leverage_allowed_ceiling:
        return Rejection(
            f"leverage is not permitted at risk level {config.risk_level}; only levels 9-10 may enable it", []
        )

    # --- market data integrity ---------------------------------------------------
    if _quote_is_stale(quote, limits):
        return Rejection(
            f"market data for {symbol} is stale ({quote.age_seconds():.0f}s old, "
            f"limit is {limits.quote_staleness_seconds:.0f}s) - refusing to trade on stale data",
            [],
        )

    # --- do-not-trade: liquidity ---------------------------------------------------
    required_liquidity = max(risk_profile.min_avg_dollar_volume, limits.min_avg_dollar_volume_floor)
    if analysis.avg_dollar_volume is not None and analysis.avg_dollar_volume < required_liquidity:
        return Rejection(
            f"{symbol} average dollar volume (${analysis.avg_dollar_volume:,.0f}/day) is below the "
            f"${required_liquidity:,.0f}/day minimum for risk level {config.risk_level} - too illiquid",
            [],
        )

    # --- do-not-trade: volatility tolerance -----------------------------------------
    if (
        analysis.annualized_volatility is not None
        and analysis.annualized_volatility > risk_profile.volatility_ceiling_annualized
    ):
        return Rejection(
            f"{symbol} annualized volatility ({analysis.annualized_volatility:.0%}) exceeds the "
            f"{risk_profile.volatility_ceiling_annualized:.0%} ceiling for risk level {config.risk_level}",
            [],
        )

    # --- do-not-trade: known event risk ---------------------------------------------
    if analysis.days_to_earnings is not None and 0 <= analysis.days_to_earnings <= 1:
        return Rejection(
            f"{symbol} reports earnings within {analysis.days_to_earnings} day(s) - "
            "a major known event makes this trade unusually risky right now",
            [],
        )

    # --- do-not-trade: confidence / signal -------------------------------------------
    if analysis.signal != "BUY" or analysis.confidence < MIN_CONFIDENCE_TO_TRADE:
        return Rejection(
            f"{symbol} does not meet the confidence/signal bar (signal={analysis.signal}, "
            f"confidence={analysis.confidence}/100, minimum required is {MIN_CONFIDENCE_TO_TRADE})",
            analysis.warnings,
        )

    # --- daily loss limit ------------------------------------------------------------
    daily_loss_reason = limits_checks.check_daily_loss_limit(daily_start_value, account.portfolio_value, limits)
    if daily_loss_reason:
        return Rejection(daily_loss_reason, [])

    # --- open positions count ----------------------------------------------------------
    open_positions_reason = limits_checks.check_open_positions_limit(
        account, limits, risk_profile.max_open_positions
    )
    if open_positions_reason and account.position_for(symbol) is None:
        return Rejection(open_positions_reason, [])

    # --- position sizing ---------------------------------------------------------------
    entry_price = quote.price
    computed_stop = stop_loss.compute_stop_loss(entry_price, analysis.atr_value, side, risk_profile)
    sizing = position_sizing.size_position(
        portfolio_value=account.portfolio_value,
        available_cash=account.cash,
        entry_price=entry_price,
        stop_loss=computed_stop,
        risk_profile=risk_profile,
        limits=limits,
    )
    if sizing.quantity <= 0:
        return Rejection(
            f"calculated position size for {symbol} rounds to 0 shares given current cash/limits - skipping", []
        )

    order_value = sizing.position_value

    # --- cash --------------------------------------------------------------------------
    cash_reason = limits_checks.check_sufficient_cash(account, order_value, side)
    if cash_reason:
        return Rejection(cash_reason, [])

    # --- exposure / concentration --------------------------------------------------------
    exposure_reason = limits_checks.check_portfolio_exposure(account, order_value, limits)
    if exposure_reason:
        return Rejection(exposure_reason, [])

    concentration_reason = limits_checks.check_symbol_concentration(account, symbol, order_value, limits)
    if concentration_reason:
        return Rejection(concentration_reason, [])

    sector_reason = limits_checks.check_sector_concentration(account, sector, order_value, limits)
    if sector_reason:
        return Rejection(sector_reason, [])

    # --- absolute position-size limit (belt-and-suspenders on top of sizing) -------------
    max_position_value = account.portfolio_value * min(risk_profile.default_max_position_pct, limits.max_position_percent)
    if order_value > max_position_value + 1e-6:
        return Rejection(
            f"order value ${order_value:,.2f} exceeds the maximum position-size limit "
            f"of ${max_position_value:,.2f} for this account/risk level",
            [],
        )

    portfolio_pct_after = (account.exposure_value() + order_value) / account.portfolio_value
    max_dollar_loss = sizing.dollar_risk
    risk_pct_of_portfolio = max_dollar_loss / account.portfolio_value if account.portfolio_value else 0.0
    upside = (analysis.target_price - entry_price) * sizing.quantity
    downside = max_dollar_loss

    reason_text = "; ".join(analysis.reasons) or "meets risk-level and technical criteria"

    return TradeProposal(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        asset_class=asset_class,
        quantity=sizing.quantity,
        entry_price=entry_price,
        stop_loss=computed_stop,
        target_price=analysis.target_price,
        estimated_order_value=order_value,
        portfolio_pct_after=portfolio_pct_after,
        max_dollar_loss=max_dollar_loss,
        risk_pct_of_portfolio=risk_pct_of_portfolio,
        reason=reason_text,
        risk_level=config.risk_level,
        confidence=analysis.confidence,
        upside_estimate=upside,
        downside_estimate=downside,
        major_risks=analysis.warnings,
    )
