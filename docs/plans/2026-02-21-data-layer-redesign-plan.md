# Data Layer Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace IBKR-coupled data layer with a generic `DataProvider` protocol, rename `IBKRContract` → `Instrument`, consolidate IBKR logic into `IBKRProvider`, and add TimescaleDB continuous aggregates to replace Python bar aggregation.

**Architecture:** `IBKRProvider` implements `DataProvider` protocol and wraps all `ib_insync` logic (connection, tick streaming, historical fetch). A bounded `asyncio.Queue` bridges ib_insync's synchronous callbacks to an async iterator exposed by `stream_ticks()`. TimescaleDB materializes 5m/15m/1h views from stored 1m bars — the Python `aggregate_1m_to_tf()` is deleted.

**Tech Stack:** Python 3.11+, `typing.Protocol`, `asyncio`, `ib_insync`, `pydantic`, `TimescaleDB`, `pytest`, `unittest.mock`

---

## Task 1: Add `AssetClass` and `Instrument` to models

**Files:**
- Modify: `src/core/models.py`
- Test: `tests/unit/core/test_models.py` *(create if not exists)*

**Step 1: Write the failing test**

Create `tests/unit/core/test_models.py` (or add to existing):

```python
import pytest
from src.core.models import AssetClass, Instrument

class TestAssetClass:
    def test_all_values_defined(self):
        assert AssetClass.FUTURES == "futures"
        assert AssetClass.EQUITY == "equity"
        assert AssetClass.CRYPTO == "crypto"
        assert AssetClass.FX == "fx"
        assert AssetClass.OPTION == "option"

class TestInstrument:
    def test_futures_instrument(self):
        inst = Instrument(
            symbol="ESH6",
            name="E-mini S&P 500",
            asset_class=AssetClass.FUTURES,
            exchange="CME",
            base="ES",
            expiry="20260320",
            point_value=50.0,
            tick_size=0.25,
            sector="equity_index",
        )
        assert inst.symbol == "ESH6"
        assert inst.asset_class == AssetClass.FUTURES
        assert inst.point_value == 50.0

    def test_equity_instrument_optional_futures_fields(self):
        inst = Instrument(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            exchange="NASDAQ",
        )
        assert inst.base == ""
        assert inst.expiry == ""
        assert inst.point_value == 0

    def test_provider_meta_accepts_arbitrary_dict(self):
        inst = Instrument(
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            provider_meta={"product_id": "BTC-USD", "fee_rate": 0.001},
        )
        assert inst.provider_meta["product_id"] == "BTC-USD"

    def test_defaults_to_futures(self):
        inst = Instrument(symbol="NQH6")
        assert inst.asset_class == AssetClass.FUTURES
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_models.py -v
```
Expected: `ImportError: cannot import name 'AssetClass'`

**Step 3: Add to `src/core/models.py`**

Add after the existing `DataSource` class:

```python
class AssetClass(StrEnum):
    """Asset class classification."""
    FUTURES = "futures"
    EQUITY  = "equity"
    CRYPTO  = "crypto"
    FX      = "fx"
    OPTION  = "option"


class Instrument(BaseModel):
    """Generic tradable instrument — provider-agnostic."""
    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.FUTURES
    exchange: str = ""
    sector: str = ""
    tick_size: float = 0
    # Futures-specific — empty/zero for equities and crypto
    base: str = ""
    expiry: str = ""
    point_value: float = 0
    # Escape hatch for provider-specific metadata
    provider_meta: dict = {}
```

**Step 4: Run tests**

```bash
pytest tests/unit/core/test_models.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/core/models.py tests/unit/core/test_models.py
git commit -m "feat: add AssetClass and Instrument models"
```

---

## Task 2: Rename `IBKRContract` → `Instrument` in settings

**Files:**
- Modify: `src/config/settings.py`
- Modify: `tests/unit/config/test_settings.py`

**Context:** `IBKRContract` is defined in `src/config/settings.py` and imported by several files. We rename it to `Instrument` (already defined in `models.py`), add `asset_class=AssetClass.FUTURES` to all defaults, and keep a deprecated alias so nothing breaks immediately.

**Step 1: Update the imports in test to verify current state**

Run the existing tests first:
```bash
pytest tests/unit/config/test_settings.py -v
```
All should PASS (baseline check).

**Step 2: Update `src/config/settings.py`**

Replace the `IBKRContract` class definition and all usages with `Instrument`:

```python
# At top of file, add import:
from src.core.models import AssetClass, Instrument

# Remove the IBKRContract class definition entirely.
# Add deprecated alias below imports for backwards compat during transition:
IBKRContract = Instrument  # deprecated — use Instrument
```

