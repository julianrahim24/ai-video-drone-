"""
Order submission with idempotency, duplicate-order protection, and
never-assume-success verification.

Rules enforced here, straight from the spec:
  - never place an order while the kill switch is tripped
  - never submit two orders for what is clearly the same intended trade
  - never assume an order succeeded if the broker's response doesn't confirm it
  - before retrying a submission that failed/errored, check whether the
    original attempt actually went through first
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date

from trading.broker.base import Broker, BrokerError
from trading.execution.kill_switch import KillSwitch
from trading.logging_setup import EventLogger
from trading.models import OrderRecord, OrderStatus, TradeProposal, TradingMode

UNRESOLVED_STATUSES = {OrderStatus.UNKNOWN, OrderStatus.SUBMITTED, OrderStatus.PENDING_APPROVAL}


class OrderManager:
    def __init__(self, broker: Broker, kill_switch: KillSwitch, logger: EventLogger, state_dir: str = "logs"):
        self.broker = broker
        self.kill_switch = kill_switch
        self.logger = logger
        os.makedirs(state_dir, exist_ok=True)
        self._fingerprint_path = os.path.join(state_dir, "order_fingerprints.json")
        self._fingerprints: dict[str, str] = self._load_fingerprints()

    def _load_fingerprints(self) -> dict[str, str]:
        if not os.path.exists(self._fingerprint_path):
            return {}
        with open(self._fingerprint_path) as f:
            return json.load(f)

    def _save_fingerprints(self) -> None:
        with open(self._fingerprint_path, "w") as f:
            json.dump(self._fingerprints, f, indent=2)

    @staticmethod
    def _fingerprint(proposal: TradeProposal) -> str:
        return "|".join(
            [
                proposal.symbol,
                proposal.side.value,
                f"{proposal.quantity:g}",
                f"{round(proposal.entry_price, 2):.2f}",
                date.today().isoformat(),
            ]
        )

    def submit(self, proposal: TradeProposal, mode: TradingMode) -> OrderRecord:
        self.kill_switch.check_or_raise()

        fp = self._fingerprint(proposal)
        if fp in self._fingerprints:
            self.kill_switch.trip("duplicate order detected", logger=self.logger)
            self.logger.event(
                "duplicate_order_blocked", proposal_id=proposal.id, fingerprint=fp,
                existing_client_order_id=self._fingerprints[fp],
            )
            raise BrokerError(
                f"a matching order for {proposal.symbol} was already submitted today "
                f"(client_order_id={self._fingerprints[fp]}) - refusing to submit a duplicate"
            )

        client_order_id = str(uuid.uuid4())
        self._fingerprints[fp] = client_order_id
        self._save_fingerprints()

        self.logger.event(
            "order_submitting",
            proposal_id=proposal.id,
            client_order_id=client_order_id,
            symbol=proposal.symbol,
            side=proposal.side.value,
            quantity=proposal.quantity,
            mode=mode.value,
        )

        record = self._place_with_verification(client_order_id, proposal, mode)
        return record

    def _place_with_verification(self, client_order_id: str, proposal: TradeProposal, mode: TradingMode) -> OrderRecord:
        try:
            record = self.broker.place_order(
                client_order_id=client_order_id,
                symbol=proposal.symbol,
                side=proposal.side,
                quantity=proposal.quantity,
                order_type="market",
            )
        except BrokerError as e:
            # Connection may have been lost mid-submission. Never assume it
            # failed - check whether it actually went through before doing
            # anything else.
            self.logger.error(f"order submission raised an error, verifying before giving up: {e}",
                               client_order_id=client_order_id)
            record = self._verify_uncertain_order(client_order_id, proposal, mode, str(e))
            return record

        if record.status in UNRESOLVED_STATUSES:
            record = self._verify_uncertain_order(client_order_id, proposal, mode, "unresolved status after placement")
            return record

        self._log_terminal_status(record, proposal)
        return record

    def _verify_uncertain_order(
        self, client_order_id: str, proposal: TradeProposal, mode: TradingMode, original_error: str
    ) -> OrderRecord:
        try:
            record = self.broker.get_order_status(client_order_id)
        except BrokerError:
            record = None

        if record is None or record.status in UNRESOLVED_STATUSES:
            # Cannot confirm the order one way or the other. Per spec: never
            # assume success or failure, and stop placing new trades.
            self.kill_switch.trip(
                f"order status could not be confirmed for {proposal.symbol} ({original_error})",
                logger=self.logger,
            )
            self.logger.error(
                "order_status_unconfirmed", client_order_id=client_order_id, symbol=proposal.symbol,
                original_error=original_error,
            )
            raise BrokerError(
                f"could not confirm the status of the order for {proposal.symbol} after an error - "
                "kill switch has been activated; check the broker directly before doing anything else"
            )

        self._log_terminal_status(record, proposal)
        return record

    def _log_terminal_status(self, record: OrderRecord, proposal: TradeProposal) -> None:
        if record.status == OrderStatus.FILLED:
            self.logger.event(
                "order_executed", client_order_id=record.client_order_id, proposal_id=proposal.id,
                symbol=record.symbol, side=record.side.value, quantity=record.quantity,
                fill_price=record.fill_price, mode=record.mode.value,
                broker_order_id=record.broker_order_id,
            )
        elif record.status == OrderStatus.FAILED:
            self.logger.event(
                "order_failed", client_order_id=record.client_order_id, proposal_id=proposal.id,
                symbol=record.symbol, notes=record.notes,
            )
        elif record.status == OrderStatus.CANCELLED:
            self.logger.event(
                "order_cancelled", client_order_id=record.client_order_id, proposal_id=proposal.id,
                symbol=record.symbol,
            )
