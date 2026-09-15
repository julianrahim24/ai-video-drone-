"""
Covers the required do-not-trade / fail-safe scenarios from the spec:
oversized position, daily loss limit, portfolio exposure, insufficient cash,
stale market data - plus the options/leverage gating rules.
"""
from trading.models import AssetClass, OrderSide, Position
from trading.risk import position_sizing
from trading.risk.risk_engine import Rejection, evaluate_trade
from tests.factories import make_account, make_analysis, make_config, make_quote


def test_valid_trade_produces_a_proposal():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert not isinstance(result, Rejection)
    assert result.symbol == "AAPL"
    assert result.quantity > 0
    assert result.max_dollar_loss <= 25_000 * (config.risk_profile().max_trade_risk_pct / 100) + 1e-6


def test_stale_market_data_is_refused():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    stale_quote = make_quote(age_seconds=999)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=stale_quote, analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "stale" in result.reason


def test_daily_loss_limit_blocks_new_trades():
    account = make_account(cash=24_000, portfolio_value=24_000)  # portfolio down from 25,000
    config = make_config(risk_level=5, max_daily_loss_percent=0.03)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "daily loss limit" in result.reason


def test_portfolio_exposure_limit_blocks_new_trades():
    existing = Position(symbol="MSFT", quantity=150, avg_price=100.0)  # $15,000 of $25,000 = 60%
    account = make_account(cash=10_000, portfolio_value=25_000, positions=[existing])
    config = make_config(risk_level=5)  # max_portfolio_exposure defaults to 65%
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "exposure" in result.reason


def test_insufficient_cash_is_refused_safely():
    account = make_account(cash=0.0, portfolio_value=25_000, positions=[Position("MSFT", 250, 100.0)])
    config = make_config(risk_level=5)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)


def test_oversized_position_is_rejected_even_if_sizing_misbehaves(monkeypatch):
    """Defense in depth: even if the sizing function ever returned something
    too big, the risk engine's own absolute cap must still refuse it."""
    account = make_account(cash=20_000_000, portfolio_value=20_000_000)
    config = make_config(risk_level=5)

    class OversizedResult:
        quantity = 100_000
        position_value = 10_000_000.0
        dollar_risk = 500.0
        capped_by = []

    monkeypatch.setattr(position_sizing, "size_position", lambda **kwargs: OversizedResult())
    result = evaluate_trade(
        account=account, daily_start_value=20_000_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    # Whichever guardrail catches it first (concentration, exposure, or the
    # absolute position-size cap), an oversized order must never go through.
    assert isinstance(result, Rejection)


def test_low_confidence_signal_is_refused():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    weak_analysis = make_analysis(confidence=40, signal="NO_TRADE")
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=weak_analysis, config=config,
    )
    assert isinstance(result, Rejection)
    assert "confidence" in result.reason


def test_earnings_within_a_day_is_refused():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    analysis = make_analysis(days_to_earnings=1)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=analysis, config=config,
    )
    assert isinstance(result, Rejection)
    assert "earnings" in result.reason


def test_illiquid_stock_is_refused():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    analysis = make_analysis(avg_dollar_volume=10_000)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=analysis, config=config,
    )
    assert isinstance(result, Rejection)
    assert "illiquid" in result.reason


def test_options_blocked_below_risk_level_5():
    account = make_account(cash=25_000)
    config = make_config(risk_level=3)
    config.allow_options = True
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.OPTION, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "options are not permitted" in result.reason


def test_options_blocked_unless_explicitly_enabled_even_at_high_level():
    account = make_account(cash=25_000)
    config = make_config(risk_level=7)
    assert config.allow_options is False
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.OPTION, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "disabled" in result.reason


def test_leverage_blocked_below_level_9():
    account = make_account(cash=25_000)
    config = make_config(risk_level=7)
    config.allow_leverage = True
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.BUY,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "leverage is not permitted" in result.reason


def test_sell_without_existing_position_is_refused():
    account = make_account(cash=25_000)
    config = make_config(risk_level=5)
    result = evaluate_trade(
        account=account, daily_start_value=25_000, symbol="AAPL", side=OrderSide.SELL,
        asset_class=AssetClass.EQUITY, quote=make_quote(), analysis=make_analysis(), config=config,
    )
    assert isinstance(result, Rejection)
    assert "no existing long position" in result.reason