Then update `Settings.contracts` field type:
```python
contracts: list[Instrument] = Field(default_factory=list)
```

Update `build_contracts` validator return types:
```python
return [Instrument(**item) for item in parsed if isinstance(item, dict)]
```

Update all default contract definitions — add `asset_class=AssetClass.FUTURES` to each:
```python
Instrument(
    symbol="ESH6", base="ES", exchange="CME", expiry="20260320",
    name="E-mini S&P 500", point_value=50, tick_size=0.25,
    sector="equity_index", asset_class=AssetClass.FUTURES,
),
# ... same for all other contracts
```

Update `get_contract_info` return type annotation:
```python
def get_contract_info(symbol: str, settings: Settings | None = None) -> Instrument | None:
```

**Step 3: Update `tests/unit/config/test_settings.py`**

Change the import:
```python
# Old:
from src.config.settings import IBKRContract, Settings, ...
# New:
from src.config.settings import Settings, ...
from src.core.models import Instrument
```

Update any test that references `IBKRContract` to use `Instrument`. Any test that calls `get_contract_info` and checks the return type should assert `isinstance(result, Instrument)`.

**Step 4: Run tests**

```bash
pytest tests/unit/config/test_settings.py -v
```
Expected: all PASS

**Step 5: Verify nothing else broke**

```bash
pytest tests/ -v --tb=short -q
```
Expected: 476 PASS (same as before)

**Step 6: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings.py src/core/models.py
git commit -m "refactor: rename IBKRContract to Instrument, add AssetClass"
```

---

## Task 3: Create `src/providers/base.py` — Protocol + wire models

**Files:**
- Create: `src/providers/__init__.py`
- Create: `src/providers/base.py`
- Create: `tests/unit/providers/__init__.py`
- Create: `tests/unit/providers/test_base.py`

**Step 1: Write the failing tests**

```python
# tests/unit/providers/test_base.py
import pytest
from datetime import datetime, timezone
from src.providers.base import Tick, OHLCVBar, DataProvider
from src.core.models import Instrument

class TestTick:
    def test_minimal_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            price=5100.25,
            source="ibkr",
        )
        assert tick.symbol == "ESH6"
        assert tick.bid is None
        assert tick.ask is None

    def test_full_tick(self):
        tick = Tick(
            symbol="ESH6",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            price=5100.25,
            bid=5100.00,
            ask=5100.50,
            bid_size=10,
            ask_size=15,
            size=2,
            source="ibkr",
        )
        assert tick.bid == 5100.00
        assert tick.ask == 5100.50

class TestOHLCVBar:
    def test_bar_creation(self):
        bar = OHLCVBar(
            symbol="ESH6",
            timeframe="1m",
            timestamp=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
            open=5100.0,
            high=5105.0,
            low=5098.0,
            close=5102.0,
            volume=1500,
            source="ibkr",
        )
        assert bar.timeframe == "1m"
        assert bar.high == 5105.0

class TestDataProviderProtocol:
    def test_protocol_is_runtime_checkable(self):
        # A class that doesn't implement the protocol should not be an instance
        class NotAProvider:
            pass
        assert not isinstance(NotAProvider(), DataProvider)

    def test_minimal_implementation_satisfies_protocol(self):
        from collections.abc import AsyncIterator

        class MinimalProvider:
            name = "test"
            async def connect(self) -> bool: return True
            async def disconnect(self) -> None: pass
            def is_connected(self) -> bool: return True
            async def resolve_instrument(self, query: str): return None
            async def stream_ticks(self, symbols): ...
            async def fetch_historical_bars(self, symbol, timeframe, start, end): return []

        assert isinstance(MinimalProvider(), DataProvider)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/providers/test_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.providers'`

**Step 3: Create `src/providers/__init__.py`** (empty for now)

```python
# src/providers/__init__.py
```

**Step 4: Create `src/providers/base.py`**

