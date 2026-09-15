"""
Heuristic, rule-based analysis engine.

IMPORTANT: nothing here predicts future price movement. Every indicator is a
description of the past. The "confidence" score is a bounded (0-100) measure
of how many independent, generally-followed heuristics currently agree with
each other for this symbol - not a probability of profit. Treat low
confidence and "unknown" trend/volatility as reasons to skip a trade, not as
neutral inputs to force a signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from trading.analysis import indicators as ind
from trading.data.provider_base import DataProviderError, MarketDataProvider

BENCHMARK_SYMBOL = "SPY"


@dataclass
class AnalysisResult:
    symbol: str
    signal: str                 # "BUY", "SELL", "NO_TRADE"
    confidence: int              # 0-100
    risk_label: str              # "Low", "Moderate", "High"
    entry_price: float
    stop_loss: float
    target_price: float
    atr_value: float
    annualized_volatility: float | None
    avg_dollar_volume: float | None
    trend: str
    market_trend: str
    rsi_value: float | None
    relative_strength_value: float | None
    support: float | None
    resistance: float | None
    days_to_earnings: int | None
    reasons: list[str]
    warnings: list[str]


class AnalysisEngine:
    def __init__(self, data_provider: MarketDataProvider, stop_atr_multiple: float = 2.0,
                 reward_risk_ratio: float = 2.0):
        self.data_provider = data_provider
        self.stop_atr_multiple = stop_atr_multiple
        self.reward_risk_ratio = reward_risk_ratio

    def analyze(self, symbol: str, earnings_date: date | None = None) -> AnalysisResult:
        bars = self.data_provider.get_daily_bars(symbol, lookback_days=260)
        if len(bars) < 60:
            raise DataProviderError(f"not enough price history for {symbol} to analyze safely")
        vals = ind.closes(bars)

        try:
            bench_bars = self.data_provider.get_daily_bars(BENCHMARK_SYMBOL, lookback_days=260)
            bench_vals = ind.closes(bench_bars)
            market_trend = ind.trend_direction(bench_vals)
            rel_strength = ind.relative_strength(vals, bench_vals, period=60)
        except DataProviderError:
            market_trend = "unknown"
            rel_strength = None

        trend = ind.trend_direction(vals)
        rsi_value = ind.rsi(vals, 14)
        vol = ind.annualized_volatility(vals, 20)
        atr_value = ind.atr(bars, 14) or (vals[-1] * 0.02)
        avg_vol = ind.avg_volume(bars, 20)
        avg_dollar_volume = (avg_vol * vals[-1]) if avg_vol else None
        sr = ind.support_resistance(bars, 40)
        support, resistance = sr if sr else (None, None)
        current_price = vals[-1]

        days_to_earnings = None
        if earnings_date is not None:
            days_to_earnings = (earnings_date - datetime.now(timezone.utc).date()).days

        reasons: list[str] = []
        warnings: list[str] = []
        score = 0

        if trend == "up":
            score += 25
            reasons.append("20-day SMA above 50-day SMA (uptrend)")
        elif trend == "down":
            score -= 25
            reasons.append("20-day SMA below 50-day SMA (downtrend)")
        else:
            warnings.append("trend is flat/unclear")

        if rsi_value is not None:
            if 45 <= rsi_value <= 65:
                score += 15
                reasons.append(f"RSI {rsi_value:.0f} in healthy range")
            elif rsi_value > 75:
                score -= 15
                warnings.append(f"RSI {rsi_value:.0f} is overbought")
            elif rsi_value < 25:
                warnings.append(f"RSI {rsi_value:.0f} is oversold - possible reversal risk either direction")

        if rel_strength is not None:
            if rel_strength > 0.02:
                score += 15
                reasons.append("outperforming the market over the last ~60 sessions")
            elif rel_strength < -0.02:
                score -= 15
                warnings.append("underperforming the market over the last ~60 sessions")

        if market_trend == "up":
            score += 10
            reasons.append("broad market (SPY) is in an uptrend")
        elif market_trend == "down":
            score -= 20
            warnings.append("broad market (SPY) is in a downtrend - a headwind for long trades")

        if avg_vol is not None:
            if avg_vol > 500_000:
                score += 10
            elif avg_vol < 100_000:
                score -= 20
                warnings.append("low average volume - liquidity risk")

        if vol is not None:
            if vol < 0.30:
                score += 10
            elif vol > 0.70:
                score -= 15
                warnings.append(f"high annualized volatility ({vol:.0%})")

        if support is not None and resistance is not None:
            band = resistance - support
            if band > 0:
                pos_in_band = (current_price - support) / band
                if pos_in_band < 0.35:
                    score += 10
                    reasons.append("price near recent support")
                elif pos_in_band > 0.90:
                    score -= 10
                    warnings.append("price near recent resistance")

        if days_to_earnings is not None and 0 <= days_to_earnings <= 2:
            score -= 30
            warnings.append(f"earnings in {days_to_earnings} day(s) - event risk")

        confidence = max(0, min(100, 50 + score))

        if vol is not None and vol > 0.9:
            risk_label = "High"
        elif vol is not None and vol > 0.5:
            risk_label = "Moderate"
        else:
            risk_label = "Low"

        if confidence >= 65 and trend == "up" and (rel_strength is None or rel_strength > -0.02):
            signal = "BUY"
        else:
            signal = "NO_TRADE"
            if confidence < 65:
                warnings.append(f"confidence {confidence}/100 below the 65 threshold required to trade")

        stop_loss = round(current_price - self.stop_atr_multiple * atr_value, 2)
        risk_per_share = current_price - stop_loss
        target_price = round(current_price + self.reward_risk_ratio * risk_per_share, 2)

        return AnalysisResult(
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            risk_label=risk_label,
            entry_price=round(current_price, 2),
            stop_loss=stop_loss,
            target_price=target_price,
            atr_value=round(atr_value, 4),
            annualized_volatility=vol,
            avg_dollar_volume=avg_dollar_volume,
            trend=trend,
            market_trend=market_trend,
            rsi_value=rsi_value,
            relative_strength_value=rel_strength,
            support=support,
            resistance=resistance,
            days_to_earnings=days_to_earnings,
            reasons=reasons,
            warnings=warnings,
        )
