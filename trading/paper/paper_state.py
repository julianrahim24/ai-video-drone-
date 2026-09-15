"""Persisted state for the paper-trading portfolio (JSON file on disk)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date

from trading.models import AccountSnapshot, Position

DEFAULT_STARTING_CASH = 25_000.0


@dataclass
class PaperPortfolioState:
    cash: float = DEFAULT_STARTING_CASH
    positions: dict[str, dict] = field(default_factory=dict)  # symbol -> {quantity, avg_price, sector}
    realized_pnl_total: float = 0.0
    daily_start_value: float = DEFAULT_STARTING_CASH
    daily_pnl_date: str = field(default_factory=lambda: date.today().isoformat())
    inception_cash: float = DEFAULT_STARTING_CASH

    def to_account_snapshot(self, mark_prices: dict[str, float]) -> AccountSnapshot:
        positions = [
            Position(
                symbol=sym,
                quantity=p["quantity"],
                avg_price=p["avg_price"],
                sector=p.get("sector"),
            )
            for sym, p in self.positions.items()
            if p["quantity"] != 0
        ]
        market_value = sum(mark_prices.get(p.symbol, p.avg_price) * p.quantity for p in positions)
        return AccountSnapshot(cash=self.cash, portfolio_value=self.cash + market_value, positions=positions)


class PaperStateStore:
    def __init__(self, state_dir: str = "logs"):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "paper_portfolio.json")
        self.state = self._load()

    def _load(self) -> PaperPortfolioState:
        if not os.path.exists(self.path):
            state = PaperPortfolioState()
            self._save(state)
            return state
        with open(self.path) as f:
            raw = json.load(f)
        state = PaperPortfolioState(**raw)
        today = date.today().isoformat()
        if state.daily_pnl_date != today:
            # New trading day: reset the daily loss-limit reference point.
            state.daily_pnl_date = today
            # daily_start_value gets refreshed to current value by caller (needs mark prices)
        return state

    def _save(self, state: PaperPortfolioState | None = None) -> None:
        state = state or self.state
        with open(self.path, "w") as f:
            json.dump(asdict(state), f, indent=2)

    def save(self) -> None:
        self._save(self.state)

    def refresh_daily_anchor_if_needed(self, current_portfolio_value: float) -> None:
        today = date.today().isoformat()
        if self.state.daily_pnl_date != today or self.state.daily_start_value in (None, 0):
            self.state.daily_pnl_date = today
            self.state.daily_start_value = current_portfolio_value
            self.save()

    def reset(self, starting_cash: float = DEFAULT_STARTING_CASH) -> None:
        self.state = PaperPortfolioState(cash=starting_cash, daily_start_value=starting_cash, inception_cash=starting_cash)
        self.save()
