from trading.analysis.engine import AnalysisEngine
from trading.data.synthetic_provider import SyntheticDataProvider


def test_analysis_produces_a_bounded_confidence_score():
    provider = SyntheticDataProvider(base_prices={"AAPL": 150.0, "SPY": 450.0})
    engine = AnalysisEngine(provider)
    result = engine.analyze("AAPL")
    assert 0 <= result.confidence <= 100
    assert result.signal in ("BUY", "SELL", "NO_TRADE")
    assert result.stop_loss < result.entry_price < result.target_price or result.signal != "BUY"


def test_not_enough_history_raises():
    from trading.data.provider_base import DataProviderError, MarketDataProvider
    from trading.models import Quote
    from datetime import datetime, timezone

    class TinyProvider(MarketDataProvider):
        name = "tiny"

        def get_quote(self, symbol):
            return Quote(symbol=symbol, price=100.0, bid=99.9, ask=100.1, volume=1000,
                         as_of=datetime.now(timezone.utc), source="tiny")

        def get_daily_bars(self, symbol, lookback_days=260):
            return [{"date": "2026-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}]

    engine = AnalysisEngine(TinyProvider())
    try:
        engine.analyze("AAPL")
        assert False, "expected DataProviderError"
    except DataProviderError:
        pass
