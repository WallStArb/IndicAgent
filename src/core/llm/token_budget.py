"""TokenBudget — daily token spend tracking per call_type + provider.

Resets at UTC midnight. Exceeding the daily limit falls back to Ollama-only.
"""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)


class TokenBudget:
    """Track daily token spend; expose exceeded() for fallback routing."""

    def __init__(self, daily_token_limit: int, cost_per_1k: float = 0.0) -> None:
        self._limit = daily_token_limit
        self._cost_per_1k = cost_per_1k
        self._day: str = datetime.now(UTC).strftime("%Y-%m-%d")
        self._tokens: int = 0
        self._by_type: dict[str, int] = {}

    def _check_rollover(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self._tokens = 0
            self._by_type = {}

    def record(self, call_type: str, provider: str, tokens: int) -> None:
        self._check_rollover()
        self._tokens += tokens
        self._by_type[call_type] = self._by_type.get(call_type, 0) + tokens
        logger.debug(
            "token_budget.recorded",
            call_type=call_type,
            provider=provider,
            tokens=tokens,
            total_today=self._tokens,
        )

    def is_exceeded(self) -> bool:
        self._check_rollover()
        return self._tokens > self._limit

    def total_tokens_today(self) -> int:
        self._check_rollover()
        return self._tokens

    def estimated_cost_today(self) -> float:
        return (self._tokens / 1000.0) * self._cost_per_1k
