# Data Layer Redesign — Design Document

**Date:** 2026-02-21
**Status:** Approved
**Scope:** Provider abstraction, generic instrument model, TimescaleDB continuous aggregates

---

## Problem Statement

The current data layer is tightly coupled to Interactive Brokers (IBKR):

- `IBKRContract` model is IBKR-specific in name and implied usage
- The high-frequency daemon imports `ib_insync` directly with no abstraction boundary
- `IBKRFetcher` in `historical_backfill.py` is a standalone class, duplicating connection logic
- Higher timeframe bars (5m, 15m, 1h) are built manually in Python — redundant given TimescaleDB
- Settings are `ib_host / ib_port / ib_client_id` with no generic provider concept

**Goal:** Make the data layer provider-agnostic so that:
1. Any broker or data feed can be added by implementing a single protocol
2. The pipeline (Redis → plugins → signals) is completely unaware of which provider is active
3. TimescaleDB handles bar aggregation natively — no Python aggregation code

---

## Design Decisions

### Decision 1: Provider abstraction via Protocol (not ABC)

Python `typing.Protocol` (structural subtyping) over `abc.ABC`. Providers don't need to import a base class — they just implement the interface. Makes third-party integrations clean.

### Decision 2: Async iterator for tick streaming

`stream_ticks()` returns an `AsyncIterator[Tick]`. The IBKR implementation bridges ib_insync's callback system to an `asyncio.Queue`, then yields from it. This pattern already exists in `AsyncTickPublisher` — we're formalizing it. Future REST/WebSocket providers (Alpaca, TradeStation) map naturally to async iterators.

### Decision 3: 1m bars as the only stored timeframe

Store only `1m` OHLCV in `market_data_ohlcv`. TimescaleDB continuous aggregates materialize 5m, 15m, 1h automatically. Python aggregation code (`aggregate_1m_to_tf()`) is deleted.

### Decision 4: Futures-specific fields remain, become optional

`base`, `expiry`, `point_value` stay on `Instrument` but are optional (empty/zero for equities and crypto). No separate model hierarchy needed — the `asset_class` field carries the semantic distinction.

### Decision 5: Provider routing deferred

No multi-provider routing, config-driven provider selection, or failover logic in this iteration. One provider per deployment. When a second provider is needed, implementing the protocol is sufficient — no routing infrastructure required.

---

## Architecture

### New directory: `src/providers/`

```
src/providers/
├── __init__.py          # exports: DataProvider, IBKRProvider, Tick, OHLCVBar
├── base.py              # DataProvider protocol + normalized wire models
└── ibkr.py              # IBKRProvider — wraps ib_insync
```

### Data flow (unchanged externally, clean internally)

```
User config (symbols, provider)
        ↓
IBKRProvider (or future: AlpacaProvider, TradeStationProvider)
        ↓ Tick / OHLCVBar (normalized)
market_data_daemon.py (thin orchestrator)
        ↓
Redis streams (ticks: ephemeral, 1m bars: short TTL)
        ↓
TimescaleDB market_data_ohlcv (1m stored)
        ↓ (continuous aggregates — auto-materialized)
market_data_5m / market_data_15m / market_data_1h views
        ↓
I1 → I7 pipeline (unchanged)
```

---

## Models

### `Instrument` (replaces `IBKRContract`)

Location: `src/core/models.py`

```python
class AssetClass(StrEnum):
    FUTURES = "futures"
    EQUITY  = "equity"
    CRYPTO  = "crypto"
    FX      = "fx"
    OPTION  = "option"

class Instrument(BaseModel):
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
    # Provider-specific extras — do not add provider fields to core model
    provider_meta: dict = {}
```

`Settings.contracts` changes type from `list[IBKRContract]` to `list[Instrument]`. All IBKR futures contracts in the default list gain `asset_class=AssetClass.FUTURES`. All existing fields map 1:1.

### Normalized wire models

Location: `src/providers/base.py`

```python
class Tick(BaseModel):
    symbol: str
    timestamp: datetime
    price: float
    size: int | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    source: str           # provider name: "ibkr", "alpaca", etc.

class OHLCVBar(BaseModel):
    symbol: str
    timeframe: str        # "1m", "5m", "15m", "1h"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
```

---

## DataProvider Protocol

Location: `src/providers/base.py`

```python
from typing import AsyncIterator, Protocol, runtime_checkable
from datetime import datetime

@runtime_checkable
class DataProvider(Protocol):
    name: str             # "ibkr", "alpaca", "tradestation"

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...

    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a user-entered symbol string to a concrete Instrument.

        Each provider handles its own lookup:
        - IBKR: reqContractDetails
        - Alpaca: assets API
        - TradeStation: symbol search API
        Returns None if not found.
        """
        ...

    def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator that yields normalized Ticks as they arrive.

        Implementations push ticks into an asyncio.Queue and yield from it.
        The caller consumes: async for tick in provider.stream_ticks(symbols)
        """
        ...

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars for the given symbol and timeframe."""
        ...
```

