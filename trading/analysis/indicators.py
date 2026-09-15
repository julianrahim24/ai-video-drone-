"""Plain-Python technical indicators over a list of daily bars
({date, open, high, low, close, volume}, oldest first). No indicator here
is predictive on its own - see analysis/engine.py for how they're combined
into a bounded confidence score, never a guarantee."""
from __future__ import annotations

import statistics


def closes(bars: list[dict]) -> list[float]:
    return [b["close"] for b in bars]


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def daily_returns(values: list[float]) -> list[float]:
    return [(values[i] / values[i - 1]) - 1 for i in range(1, len(values))]


def annualized_volatility(values: list[float], period: int = 20) -> float | None:
    rets = daily_returns(values[-(period + 1):])
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * (252 ** 0.5)


def atr(bars: list[dict], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        high, low, prev_close = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs) / period


def relative_strength(symbol_values: list[float], benchmark_values: list[float], period: int = 60) -> float | None:
    """Symbol's total return minus benchmark's total return over `period` bars."""
    if len(symbol_values) < period + 1 or len(benchmark_values) < period + 1:
        return None
    sym_ret = symbol_values[-1] / symbol_values[-period - 1] - 1
    bench_ret = benchmark_values[-1] / benchmark_values[-period - 1] - 1
    return sym_ret - bench_ret


def avg_volume(bars: list[dict], period: int = 20) -> float | None:
    if len(bars) < period:
        return None
    recent = bars[-period:]
    return sum(b["volume"] for b in recent) / period


def support_resistance(bars: list[dict], period: int = 40) -> tuple[float, float] | None:
    if len(bars) < period:
        return None
    recent = bars[-period:]
    return (min(b["low"] for b in recent), max(b["high"] for b in recent))


def trend_direction(values: list[float]) -> str:
    """'up' / 'down' / 'flat' based on 20 vs 50 SMA, or 'unknown' if too little history."""
    s20, s50 = sma(values, 20), sma(values, 50)
    if s20 is None or s50 is None:
        return "unknown"
    if s20 > s50 * 1.005:
        return "up"
    if s20 < s50 * 0.995:
        return "down"
    return "flat"
