"""Shared fixtures for tests/unit/ only (not tests/integration/)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_ibkr_hist_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """todo 122: src/providers/ibkr.py's `_hist_rate_limiter` is a process-wide
    module-level singleton (real time.monotonic() timestamps, real asyncio.sleep()),
    never reset between tests. Any unit test exercising fetch_historical_bars() --
    even fully mocked at the ib_insync layer -- still pays the real 55-req/10-min
    throttle. Once cumulative calls across the pytest session cross that limit, the
    next acquire() blocks for real, up to ~601s, with the event loop idle and zero
    CPU (confirmed via py-spy: reproducible full-suite hang at the same point in
    collection order). No unit test asserts on the limiter's own behavior, so a
    session-wide no-op is a pure test-isolation fix -- production behavior
    (ibkr.py itself) is untouched.
    """
    try:
        from src.providers import ibkr
    except ImportError:
        return

    async def _noop_acquire() -> None:
        return None

    monkeypatch.setattr(ibkr._hist_rate_limiter, "acquire", _noop_acquire)