```python
"""
DataProvider protocol and normalized wire models.

All data providers emit Tick and OHLCVBar instances — the pipeline
is completely unaware of which provider is active.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from src.core.models import Instrument


class Tick(BaseModel):
    """Normalized real-time tick from any provider."""
    symbol: str
    timestamp: datetime
    price: float
    size: int | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    source: str  # provider name: "ibkr", "alpaca", etc.


class OHLCVBar(BaseModel):
    """Normalized OHLCV bar from any provider."""
    symbol: str
    timeframe: str   # "1m", "5m", "15m", "1h"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


@runtime_checkable
class DataProvider(Protocol):
    """Protocol that every data provider must implement.

    Adding a new provider:
    1. Create src/providers/<name>.py
    2. Implement all methods below
    3. Pass instance to the daemon — nothing else changes.
    """

    name: str  # "ibkr", "alpaca", "tradestation"

    async def connect(self) -> bool:
        """Establish connection to the data source. Returns True on success."""
        ...

    async def disconnect(self) -> None:
        """Cleanly disconnect."""
        ...

    def is_connected(self) -> bool:
        """Return True if the connection is currently active."""
        ...

    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a user-entered symbol string to a concrete Instrument.

        Each provider handles its own lookup (IBKR reqContractDetails,
        Alpaca assets API, etc.). Returns None if not found.
        """
        ...

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator that yields normalized Ticks as they arrive.

        Usage:
            async for tick in provider.stream_ticks(["ESH6", "NQH6"]):
                await publish(tick)
        """
        ...

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars. timeframe: '1m', '5m', '15m', '1h'."""
        ...
```

**Step 5: Create `tests/unit/providers/__init__.py`** (empty)

**Step 6: Run tests**

```bash
pytest tests/unit/providers/test_base.py -v
```
Expected: all PASS

**Step 7: Commit**

```bash
git add src/providers/ tests/unit/providers/
git commit -m "feat: add DataProvider protocol, Tick, OHLCVBar models"
```

---

## Task 4: Create `IBKRProvider` — connect / disconnect / is_connected

**Files:**
- Create: `src/providers/ibkr.py`
- Create: `tests/unit/providers/test_ibkr_provider.py`

**Step 1: Write the failing tests**

```python
# tests/unit/providers/test_ibkr_provider.py
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from src.providers.ibkr import IBKRProvider
from src.providers.base import DataProvider


@pytest.fixture
def mock_ib():
    """Mock ib_insync.IB instance."""
    ib = MagicMock()
    ib.isConnected.return_value = True
    ib.pendingTickersEvent = MagicMock()
    return ib


@pytest.fixture
def provider():
    return IBKRProvider(host="127.0.0.1", port=7497, client_id=1)


class TestIBKRProviderProtocol:
    def test_satisfies_data_provider_protocol(self, provider):
        assert isinstance(provider, DataProvider)

    def test_name(self, provider):
        assert provider.name == "ibkr"


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connect.return_value = None
            mock_ib.isConnected.return_value = True
            result = await provider.connect()
        assert result is True
        assert provider.is_connected()

    @pytest.mark.asyncio
    async def test_connect_failure_returns_false(self, provider, mock_ib):
        with patch("src.providers.ibkr.IB", return_value=mock_ib):
            mock_ib.connect.side_effect = Exception("connection refused")
            result = await provider.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_calls_ib_disconnect(self, provider, mock_ib):
        provider._ib = mock_ib
        await provider.disconnect()
        mock_ib.disconnect.assert_called_once()

    def test_is_connected_false_before_connect(self, provider):
        assert provider.is_connected() is False
```

**Step 2: Run to verify failure**

```bash
pytest tests/unit/providers/test_ibkr_provider.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.providers.ibkr'`

**Step 3: Create `src/providers/ibkr.py`** (connect/disconnect only for now)

```python
"""
IBKRProvider — DataProvider implementation for Interactive Brokers (ib_insync).

Wraps all ib_insync logic. The daemon and backfill script interact only
with the DataProvider protocol — no ib_insync imports outside this file.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime

from ib_insync import IB, Future, Stock

from src.core.models import AssetClass, Instrument
from src.providers.base import OHLCVBar, Tick

logger = logging.getLogger(__name__)

# Map our timeframe strings to ib_insync barSizeSetting values
_TF_TO_IB: dict[str, str] = {
    "1m":  "1 min",
    "5m":  "5 mins",
    "15m": "15 mins",
    "1h":  "1 hour",
    "4h":  "4 hours",
    "1d":  "1 day",
}


class IBKRProvider:
    """DataProvider implementation for Interactive Brokers via ib_insync."""

    name = "ibkr"

    def __init__(self, host: str, port: int, client_id: int, tick_queue_size: int = 5000):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._tick_queue_size = tick_queue_size
        self._ib: IB | None = None
        self._tick_queue: asyncio.Queue[Tick] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._qualified_contracts: dict[str, object] = {}

    async def connect(self) -> bool:
        """Connect to TWS/Gateway. Returns True on success."""
        try:
            self._ib = IB()
            self._ib.connect(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=20,
                readonly=False,
            )
            connected = self._ib.isConnected()
            if connected:
                logger.info("IBKRProvider connected", host=self._host, port=self._port)
            return connected
        except Exception as e:
            logger.error("IBKRProvider connect failed", error=str(e))
            return False

    async def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._ib:
            self._ib.disconnect()
            logger.info("IBKRProvider disconnected")

    def is_connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())
```

