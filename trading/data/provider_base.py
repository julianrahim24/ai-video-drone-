"""Market data provider abstraction, so the analysis engine and paper
broker never depend directly on a specific vendor."""
from __future__ import annotations

from abc import ABC, abstractmethod

from trading.models import Quote


class DataProviderError(Exception):
    pass


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        ...

    @abstractmethod
    def get_daily_bars(self, symbol: str, lookback_days: int = 260) -> list[dict]:
        """Returns a list of {date, open, high, low, close, volume} dicts,
        oldest first. Must raise DataProviderError rather than return
        fabricated/interpolated bars if data is unavailable."""

    def get_avg_dollar_volume(self, symbol: str, lookback_days: int = 20) -> float:
        bars = self.get_daily_bars(symbol, lookback_days=lookback_days)
        if not bars:
            raise DataProviderError(f"no bars for {symbol}")
        recent = bars[-lookback_days:]
        return sum(b["close"] * b["volume"] for b in recent) / len(recent)
