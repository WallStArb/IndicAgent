"""RateLimiter — token bucket rate limiting for LLM providers.

Tracks RPM (requests/minute) and TPM (tokens/minute) with asyncio.sleep backoff.
"""
from __future__ import annotations

import asyncio
import time

import structlog

logger = structlog.get_logger(__name__)

_MIN_BACKOFF_S = 0.1
_MAX_BACKOFF_S = 30.0


class RateLimiter:
    """Per-provider token bucket rate limiter."""

    def __init__(self, rpm: int, tpm: int) -> None:
        self._rpm = rpm
        self._tpm = tpm
        # Sliding window: list of (monotonic_ts, tokens)
        self._requests: list[float] = []
        self._tokens: list[tuple[float, int]] = []

    def _prune(self, window_s: float = 60.0) -> None:
        cutoff = time.monotonic() - window_s
        self._requests = [t for t in self._requests if t > cutoff]
        self._tokens = [(t, n) for t, n in self._tokens if t > cutoff]

    def _requests_in_window(self) -> int:
        return len(self._requests)

    def _tokens_in_window(self) -> int:
        return sum(n for _, n in self._tokens)

    async def acquire(self, tokens: int) -> None:
        """Wait until rate limits allow this request, then record it."""
        backoff = _MIN_BACKOFF_S
        while True:
            self._prune()
            if self._requests_in_window() < self._rpm and self._tokens_in_window() + tokens <= self._tpm:
                now = time.monotonic()
                self._requests.append(now)
                self._tokens.append((now, tokens))
                return
            logger.debug("rate_limiter.waiting", backoff_s=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_S)