**Step 4: Run tests**

```bash
pytest tests/unit/providers/test_ibkr_provider.py::TestIBKRProviderProtocol -v
pytest tests/unit/providers/test_ibkr_provider.py::TestConnect -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/providers/ibkr.py tests/unit/providers/test_ibkr_provider.py
git commit -m "feat: IBKRProvider scaffold with connect/disconnect/is_connected"
```

---

## Task 5: `IBKRProvider.fetch_historical_bars()` — replaces `IBKRFetcher`

**Context:** `IBKRFetcher` in `historical_backfill.py` has this same logic. Once this task is done, `IBKRFetcher` is deleted.

**Step 1: Write the failing tests** (add to `test_ibkr_provider.py`)

```python
class TestFetchHistoricalBars:
    @pytest.mark.asyncio
    async def test_returns_ohlcv_bars(self, provider, mock_ib):
        """fetch_historical_bars maps ib_insync BarData to OHLCVBar list."""
        from datetime import timezone

        # Build mock BarData objects (ib_insync returns these)
        mock_bar = MagicMock()
        mock_bar.date = datetime(2026, 2, 1, 9, 30, tzinfo=timezone.utc)
        mock_bar.open = 5100.0
        mock_bar.high = 5105.0
        mock_bar.low = 5098.0
        mock_bar.close = 5102.0
        mock_bar.volume = 1500

        mock_ib.reqHistoricalData.return_value = [mock_bar]
        provider._ib = mock_ib

        # Qualify a contract for the provider
        mock_contract = MagicMock()
        provider._qualified_contracts["ESH6"] = mock_contract

        bars = await provider.fetch_historical_bars(
            symbol="ESH6",
            timeframe="1m",
            start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            end=datetime(2026, 2, 2, tzinfo=timezone.utc),
        )

        assert len(bars) == 1
        assert bars[0].symbol == "ESH6"
        assert bars[0].timeframe == "1m"
        assert bars[0].open == 5100.0
        assert bars[0].high == 5105.0
        assert bars[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_unknown_timeframe_raises(self, provider, mock_ib):
        provider._ib = mock_ib
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await provider.fetch_historical_bars(
                "ESH6", "3m",
                datetime(2026, 2, 1), datetime(2026, 2, 2)
            )

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_data(self, provider, mock_ib):
        mock_ib.reqHistoricalData.return_value = []
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()
        bars = await provider.fetch_historical_bars(
            "ESH6", "1m",
            datetime(2026, 2, 1), datetime(2026, 2, 2)
        )
        assert bars == []
```

**Step 2: Run to verify failure**

```bash
pytest tests/unit/providers/test_ibkr_provider.py::TestFetchHistoricalBars -v
```
Expected: `AttributeError: 'IBKRProvider' object has no attribute 'fetch_historical_bars'`

**Step 3: Add `fetch_historical_bars` to `src/providers/ibkr.py`**

```python
    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars from IBKR.

        Requires the contract to be pre-qualified via qualify_instrument().
        """
        if timeframe not in _TF_TO_IB:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Valid: {list(_TF_TO_IB)}")

        if not self._ib:
            raise RuntimeError("Not connected. Call connect() first.")

        contract = self._qualified_contracts.get(symbol)
        if not contract:
            raise ValueError(f"Unknown symbol '{symbol}'. Call qualify_instrument() first.")

        duration_days = max(1, (end - start).days + 1)
        ib_bars = self._ib.reqHistoricalData(
            contract,
            endDateTime=end.strftime("%Y%m%d %H:%M:%S"),
            durationStr=f"{duration_days} D",
            barSizeSetting=_TF_TO_IB[timeframe],
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )

        return [
            OHLCVBar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=bar.date if isinstance(bar.date, datetime) else datetime.fromisoformat(str(bar.date)),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=int(bar.volume),
                source="ibkr",
            )
            for bar in (ib_bars or [])
        ]

    async def qualify_instrument(self, instrument: Instrument) -> bool:
        """Qualify an instrument with IBKR and cache the contract.

        Must be called before fetch_historical_bars() or stream_ticks().
        Returns True if successfully qualified.
        """
        if not self._ib:
            return False
        try:
            if instrument.asset_class == AssetClass.FUTURES:
                contract = Future(
                    symbol=instrument.base or instrument.symbol,
                    lastTradeDateOrContractMonth=instrument.expiry,
                    exchange=instrument.exchange,
                )
            else:
                contract = Stock(symbol=instrument.symbol, exchange=instrument.exchange)

            details = self._ib.reqContractDetails(contract)
            if details:
                self._qualified_contracts[instrument.symbol] = details[0].contract
                return True
            return False
        except Exception as e:
            logger.warning("qualify_instrument failed", symbol=instrument.symbol, error=str(e))
            return False
```

