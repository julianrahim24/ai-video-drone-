"""
A MarketDataProvider backed by a JSON snapshot of REAL data pulled from
Robinhood's own official Agentic Trading MCP tools (get_equity_quotes /
get_equity_historicals) during an assistant session with that connector
enabled - not synthetic, not scraped, and not from a third-party vendor.

This exists because a standalone script running outside an MCP-connected
agent session cannot call those tools itself (see
trading/broker/robinhood_agentic_bridge.py for the same constraint on order
execution). The snapshot is a point-in-time cache: quotes are treated as
stale after `quote_max_age` and will raise DataProviderError rather than be
used past that window, exactly like every other provider in this project.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from trading.data.provider_base import DataProviderError, MarketDataProvider
from trading.models import Quote


class MCPSnapshotProvider(MarketDataProvider):
    name = "robinhood_mcp_snapshot"

    def __init__(self, path: str, quote_max_age_seconds: float = 24 * 3600):
        if not os.path.exists(path):
            raise DataProviderError(f"no MCP market data snapshot found at {path}")
        with open(path) as f:
            self._data = json.load(f)
        self.as_of = datetime.fromisoformat(self._data["as_of"].replace("Z", "+00:00"))
        self.quote_max_age_seconds = quote_max_age_seconds

    def get_quote(self, symbol: str) -> Quote:
        price = self._data["quotes"].get(symbol)
        if price is None:
            raise DataProviderError(f"no cached quote for {symbol} in this snapshot")
        age = (datetime.now(timezone.utc) - self.as_of).total_seconds()
        if age > self.quote_max_age_seconds:
            raise DataProviderError(
                f"MCP market data snapshot is {age / 3600:.1f}h old (captured {self.as_of.isoformat()}) - "
                "refusing to trade on stale data; re-fetch quotes via the Robinhood MCP tools"
            )
        return Quote(
            symbol=symbol, price=float(price), bid=None, ask=None, volume=None,
            as_of=self.as_of, source=self.name,
        )

    def get_daily_bars(self, symbol: str, lookback_days: int = 260) -> list[dict]:
        bars = self._data["bars"].get(symbol)
        if not bars:
            raise DataProviderError(f"no cached daily bars for {symbol} in this snapshot")
        return bars[-lookback_days:]
