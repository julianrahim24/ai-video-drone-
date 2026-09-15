"""
Live market data via Finnhub (https://finnhub.io) - a legitimate, documented,
free-tier REST API with its own developer API key. This is NOT Robinhood's
private app API and involves no scraping, session cookies, or credential
bypass; it is a standard third-party market-data vendor used only to fetch
public price/volume history for the analysis engine.

Requires FINNHUB_API_KEY in the environment. Raises DataProviderError rather
than inventing data if the key is missing or a request fails.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from trading.data.provider_base import DataProviderError, MarketDataProvider
from trading.models import Quote

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider(MarketDataProvider):
    name = "finnhub"

    def __init__(self, api_key: str | None, timeout: float = 10.0):
        if not api_key:
            raise DataProviderError(
                "FINNHUB_API_KEY is not set. Get a free key at https://finnhub.io "
                "and set it as an environment variable - never hard-code it."
            )
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "token": self.api_key}
        try:
            resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise DataProviderError(f"network error calling Finnhub {path}: {e}") from e
        if resp.status_code != 200:
            raise DataProviderError(f"Finnhub {path} returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise DataProviderError(f"Finnhub {path} returned non-JSON response") from e

    def get_quote(self, symbol: str) -> Quote:
        data = self._get("/quote", {"symbol": symbol})
        price = data.get("c")
        if price in (None, 0):
            raise DataProviderError(f"Finnhub returned no current price for {symbol}")
        return Quote(
            symbol=symbol,
            price=float(price),
            bid=None,
            ask=None,
            volume=None,
            as_of=datetime.now(timezone.utc),
            source=self.name,
        )

    def get_daily_bars(self, symbol: str, lookback_days: int = 260) -> list[dict]:
        end = int(time.time())
        start = int((datetime.now(timezone.utc) - timedelta(days=int(lookback_days * 1.6) + 10)).timestamp())
        data = self._get(
            "/stock/candle",
            {"symbol": symbol, "resolution": "D", "from": start, "to": end},
        )
        if data.get("s") != "ok":
            raise DataProviderError(f"Finnhub has no candle data for {symbol} (status={data.get('s')})")
        bars = [
            {
                "date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
            for t, o, h, l, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
            )
        ]
        return bars[-lookback_days:]