**Step 4: Run tests**

```bash
pytest tests/unit/providers/test_ibkr_provider.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/providers/ibkr.py tests/unit/providers/test_ibkr_provider.py
git commit -m "feat: IBKRProvider.fetch_historical_bars + qualify_instrument"
```

---

## Task 6: `IBKRProvider.stream_ticks()` — async iterator with queue bridge

**Context:** ib_insync fires `pendingTickersEvent` synchronously on its own thread. We bridge this to an `asyncio.Queue` using `call_soon_threadsafe`, then yield from it.

**Step 1: Write the failing tests** (add to `test_ibkr_provider.py`)

```python
class TestStreamTicks:
    @pytest.mark.asyncio
    async def test_stream_ticks_yields_normalized_ticks(self, provider, mock_ib):
        """Ticks pushed to the queue appear in the async iterator."""
        provider._ib = mock_ib
        provider._qualified_contracts["ESH6"] = MagicMock()

        # Simulate what ib_insync gives us
        mock_ticker = MagicMock()
        mock_ticker.contract.localSymbol = "ESH6"
        mock_ticker.last = 5100.25
        mock_ticker.lastSize = 2
        mock_ticker.bid = 5100.0
        mock_ticker.ask = 5100.5
        mock_ticker.bidSize = 10
        mock_ticker.askSize = 15

        collected = []

        async def collect_one():
            async for tick in provider.stream_ticks(["ESH6"]):
                collected.append(tick)
                break  # stop after first tick

        # Start the stream, fire a fake ticker event, collect
        task = asyncio.create_task(collect_one())
        await asyncio.sleep(0)  # let stream_ticks initialize queue + loop

        # Simulate ib_insync callback firing
        provider._handle_pending_tickers([mock_ticker])
        await asyncio.wait_for(task, timeout=2.0)

        assert len(collected) == 1
        assert collected[0].symbol == "ESH6"
        assert collected[0].price == 5100.25
        assert collected[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_normalize_ticker_skips_zero_price(self, provider):
        mock_ticker = MagicMock()
        mock_ticker.contract.localSymbol = "ESH6"
        mock_ticker.last = 0.0
        mock_ticker.bid = None
        mock_ticker.ask = None
        tick = provider._normalize_ticker(mock_ticker)
        assert tick is None
```

**Step 2: Run to verify failure**

```bash
pytest tests/unit/providers/test_ibkr_provider.py::TestStreamTicks -v
```
Expected: `AttributeError: 'IBKRProvider' object has no attribute 'stream_ticks'`

**Step 3: Add `stream_ticks` to `src/providers/ibkr.py`**

```python
    def _normalize_ticker(self, ticker) -> Tick | None:
        """Normalize an ib_insync Ticker to a Tick. Returns None if no valid price."""
        symbol = getattr(ticker.contract, "localSymbol", None)
        if not symbol:
            return None

        price = None
        for attr in ("last", "close", "bid", "ask"):
            val = getattr(ticker, attr, None)
            if val and float(val) > 0:
                price = float(val)
                break
        if not price:
            return None

        from datetime import timezone
        return Tick(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            price=price,
            size=int(getattr(ticker, "lastSize", None) or 0) or None,
            bid=float(ticker.bid) if getattr(ticker, "bid", None) and ticker.bid > 0 else None,
            ask=float(ticker.ask) if getattr(ticker, "ask", None) and ticker.ask > 0 else None,
            bid_size=int(ticker.bidSize) if getattr(ticker, "bidSize", None) and ticker.bidSize > 0 else None,
            ask_size=int(ticker.askSize) if getattr(ticker, "askSize", None) and ticker.askSize > 0 else None,
            source="ibkr",
        )

    def _handle_pending_tickers(self, tickers) -> None:
        """ib_insync callback — runs on ib_insync's thread. Bridge to asyncio queue."""
        if not self._tick_queue or not self._loop:
            return
        for ticker in tickers:
            if ticker.contract.localSymbol not in self._qualified_contracts:
                continue
            tick = self._normalize_ticker(ticker)
            if tick:
                try:
                    self._loop.call_soon_threadsafe(self._tick_queue.put_nowait, tick)
                except Exception:
                    pass  # drop on full queue — backpressure

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator yielding normalized Ticks.

        Bridges ib_insync's sync callbacks to asyncio via a bounded Queue.
        Subscribes to all symbols via reqMktData on entry.
        """
        self._loop = asyncio.get_event_loop()
        self._tick_queue = asyncio.Queue(maxsize=self._tick_queue_size)

        # Register callback
        self._ib.pendingTickersEvent += self._handle_pending_tickers

        # Subscribe to market data for each symbol
        for symbol in symbols:
            contract = self._qualified_contracts.get(symbol)
            if contract and self._ib:
                self._ib.reqMktData(contract, genericTickList="233", snapshot=False)

        try:
            while True:
                tick = await self._tick_queue.get()
                yield tick
        finally:
            self._ib.pendingTickersEvent -= self._handle_pending_tickers
```

