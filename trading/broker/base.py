"""
Broker abstraction. Every execution venue (paper, Robinhood crypto, the
agentic equity/option bridge) implements this same interface so the risk
engine, order manager, and CLI never need to know which one they're talking
to. This isolation is deliberate: if Robinhood changes an API, only one
adapter file needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from trading.models import AccountSnapshot, OrderRecord, OrderSide, Quote


class BrokerError(Exception):
    """Raised for any broker failure. Callers must treat this as
    'order status unknown - do not assume success or failure' unless the
    broker explicitly confirmed one or the other."""


class Broker(ABC):
    name: str

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """Must raise BrokerError rather than return a guessed/partial
        snapshot if the account state cannot be verified."""

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        ...

    @abstractmethod
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
        """Must be idempotent on client_order_id: submitting the same
        client_order_id twice must never result in two live orders."""

    @abstractmethod
    def get_order_status(self, client_order_id: str) -> OrderRecord:
        ...

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> OrderRecord:
        ...
