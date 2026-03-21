# Feature Pipeline Renaissance Refactor — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Replaces:** `indicator_service.py`, `market_analysis_service.py`
**Scope:** bars → I1 → I2–I6 → I7 (signal generation) full pipeline refactor

---

## Problem Statement

The current intelligence pipeline has five structural violations of Renaissance principles:

### 1. Bar history lives in three places
`indicator_service` uses `OrderedDict`, `market_analysis_service` uses `deque(200)`, `signal_generator_service` uses `deque(200)`. Three independent copies of the same state with different implementations. Divergence is guaranteed over time. Bugs fixed in one are not fixed in others.

### 2. The DAG is a linear chain of Kafka hops
```
market.bars → indicator_service → Redpanda → market_analysis → Redpanda → signal_generator
```
Three Kafka round trips in the hot path. Each hop adds latency and an ordering risk. I6 cross-timeframe analysis can start before all symbols' I1 events for a given bar have arrived — a race condition that produces incorrect confluence scores.

### 3. HTF context is stale at I6
`market_analysis_service` reads 5m/15m/1h bar context from TimescaleDB aggregate views. These views reflect data written by `feature_writer_service`, which writes in batches. At the moment I6 runs, its HTF context may be 30–100ms stale — or more during high load. I6 confluence is computed against a different bar than the one that triggered it.

### 4. No per-bar computation model
There is no concept of "process this bar end-to-end." A bar arrives at indicator_service, I1 is computed, published to Kafka. Then market_analysis eventually picks it up and runs I2–I6. The bar and its derived features are computed in different processes with no shared coordination.

### 5. Stringly-typed message bus
The TWS daemon publishes bars as string dicts: `{"open": "6660.25", "volume": "423"}`. Every consumer re-parses strings. Type errors appear at runtime, not at the contract boundary.

---

## Renaissance Principles Applied

**Observation is not decision.** I1–I6 answer "what is the market doing?" I7 answers "what should the model do about it?" These are different problems. They belong in different services with a typed contract between them.

**Own the computation.** The feature vector for a bar — across all timeframes — must be computed from the same bar event. No DB queries in the hot path. No stale HTF context. One bar in, one complete observation vector out.

**Instrument everything.** Every published event carries its own `pipeline_latency_ms`. You always know if the pipeline is degrading.

**Reuse means shared modules, not shared state.** `BarHistory` and `BarAccumulator` live in `src/core/`, consumed by whichever service needs them. One implementation, one place to fix bugs.

---

## Architecture

### Service DAG

```
TWS Daemon
    │
    ▼  development.market.bars (BarMessage — typed)
    │
FeaturePipelineService                    [NEW — replaces indicator + market_analysis]
    │
    │  Internal per-bar execution (asyncio.gather across 61 symbols):
    │    BarHistory.append(bar_1m)
    │    BarAccumulator.update(bar_1m) → HTF bars
    │    BarHistory.append(HTF bars)
    │    I1 → I2 → I3 → I4 → I5 → I6   (sequential within symbol)
    │    I6 reads in-memory HTF state — no DB queries
    │    → IntelligenceEvent
    │
    ▼  development.intelligence.events (IntelligenceEvent — typed)
    │
    ├──► SignalGeneratorService (I7)       [SIMPLIFIED]
    │         regime gating, setup detection, signal_ledger write
    │         BarHistory seeded from IntelligenceEvents (no DB seed)
    │              └──► development.signals.events
    │                        └──► SignalLifecycleService  [UNCHANGED]
    │
    ├──► FeatureWriterService              [UNCHANGED]
    │         async DB persistence to intelligence_features
    │
    └──► AINarrativeService (I8)           [UNCHANGED]
```

### Services Deleted
- `indicagent-indicator` (indicator_service.py)
- `indicagent-market-analysis` (market_analysis_service.py)

### Services Added
- `indicagent-feature-pipeline` (feature_pipeline_service.py)

### Topics Retired
- `development.indicators` — was I1 output, no longer needed

### Topics Schema-Updated
- `development.market.bars` — string dict → typed BarMessage
- `development.intelligence.events` — JSONB dict → typed IntelligenceEvent

---

## Shared Modules

### `src/core/bar_history.py`

Single implementation of rolling bar window. Replaces three diverging implementations across indicator_service, market_analysis_service, and signal_generator_service.

```python
class BarHistory:
    def __init__(self, maxlen: int = 200) -> None
    def append(self, bar: BarMessage) -> None
    def get(self, symbol: str, tf: str) -> deque[BarMessage]
    def to_dataframe(self, symbol: str, tf: str) -> pd.DataFrame
    def is_warm(self, symbol: str, tf: str, min_bars: int) -> bool
    def seed(self, symbol: str, tf: str, bars: list[BarMessage]) -> None
```