**Step 4: Run tests**

```bash
pytest tests/unit/providers/test_ibkr_provider.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/providers/ibkr.py tests/unit/providers/test_ibkr_provider.py
git commit -m "feat: IBKRProvider.stream_ticks — async iterator with ib_insync queue bridge"
```

---

## Task 7: `IBKRProvider.resolve_instrument()` + update `__init__.py`

**Step 1: Write the failing test** (add to `test_ibkr_provider.py`)

```python
class TestResolveInstrument:
    @pytest.mark.asyncio
    async def test_resolves_futures_contract(self, provider, mock_ib):
        from src.core.models import AssetClass

        mock_detail = MagicMock()
        mock_detail.contract.localSymbol = "ESH6"
        mock_detail.longName = "E-mini S&P 500"
        mock_detail.contract.exchange = "CME"
        mock_detail.contract.symbol = "ES"
        mock_detail.contract.lastTradeDateOrContractMonth = "20260320"
        mock_detail.minTick = 0.25
        mock_detail.contract.multiplier = "50"

        mock_ib.reqContractDetails.return_value = [mock_detail]
        provider._ib = mock_ib

        instrument = await provider.resolve_instrument("ES")

        assert instrument is not None
        assert instrument.symbol == "ESH6"
        assert instrument.asset_class == AssetClass.FUTURES
        assert instrument.tick_size == 0.25

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_symbol(self, provider, mock_ib):
        mock_ib.reqContractDetails.return_value = []
        provider._ib = mock_ib
        result = await provider.resolve_instrument("XXXXXX")
        assert result is None
```

**Step 2: Add `resolve_instrument` to `src/providers/ibkr.py`**

```python
    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a symbol query to an Instrument via IBKR contract details."""
        if not self._ib:
            return None
        try:
            # Try as futures first (most common for this platform)
            contract = Future(symbol=query)
            details = self._ib.reqContractDetails(contract)
            if details:
                d = details[0]
                c = d.contract
                return Instrument(
                    symbol=c.localSymbol or c.symbol,
                    name=getattr(d, "longName", ""),
                    asset_class=AssetClass.FUTURES,
                    exchange=c.exchange,
                    base=c.symbol,
                    expiry=c.lastTradeDateOrContractMonth,
                    tick_size=float(d.minTick),
                    point_value=float(c.multiplier or 0),
                    provider_meta={"con_id": c.conId},
                )
        except Exception as e:
            logger.debug("resolve_instrument futures lookup failed", query=query, error=str(e))
        return None
```

**Step 3: Update `src/providers/__init__.py`**

```python
"""
IndicAgent data providers.

Usage:
    from src.providers import IBKRProvider
    from src.providers.base import DataProvider, Tick, OHLCVBar
"""
from src.providers.base import DataProvider, OHLCVBar, Tick
from src.providers.ibkr import IBKRProvider

__all__ = ["DataProvider", "IBKRProvider", "OHLCVBar", "Tick"]
```

**Step 4: Run all provider tests**

```bash
pytest tests/unit/providers/ -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/providers/ tests/unit/providers/
git commit -m "feat: IBKRProvider.resolve_instrument + providers __init__ exports"
```

---

## Task 8: Refactor `high_frequency_tws_daemon.py` to use `IBKRProvider`

**Context:** The daemon currently contains all IBKR connection/subscription/tick-normalization logic. We extract that to `IBKRProvider` (already done). The daemon becomes a thin orchestrator: get provider → connect → stream ticks → publish to Redis.

**Step 1: Run existing daemon tests first (baseline)**

```bash
pytest tests/unit/daemons/ -v
```
All should PASS.

**Step 2: Refactor the daemon**

Key changes to `production/daemons/high_frequency_tws_daemon.py`:

