from trading.config import PortfolioLimits, profile_for_level
from trading.risk.position_sizing import size_position


def test_position_size_capped_by_max_position_percent():
    profile = profile_for_level(5)  # default_max_position_pct=0.10
    limits = PortfolioLimits()
    result = size_position(
        portfolio_value=25_000, available_cash=25_000, entry_price=100, stop_loss=95,
        risk_profile=profile, limits=limits,
    )
    # risk-based size would be (25000*0.02)/5 = 100 shares = $10,000, but the
    # position-size cap is min(0.10, 0.15) * 25000 = $2,500 -> 25 shares.
    assert result.quantity == 25
    assert result.position_value == 2_500.0
    assert "max_position_percent" in result.capped_by


def test_position_size_capped_by_available_cash():
    profile = profile_for_level(5)
    limits = PortfolioLimits()
    result = size_position(
        portfolio_value=25_000, available_cash=1_000, entry_price=100, stop_loss=95,
        risk_profile=profile, limits=limits,
    )
    assert result.quantity == 10
    assert result.position_value == 1_000.0
    assert "available_cash" in result.capped_by


def test_position_size_never_exceeds_risk_amount_when_unconstrained():
    profile = profile_for_level(9)  # 5% max trade risk, wide position cap
    limits = PortfolioLimits(max_position_percent=0.99)
    result = size_position(
        portfolio_value=100_000, available_cash=100_000, entry_price=50, stop_loss=48,
        risk_profile=profile, limits=limits,
    )
    max_dollar_risk = 100_000 * 0.05
    assert result.dollar_risk <= max_dollar_risk


def test_zero_or_negative_inputs_raise():
    profile = profile_for_level(5)
    limits = PortfolioLimits()
    try:
        size_position(portfolio_value=10_000, available_cash=10_000, entry_price=0, stop_loss=1,
                       risk_profile=profile, limits=limits)
        assert False, "expected ValueError"
    except ValueError:
        pass
