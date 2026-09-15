"""Stop-loss distance calculation. Risk level controls how many ATRs of
room a stop gets - tighter for conservative levels, wider for aggressive
ones, since a stop that's too tight for the level just gets stopped out by
noise, and one that's too wide breaks the level's max-loss promise."""
from __future__ import annotations

from trading.config import RiskLevelProfile
from trading.models import OrderSide


def compute_stop_loss(entry_price: float, atr_value: float, side: OrderSide, profile: RiskLevelProfile) -> float:
    distance = atr_value * profile.stop_loss_atr_multiple
    if side == OrderSide.BUY:
        return round(max(entry_price - distance, 0.01), 2)
    return round(entry_price + distance, 2)


def risk_per_share(entry_price: float, stop_loss: float, side: OrderSide) -> float:
    diff = (entry_price - stop_loss) if side == OrderSide.BUY else (stop_loss - entry_price)
    return max(diff, 0.0)
