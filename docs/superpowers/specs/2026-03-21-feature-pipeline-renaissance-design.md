# Feature Pipeline Renaissance Refactor — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Replaces:** `indicator_service.py`, `market_analysis_service.py`, `timeframes_builder_service.py`
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
`market_analysis_service` reads 5m/15m/1h bar context from TimescaleDB aggregate views. These views reflect data written by `feature_writer_service` in batches. At the moment I6 runs, its HTF context may be 30–100ms stale. I6 confluence is computed against a different bar than the one that triggered it.

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
FeaturePipelineService              [NEW — replaces indicator + market_analysis + timeframes_builder]
    │
    │  Internal per-bar execution (bounded asyncio.gather across 61 symbols):
    │    BarHistory.append(bar_1m)
    │    BarAccumulator.update(bar_1m) → HTF bars
    │    BarHistory.append(HTF bars)
    │    I1 → I2 → I3 → I4 → I5 → I6   (sequential within symbol)
    │    I6 reads in-memory HTF state — no DB queries
    │    → IntelligenceEvent
    │
    ├──► development.market.bars.htf (BarMessage — typed)
    │         HTF bars published for downstream consumers
    │         └──► SignalLifecycleService  [UNCHANGED — still consumes HTF bars]
    │
    ▼  development.intelligence (IntelligenceEvent — typed)
    │
    ├──► SignalGeneratorService (I7)       [SIMPLIFIED]
    │         regime gating, setup detection, signal_ledger write
    │         BarHistory populated from IntelligenceEvents (no DB seed)
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
- `indicagent-timeframes` (timeframes_builder_service.py) — replaced by BarAccumulator in-process

### Services Added
- `indicagent-feature-pipeline` (feature_pipeline_service.py)

### Topics Retired
- `development.indicators` — was I1 output, no longer needed

### Topics Schema-Updated
- `development.market.bars` — string dict → typed BarMessage
- `development.market.bars.htf` — still published, now by FeaturePipelineService via BarAccumulator
- `development.intelligence` — JSONB dict → typed IntelligenceEvent (topic name unchanged)

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
    def migrate_symbol(self, old_symbol: str, new_symbol: str) -> None  # for futures rolls
```

- Pure class, no global state, no side effects
- Instantiated once per service, passed into plugin execution context
- `to_dataframe()` is the canonical path for indicator computation
- `is_warm()` gates plugin execution — no plugin runs on insufficient history
- `migrate_symbol()` used by roll handler to move bar history to new contract key

### `src/core/bar_accumulator.py`

Derives HTF bars from the 1m bar stream in-pipeline. Replaces `timeframes_builder_service` and eliminates DB aggregate view queries for HTF context at I6.

```python
class BarAccumulator:
    def __init__(self, timeframes: list[str], session: TradingSession) -> None
    def update(self, bar_1m: BarMessage) -> list[BarMessage]
    # Returns [] on most bars, [BarMessage, ...] when HTF windows close
    def current_partial(self, tf: str) -> BarMessage | None
    # Returns in-progress partial bar for a given timeframe (for startup state restore)
```

- Maintains one partial OHLCV accumulator per tf
- Window boundaries: 5m at :00/:05/:10/:15…, 15m at :00/:15/:30/:45, 1h at :00
- Session-aware: a partial bar at a session break is closed and emitted, not carried forward
- Does not synthesize bars for gaps — if no 1m bars arrived in a 5m window, no 5m bar is emitted
- Completed HTF bars are both (a) injected into BarHistory and (b) published to `market.bars.htf`

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

### `IntelligenceEvent` — extend existing schema

The existing `IntelligenceEvent` in `src/intelligence/schemas.py` is extended with two new fields. Do NOT create a new class — extend in place to avoid breaking import sites.

```python
# Added to existing IntelligenceEvent in src/intelligence/schemas.py:
session_type: SessionType = SessionType.RTH      # which session produced this bar
pipeline_latency_ms: float = 0.0                 # bar_close_ts → publish delta
```

All existing i1/i2/i3/i4/i5/smc/i6 JSONB tier fields are retained for backward compatibility with FeatureWriterService and AINarrativeService. Migration to fully typed tier output models (I1Output, I2Output, etc.) is deferred to a follow-up phase.

---

## FeaturePipelineService — Internal Execution

### Startup

```
1. Connect to TimescaleDB
2. Primary seed: query intelligence_features for last 200 bars per (symbol, tf)
   — single ROW_NUMBER() window query, not 61×5 queries
   — filter by active contracts from get_active_contracts()
