"""IBKRAdapter — DataProviderAdapter implementation wrapping IBKRProvider.

Encapsulates all IBKR-specific logic (official bar streaming,
provider_meta['ibkr'] key lookup) so that BaseProvider only
sees the provider-agnostic DataProviderAdapter interface.

Swapping IBKR for another broker = one new adapter file. Everything downstream
(MergerAgent, FeatureComputeAgent, etc.) is untouched.

Phase 54-02 — Provider Abstraction Layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from src.core.bar_normalizer import SOURCE_IBKR_GENERIC, SOURCE_IBKR_NAMED
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage, SessionType
from src.observability.metrics import PROVIDER_BARS_DROPPED_TOTAL
from src.providers.base import OHLCVBar
from src.providers.ibkr import IBKRProvider

# Map Instrument.session_id → SessionType for bar emission.
# session_id is the trading calendar identifier; SessionType is the bar-level
# session classification used downstream by the feature pipeline.
_SESSION_ID_TO_TYPE: dict[str, SessionType] = {
    "fx_24_5": SessionType.FX,
    "nyse": SessionType.RTH,
    "futures_24_5": SessionType.RTH,
}

_DEFAULT_SESSION_TYPE = SessionType.RTH

logger = logging.getLogger(__name__)


class IBKRAdapter:
    """DataProviderAdapter that wraps IBKRProvider and produces BarMessage directly.

    Uses IBKR's keepUpToDate official bars as the primary live bar source.

    provider_name = 'ibkr' — matches the key used in provider_meta lookups,
    topic keys, and Prometheus metric labels.
    """

    provider_name: str = "ibkr"

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._provider = IBKRProvider(host=host, port=port, client_id=client_id)

        # Dedup guard: last emitted bar timestamp per symbol.
        # Bars are monotonically non-decreasing — keep only the most recent.
        self._last_emitted_ts: dict[str, datetime] = {}

        # Pre-cached attribute dicts for drop counters
        self._m_dropped_queue_full_attrs = {
            "provider": self.provider_name,
            "agent": "ibkr_provider_agent",
            "reason": "queue_full",
        }
        self._m_dropped_dup_attrs = {
            "provider": self.provider_name,
            "agent": "ibkr_provider_agent",
            "reason": "duplicate",
        }

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establish connection to IBKR TWS."""
        return await self._provider.connect()

    async def disconnect(self) -> None:
        """Cleanly disconnect from IBKR TWS."""
        await self._provider.disconnect()

    def is_connected(self) -> bool:
        """Return True if the IBKR connection is currently active."""
        return self._provider.is_connected()

    # ------------------------------------------------------------------
    # stream_bars — primary live bar source
    # ------------------------------------------------------------------

    async def stream_bars(self, instruments: list[Instrument]) -> AsyncIterator[BarMessage]:
        """Async iterator yielding completed 1m BarMessage instances.

        Source: IBKRProvider.stream_official_bars() with keepUpToDate=True
        (IBKR's audited historical stream, ~2-5s after bar close).
        """
        symbols = [i.symbol for i in instruments]
        sym_to_instrument: dict[str, Instrument] = {i.symbol: i for i in instruments}

        # Bounded: drops here surface via PROVIDER_BARS_DROPPED_TOTAL{reason="queue_full"}
        # rather than blocking the ib_insync callback thread.
        bar_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        loop = asyncio.get_running_loop()

        def _make_bar_msg(sym: str, bar: OHLCVBar) -> BarMessage | None:
            """Convert OHLCVBar → BarMessage with dedup guard. Returns None if duplicate."""
            last_ts = self._last_emitted_ts.get(sym)
            if last_ts is not None and bar.timestamp <= last_ts:
                PROVIDER_BARS_DROPPED_TOTAL.add(1, self._m_dropped_dup_attrs)
                return None
            self._last_emitted_ts[sym] = bar.timestamp
            instrument = sym_to_instrument.get(sym)
            session_type = _SESSION_ID_TO_TYPE.get(
                instrument.session_id if instrument else "futures_24_5",
                _DEFAULT_SESSION_TYPE,
            )
            return BarMessage(
                ts=bar.timestamp,
                symbol=sym,
                tf="1m",
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=SOURCE_IBKR_GENERIC,
                session_type=session_type,
                gap_preceding=False,
                is_flat_bar=False,
            )

        # Shared mutable state for bar-flow watchdog.
        # last_bar_wall[0] is updated via loop.time() each time a bar arrives.
        last_bar_wall: list[float] = [loop.time()]

        def _enqueue_bar(msg: BarMessage) -> None:
            """Non-blocking enqueue. Drops + increments counter on QueueFull."""
            try:
                bar_queue.put_nowait(msg)
                last_bar_wall[0] = loop.time()
            except asyncio.QueueFull:
                PROVIDER_BARS_DROPPED_TOTAL.add(1, self._m_dropped_queue_full_attrs)
                logger.warning(
                    "ibkr_adapter.bar_queue_full_dropping symbol=%s ts=%s",
                    msg.symbol,
                    msg.ts.isoformat(),
                )

        async def _official_bars_stream() -> None:
            """Primary live bar source: keepUpToDate official bars."""
            try:
                async for sym, bar in self._provider.stream_official_bars(symbols):
                    msg = _make_bar_msg(sym, bar)
                    if msg:
                        _enqueue_bar(msg)
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error("official_bars_stream error", exc_info=error)

        # Watchdog: detect TWS disconnect so _stream_loop can reconnect.
        # After error 1100 (TWS lost), ib_insync restores the TCP connection
        # (error 1102) but keepUpToDate and RTB subscriptions must be
        # re-established. We signal via a sentinel on bar_queue so stream_bars
        # raises and _stream_loop catches it, calling _reconnect().
        _RECONNECT = object()  # sentinel — not a BarMessage
        _DISCONNECT_GRACE = 120  # seconds: allow TWS to auto-reconnect before raising
        # Renaissance: detect keepUpToDate silent dropout (still TCP-connected but
        # no bars arriving). Threshold > IBKR maintenance window (~15 min) so we
        # don't restart during a normal nightly pause, but catch indefinite silence.
        _NO_BAR_TIMEOUT_S = 1200  # 20 minutes
        # Soft threshold: after this much silence, actively ping the broker to
        # disambiguate "quiet market" from "dead subscription" without waiting
        # the full 20-min hard timeout.
        _PING_AFTER_SILENCE_S = 300  # 5 minutes

        async def _bar_flow_watchdog() -> None:
            """Reconnect when bars stop flowing despite TCP connection being alive.

            keepUpToDate streams silently die after IBKR maintenance windows
            without triggering error 1100/1102. _connection_watchdog cannot
            detect this because is_connected() stays True. This watchdog
            watches the wall-clock arrival time of bars and forces a restart
            either when an active ping fails past the soft threshold, or when
            silence exceeds _NO_BAR_TIMEOUT_S while the provider reports itself
            connected.
            """
            pinged_this_gap = False
            while True:
                await asyncio.sleep(60)
                silence_s = loop.time() - last_bar_wall[0]
                if silence_s < _PING_AFTER_SILENCE_S:
                    pinged_this_gap = False
                    continue

                if not self._provider.is_connected():
                    # _connection_watchdog handles the TCP-down case.
                    continue

                # Soft threshold crossed — actively ping once per silence gap
                # to catch dead subscriptions that keep is_connected() True.
                if not pinged_this_gap:
                    pinged_this_gap = True
                    try:
                        alive = await self._provider.ping()
                    except Exception as error:
                        logger.warning(
                            "ibkr_adapter.ping_exception_forcing_restart silence=%ds err=%s",
                            int(silence_s),
                            error,
                        )
                        await bar_queue.put(_RECONNECT)
                        return
                    if not alive:
                        logger.warning(
                            "ibkr_adapter.ping_failed_forcing_restart silence=%ds",
                            int(silence_s),
                        )
                        await bar_queue.put(_RECONNECT)
                        return

                if silence_s > _NO_BAR_TIMEOUT_S:
                    logger.warning(
                        "ibkr_adapter.bar_flow_timeout_forcing_restart silence=%ds threshold=%ds",
                        int(silence_s),
                        _NO_BAR_TIMEOUT_S,
                    )
                    await bar_queue.put(_RECONNECT)
                    return

        async def _connection_watchdog() -> None:
            disconnect_at: float | None = None
            was_disconnected = False
            while True:
                await asyncio.sleep(15)
                connected = self._provider.is_connected()
                if not connected:
                    if disconnect_at is None:
                        disconnect_at = loop.time()
                        was_disconnected = True
                        logger.warning("ibkr_adapter.tws_disconnected")
                    elif loop.time() - disconnect_at > _DISCONNECT_GRACE:
                        logger.warning("ibkr_adapter.tws_disconnect_timeout_forcing_restart")
                        await bar_queue.put(_RECONNECT)
                        return
                else:
                    if was_disconnected:
                        # Reconnected — force stream restart to re-subscribe
                        logger.info("ibkr_adapter.tws_reconnected_forcing_restart")
                        await bar_queue.put(_RECONNECT)
                        return
                    disconnect_at = None

        official_task = asyncio.ensure_future(_official_bars_stream())
        watchdog_task = asyncio.ensure_future(_connection_watchdog())
        bar_flow_task = asyncio.ensure_future(_bar_flow_watchdog())

        try:
            while True:
                bar = await bar_queue.get()
                if bar is _RECONNECT:
                    raise ConnectionError(
                        "TWS reconnect detected — restarting streams to re-subscribe"
                    )
                yield bar
        except asyncio.CancelledError:
            pass
        finally:
            for task in (official_task, watchdog_task, bar_flow_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    # ------------------------------------------------------------------
    # fetch_historical
    # ------------------------------------------------------------------

    async def fetch_historical(
        self,
        symbol: str,
        tf: str,
        start: datetime,
        end: datetime,
    ) -> list[BarMessage]:
        """Fetch historical bars and convert each to BarMessage with SOURCE_IBKR_NAMED."""
        raw_bars: list[OHLCVBar] = await self._provider.fetch_historical_bars(
            symbol=symbol,
            timeframe=tf,
            start=start,
            end=end,
        )
        result: list[BarMessage] = []
        for bar in raw_bars:
            ts = bar.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bar_msg = BarMessage(
                ts=ts,
                symbol=bar.symbol,
                tf=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=int(bar.volume),
                source=SOURCE_IBKR_NAMED,
                session_type=SessionType.RTH,
                gap_preceding=False,
                is_flat_bar=False,
            )
            result.append(bar_msg)
        return result

    # ------------------------------------------------------------------
    # qualify_instrument
    # ------------------------------------------------------------------

    async def qualify_instrument(self, instrument: Instrument) -> Instrument:
        """Resolve/enrich instrument metadata using IBKR-specific lookup.

        Reads provider_meta[self.provider_name] (i.e. provider_meta['ibkr'])
        for broker-specific overrides like trading_class.

        Returns the original Instrument (possibly enriched in-place by the
        underlying IBKRProvider). Raises ValueError if qualification fails.
        """
        ibkr_meta = instrument.provider_meta.get(self.provider_name, {})
        ibkr_symbol = ibkr_meta.get("symbol") or instrument.base or instrument.symbol
        trading_class = ibkr_meta.get("trading_class", "")

        success = await self._provider.qualify_instrument(
            instrument, ibkr_symbol=ibkr_symbol, trading_class=trading_class
        )
        if not success:
            raise ValueError(f"IBKRAdapter.qualify_instrument failed for {instrument.symbol!r}")
        return instrument
