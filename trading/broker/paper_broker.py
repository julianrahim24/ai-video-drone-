"""
Simulated broker. This is the default and always-available execution venue.
Fills happen immediately at the last known quote (plus a small configurable
slippage) - there is no real order routing, no real money, and no network
dependency on Robinhood at all.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from trading.broker.base import Broker, BrokerError
from trading.data.provider_base import MarketDataProvider
from trading.logging_setup import get_logger
from trading.models import (
    AccountSnapshot,
    OrderRecord,
    OrderSide,
    OrderStatus,
    Quote,
    TradingMode,
)
from trading.paper.paper_state import PaperStateStore

SLIPPAGE_BPS_DEFAULT = 5  # 0.05%, a conservative assumption for liquid names


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, data_provider: MarketDataProvider, state_dir: str = "logs"):
        self.data_provider = data_provider
        self.store = PaperStateStore(state_dir)
        self.log = get_logger(state_dir)
        self._orders: dict[str, OrderRecord] = {}

    def get_account(self) -> AccountSnapshot:
        marks = {}
        for sym in self.store.state.positions:
            try:
                marks[sym] = self.data_provider.get_quote(sym).price
            except Exception:
                marks[sym] = self.store.state.positions[sym]["avg_price"]
        snapshot = self.store.state.to_account_snapshot(marks)
        self.store.refresh_daily_anchor_if_needed(snapshot.portfolio_value)
        return snapshot

    def get_quote(self, symbol: str) -> Quote:
        return self.data_provider.get_quote(symbol)

    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderRecord:
        if client_order_id in self._orders:
            # Idempotent replay: never double-fill a simulated order either,
            # so paper mode exercises the same duplicate-protection discipline
            # as live mode.
            return self._orders[client_order_id]

        quote = self.data_provider.get_quote(symbol)
        slippage = quote.price * (SLIPPAGE_BPS_DEFAULT / 10_000)
        fill_price = quote.price + slippage if side == OrderSide.BUY else quote.price - slippage

        cost = fill_price * quantity
        state = self.store.state
        if side == OrderSide.BUY:
            if cost > state.cash + 1e-6:
                record = OrderRecord(
                    client_order_id=client_order_id,
                    proposal_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    mode=TradingMode.PAPER,
                    status=OrderStatus.FAILED,
                    notes="insufficient simulated cash",
                )
                self._orders[client_order_id] = record
                self.log.event("order_failed", client_order_id=client_order_id, reason="insufficient_cash")
                return record
            existing = state.positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
            new_qty = existing["quantity"] + quantity
            new_avg = (
                (existing["quantity"] * existing["avg_price"] + quantity * fill_price) / new_qty
                if new_qty
                else fill_price
            )
            state.positions[symbol] = {"quantity": new_qty, "avg_price": new_avg, "sector": existing.get("sector")}
            state.cash -= cost
        else:
            existing = state.positions.get(symbol)
            if not existing or existing["quantity"] < quantity - 1e-9:
                record = OrderRecord(
                    client_order_id=client_order_id,
                    proposal_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    mode=TradingMode.PAPER,
                    status=OrderStatus.FAILED,
                    notes="insufficient simulated position to sell",
                )
                self._orders[client_order_id] = record
                self.log.event("order_failed", client_order_id=client_order_id, reason="insufficient_position")
                return record
            realized = (fill_price - existing["avg_price"]) * quantity
            state.realized_pnl_total += realized
            existing["quantity"] -= quantity
            state.cash += cost
            if existing["quantity"] <= 1e-9:
                del state.positions[symbol]
            else:
                state.positions[symbol] = existing

        self.store.save()
        record = OrderRecord(
            client_order_id=client_order_id,
            proposal_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            mode=TradingMode.PAPER,
            status=OrderStatus.FILLED,
            broker_order_id=f"paper-{uuid.uuid4()}",
            fill_price=fill_price,
        )
        self._orders[client_order_id] = record
        self.log.event(
            "order_filled",
            client_order_id=client_order_id,
            symbol=symbol,
            side=side.value,
            quantity=quantity,
            fill_price=fill_price,
            mode="PAPER",
        )
        return record

    def get_order_status(self, client_order_id: str) -> OrderRecord:
        record = self._orders.get(client_order_id)
        if record is None:
            raise BrokerError(f"unknown paper order {client_order_id}")
        return record

    def cancel_order(self, client_order_id: str) -> OrderRecord:
        record = self._orders.get(client_order_id)
        if record is None:
            raise BrokerError(f"unknown paper order {client_order_id}")
        if record.status == OrderStatus.FILLED:
            raise BrokerError("cannot cancel an already-filled paper order")
        record.status = OrderStatus.CANCELLED
        record.updated_at = datetime.now(timezone.utc)
        return record
