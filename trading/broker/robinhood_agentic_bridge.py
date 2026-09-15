"""
Live EQUITY/OPTION execution bridge.

WHY THIS FILE EXISTS: Robinhood has no standalone, documented REST API for
placing stock/option orders (confirmed by research before writing this
module - see README "API research" section). The only officially-sanctioned
programmatic path is Robinhood Agentic Trading, which runs over MCP and
requires an MCP-capable agent session (Claude Code, Claude Desktop, ChatGPT)
connected with the user's own Robinhood-authorized permission. There is no
documented way for an unattended background script to authenticate to it on
its own, and this app will not attempt an unofficial workaround.

This class does NOT place real orders itself. It hands a fully risk-checked,
already-approved order to a JSON file queue and clearly reports that. A
human running this app inside an MCP-connected agent session (this
project's own Claude Code session, for example) is expected to read
logs/agentic_bridge/pending_orders.jsonl, place each order with the real
Robinhood MCP tools (review_equity_order/place_equity_order or
review_option_order/place_option_order), and write the result back to
logs/agentic_bridge/order_results.json keyed by client_order_id, e.g.:

    {"<client_order_id>": {"status": "filled", "broker_order_id": "...",
                            "fill_price": 123.45}}

get_account()/get_quote() likewise depend on a snapshot the agent session
writes to logs/agentic_bridge/account_snapshot.json - this bridge refuses to
guess at real account values and raises BrokerError with exact instructions
if that file is missing or stale, rather than fabricate a balance.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from trading.broker.base import Broker, BrokerError
from trading.models import AccountSnapshot, OrderRecord, OrderSide, OrderStatus, Position, Quote, TradingMode

SNAPSHOT_MAX_AGE = timedelta(minutes=5)


class RobinhoodAgenticBridgeBroker(Broker):
    name = "robinhood_agentic_bridge"

    def __init__(self, state_dir: str = "logs"):
        self.dir = os.path.join(state_dir, "agentic_bridge")
        os.makedirs(self.dir, exist_ok=True)
        self.snapshot_path = os.path.join(self.dir, "account_snapshot.json")
        self.pending_path = os.path.join(self.dir, "pending_orders.jsonl")
        self.results_path = os.path.join(self.dir, "order_results.json")

    def _instructions(self) -> str:
        return (
            "Live equity/option trading requires an MCP-connected agent session "
            "(e.g. this project opened in Claude Code/Desktop with the Robinhood "
            "connector enabled) to read the queue and execute via the official "
            "Robinhood Agentic Trading tools. See trading/broker/robinhood_agentic_bridge.py "
            "for the exact file protocol."
        )

    def get_account(self) -> AccountSnapshot:
        if not os.path.exists(self.snapshot_path):
            raise BrokerError(f"no account snapshot available yet. {self._instructions()}")
        with open(self.snapshot_path) as f:
            data = json.load(f)
        as_of = datetime.fromisoformat(data["as_of"])
        if datetime.now(timezone.utc) - as_of > SNAPSHOT_MAX_AGE:
            raise BrokerError(
                f"account snapshot is stale ({as_of.isoformat()}) - refusing to size a live trade "
                f"against outdated balances. {self._instructions()}"
            )
        positions = [Position(**p) for p in data.get("positions", [])]
        return AccountSnapshot(cash=data["cash"], portfolio_value=data["portfolio_value"], positions=positions, as_of=as_of)

    def get_quote(self, symbol: str) -> Quote:
        raise BrokerError(
            "the agentic bridge does not fetch its own quotes - equity/option analysis uses the "
            "configured market data provider; only order execution goes through the agent bridge."
        )

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
        entry = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side.value,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.pending_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return OrderRecord(
            client_order_id=client_order_id,
            proposal_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            mode=TradingMode.LIVE,
            status=OrderStatus.QUEUED_FOR_AGENT,
            notes=self._instructions(),
        )

    def get_order_status(self, client_order_id: str) -> OrderRecord:
        results = {}
        if os.path.exists(self.results_path):
            with open(self.results_path) as f:
                results = json.load(f)
        result = results.get(client_order_id)
        if result is None:
            return OrderRecord(
                client_order_id=client_order_id, proposal_id=client_order_id, symbol="", side=OrderSide.BUY,
                quantity=0, mode=TradingMode.LIVE, status=OrderStatus.QUEUED_FOR_AGENT,
                notes="not yet executed by an agent session",
            )
        status = OrderStatus(result.get("status", "unknown"))
        return OrderRecord(
            client_order_id=client_order_id, proposal_id=client_order_id,
            symbol=result.get("symbol", ""), side=OrderSide(result.get("side", "buy")),
            quantity=result.get("quantity", 0), mode=TradingMode.LIVE, status=status,
            broker_order_id=result.get("broker_order_id"), fill_price=result.get("fill_price"),
        )

    def cancel_order(self, client_order_id: str) -> OrderRecord:
        raise BrokerError(
            "cancelling a queued equity/option order must be done by the agent session that will "
            "execute it - remove it from pending_orders.jsonl before it is picked up, or cancel "
            "directly in Robinhood if it was already placed."
        )