- Pure class, no global state, no side effects
- Instantiated once per service, passed into plugin execution context
- `to_dataframe()` is the canonical path for indicator computation — replaces ad-hoc DataFrame construction in each service
- `is_warm()` gates plugin execution — no plugin runs on insufficient history

### `src/core/bar_accumulator.py`

Derives HTF bars from the 1m bar stream in-pipeline. Replaces DB aggregate view queries for HTF context.

```python
class BarAccumulator:
    def __init__(self, timeframes: list[str], session: TradingSession) -> None
    def update(self, bar_1m: BarMessage) -> list[BarMessage]
    # Returns [] on most bars, [BarMessage, ...] when HTF windows close
```

- Maintains one partial OHLCV accumulator per (symbol, tf)
- Window boundaries: 5m at :00/:05/:10, 15m at :00/:15/:30/:45, 1h at :00
- Session-aware: a partial bar at a session break is closed and emitted, not carried forward
- Does not synthesize bars for gaps — if no 1m bars arrived in a 5m window, no 5m bar is emitted

### `src/core/schemas/bar_message.py`

```python
class SessionType(str, Enum):
    RTH = "rth"           # Regular trading hours
    ETH = "eth"           # Extended / overnight
    CRYPTO = "crypto"     # 24/7
    FX = "fx"             # 24/5
    CLOSED = "closed"     # Market closed (should not produce bars)

class BarMessage(BaseModel):
    ts: datetime            # UTC-aware
    symbol: str
    tf: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: Literal["ibkr_named", "ibkr_seed", "htf_derived"]
    session_type: SessionType
    gap_preceding: bool     # True if previous expected bar was missing
```

`session_type` set by TWS daemon from instrument config. `gap_preceding` set by FeaturePipelineService when it detects a missing bar in BarHistory. `source="htf_derived"` for bars emitted by BarAccumulator.

### `src/core/schemas/intelligence_event.py`

```python
class IntelligenceEvent(BaseModel):
    ts: datetime
    symbol: str
    tf: str
    bar: BarOHLCV
    session_type: SessionType
    i1: I1Output
    i2: I2Output
    i3: I3Output
    i4: I4Output
    i5: I5Output
    smc: SMCOutput
    i6: I6Output
    computed_at: datetime
    pipeline_latency_ms: float   # bar_close_ts → publish delta
```

Fully typed. No JSONB dict key lookups. I7 deserializes with complete type safety. `pipeline_latency_ms` is mandatory — every event carries its own latency measurement.

---

## FeaturePipelineService — Internal Execution

### Startup

```
1. Connect to TimescaleDB
2. Query intelligence_features: last 200 bars per (symbol, tf)
   — one query with ROW_NUMBER() window function, not 61×5 queries
3. BarHistory.seed() for all (symbol, tf) pairs
4. Reconstruct BarAccumulator partial state from most recent 1m bars
5. Begin consuming development.market.bars
```

Seeding completes before consuming begins. The service does not process live bars with cold history.

### Per-bar execution

```python
async def _on_bar(self, bar: BarMessage) -> None:
    await asyncio.gather(
        *[self._process_symbol(bar) for bar in grouped_by_symbol],
        return_exceptions=True   # one symbol's exception doesn't block others
    )

async def _process_symbol(self, bar: BarMessage) -> None:
    self.bar_history.append(bar)
    htf_bars = self.bar_accumulator.update(bar)
    for htf_bar in htf_bars:
        self.bar_history.append(htf_bar)

    if not self.bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
        return   # not enough history — skip, don't publish partial events

    frames = self._build_plugin_frames(bar)
    event = self._run_plugin_tiers(bar, frames)
    await self._publish(event)
```

### Plugin tier execution

I1–I6 plugins run sequentially within a symbol, as before. Each tier's output is passed to the next. I6 reads HTF state from `bar_history` (in-memory, just updated by BarAccumulator) — no DB queries.

The plugin system — TIER_I1…TIER_I6 registration, plugin protocol, `registry.validate_tier()` — is unchanged. Plugins remain individual modules. Only their host changes.

---

## SignalGeneratorService — Simplification

### What changes
- Remove `bar_history` DB seed on startup — `BarHistory` is built from incoming `IntelligenceEvent` bars
- Remove `bar_history` as a separate maintained structure — use `BarHistory` module, populated from events
- Remove subscription to `development.indicators` (topic retired)
- Consume typed `IntelligenceEvent` instead of raw JSONB dict

