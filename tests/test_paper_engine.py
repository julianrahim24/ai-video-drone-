from trading.broker.base import BrokerError
from trading.broker.paper_broker import PaperBroker
from trading.data.synthetic_provider import SyntheticDataProvider
from trading.models import OrderSide, OrderStatus


def make_broker(tmp_path, base_prices=None):
    provider = SyntheticDataProvider(base_prices=base_prices or {"AAPL": 100.0})
    return PaperBroker(provider, str(tmp_path))


def test_buy_updates_cash_and_position(tmp_path):
    broker = make_broker(tmp_path)
    account_before = broker.get_account()
    record = broker.place_order("order-1", "AAPL", OrderSide.BUY, 10, "market")
    assert record.status == OrderStatus.FILLED
    account_after = broker.get_account()
    assert account_after.cash < account_before.cash
    position = account_after.position_for("AAPL")
    assert position is not None
    assert position.quantity == 10


def test_sell_realizes_pnl(tmp_path):
    broker = make_broker(tmp_path)
    broker.place_order("buy-1", "AAPL", OrderSide.BUY, 10, "market")
    record = broker.place_order("sell-1", "AAPL", OrderSide.SELL, 10, "market")
    assert record.status == OrderStatus.FILLED
    account = broker.get_account()
    assert account.position_for("AAPL") is None


def test_cannot_sell_more_than_held(tmp_path):
    broker = make_broker(tmp_path)
    broker.place_order("buy-1", "AAPL", OrderSide.BUY, 5, "market")
    record = broker.place_order("sell-1", "AAPL", OrderSide.SELL, 999, "market")
    assert record.status == OrderStatus.FAILED


def test_insufficient_cash_fails_safely(tmp_path):
    broker = make_broker(tmp_path)
    record = broker.place_order("buy-huge", "AAPL", OrderSide.BUY, 10_000_000, "market")
    assert record.status == OrderStatus.FAILED
    account = broker.get_account()
    assert account.position_for("AAPL") is None


def test_duplicate_client_order_id_does_not_double_fill(tmp_path):
    broker = make_broker(tmp_path)
    r1 = broker.place_order("same-id", "AAPL", OrderSide.BUY, 10, "market")
    r2 = broker.place_order("same-id", "AAPL", OrderSide.BUY, 10, "market")
    assert r1 is r2
    account = broker.get_account()
    assert account.position_for("AAPL").quantity == 10  # not 20


def test_unknown_order_status_raises(tmp_path):
    broker = make_broker(tmp_path)
    try:
        broker.get_order_status("never-placed")
        assert False, "expected BrokerError"
    except BrokerError:
        pass
