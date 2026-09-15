"""
Structured, append-only logging for every trading-relevant event.

Every proposed / approved / rejected / executed / cancelled / failed order,
every portfolio and risk calculation, and every error is written as one JSON
line to logs/trading_events.jsonl, plus a human-readable line to
logs/trading.log. Both include a UTC timestamp. Order-related events include
the order id so an order's full lifecycle can be reconstructed later.

Never log secrets: callers must not pass API keys/tokens into `data`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

_SENSITIVE_KEY_FRAGMENTS = ("key", "secret", "token", "password", "signature")


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for k, v in data.items():
        if any(frag in k.lower() for frag in _SENSITIVE_KEY_FRAGMENTS):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


class EventLogger:
    def __init__(self, state_dir: str = "logs"):
        os.makedirs(state_dir, exist_ok=True)
        self.jsonl_path = os.path.join(state_dir, "trading_events.jsonl")
        self.text_path = os.path.join(state_dir, "trading.log")

        self._logger = logging.getLogger("trading")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.FileHandler(self.text_path)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self._logger.addHandler(handler)
            stream = logging.StreamHandler()
            stream.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(stream)

    def event(self, event_type: str, **data: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **_redact(data),
        }
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self._logger.info("[%s] %s", event_type, json.dumps(_redact(data), default=str))

    def error(self, message: str, **data: Any) -> None:
        self.event("error", message=message, **data)


_default_logger: EventLogger | None = None


def get_logger(state_dir: str = "logs") -> EventLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = EventLogger(state_dir)
    return _default_logger