---

## IBKRProvider

Location: `src/providers/ibkr.py`

Consolidates logic currently split across:
- `high_frequency_tws_daemon.py` (connection, subscriptions, tick callbacks)
- `historical_backfill.py` `IBKRFetcher` class (historical bar fetching)

**Tick bridge pattern:**
```
ib_insync pendingTickersEvent callback
    → normalize to Tick model
    → asyncio.Queue (bounded, backpressure-safe)
    → stream_ticks() async generator yields Tick
    → daemon loop publishes to Redis
```

**Key methods:**
- `connect()` — `ib.connect(host, port, client_id)`
- `disconnect()` — `ib.disconnect()`
- `is_connected()` — `ib.isConnected()`
- `resolve_instrument(query)` — `ib.reqContractDetails(contract)` lookup
- `stream_ticks(symbols)` — subscribe via `reqMktData`, yield from queue
- `fetch_historical_bars(...)` — `ib.reqHistoricalData()` with timeframe mapping

**Config:** `IBKRProvider` takes `host`, `port`, `client_id` directly — no dependency on `Settings`. The daemon passes these from settings. This keeps the provider testable in isolation.

---

## TimescaleDB Continuous Aggregates

New migration: `db/migrations/v1.2.0_continuous_aggregates.sql`

Three materialized views on `market_data_ohlcv` (1m hypertable):

```sql
-- 5-minute bars
CREATE MATERIALIZED VIEW market_data_5m
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
GROUP BY time_bucket('5 minutes', timestamp), symbol
WITH NO DATA;

-- 15-minute bars (same pattern)
-- 1-hour bars (same pattern)

-- Refresh policies (auto-update as new 1m bars arrive)
SELECT add_continuous_aggregate_policy('market_data_5m',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
```

**What gets deleted:** `aggregate_1m_to_tf()`, `time_bucket()`, and the TF aggregation loop in `historical_backfill.py` (~80 lines). Any service querying 5m/15m/1h queries the view instead.

---

## Files Changed

| File | Change |
|---|---|
| `src/core/models.py` | Add `AssetClass`, `Instrument`; keep `IBKRContract` as deprecated alias temporarily |
| `src/config/settings.py` | `IBKRContract` → `Instrument`, add `asset_class=AssetClass.FUTURES` to all defaults |
| `src/providers/__init__.py` | **New** — exports `DataProvider`, `IBKRProvider`, `Tick`, `OHLCVBar` |
| `src/providers/base.py` | **New** — `DataProvider` protocol, `Tick`, `OHLCVBar` |
| `src/providers/ibkr.py` | **New** — `IBKRProvider` implementation |
| `production/daemons/high_frequency_tws_daemon.py` | Delegate to `IBKRProvider`; remove IBKR-specific connection and tick logic |
| `production/scripts/historical_backfill.py` | Replace `IBKRFetcher` with `IBKRProvider.fetch_historical_bars()`; delete `aggregate_1m_to_tf()` |
| `db/migrations/v1.2.0_continuous_aggregates.sql` | **New** — 5m, 15m, 1h continuous aggregate views + refresh policies |
| `tests/unit/providers/` | **New** — `IBKRProvider` unit tests (mocked ib_insync) |
| `tests/unit/core/test_models.py` | Update for `Instrument`, `AssetClass` |
| `tests/unit/config/test_settings.py` | Update for renamed model |

---

## What Does NOT Change

- Redis stream schema (same keys, same field names — Tick maps cleanly to existing schema)
- Plugin pipeline (I1–I7) — completely unaffected
- `market_data_ohlcv` hypertable schema — we only add views on top of it
- Dashboard / SSE / API routes — unaffected
- `AsyncTickPublisher` — retained as-is; IBKRProvider feeds it

---

## Adding a Future Provider

To add Alpaca:
1. Create `src/providers/alpaca.py`
2. Implement `DataProvider` protocol (`connect`, `disconnect`, `is_connected`, `resolve_instrument`, `stream_ticks`, `fetch_historical_bars`)
3. Pass `AlpacaProvider` to the daemon instead of `IBKRProvider`
4. No other files change

---

## Success Criteria

- [ ] `IBKRContract` references replaced by `Instrument` across all files
- [ ] `src/providers/ibkr.py` passes all unit tests with mocked ib_insync
- [ ] Daemon delegates tick streaming and historical fetch to `IBKRProvider`
- [ ] `aggregate_1m_to_tf()` deleted; historical backfill uses continuous aggregates
- [ ] Continuous aggregate views queryable in TimescaleDB
- [ ] All 476 existing tests pass
- [ ] `isinstance(IBKRProvider(), DataProvider)` is `True` (runtime_checkable)
