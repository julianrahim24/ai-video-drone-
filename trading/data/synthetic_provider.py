"""
Deterministic, offline synthetic data provider.

FOR TESTING AND DEMOS ONLY. It generates a reproducible pseudo-random price
series seeded from the symbol name - it is not real market data and must
never be used to size or approve a real trade. The risk/paper engine tests
use this so they run without network access or an API key.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from trading.data.provider_base import MarketDataProvider
from trading.models import Quote


class SyntheticDataProvider(MarketDataProvider):
    name = "synthetic-test-data"

    def __init__(self, base_prices: dict[str, float] | None = None):
        self.base_prices = base_prices or {}

    def _seed_for(self, symbol: str) -> int:
        return int(hashlib.sha256(symbol.encode()).hexdigest(), 16) % (2**32)

    def _series(self, symbol: str, n: int) -> list[float]:
        rng = random.Random(self._seed_for(symbol))
        price = self.base_prices.get(symbol, 100.0 + (self._seed_for(symbol) % 200))
        prices = []
        for _ in range(n):
            price *= 1 + rng.gauss(0.0003, 0.015)
            price = max(price, 0.5)
            prices.append(price)
        return prices

    def get_quote(self, symbol: str) -> Quote:
        price = self._series(symbol, 1)[0]
        return Quote(
            symbol=symbol,
            price=round(price, 2),
            bid=round(price * 0.999, 2),
            ask=round(price * 1.001, 2),
            volume=1_000_000,
            as_of=datetime.now(timezone.utc),
            source=self.name,
        )

    def get_daily_bars(self, symbol: str, lookback_days: int = 260) -> list[dict]:
        closes = self._series(symbol, lookback_days)
        today = datetime.now(timezone.utc).date()
        bars = []
        for i, close in enumerate(closes):
            d = today - timedelta(days=(lookback_days - i))
            bars.append(
                {
                    "date": d.isoformat(),
                    "open": close * 0.998,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                }
            )
        return bars
