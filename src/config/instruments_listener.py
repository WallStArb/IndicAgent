"""InstrumentsListener: LISTEN instruments on a dedicated connection and call back on NOTIFY.

The `trg_instruments_notify` trigger (migration 213) fires NOTIFY instruments on every change
to the instruments table. A subscriber passes `invalidate_active_contracts_cache` as the
callback, so a contract change reaches its next `get_active_contracts()` in about a second
instead of at the TTL expiry. Extracted from the v2.x pipeline CacheManager (todo 509), whose
other caches had no live reader.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import asyncpg
import structlog

from src.observability.metrics import gauge

_CHANNEL = "instruments"


class InstrumentsListener:
    """Holds one asyncpg connection for its lifetime and reconnects on failure."""

    def __init__(
        self,
        database_url: str,
        on_change: Callable[[], None],
        *,
        heartbeat_s: float,
        reconnect_backoff_s: float,
    ) -> None:
        """`heartbeat_s` and `reconnect_backoff_s` come from the
        `infra.instruments_listener.*` APR keys (migration 503)."""
        self._database_url = database_url
        self._on_change = on_change
        self._heartbeat_s = heartbeat_s
        self._reconnect_backoff_s = reconnect_backoff_s
        self._connected = gauge(
            "instruments_listener_connected",
            "1 when LISTEN instruments connection is active, 0 when reconnecting",
        )
        self._logger = structlog.get_logger(__name__)

    def start(self) -> asyncio.Task:
        """The listener task; the caller owns its lifecycle (keep a reference, cancel it)."""
        return asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                conn = await asyncpg.connect(self._database_url)
                listening = False
                try:
                    # This connection sits idle waiting for NOTIFY; the DB-wide
                    # idle_session_timeout (1h) would kill it every hour and risk a missed
                    # NOTIFY in the reconnect gap. Exempt just this connection.
                    await conn.execute("SET idle_session_timeout = 0")
                    await conn.add_listener(_CHANNEL, self._on_notify)
                    self._connected.add(1)
                    listening = True
                    # A change made while no connection was listening (startup, the backoff
                    # gap, a DB restart) sent a NOTIFY nobody heard, so every (re)connect
                    # invalidates once.
                    self._on_change()
                    while not conn.is_closed():
                        await asyncio.sleep(self._heartbeat_s)
                finally:
                    # The gauge goes down only if this connection brought it up, so a failed
                    # connect or setup cannot drive it negative.
                    if listening:
                        self._connected.add(-1)
                    # Closing ends the LISTEN. A close that fails on a broken connection
                    # must neither mask the real error nor leak the socket.
                    try:
                        await conn.close()
                    except Exception:
                        conn.terminate()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._logger.warning("instruments_listener.error", error=str(error))
                await asyncio.sleep(self._reconnect_backoff_s)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        # Debug, not info: a bulk instruments update fires one NOTIFY per row.
        self._logger.debug("instruments_listener.instrument_changed", symbol=payload)
        self._on_change()
