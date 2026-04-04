"""Tests for IBKRAdapter — Phase 54-02.

TDD RED phase: all tests must fail before IBKRAdapter is implemented.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.bar_normalizer import SOURCE_IBKR_GENERIC, SOURCE_IBKR_NAMED
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage
from src.providers.base import DataProviderAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def instrument_es() -> Instrument:
    return Instrument(
        symbol="ESM6",
        base="ES",
        exchange="CME",
        expiry="202606",
        name="E-mini S&P 500",
        point_value=50,
        tick_size=0.25,
        session_id="futures_24_5",
    )


@pytest.fixture
def instrument_vx() -> Instrument:
    return Instrument(
        symbol="VXJ6",
        base="VIX",
        exchange="CFE",
        expiry="20260415",
        name="CBOE VIX Futures",
        point_value=1000,
        tick_size=0.05,
        sector="volatility",
        provider_meta={"ibkr": {"trading_class": "VX"}},
    )


@pytest.fixture
def adapter():
    """IBKRAdapter with mocked IBKRProvider."""
    from src.providers.ibkr_adapter import IBKRAdapter

    return IBKRAdapter(host="127.0.0.1", port=7497, client_id=35)


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_satisfies_protocol(self, adapter):
        """IBKRAdapter must satisfy the runtime-checkable DataProviderAdapter Protocol."""
        assert isinstance(adapter, DataProviderAdapter)

    def test_provider_name_is_ibkr(self, adapter):
        """provider_name must equal 'ibkr' for topic-key routing and metric labels."""
        assert adapter.provider_name == "ibkr"


# ---------------------------------------------------------------------------
# stream_bars
# ---------------------------------------------------------------------------


def _make_mock_provider_for_stream(instrument: Instrument) -> MagicMock:
    """Build a mock IBKRProvider with official-bars stream stubbed."""
    from src.providers.base import OHLCVBar
    from src.core.bar_normalizer import SOURCE_IBKR_GENERIC

    ts1 = datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 28, 14, 1, 0, tzinfo=UTC)
    bar1 = OHLCVBar(
        symbol=instrument.symbol, timeframe="1m", timestamp=ts1,
        open=100.0, high=101.0, low=99.0, close=100.5, volume=100,
        source=SOURCE_IBKR_GENERIC,
    )
    bar2 = OHLCVBar(
        symbol=instrument.symbol, timeframe="1m", timestamp=ts2,
        open=100.5, high=101.5, low=99.5, close=101.0, volume=120,
        source=SOURCE_IBKR_GENERIC,
    )

    async def _fake_official(symbols, timeframe="1m"):
        yield (instrument.symbol, bar1)
        yield (instrument.symbol, bar2)

    provider = MagicMock()
    provider.stream_official_bars = _fake_official
    return provider


async def _collect_one_bar(adapter, instruments, timeout_secs=5.0) -> list[BarMessage]:
    """Collect the first bar from stream_bars with a hard timeout."""
    bars: list[BarMessage] = []
    gen = adapter.stream_bars(instruments)
    try:
        async with asyncio.timeout(timeout_secs):
            async for bar in gen:
                bars.append(bar)
                break
    except TimeoutError:
        pass
    finally:
        await gen.aclose()
    return bars


class TestStreamBars:
    @pytest.mark.asyncio
    async def test_stream_bars_yields_bar_message(self, adapter, instrument_es):
        """stream_bars must yield BarMessage instances."""
        adapter._provider = _make_mock_provider_for_stream(instrument_es)
        bars = await _collect_one_bar(adapter, [instrument_es])
        assert len(bars) >= 1
        assert isinstance(bars[0], BarMessage)

    @pytest.mark.asyncio
    async def test_stream_bars_source_is_ibkr_generic(self, adapter, instrument_es):
        """Bars from stream_bars must have source == SOURCE_IBKR_GENERIC."""
        adapter._provider = _make_mock_provider_for_stream(instrument_es)
        bars = await _collect_one_bar(adapter, [instrument_es])
        assert len(bars) >= 1
        assert bars[0].source == SOURCE_IBKR_GENERIC

    @pytest.mark.asyncio
    async def test_stream_bars_ts_is_utc_aware(self, adapter, instrument_es):
        """Bars from stream_bars must have UTC-aware ts."""
        adapter._provider = _make_mock_provider_for_stream(instrument_es)
        bars = await _collect_one_bar(adapter, [instrument_es])
        assert len(bars) >= 1
        assert bars[0].ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_stream_bars_symbol_from_instrument(self, adapter, instrument_es):
        """Bars from stream_bars must carry the instrument symbol."""
        adapter._provider = _make_mock_provider_for_stream(instrument_es)
        bars = await _collect_one_bar(adapter, [instrument_es])
        assert len(bars) >= 1
        assert bars[0].symbol == instrument_es.symbol


# ---------------------------------------------------------------------------
# fetch_historical
# ---------------------------------------------------------------------------


class TestFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_historical_returns_list_of_bar_message(
        self, adapter, instrument_es
    ):
        """fetch_historical must return list[BarMessage]."""
        from src.providers.base import OHLCVBar

        fake_bar = OHLCVBar(
            symbol="ESM6",
            timeframe="1m",
            timestamp=datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC),
            open=5100.0,
            high=5105.0,
            low=5095.0,
            close=5102.0,
            volume=1000,
            source=SOURCE_IBKR_NAMED,
        )
        adapter._provider = MagicMock()
        adapter._provider.fetch_historical_bars = AsyncMock(return_value=[fake_bar])

        start = datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 28, 15, 0, 0, tzinfo=UTC)
        result = await adapter.fetch_historical(
            symbol="ESM6", tf="1m", start=start, end=end
        )

        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], BarMessage)

    @pytest.mark.asyncio
    async def test_fetch_historical_source_is_ibkr_named(
        self, adapter, instrument_es
    ):
        """fetch_historical bars must have source == SOURCE_IBKR_NAMED."""
        from src.providers.base import OHLCVBar

        fake_bar = OHLCVBar(
            symbol="ESM6",
            timeframe="1m",
            timestamp=datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC),
            open=5100.0,
            high=5105.0,
            low=5095.0,
            close=5102.0,
            volume=1000,
            source=SOURCE_IBKR_NAMED,
        )
        adapter._provider = MagicMock()
        adapter._provider.fetch_historical_bars = AsyncMock(return_value=[fake_bar])

        start = datetime(2026, 3, 28, 14, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 28, 15, 0, 0, tzinfo=UTC)
        result = await adapter.fetch_historical(
            symbol="ESM6", tf="1m", start=start, end=end
        )

        assert result[0].source == SOURCE_IBKR_NAMED


# ---------------------------------------------------------------------------
# qualify_instrument
# ---------------------------------------------------------------------------


class TestQualifyInstrument:
    @pytest.mark.asyncio
    async def test_qualify_instrument_reads_nested_meta(
        self, adapter, instrument_vx
    ):
        """qualify_instrument must read provider_meta['ibkr']['trading_class']."""
        adapter._provider = MagicMock()
        adapter._provider.qualify_instrument = AsyncMock(return_value=True)
        adapter._provider._qualified_contracts = {instrument_vx.symbol: MagicMock()}

        result = await adapter.qualify_instrument(instrument_vx)

        # Should have called the underlying provider's qualify_instrument
        adapter._provider.qualify_instrument.assert_called_once()
        # Result must be an Instrument (possibly enriched)
        assert isinstance(result, Instrument)

    @pytest.mark.asyncio
    async def test_qualify_instrument_empty_meta_ok(self, adapter, instrument_es):
        """qualify_instrument must not crash when provider_meta is empty."""
        assert instrument_es.provider_meta == {}

        adapter._provider = MagicMock()
        adapter._provider.qualify_instrument = AsyncMock(return_value=True)
        adapter._provider._qualified_contracts = {instrument_es.symbol: MagicMock()}

        # Must not raise
        result = await adapter.qualify_instrument(instrument_es)
        assert isinstance(result, Instrument)


# ---------------------------------------------------------------------------
# Settings — nested provider_meta
# ---------------------------------------------------------------------------


class TestSettingsNestedProviderMeta:
    def test_vx_settings_nested_provider_meta(self):
        """VX base symbol in Settings must have provider_meta == {'ibkr': {'trading_class': 'VX'}}.

        Phase 58.1-05 replaced front-month codes (VXJ6) with base-symbol templates (VX).
        """
        from src.config.settings import Settings

        settings = Settings()
        vx = next(
            (c for c in settings.contracts if c.symbol == "VIX"), None
        )
        assert vx is not None, "VIX not found in default contracts"
        assert vx.provider_meta == {"ibkr": {"trading_class": "VX"}}, (
            f"Expected nested provider_meta, got {vx.provider_meta!r}"
        )
