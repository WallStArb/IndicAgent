"""InstrumentsListener (todo 509, extracted from the v2.x CacheManager)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.instruments_listener import InstrumentsListener


def _listener(on_change=None) -> InstrumentsListener:
    return InstrumentsListener(
        "postgresql://unused", on_change or MagicMock(), heartbeat_s=1, reconnect_backoff_s=1
    )


def test_notify_calls_the_callback_once():
    on_change = MagicMock()
    _listener(on_change)._on_notify(None, 0, "instruments", "SPY")
    on_change.assert_called_once_with()


@pytest.mark.asyncio
async def test_a_failed_connect_backs_off_and_retries():
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    listener = InstrumentsListener(
        "postgresql://unused", MagicMock(), heartbeat_s=10, reconnect_backoff_s=7
    )
    with (
        patch("src.config.instruments_listener.asyncpg.connect", side_effect=OSError("down")),
        patch("src.config.instruments_listener.asyncio.sleep", side_effect=fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await listener._run()
    assert sleeps == [7, 7]


@pytest.mark.asyncio
async def test_the_gauge_returns_to_zero_after_a_failed_connect_and_a_closed_connection():
    """A failed connect never raised the gauge, so it must not lower it; a connection that
    listened and then closed lowers it once."""
    calls = {"n": 0}
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.add_listener = AsyncMock()
    conn.remove_listener = AsyncMock()
    conn.close = AsyncMock()
    conn.is_closed = MagicMock(side_effect=[False, True, True])

    async def fake_connect(_url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("down")
        if calls["n"] == 2:
            return conn
        raise asyncio.CancelledError

    async def no_sleep(_seconds):
        return None

    listener = _listener()
    listener._connected = MagicMock()
    with (
        patch("src.config.instruments_listener.asyncpg.connect", side_effect=fake_connect),
        patch("src.config.instruments_listener.asyncio.sleep", side_effect=no_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await listener._run()
    deltas = [c.args[0] for c in listener._connected.add.call_args_list]
    assert deltas == [1, -1]
    listener._on_change.assert_called_once_with()  # the reconnect invalidated once
    conn.remove_listener.assert_not_called()
