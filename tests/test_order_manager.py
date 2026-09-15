import uuid

import pytest

from trading.broker.base import Broker, BrokerError
from trading.execution.kill_switch import KillSwitch, KillSwitchActive
from trading.execution.order_manager import OrderManager
from trading.logging_setup import EventLogger
from trading.models import AssetClass, OrderRecord, OrderSide, OrderStatus, TradeProposal, TradingMode


class FakeBroker(Broker):
    name = "fake"

    def __init__(self):
        self.place_order_calls = []
        self.place_order_responses = []  # list of OrderRecord or Exception, consumed in order
        self.get_order_status_default = None  # OrderRecord or Exception, returned for ANY id if set

    def get_account(self):
        raise NotImplementedError

    def get_quote(self, symbol):
        raise NotImplementedError

    def place_order(self, client_order_id, symbol, side, quantity, order_type, limit_price=None, stop_price=None):
        self.place_order_calls.append(client_order_id)
        behavior = self.place_order_responses.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    def get_order_status(self, client_order_id):
        if self.get_order_status_default is not None:
            if isinstance(self.get_order_status_default, Exception):
                raise self.get_order_status_default
            return self.get_order_status_default
        raise BrokerError(f"unknown order {client_order_id}")

    def cancel_order(self, client_order_id):
        raise NotImplementedError


def make_proposal(symbol="AAPL", quantity=10, entry_price=100.0) -> TradeProposal:
    return TradeProposal(
        id=str(uuid.uuid4()), symbol=symbol, side=OrderSide.BUY, asset_class=AssetClass.EQUITY,
        quantity=quantity, entry_price=entry_price, stop_loss=95.0, target_price=110.0,
        estimated_order_value=quantity * entry_price, portfolio_pct_after=0.1, max_dollar_loss=50.0,
        risk_pct_of_portfolio=0.02, reason="test", risk_level=5, confidence=80,
        upside_estimate=100.0, downside_estimate=50.0, major_risks=[],
    )


def make_manager(tmp_path):
    broker = FakeBroker()
    kill_switch = KillSwitch(str(tmp_path))
    logger = EventLogger(str(tmp_path))
    om = OrderManager(broker, kill_switch, logger, str(tmp_path))
    return om, broker, kill_switch


def filled_record(proposal, client_order_id="x") -> OrderRecord:
    return OrderRecord(
        client_order_id=client_order_id, proposal_id=proposal.id, symbol=proposal.symbol, side=proposal.side,
        quantity=proposal.quantity, mode=TradingMode.PAPER, status=OrderStatus.FILLED, fill_price=proposal.entry_price,
    )


def test_successful_submit_fills(tmp_path):
    om, broker, _ = make_manager(tmp_path)
    proposal = make_proposal()
    broker.place_order_responses = [filled_record(proposal)]
    record = om.submit(proposal, TradingMode.PAPER)
    assert record.status == OrderStatus.FILLED
    assert len(broker.place_order_calls) == 1


def test_duplicate_order_is_blocked_and_trips_kill_switch(tmp_path):
    om, broker, kill_switch = make_manager(tmp_path)
    proposal = make_proposal()
    broker.place_order_responses = [filled_record(proposal)]
    om.submit(proposal, TradingMode.PAPER)

    duplicate = make_proposal()  # same symbol/side/qty/price -> same fingerprint, same day
    with pytest.raises(BrokerError, match="duplicate"):
        om.submit(duplicate, TradingMode.PAPER)
    assert kill_switch.is_tripped()
    assert len(broker.place_order_calls) == 1  # never reached the broker a second time


def test_submit_refused_when_kill_switch_already_tripped(tmp_path):
    om, broker, kill_switch = make_manager(tmp_path)
    kill_switch.trip("previous failure")
    with pytest.raises(KillSwitchActive):
        om.submit(make_proposal(), TradingMode.PAPER)
    assert broker.place_order_calls == []


def test_unconfirmable_order_trips_kill_switch_and_never_assumes_success(tmp_path):
    om, broker, kill_switch = make_manager(tmp_path)
    proposal = make_proposal()
    broker.place_order_responses = [BrokerError("connection reset mid-submission")]
    # get_order_status_default left None -> raises BrokerError("unknown ...") -> unconfirmable
    with pytest.raises(BrokerError, match="could not confirm"):
        om.submit(proposal, TradingMode.LIVE)
    assert kill_switch.is_tripped()


def test_checks_actual_execution_before_treating_a_transient_error_as_failure(tmp_path):
    om, broker, kill_switch = make_manager(tmp_path)
    proposal = make_proposal()
    broker.place_order_responses = [BrokerError("connection reset mid-submission")]
    broker.get_order_status_default = filled_record(proposal, client_order_id="already-executed")
    record = om.submit(proposal, TradingMode.LIVE)
    assert record.status == OrderStatus.FILLED
    assert not kill_switch.is_tripped()