3. Fallback seed: if intelligence_features has < min_bars_for_tf(tf) rows for a
   (symbol, tf) pair, fill from market_data_ohlcv
4. BarHistory.seed() for all (symbol, tf) pairs
5. Reconstruct BarAccumulator partial state:
   — determine last HTF window boundary from seeded 1m bars
   — replay 1m bars from development.market.bars Redpanda topic
     (seek to last 5m window boundary timestamp, ~5 minutes of messages)
   — this restores the in-progress partial accumulator without a DB query
6. Re-publish last known IntelligenceEvent per (symbol, tf) to development.intelligence
   — SSE broadcaster replays topic history but this ensures fresh state
     is immediately available for the dashboard on service restart
7. Subscribe to development.system.events for roll events
8. Begin consuming development.market.bars
```

Seeding completes before consuming begins. The service does not process live bars with cold history.

### Per-bar execution

```python
_SEM = asyncio.Semaphore(min(32, (os.cpu_count() or 4) * 2))

async def _on_bars(self, bars: list[BarMessage]) -> None:
    """Called once per Kafka poll — bars is all messages in the batch."""
    async def _bounded(bar: BarMessage) -> None:
        async with _SEM:
            await self._process_symbol(bar)
    await asyncio.gather(*[_bounded(b) for b in bars], return_exceptions=True)

async def _process_symbol(self, bar: BarMessage) -> None:
    self.bar_history.append(bar)
    htf_bars = self.bar_accumulator.update(bar)
    for htf_bar in htf_bars:
        self.bar_history.append(htf_bar)
        await self._publish_htf(htf_bar)   # → development.market.bars.htf

    if not self.bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
        return   # not enough history — skip

    frames = self._build_plugin_frames(bar)
    event = self._run_plugin_tiers(bar, frames)
    await self._publish_intelligence(event)