- Remove direct `ib_insync` imports (`IB`, `Future`, `Ticker`)
- Remove `connect_tws()`, `subscribe_to_contracts()`, `on_pending_tickers()`, `_build_tick_data()` methods
- Add `self.provider: IBKRProvider` as the single IBKR interface
- `connect_tws()` → `self.provider = IBKRProvider(host, port, client_id); await self.provider.connect()`
- Tick subscription → `async for tick in self.provider.stream_ticks(symbols)`
- 1m bar polling → `self.provider.fetch_historical_bars(symbol, "1m", start, end)` (kept as internal polling cycle)
- Tick accumulator (`_update_tick_accumulator`, provisional bar flush) stays in the daemon — it's a daemon-level optimization

**Key daemon `run()` loop after refactor:**

```python
async def _tick_loop(self):
    """Consume ticks from provider and publish to Redis."""
    symbols = [c["symbol"] for c in self.contracts]
    async for tick in self.provider.stream_ticks(symbols):
        stream_name = sk_market(self.env_prefix, tick.symbol, "tick")
        await self.async_redis.xadd(
            stream_name,
            tick.model_dump(mode="json"),
            maxlen=10000,
            approximate=True,
        )
        self._update_tick_accumulator(tick.symbol, {"last": tick.price, "volume": tick.size or 0}, datetime.now())
```

**Step 3: Update daemon tests**

Existing daemon tests test `_update_tick_accumulator`, `_flush_provisional_bar`, etc. — those stay unchanged since that code remains in the daemon. Only update imports if any test imports `HighFrequencyTWSDaemon` and tests `connect_tws` or `subscribe_to_contracts` directly.

```bash
pytest tests/unit/daemons/ -v
```
Expected: all PASS

**Step 4: Run full suite**

```bash
pytest tests/ -v -q
```
Expected: all PASS

**Step 5: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py tests/unit/daemons/
git commit -m "refactor: daemon delegates IBKR connection and ticks to IBKRProvider"
```

---

## Task 9: Refactor `historical_backfill.py` — use `IBKRProvider`, delete `aggregate_1m_to_tf`

**Context:** The backfill script has its own `IBKRFetcher` class and a `aggregate_1m_to_tf()` function. Both get deleted. The script uses `IBKRProvider.qualify_instrument()` + `IBKRProvider.fetch_historical_bars()` for data fetching. For bar aggregation, we no longer build 5m/15m/1h in Python — the script only fetches and stores 1m bars. TimescaleDB continuous aggregates (Task 10) handle the rest.

**Step 1: Delete tests for functions being removed**

In `tests/unit/test_historical_backfill.py`:
- Delete `TestTimeBucket` class entirely
- Delete `TestAggregate1mToTf` class entirely
- Keep all other tests (plugin replay, DB storage, etc.)

**Step 2: Run remaining backfill tests to confirm baseline**

```bash
pytest tests/unit/test_historical_backfill.py -v
```
All remaining tests should PASS.

**Step 3: Refactor `historical_backfill.py`**

Replace `IBKRFetcher` class and all usages with `IBKRProvider`:

```python
# Old import (delete):
# from src.providers.ibkr import IBKRFetcher  (doesn't exist yet — it's inline in the script)

# New import:
from src.providers import IBKRProvider
```

Replace `IBKRFetcher` instantiation:
```python
# Old:
fetcher = IBKRFetcher(host, port, client_id)
fetcher.connect()
bars = fetcher.fetch_bars(symbol, days)

# New:
provider = IBKRProvider(host=host, port=port, client_id=client_id)
asyncio.run(provider.connect())
for instrument in settings.contracts:
    asyncio.run(provider.qualify_instrument(instrument))
    bars = asyncio.run(provider.fetch_historical_bars(
        symbol=instrument.symbol,
        timeframe="1m",
        start=start_dt,
        end=end_dt,
    ))
    # store bars in DB
```

Delete:
- `IBKRFetcher` class (entire class)
- `aggregate_1m_to_tf()` function
- `time_bucket()` function
- The TF aggregation loop (`for tf_name, tf_min in TF_MINUTES.items()`) — only `"1m"` bars are stored now
- `TF_MINUTES` and `DEFAULT_TIMEFRAMES` constants (or reduce to just `["1m"]`)

**Step 4: Run full backfill tests**

```bash
pytest tests/unit/test_historical_backfill.py -v
```
Expected: all remaining tests PASS

**Step 5: Run full suite**

```bash
pytest tests/ -v -q
```
Expected: all PASS

**Step 6: Commit**

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "refactor: backfill uses IBKRProvider, delete aggregate_1m_to_tf and IBKRFetcher"
```

---

## Task 10: TimescaleDB continuous aggregates migration

**Files:**
- Create: `db/migrations/v1.2.0_continuous_aggregates.sql`
- Modify: `db/db_setup.sh` (to run the new migration)

**Step 1: Check existing migrations directory**

```bash
ls db/migrations/
```
Note the existing migration filenames and numbering convention.