### What stays identical
- `_regime_cache` — regime gating, unchanged
- `_cross_asset_cache` — cross-asset data injection, unchanged
- `_htf_intel_cache` — HTF intelligence injection, unchanged
- Plugin state per I7 plugin (chandelier, etc.) — unchanged
- Signal ledger write logic — unchanged
- TIER_I7 plugin execution — unchanged

---

## Quantified Improvements

| Dimension | Current | New | Delta |
|-----------|---------|-----|-------|
| Kafka hops in hot path | 3 | 1 | −67% |
| Bar history copies | 3× (OrderedDict + 2× deque) | 1× shared module | −67% memory |
| HTF staleness at I6 | 30–100ms+ (DB query) | ~0ms (in-pipeline) | eliminated |
| I6 ordering guarantee | None (race across symbols) | Guaranteed (in-process) | eliminates bug class |
| Signal latency (bar close → publish) | ~200–500ms | ~20–50ms | ~10× faster |
| Bar history seeding routines | 3 independent | 1 shared | simpler, consistent |
| Bar history implementations | 3 | 1 | eliminates divergence |
| Services in hot path | 3 | 1 | simpler ops |
| Systemd units managed | indicator + market-analysis + signal-gen | feature-pipeline + signal-gen | −1 unit |

---

## Migration Plan

### Step 1 — Build shared modules and new service (no live changes)
- `src/core/bar_history.py` + tests
- `src/core/bar_accumulator.py` + tests
- `src/core/schemas/bar_message.py`
- `src/core/schemas/intelligence_event.py`
- `services/feature_pipeline_service.py` + integration tests
- `systemd/indicagent-feature-pipeline.service`

### Step 2 — Update TWS daemon
- Publish `BarMessage` typed schema instead of string dict
- Set `session_type` from instrument config
- No change to topic name or Kafka key

### Step 3 — Cutover (single restart sequence)
```bash
sudo systemctl stop indicagent-indicator indicagent-market-analysis
sudo systemctl start indicagent-feature-pipeline
# validate: intelligence.events flowing, pipeline_latency_ms metric visible
```
Rollback: stop feature-pipeline, start indicator + market-analysis (TWS still publishing to same topic).

### Step 4 — Simplify SignalGeneratorService
- Remove DB seed, wire BarHistory to IntelligenceEvent stream
- Restart `indicagent-signal-generator`

### Step 5 — Cleanup
- Delete `services/indicator_service.py`
- Delete `services/market_analysis_service.py`
- Delete `systemd/indicagent-indicator.service`
- Delete `systemd/indicagent-market-analysis.service`
- Retire `development.indicators` Redpanda topic

---

## Testing Strategy

### Unit tests
- `BarHistory`: append, maxlen eviction, `to_dataframe()`, `is_warm()`, seed
- `BarAccumulator`: 5m/15m/1h window boundaries, session break close, no bar synthesized for gaps
- `BarMessage` + `IntelligenceEvent`: serialization round-trip, all fields present
- All existing I1–I6 plugin unit tests pass unchanged (plugin API not changing)

### Integration tests
- Feed 200 BarMessages → assert IntelligenceEvent has all tier fields populated
- Startup seed: load BarHistory from DB fixtures → process first bar → assert I6 has HTF context
- Gap detection: feed bars with a missing bar in sequence → assert `gap_preceding=True` on bar after gap

### Regression
- Run both old pipeline and FeaturePipelineService against identical 200-bar fixture
- Assert I1 indicator values numerically identical
- Assert I6 CTF scores within tolerance (HTF derivation from 1m bars vs DB views may differ at window edges — document delta, accept)

---

## Success Criteria

- `intelligence.events` published for all 61 symbols on every bar
- `pipeline_latency_ms` < 50ms at p99
- I6 `ctf_*` scores reflect in-pipeline HTF state (not DB query)
- All existing I1–I6 plugin unit tests pass
- `bar_history` module has one implementation used by both FeaturePipelineService and SignalGeneratorService
- `indicagent-indicator` and `indicagent-market-analysis` systemd units do not exist
- No `float(bar["open"])` string coercions anywhere in the codebase

---

## What Does Not Change

- TWS daemon bar polling logic (bars come from IBKR, not tick aggregation)
- Plugin system: TIER_I1…TIER_I7, plugin protocol, registry validation
- All I1–I7 plugin implementations
- FeatureWriterService, SignalLifecycleService, AINarrativeService, LLMWriterService, CrossAssetService, API
- `development.market.bars` topic name and Kafka key convention
- TimescaleDB schema — `intelligence_features`, `signal_ledger` unchanged
- Dashboard and SSE layer — unchanged