```

The `asyncio.Semaphore` bounds concurrent symbol processing to `min(32, cpu_count×2)`. This prevents thread pool exhaustion when all 61 symbols arrive in a single Kafka poll batch. One symbol's exception does not block others (`return_exceptions=True`).

### Plugin tier execution

I1–I6 plugins run sequentially within a symbol. Each tier's output is passed to the next. I6 reads HTF state from `bar_history` — no DB queries.

**CPU-bound plugin execution — `asyncio.to_thread` with per-key locks:**
CPU-bound plugins (GARCH, HMM) must not block the event loop. FeaturePipelineService uses the same pattern as `market_analysis_service` today: each plugin call is wrapped with `asyncio.to_thread(_sync_compute)` backed by per-`(plugin, symbol, tf)` threading locks. Plugins mutate `_state` during `compute_full()` and are not thread-safe — the lock prevents concurrent calls to the same plugin instance for the same (symbol, tf). The semaphore provides inter-symbol parallelism; the per-key lock provides intra-plugin safety. Reference: `market_analysis_service.py` lines 246–260.

**`smc_trend_direction` rename:**
After SMC plugins run, `trend_direction` in the SMC result dict is renamed to `smc_trend_direction` before merging into `frames["features"]`. Without this, SMC's `trend_direction` overwrites `I3Structure.trend_direction` in the flat features dict, and every I4–I6 plugin consuming `trend_direction` from `frames["features"]` gets the wrong value. This rename must be preserved exactly as in `market_analysis_service.py` lines 293–295.

**`_prev_i1_features` for I2 crossover detection:**
FeaturePipelineService maintains `_prev_i1_features: dict[str, Any]` keyed by `f"{symbol}:{tf}"`. After I1 runs, the result is injected into the next bar's plugin frames as `frames["prev_features"]` — exactly as `market_analysis_service` does today. This is required for I2 composite plugins (MACDEvents, RSIEvents) to detect crossovers correctly.

```python
frames["prev_features"] = self._prev_i1_features.get(f"{bar.symbol}:{bar.tf}", {})
# ... run I1 ...
self._prev_i1_features[f"{bar.symbol}:{bar.tf}"] = i1_result
```

### Futures roll handling

FeaturePipelineService subscribes to `topic_system_events()` and handles roll events with the same logic as `indicator_service._handle_roll_event()` today:

1. `BarHistory.migrate_symbol(old_symbol, new_symbol)` — move bar history to new contract key
2. Adjust price-sensitive I1 plugin state (Bollinger bands, Keltner channels, Donchian channels) by `roll_gap` — prevents incorrect levels after contract expiry
3. Log roll event with old/new symbol, roll gap, and adjusted plugin count

Without roll handling, I1 plugins track pre-roll price levels after contract expiry and produce incorrect indicator values for the entire new contract's life.

The plugin system — TIER_I1…TIER_I6 registration, plugin protocol, `registry.validate_tier()` — is unchanged. Plugins remain individual modules. Only their host changes.

---

## SignalGeneratorService — Simplification

### What changes
- Remove `bar_history` DB seed on startup — `BarHistory` module is populated by appending bars extracted from incoming `IntelligenceEvent.bar` fields
- Remove subscription to `development.indicators` (topic retired)
- Consume typed `IntelligenceEvent` (extended schema) instead of raw JSONB dict

### What stays identical
- `_regime_cache` — regime gating, unchanged
- `_cross_asset_cache` — cross-asset data injection, unchanged
- `_htf_intel_cache` — HTF intelligence injection, unchanged
- `_plugin_states` keyed by `(plugin_name, symbol, tf)` — I7 plugin state (chandelier exit, cooldown counters, Kalman filter) is **not** persisted across restarts and resets on service start. This is acceptable and intentional — do not attempt to persist or seed I7 state during simplification.
- `frames["pattern_weights"]` injection via `pattern_reliability` TTL cache — this DB query stays in `SignalGeneratorService`, not in `FeaturePipelineService`. It is the only DB touch remaining in the signal generator after seed removal.
- Signal ledger write logic — unchanged
- TIER_I7 plugin execution — unchanged

---

## Quantified Improvements

| Dimension | Current | New | Delta |
|-----------|---------|-----|-------|
| Kafka hops in hot path | 3 | 1 | −67% |
| Bar history implementations | 3 (OrderedDict + 2× deque) | 1 shared module | eliminates divergence |
| HTF staleness at I6 | 30–100ms+ (DB query) | ~0ms (in-pipeline) | eliminated |
| I6 ordering guarantee | None (race across symbols) | Guaranteed (in-process) | eliminates bug class |
| Signal latency (bar close → publish) | ~200–500ms | ~20–50ms | ~10× faster |
| Bar history seeding routines | 3 independent (diverging) | 1 shared | consistent |
| Services in hot path | 3 | 1 | simpler ops |
| Systemd units managed | 3 (indicator + market-analysis + timeframes) | 1 (feature-pipeline) | −2 units |

Note: raw memory saved from bar history unification is modest (~5–7MB total). The correctness benefit — one implementation, no divergence — is the primary gain.

---

## Migration Plan

### Step 1 — Build shared modules and new service (no live changes)
- `src/core/bar_history.py` + unit tests (including `migrate_symbol`)
- `src/core/bar_accumulator.py` + unit tests (including session break, partial state restore)
- `src/core/schemas/bar_message.py` (BarMessage + SessionType)
- Extend `src/intelligence/schemas.py` IntelligenceEvent (add `session_type`, `pipeline_latency_ms`)
- `services/feature_pipeline_service.py` (with roll handler, prev_features, bounded semaphore)
- Integration tests
- `systemd/indicagent-feature-pipeline.service`

### Step 2 — Update TWS daemon
- Publish `BarMessage` typed schema instead of string dict
- Set `session_type` from instrument config at publish time
- No change to topic name or Kafka key

### Step 3 — Cutover (single restart sequence)
```bash
sudo systemctl stop indicagent-indicator indicagent-market-analysis indicagent-timeframes
sudo systemctl start indicagent-feature-pipeline
# validate: development.intelligence flowing, pipeline_latency_ms metric visible,
#           development.market.bars.htf flowing (signal-lifecycle depends on it)
```
Rollback: stop feature-pipeline, start indicator + market-analysis + timeframes.

### Step 4 — Simplify SignalGeneratorService
- Remove DB seed, wire BarHistory to IntelligenceEvent stream
- Restart `indicagent-signal-generator`

### Step 5 — Cleanup
- Delete `services/indicator_service.py`
- Delete `services/market_analysis_service.py`
- Delete `services/timeframes_builder_service.py`
- Delete systemd units for all three
- Retire `development.indicators` Redpanda topic

---

## Testing Strategy

### Unit tests
- `BarHistory`: append, maxlen eviction, `to_dataframe()`, `is_warm()`, seed, `migrate_symbol()`
- `BarAccumulator`: 5m/15m/1h window boundaries, session break close, no bar synthesized for gaps, `current_partial()` for startup restore
- `BarMessage` serialization round-trip
- `IntelligenceEvent` backward compatibility: existing fields unchanged, new fields have defaults
- All existing I1–I6 plugin unit tests pass unchanged (plugin API not changing)

### Integration tests
- Feed 200 BarMessages → assert IntelligenceEvent has all tier fields populated, `pipeline_latency_ms` > 0
- Startup seed: load BarHistory from DB fixtures → process first bar → assert I6 has HTF context
- Gap detection: feed bars with a gap → assert `gap_preceding=True` on bar after gap
- Roll event: inject roll event → assert `BarHistory.migrate_symbol()` called, I1 state adjusted
- `_prev_features` continuity: feed 3 bars → assert I2 crossover detection correct on bar 2 and 3
- BarAccumulator partial restore: seed BarHistory with 12 1m bars (8 minutes into a 15m window), assert partial accumulator state is correct after replay

### Regression
- Run both old pipeline and FeaturePipelineService against identical 200-bar fixture
- Assert I1 indicator values numerically identical
- Assert I6 CTF scores within tolerance (HTF derivation from 1m bars vs DB views may differ at window edges — document delta, accept)

---

## Success Criteria

- `development.intelligence` published for all 61 symbols on every bar
- `development.market.bars.htf` published when HTF windows close — SignalLifecycleService unaffected
- `pipeline_latency_ms` < 50ms at p99
- I6 `ctf_*` scores reflect in-pipeline HTF state (not DB query)
- All existing I1–I6 plugin unit tests pass
- `BarHistory` module has one implementation used by both FeaturePipelineService and SignalGeneratorService
- `indicagent-indicator`, `indicagent-market-analysis`, `indicagent-timeframes` systemd units do not exist
- No `float(bar["open"])` string coercions in the codebase
- Roll events handled correctly: bar history migrated, I1 price state adjusted by roll gap
- I2 crossover detection correct on bar 2+ (prev_features injected)

---

## What Does Not Change

- TWS daemon bar polling logic (bars come from IBKR, not tick aggregation)
- Plugin system: TIER_I1…TIER_I7, plugin protocol, registry validation
- All I1–I7 plugin implementations
- FeatureWriterService, SignalLifecycleService, AINarrativeService, LLMWriterService, CrossAssetService, API
- `development.market.bars` topic name and Kafka key convention
- `development.intelligence` topic name (only schema extended, not renamed)
- TimescaleDB schema — `intelligence_features`, `signal_ledger` unchanged
- Dashboard and SSE layer — unchanged
- `src/intelligence/schemas.py` import paths — IntelligenceEvent is extended in-place, not moved
