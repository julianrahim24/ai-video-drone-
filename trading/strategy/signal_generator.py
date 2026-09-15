"""
"Find me a trade": scans a watchlist, runs the analysis engine on each
symbol, and hands every candidate through the risk engine. Only proposals
that survive every risk-level and portfolio-limit check are returned - nothing
here bypasses the risk engine, and this module places no orders itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading.analysis.engine import AnalysisEngine
from trading.config import AppConfig
from trading.data.provider_base import DataProviderError, MarketDataProvider
from trading.models import AccountSnapshot, AssetClass, OrderSide, TradeProposal
from trading.risk.risk_engine import Rejection, evaluate_trade

# A small, diversified, liquid default universe. Users can override with
# their own watchlist; this is not investment advice, just a reasonable
# starting scan set of large, well-established names and broad ETFs.
DEFAULT_WATCHLIST: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "JPM": "Financials", "V": "Financials",
    "JNJ": "Healthcare", "UNH": "Healthcare",
    "PG": "Consumer Staples", "COST": "Consumer Staples",
    "XOM": "Energy",
    "SPY": "Broad Market ETF", "QQQ": "Broad Market ETF", "VTI": "Broad Market ETF",
}


@dataclass
class ScanCandidate:
    symbol: str
    outcome: TradeProposal | Rejection


def find_trades(
    *,
    account: AccountSnapshot,
    daily_start_value: float,
    config: AppConfig,
    data_provider: MarketDataProvider,
    analysis_engine: AnalysisEngine,
    watchlist: dict[str, str] | None = None,
    top_n: int = 3,
) -> tuple[list[TradeProposal], list[ScanCandidate]]:
    watchlist = watchlist or DEFAULT_WATCHLIST
    candidates: list[ScanCandidate] = []

    for symbol, sector in watchlist.items():
        try:
            quote = data_provider.get_quote(symbol)
            analysis = analysis_engine.analyze(symbol)
        except DataProviderError as e:
            candidates.append(ScanCandidate(symbol, Rejection(f"market data unavailable: {e}", [])))
            continue

        outcome = evaluate_trade(
            account=account,
            daily_start_value=daily_start_value,
            symbol=symbol,
            side=OrderSide.BUY,
            asset_class=AssetClass.EQUITY,
            quote=quote,
            analysis=analysis,
            config=config,
            sector=sector,
        )
        candidates.append(ScanCandidate(symbol, outcome))

    proposals = [c.outcome for c in candidates if isinstance(c.outcome, TradeProposal)]
    proposals.sort(key=lambda p: p.confidence or 0, reverse=True)
    return proposals[:top_n], candidates
