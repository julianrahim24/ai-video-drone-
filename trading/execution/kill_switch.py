"""
Master kill switch.

Once tripped, NO new order (paper or live) may be submitted until a human
explicitly resets it with the exact confirmation phrase. State is persisted
to disk so a trip survives a process restart - a crash or restart must never
silently clear an active kill switch.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

RESET_CONFIRMATION_PHRASE = "I UNDERSTAND THE RISK"


class KillSwitchActive(Exception):
    def __init__(self, reason: str, tripped_at: str):
        super().__init__(f"kill switch is active ({reason}, tripped at {tripped_at}) - no new orders can be placed")
        self.reason = reason
        self.tripped_at = tripped_at


@dataclass
class KillSwitchState:
    tripped: bool = False
    reason: str | None = None
    tripped_at: str | None = None


class KillSwitch:
    def __init__(self, state_dir: str = "logs"):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "kill_switch.json")
        self.state = self._load()

    def _load(self) -> KillSwitchState:
        if not os.path.exists(self.path):
            return KillSwitchState()
        with open(self.path) as f:
            return KillSwitchState(**json.load(f))

    def _save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    def trip(self, reason: str, logger=None) -> None:
        self.state = KillSwitchState(
            tripped=True, reason=reason, tripped_at=datetime.now(timezone.utc).isoformat()
        )
        self._save()
        if logger:
            logger.event("kill_switch_tripped", reason=reason)

    def check_or_raise(self) -> None:
        if self.state.tripped:
            raise KillSwitchActive(self.state.reason or "unknown", self.state.tripped_at or "unknown")

    def is_tripped(self) -> bool:
        return self.state.tripped

    def reset(self, confirmation_phrase: str, logger=None) -> bool:
        if confirmation_phrase != RESET_CONFIRMATION_PHRASE:
            return False
        previous_reason = self.state.reason
        self.state = KillSwitchState()
        self._save()
        if logger:
            logger.event("kill_switch_reset", previous_reason=previous_reason)
        return True
