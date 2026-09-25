# Data Layer Renaissance Refactor — Design Spec

**Last Updated:** 2026-05-02

**Status**: Approved
**Date**: 2026-03-21
**Phase**: 44.1 (inserted between Phase 44 and Phase 45)
**Author**: brainstorming session

---

## Problem Statement

The data ingestion pipeline from IBKR TWS through to I1 has five Renaissance violations that have caused repeated production incidents, most recently the PAXOS crypto freeze on 2026-03-21 where "market closed" was architecturally indistinguishable from "pipeline broken":

1. **Pull masquerading as push** — `reqHistoricalDataAsync` is called in a 60-second polling loop for live bar delivery. We already own a push feed: the existing `reqMktData` tick subscriptions. Bars should be built from ticks, not polled separately.
2. **Session model doesn't exist** — no object can answer "for BTCUSD right now, is a bar expected? When is the next one due?" Without this, gap detection is impossible and closed markets look like broken pipelines.
3. **Silent data loss** — `seen_bar_timestamps` silently drops bars with no audit trail. Every drop is an unaudited filtering decision — a Renaissance violation.
4. **Duplicated bar history** — `indicator_service` uses `OrderedDict`; `market_analysis_service` uses `deque`; `signal_generator_service` uses another `deque`. Same logical concept, three implementations, no shared contract.
5. **Stringly-typed pipeline** — `build_i1_message()` flattens typed data to string dicts with lossy serialization. Typed schemas validated at the boundary prevent entire classes of downstream bugs.

---

## Design

### Principles Applied

| Renaissance Demand | Design Decision |
|---|---|
| Push, never poll | Tick aggregator builds 1m bars from existing `reqMktData` feed — zero new subscriptions |
| Every instrument has a session | `InstrumentSession` per asset class, driven by existing `SESSION_REGISTRY` in `settings.py` |
| Never silently drop | Every missing bar produces an auditable `GapEvent` |
| One module, one job | 5 focused modules replace 1 God function |
| Typed end to end | `BarMessage` Pydantic schema, never flat string dict |
| Shared infrastructure | One `BarHistory` class used by all three services |
| No new IBKR subscription lines | Tick feed is already open — dual-use for bars AND OFI/CVD |

---

### Live Bar Delivery: Tick Aggregation (not `reqRealTimeBars`)

**Why not `reqRealTimeBars`:**
- We currently use 60 of 80 IBKR market data lines for tick subscriptions (`reqMktData`)
- Adding `reqRealTimeBars` for 60 symbols = 120 total lines, exceeding the 80-line limit
- `reqRealTimeBars` also only delivers 5-second bars requiring further aggregation
- The existing `_tick_buffers[symbol]` already receives all trade ticks

**The correct Renaissance approach — dual-use the tick feed:**
```
reqMktData (60 subscriptions, already open)
    │  raw ticks → TickAggregator[symbol]
    ├──→ TickAggregator closes bar at minute boundary → OHLCVBar
    └──→ tick_buffer retained for OFI/CVD computation (unchanged)
```

`TickAggregator` is a pure stateful module per symbol. It accumulates OHLCV from ticks and emits a completed `OHLCVBar` when the minute boundary is crossed. This is zero additional IBKR API calls, zero new subscriptions, and bars emit the moment the minute closes.

---

### New DAG

```
reqMktData ticks (60 subscriptions, already open)
         │  raw tick
         ▼
    TickAggregator        accumulates OHLCV; emits OHLCVBar at minute close
         │  OHLCVBar (raw)
         ▼
    BarValidator          price > 0, volume ≥ 0, symbol known
         │  ValidatedBar
         ▼
    SessionRouter         attaches session_type from InstrumentSession
         │  SessionTaggedBar
         ▼
    GapDetector           fires GapEvent if previous bar was missing
         │  BarMessage (typed) + optional GapEvent
         ▼
Kafka: development.market.bars  (typed BarMessage schema)
         │
         ├──→ indicator_service   → BarHistory → I1 plugins → development.indicators
         ├──→ market_analysis_service → BarHistory (same class) → I2–I6
         └──→ signal_generator_service → BarHistory (same class) → I7
```

