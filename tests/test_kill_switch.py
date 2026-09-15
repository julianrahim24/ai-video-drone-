import pytest

from trading.execution.kill_switch import RESET_CONFIRMATION_PHRASE, KillSwitch, KillSwitchActive


def test_starts_clear(tmp_path):
    ks = KillSwitch(str(tmp_path))
    assert not ks.is_tripped()
    ks.check_or_raise()  # should not raise


def test_trip_blocks_new_orders(tmp_path):
    ks = KillSwitch(str(tmp_path))
    ks.trip("daily loss limit reached")
    assert ks.is_tripped()
    with pytest.raises(KillSwitchActive):
        ks.check_or_raise()


def test_reset_requires_exact_phrase(tmp_path):
    ks = KillSwitch(str(tmp_path))
    ks.trip("test")
    assert ks.reset("close enough") is False
    assert ks.is_tripped() is True
    assert ks.reset(RESET_CONFIRMATION_PHRASE) is True
    assert ks.is_tripped() is False


def test_trip_persists_across_process_restart(tmp_path):
    ks1 = KillSwitch(str(tmp_path))
    ks1.trip("stale market data")
    ks2 = KillSwitch(str(tmp_path))  # simulates a fresh process reading the same state dir
    assert ks2.is_tripped()
    assert ks2.state.reason == "stale market data"
