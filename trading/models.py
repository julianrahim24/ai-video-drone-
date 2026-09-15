"""Shared data structures used across the trading system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"


class OrderStatus(str, Enum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUEUED_FOR_AGENT = "queued_for_agent"   # equities/options live: waiting on MCP-connected agent
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"                     # could not verify - treated as unsafe, never assumed filled


@dataclass
class Quote:
    symbol: str
    price: float
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[float]
    as_of: datetime
    source: str

    def age_seconds(self) -> float:
        return (utcnow() - self.as_of).total_seconds()


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_price: float
    asset_class: AssetClass = AssetClass.EQUITY
    sector: Optional[str] = None

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_price


@dataclass
class AccountSnapshot:
    cash: float
    portfolio_value: float
    positions: list[Position] = field(default_factory=list)
    as_of: datetime = field(default_factory=utcnow)

    def position_for(self, symbol: str) -> Optional[Position]:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    def exposure_value(self) -> float:
        return sum(p.quantity * p.avg_price for p in self.positions)


@dataclass
class TradeProposal:
    """A fully-specified, not-yet-approved trade, produced by the risk engine."""
    id: str
    symbol: str
    side: OrderSide
    asset_class: AssetClass
    quantity: float
    entry_price: float
    stop_loss: float
    target_price: Optional[float]
    estimated_order_value: float
    portfolio_pct_after: float
    max_dollar_loss: float
    risk_pct_of_portfolio: float
    reason: str
    risk_level: int
    confidence: Optional[int]
    upside_estimate: Optional[float]
    downside_estimate: Optional[float]
    major_risks: list[str]
    created_at: datetime = field(default_factory=utcnow)
    status: OrderStatus = OrderStatus.PROPOSED


@dataclass
class OrderRecord:
    """Persisted record of what happened to a proposal, for idempotency and audit."""
    client_order_id: str          # our own UUID, used as idempotency key with the broker
    proposal_id: str
    symbol: str
    side: OrderSide
    quantity: float
    mode: TradingMode
    status: OrderStatus
    broker_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    notes: str = ""
