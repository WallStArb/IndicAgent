"""IBKRAdapter — DataProviderAdapter implementation wrapping IBKRProvider.

Encapsulates all IBKR-specific logic (official bar streaming, crypto polling
fallback, provider_meta['ibkr'] key lookup) so that BaseProviderAgent only
sees the provider-agnostic DataProviderAdapter interface.

Swapping IBKR for another broker = one new adapter file. Everything downstream
(MergerAgent, FeatureComputeAgent, etc.) is untouched.

Phase 54-02 — Provider Abstraction Layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from src.core.bar_normalizer import SOURCE_IBKR_GENERIC, SOURCE_IBKR_NAMED
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage, SessionType
from src.providers.base import OHLCVBar
from src.providers.ibkr import IBKRProvider

# Map Instrument.session_id → SessionType for bar emission.
# session_id is the trading calendar identifier; SessionType is the bar-level
# session classification used downstream by the feature pipeline.
_SESSION_ID_TO_TYPE: dict[str, SessionType] = {
    "crypto_24_7": SessionType.CRYPTO,
    "fx_24_5": SessionType.FX,
    "nyse": SessionType.RTH,
    "futures_24_5": SessionType.RTH,
}

_DEFAULT_SESSION_TYPE = SessionType.RTH

logger = logging.getLogger(__name__)


class IBKRAdapter:
    """DataProviderAdapter that wraps IBKRProvider and produces BarMessage directly.

    Uses IBKR's keepUpToDate official bars as the primary live bar source.
    Crypto symbols fall back to 65s polling (keepUpToDate+AGGTRADES unsupported).

    provider_name = 'ibkr' — matches the key used in provider_meta lookups,
    topic keys, and Prometheus metric labels.
    """

    provider_name: str = "ibkr"

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._provider = IBKRProvider(host=host, port=port, client_id=client_id)

        # Dedup guard: symbol → set of emitted ts ISO strings
        self._seen_ts: dict[str, set[str]] = defaultdict(set)
        self._seen_ts_order: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

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
    # stream_bars — primary live bar source (official bars + crypto polling)
    # ------------------------------------------------------------------

    async def stream_bars(
        self, instruments: list[Instrument]
    ) -> AsyncIterator[BarMessage]:
        """Async iterator yielding completed 1m BarMessage instances.

        Primary source: IBKRProvider.stream_official_bars() with keepUpToDate=True
        (IBKR's audited historical stream, ~2-5s after bar close). Crypto symbols
        (BTCUSD, ETHUSD) use a polling fallback every 65s because keepUpToDate=True
        is unsupported for AGGTRADES (IBKR error 321).
        """
        symbols = [i.symbol for i in instruments]
        sym_to_instrument: dict[str, Instrument] = {i.symbol: i for i in instruments}

        bar_queue: asyncio.Queue[BarMessage] = asyncio.Queue()

        def _make_bar_msg(sym: str, bar: OHLCVBar) -> BarMessage | None:
            """Convert OHLCVBar → BarMessage with dedup guard. Returns None if duplicate."""
            ts_str = bar.timestamp.isoformat()
            seen = self._seen_ts[sym]
            order = self._seen_ts_order[sym]
            if ts_str in seen:
                return None
            if len(order) == order.maxlen:
                seen.discard(order[0])  # evict before deque drops it
            seen.add(ts_str)
            order.append(ts_str)
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

        async def _official_bars_stream() -> None:
            """Primary live bar source: keepUpToDate official bars (non-crypto)."""
            try:
                async for sym, bar in self._provider.stream_official_bars(symbols):
                    msg = _make_bar_msg(sym, bar)
                    if msg:
                        await bar_queue.put(msg)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("official_bars_stream error", exc_info=exc)

        async def _crypto_poll_loop() -> None:
            """Crypto fallback: poll last 3 min every 65s (keepUpToDate+AGGTRADES = error 321)."""
            crypto_symbols = [
                sym for sym in symbols
                if sym_to_instrument.get(sym)
                and sym_to_instrument[sym].session_id == "crypto_24_7"
            ]
            if not crypto_symbols:
                return
            try:
                while True:
                    await asyncio.sleep(65)
                    now = datetime.now(UTC)
                    start = now - timedelta(minutes=3)
                    for sym in crypto_symbols:
                        try:
                            bars = await self._provider.fetch_historical_bars(
                                symbol=sym,
                                timeframe="1m",
                                start=start,
                                end=now,
                            )
                            for bar in bars:
                                msg = _make_bar_msg(sym, bar)
                                if msg:
                                    await bar_queue.put(msg)
                        except Exception as exc:
                            logger.warning(
                                "crypto_poll_loop error",
                                extra={"symbol": sym},
                                exc_info=exc,
                            )
            except asyncio.CancelledError:
                pass

        official_task = asyncio.ensure_future(_official_bars_stream())
        crypto_task = asyncio.ensure_future(_crypto_poll_loop())

        try:
            while True:
                bar = await bar_queue.get()
                yield bar
        except asyncio.CancelledError:
            pass
        finally:
            for task in (official_task, crypto_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
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
        # Extract IBKR-specific meta from the nested format
        ibkr_meta = instrument.provider_meta.get(self.provider_name, {})

        # Build an ephemeral Instrument copy with the flattened meta for
        # IBKRProvider.qualify_instrument() which reads flat provider_meta
        if ibkr_meta:
            flat_instrument = instrument.model_copy(update={"provider_meta": ibkr_meta})
        else:
            flat_instrument = instrument

        success = await self._provider.qualify_instrument(flat_instrument)
        if not success:
            raise ValueError(
                f"IBKRAdapter.qualify_instrument failed for {instrument.symbol!r}"
            )
        return instrument