**Step 2: Create the migration file**

```sql
-- db/migrations/v1.2.0_continuous_aggregates.sql
-- TimescaleDB continuous aggregates: 5m, 15m, 1h bars from 1m hypertable.
--
-- These views auto-materialize as new 1m bars are inserted into market_data_ohlcv.
-- Query them exactly like tables: SELECT * FROM market_data_5m WHERE symbol = 'ESH6'.
-- Python aggregate_1m_to_tf() is no longer needed.

-- 5-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', timestamp) AS timestamp,
    symbol,
    first(open, timestamp)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    last(close, timestamp)  AS close,
    sum(volume)             AS volume
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('5 minutes', timestamp), symbol
WITH NO DATA;

-- 15-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', timestamp) AS timestamp,
    symbol,
    first(open, timestamp)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    last(close, timestamp)  AS close,
    sum(volume)             AS volume
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('15 minutes', timestamp), symbol
WITH NO DATA;

-- 1-hour bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS timestamp,
    symbol,
    first(open, timestamp)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    last(close, timestamp)  AS close,
    sum(volume)             AS volume
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('1 hour', timestamp), symbol
WITH NO DATA;

-- Auto-refresh policies: TimescaleDB updates these every minute,
-- covering the last hour of data.
SELECT add_continuous_aggregate_policy('market_data_5m',
    start_offset  => INTERVAL '2 hours',
    end_offset    => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => true);

SELECT add_continuous_aggregate_policy('market_data_15m',
    start_offset  => INTERVAL '2 hours',
    end_offset    => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => true);

SELECT add_continuous_aggregate_policy('market_data_1h',
    start_offset  => INTERVAL '4 hours',
    end_offset    => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => true);
```

**Step 3: Update `db/db_setup.sh`** to run the new migration in order (after existing migrations).

**Step 4: Apply the migration**

```bash
psql postgresql://postgres:postgres@localhost:5432/indicagent \
  -f db/migrations/v1.2.0_continuous_aggregates.sql
```
Expected: CREATE MATERIALIZED VIEW (x3), no errors.

**Step 5: Verify views exist**

```bash
psql postgresql://postgres:postgres@localhost:5432/indicagent \
  -c "\dv market_data*"
```
Expected: `market_data_5m`, `market_data_15m`, `market_data_1h` listed.

**Step 6: Verify refresh policy**

```bash
psql postgresql://postgres:postgres@localhost:5432/indicagent \
  -c "SELECT view_name, schedule_interval FROM timescaledb_information.continuous_aggregate_policies;"
```
Expected: 3 rows, one per view.

**Step 7: Commit**

```bash
git add db/migrations/v1.2.0_continuous_aggregates.sql db/db_setup.sh
git commit -m "feat: TimescaleDB continuous aggregates for 5m, 15m, 1h bars"
```

---

## Task 11: Final verification

**Step 1: Run full test suite**

```bash
pytest tests/ -v -q
```
Expected: all tests PASS (476+ passing, 0 failing)

**Step 2: Verify `IBKRProvider` satisfies protocol at runtime**

```bash
python -c "
from src.providers import IBKRProvider
from src.providers.base import DataProvider
p = IBKRProvider('localhost', 7497, 1)
print('satisfies protocol:', isinstance(p, DataProvider))
"
```
Expected: `satisfies protocol: True`

**Step 3: Verify `Instrument` import works everywhere**

```bash
python -c "
from src.core.models import Instrument, AssetClass
from src.config.settings import Settings
s = Settings(_env_file=None)
print('contracts:', len(s.contracts))
print('first type:', type(s.contracts[0]).__name__)
print('asset_class:', s.contracts[0].asset_class)
"
```
Expected: `contracts: 22`, `first type: Instrument`, `asset_class: futures`

**Step 4: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "chore: data layer redesign complete — provider protocol, Instrument model, continuous aggregates"
```

---

## Success Checklist

- [ ] `Instrument` and `AssetClass` in `src/core/models.py`
- [ ] `IBKRContract` alias retained for zero-breakage transition
- [ ] `src/providers/base.py` — `DataProvider`, `Tick`, `OHLCVBar`
- [ ] `src/providers/ibkr.py` — `IBKRProvider` with all 6 protocol methods
- [ ] `isinstance(IBKRProvider(...), DataProvider)` is `True`
- [ ] Daemon delegates to `IBKRProvider`
- [ ] Backfill uses `IBKRProvider.fetch_historical_bars()` — `IBKRFetcher` deleted
- [ ] `aggregate_1m_to_tf()` deleted
- [ ] Continuous aggregate views created and refresh policies applied
- [ ] All 476+ tests pass