**Cold-start seed path (once at startup per symbol, unchanged):**
```
reqHistoricalDataAsync (one call per symbol, never recurring)
    → BarHistory.seed(bars)
    → publish seeded I1 state
    → TickAggregator starts accumulating live ticks
```

---

### Module Specifications

#### `src/core/session_model.py` (new)

Per-instrument session state machine. Driven by the existing `SESSION_REGISTRY` in `src/config/settings.py` — no new session definitions, maps to existing `session_id` on each `Instrument`.

```python
class SessionType(str, Enum):
    RTH = "rth"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"
    OVERNIGHT = "overnight"       # futures 23/5
    CLOSED = "closed"             # weekend, exchange halt

class InstrumentSession:
    """Knows when bars are expected for one asset class.
    Constructed from the existing SESSION_REGISTRY entry for the instrument's session_id.
    """
    def current_session(self, now: datetime) -> SessionType
    def next_bar_due(self, tf: str, last_bar_ts: datetime) -> datetime
    def is_gap(self, tf: str, last_bar_ts: datetime, now: datetime) -> bool
```

**Session mapping from existing `session_id` values:**
- `futures_23_5` → `OVERNIGHT` during overnight, `RTH` during 09:30–16:15 ET
- `nyse` (ETFs) → `PRE_MARKET` / `RTH` / `AFTER_HOURS` / `CLOSED`
- `fx_24_5` → `OVERNIGHT` Mon–Fri, `CLOSED` Fri close → Sun open
- `crypto_24_7` → maps to observed PAXOS schedule; **does not change the `session_id` config** — the session model learns from actual bar arrival times (if expected bar doesn't arrive in N minutes → `CLOSED`)

**Note on PAXOS crypto:** The existing `session_id=crypto_24_7` in settings.py is retained as-is. `InstrumentSession` is tolerant: if a symbol with `crypto_24_7` produces no bars for >5 minutes during expected hours, `GapDetector` emits a gap event but does NOT crash or freeze. The session schedule is a guide, not a hard contract.

#### `src/core/bar_history.py` (new)

Single implementation replacing `OrderedDict` in `indicator_service`, `deque` in `market_analysis_service`, and `deque` in `signal_generator_service`.

```python
class BarHistory:
    """Gap-aware bar store for one (symbol, tf)."""
    def __init__(self, symbol: str, tf: str, maxlen: int = 200)
    def append(self, bar: BarMessage) -> None        # validates monotonic timestamps
    def seed(self, bars: list[BarMessage]) -> None   # cold-start population
    def get_dataframe(self, min_bars: int) -> pd.DataFrame | None
    def last_bar_ts(self) -> datetime | None
    def bar_count(self) -> int
```

#### `BarMessage` schema (new — `src/core/bar_schema.py`)

Typed Pydantic schema replacing the current flat string dict on `development.market.bars`.

```python
class BarMessage(BaseModel):
    symbol: str
    tf: str                          # required, never empty
    timestamp: datetime              # UTC-aware, always
    open: float
    high: float
    low: float
    close: float
    volume: int
    session_type: SessionType        # what session this bar came from
    arrival_latency_ms: float        # minutes_boundary → bar_emitted delta
    source: Literal["ibkr_tick_agg", "ibkr_seed"]
    gap_preceding: bool              # was the bar before this one missing?
```

**ML training value:** `session_type` and `gap_preceding` are features the current pipeline discards entirely. Phase 49 needs them as training labels.

#### `src/core/tick_aggregator.py` (new)

Pure stateful module. One instance per symbol. Accumulates ticks into OHLCV, emits a completed `OHLCVBar` at minute boundary.

```python
class TickAggregator:
    """Accumulates ticks into 1m OHLCV bars. Emits at minute boundary."""
    def on_tick(self, tick: RawTick) -> OHLCVBar | None  # returns bar only at close
    def reset(self) -> None                               # called on session open
```

`arrival_latency_ms` on the emitted bar = `(emit_time - minute_boundary).total_seconds() * 1000`. Measures how fast ticks accumulate after the minute closes.

#### `services/tws_daemon.py` (modified)

Remove `poll_1m_bars`, `seen_bar_timestamps`, `seen_bar_timestamps_order`, and the `_fetch_bars_for_symbol` polling function. The tick callback path gains:

1. `TickAggregator[symbol].on_tick(tick)` — accumulate; if returns `OHLCVBar`, proceed
2. `BarValidator.validate(bar)` — price sanity, symbol known
3. `SessionRouter.tag(bar, session)` — attach `session_type`
4. `GapDetector.check(bar, last_bar_ts)` — emit `GapEvent` if preceding bar missing
5. Publish `BarMessage` to `development.market.bars`

`TickAggregator`, `BarValidator`, `SessionRouter`, `GapDetector` are **pure modules, not services**. They run inline in `tws_daemon`. No new systemd services.

---

### What is Eliminated

| Current | Replaced By |
|---|---|
| `poll_1m_bars` 60s polling loop | `TickAggregator` in tick callback path |
| `seen_bar_timestamps` silent dedup | Architecturally impossible — ticks never repeat |
| `datetime.now()` naive timestamps | UTC-aware timestamps from tick receipt |
| 3× `BarHistory` implementations | One shared `src/core/bar_history.py` |
| Flat string dict Kafka messages | Typed `BarMessage` validated at source |
| "Closed vs broken" ambiguity | `SessionModel.is_gap()` distinguishes |
| Stochastic "No numeric types" error | Typed `BarMessage` → `BarHistory` → typed DataFrame |

### What is NOT Changed

- Kafka topic names and stream keys
- 60 existing `reqMktData` tick subscriptions (retained, dual-use)
- I1 plugin execution logic (plugins receive same DataFrame contract)
- All 27 I1 plugin implementations
- `reqHistoricalDataAsync` for DB cold-start seeding (kept, called once at startup)
- Roll monitor logic (stays in `tws_daemon`)
- `development.market.bars.htf` topic and HTF aggregation path

---

## Plan Breakdown (4 plans)

- **44.1-01**: `SessionType` enum + `InstrumentSession` class mapped to existing `SESSION_REGISTRY` + full test coverage for all 4 asset class schedules
- **44.1-02**: `TickAggregator` + `BarMessage` typed schema + `BarValidator` + `SessionRouter` + `GapDetector` modules with tests
- **44.1-03**: `tws_daemon` refactor — remove polling path, wire `TickAggregator` into tick callback, publish typed `BarMessage`, add `GapEvent` publication
- **44.1-04**: Shared `BarHistory` class + wire into all three services (`indicator_service`, `market_analysis_service`, `signal_generator_service`) replacing `OrderedDict`/`deque`

---

## Success Criteria

1. `bars_processed` counter advances every minute during live market hours for all 4 asset classes — driven by tick aggregation, not polling
2. When PAXOS closes on weekends, health check logs `session=closed` — no freeze, no error
3. `development.market.bars` Kafka messages deserialize to `BarMessage` without validation errors — `tf` is never empty
4. `gap_preceding=True` is emitted on the first bar after a session gap
5. All three services use `src/core/bar_history.py` — grep confirms no `OrderedDict`/`deque` bar history pattern in `indicator_service`, `market_analysis_service`, `signal_generator_service`
6. All existing I1 plugin unit tests pass unchanged
7. Stochastic plugin "No numeric types to aggregate" error does not appear in `indicator_service.log` after refactor
8. Zero new IBKR market data subscription lines added — stays at 60/80
