# Intelligence Stack Latency Reduction

**Version:** 1.0
**Status:** under-review
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** latency, performance, pipeline, parallelism, hot-path, renaissance, intelligence

---

## Executive Summary

The IndicAgent intelligence pipeline processes 91 plugins across 8 tiers (I1-I8) for 23 symbols × 4 timeframes = 92 data streams. Current architecture runs plugins sequentially within tiers, stores real-time features in TimescaleDB, and suppresses I7 signals by regime classification.

**Renaissance Capital Lens:** What would Jim Simons demand?

| Principle | Current Gap | Renaissance Demand |
|-----------|---------------|---------------------|
| Instrument everything | Metrics exist but don't capture execution patterns | Add: parallel worker utilization, hot store hit/miss, state transition rates |
| Let the system run | Sequential execution artificially throttles | Parallel execution at tier boundaries |
| Earn the right through proof | No A/B framework for changes | Feature flags + shadow mode before production |
| Segment relentlessly | Regime suppression is binary | Compute all, label with regime, let ML learn |
| Degrade gracefully | No fallback paths | Graceful degradation on errors |
| Data quality over model complexity | ✓ Clean data path | Maintain clean architecture |
| Never drop data | Feature store batching loses real-time visibility | Hot store preserves all real-time data |

---

## Current Architecture

### Pipeline Flow

```
IBKR TWS (10.0.0.33:7497)
  └─► DragonflyDB Streams (hot, sub-ms)
        └─► indicator_service (I1, 23 plugins)
              └─► indicators:SYMBOL:TF
                    └─► market_analysis_service (I2/I3/I4/I5/SMC/I6, ~55 plugins)
                          └─► intelligence:SYMBOL:TF
                                ├─► signal_generator_service (I7, 17 plugins + aggregation)
                                │     └─► signal_ledger (TimescaleDB)
                                │     └─► signals:SYMBOL:TF:aggregated
                                │           └─► ai_narrative_service (I8, LLM)
                                │                 └─► narratives:SYMBOL:TF
                                └─► feature_writer_service
                                      └─► intelligence_features (TimescaleDB, async batch)
```

### Plugin Distribution by Tier

| Tier | Plugin Count | Incremental Support | Current Execution |
|-------|--------------|---------------------|-------------------|
| I1 | 23 | ✓ All | Sequential per bar |
| I2 | 9 | ✗ Full recomputation | Sequential after I1 |
| I3 | 7 | ✗ Full recomputation | Sequential, reads OHLCV directly |
| I4 | 7 | ✗ Full recomputation | Sequential after I3 |
| I5 | 14 | ✗ Full recomputation | Sequential, reads I1 features |
| SMC | 13 | ✗ Full recomputation | Sequential after I1-I5 |
| I6 Conf | 1 | ✗ Full recomputation | Sequential, reads all prior tiers |
| I7 | 17 | ✗ Full recomputation | Sequential after I6 |
| **Total** | **91** | **23 incremental** | **Sequential within tiers** |

### Current Optimizations (In-Place)

1. **Multi-stream xreadgroup** — Single `xreadgroup` call for 92 streams (23 syms × 4 TFs), avoiding 9.2s sequential polling worst case
2. **Plugin cache + state isolation** — `_plugin_cache` eliminates per-bar registry lookups; `_plugin_states` isolates per-(plugin, symbol, tf) state
3. **Incremental I1** — `compute_next()` O(1) updates vs full window recompute; measured 141× speedup
4. **Batch DB writes** — feature_writer accumulates 50 rows, flushes every 5s
5. **Consumer groups** — Independent progress tracking per service, replay capability on restart

---

## Identified Bottlenecks

### 1. Sequential Plugin Execution (Primary)

**Impact:** High — Affects all tiers except I1
**Description:** Within each tier, plugins execute in a `for` loop even when they share no dependencies.

```python
# Current pattern in market_analysis_service.py
def _run_tier(plugins: list[str], tier: str, results: dict[str, Any]) -> None:
    for pname in plugins:  # SEQUENTIAL
        t0 = time.time()
        p = self._plugin_cache[pname]
        state_key = (pname, symbol, timeframe)
        p._state = self._plugin_states.setdefault(state_key, {})
        result = p.compute_full(frames)  # or compute_next
        self._plugin_states[state_key] = p._state
```

**Example:** I3 tier has 7 plugins with no shared dependencies (SwingDetector, SupportResistance, TrendStructure, MarketProfile, SessionLevels, AnchoredVWAP, FibonacciZones). All run sequentially even though they could compute simultaneously on the same bar.

**Math:** If each plugin takes 2ms, sequential = 14ms total. With 7 parallel workers on 7-core CPU = 2ms total (theoretical max = 1× max plugin time).

**Renaissance Lens:** "Let the system run. Don't artificially serialize when parallel is safe."

**Potential Speedup:** 2-7× depending on tier size and CPU cores

---

### 2. TimescaleDB as Real-Time Query Source

**Impact:** High — Affects signal_lifecycle_service
**Description:** Signal lifecycle queries `intelligence_features` to get bar close price, zone bounds, etc. on every signal update. This is a cold-tier read on a hot path.

```python
# signal_lifecycle_service queries TimescaleDB per bar
SELECT bar_close_price, entry_zone_low, entry_zone_high
FROM intelligence_features
WHERE symbol = $1 AND feature_ts = $2 AND feature_tf = $3
```

**Math:** DB round-trip latency: ~5-10ms on local network + query execution. Signal lifecycle runs every bar for all active signals. With 10 active signals = 50-100ms total DB overhead per bar.

**Renaissance Lens:** "Storage is cheap. Compute is expensive. Why recompute or query cold storage for real-time data?"

**Potential Speedup:** 0ms queries if hot in-memory store (100% elimination of DB round-trip)

---

### 3. Per-Bar I7 Condition Scanning

**Impact:** Medium — Affects signal_generator_service
**Description:** All 17 I7 plugins scan their conditions on every bar, even when no signal fires. For example, `MeanReversion` checks `rsi < 30 AND vol_expansion > 0` on every bar for every symbol/TF.

**Math:** 17 plugins × 23 syms × 4 TFs = 1,564 condition evaluations per minute (1m bars arrive ~23×/minute). Most bars result in no signal but compute is still performed.

**Renaissance Lens:** "Segment relentlessly. A state machine that fires on transition is more efficient than repeated scanning."

**Potential Speedup:** 80-95% reduction in I7 compute (most bars are no-ops in state machine model)

---

### 4. Regime Suppression vs. Regime Labeling

**Impact:** Strategic — Affects signal quality/learning
**Description:** Current regime gate suppresses entire I7 plugin categories based on HMM classification:
- Trend plugins suppressed when `hmm_regime = 0` (ranging)
- Mean-reversion plugins suppressed when `hmm_regime ∈ {1,2}` (trending)

**Renaissance Lens:** "A rule that works globally is weaker than one that works in a specific regime. Don't drop data that could contain signal."

**Problem:** We lose information. Mean-reversion setups in trending regimes might still be profitable (contrarian trades). Trend setups in ranging regimes might catch early regime shifts.

**Potential:** Compute all signals, label with `regime_context`, `hmm_regime`, `vol_regime`. Let ML/model performance data determine which signals work in which regimes.

---

### 5. Cross-Timeframe Redundant Computation

**Impact:** Low-Medium — Affects I1-I6
**Description:** I1-I6 compute independently on 4 timeframes with no data sharing. Regimes (HMM, GARCH) that don't change within 5m are recomputed identically on 5m, 15m, 1h, 4h.

**Example:** `HMMRegime` on 1m bar at 14:00:00 produces same state as 5m, 15m, 1h at same time period (assuming regime hasn't shifted).

**Renaissance Lens:** "Segment relentlessly. Compute once, share across applicable timeframes."

**Potential Speedup:** 10-30% reduction for regime/context plugins that can inherit from lower-TF results

---

### 6. LLM Blocking Narrative Generation

**Impact:** Low-Medium — Affects ai_narrative_service
**Description:** Each signal triggers a synchronous LLM call (60s timeout) before narrative is published. Sequential processing creates backlog.

**Math:** With 5 signals/minute and 60s avg LLM time = 300s/minute of compute. Service can only process 1 signal concurrently.

**Renaissance Lens:** "Degrade gracefully. LLM timeout is a single point of failure for narrative pipeline."

**Potential:** Memoization cache (similar signals = similar narratives), async queue with worker pool, or timeout/fallback to template narrative.

---

## Proposed Approaches

### Approach 1: Async Parallel Execution

**Concept:** Execute independent plugins concurrently within tiers using `asyncio` or thread pools.

**Architecture Change:**

```python
# New pattern: grouped concurrent execution
async def _run_tier_parallel(
    self,
    plugins: list[str],
    tier: str,
    symbol: str,
    timeframe: str,
    frames: dict[str, Any]
) -> dict[str, Any]:
    """Execute independent plugin groups concurrently."""
    # Build dependency graph within tier
    groups = self._build_independent_groups(plugins, tier)

    # Execute groups sequentially, but groups concurrently
    results: dict[str, Any] = {}
    for group in groups:
        group_results = await asyncio.gather(*[
            self._execute_plugin_safe(pname, symbol, timeframe, frames)
            for pname in group
        ])
        results.update(group_results)

    return results
```

**Implementation Details:**

1. **Dependency Analysis:** Build within-tier dependency graph from plugin `inputs` declarations
2. **Independent Groups:** Topologically sort within tier, group nodes with no edges between them
3. **Safe Concurrency:** Use thread-safe state swapping (`threading.Lock` per state_key) or asyncio-safe patterns
4. **Metrics:** Add `plugin_execution_parallel_ms`, `plugin_queue_wait_ms`, `tier_execution_parallel_speedup`

**Trade-offs:**

| Pro | Con |
|-----|-------|
| 2-4× speedup for compute-bound tiers | State access requires locking/async safety |
| Scales linearly with CPU cores | More complex debugging (race conditions) |
| No API changes — internal service refactor | Potential for state corruption if isolation fails |

**Renaissance Fit:** High — "Let the system run at natural parallel speed."

**Estimated Effort:** 3-5 days implementation, 2-3 days testing

---

### Approach 2: Hot Feature Store Layer

**Concept:** In-memory feature store with read/write-through to TimescaleDB. Real-time services read from hot store; feature writer syncs both.

**Architecture:**

```
intelligence:SYMBOL:TF (stream)
  └─► feature_writer_service
        ├─► Hot Feature Store (in-memory, Redis or pure Python)
        └─► TimescaleDB (async batch, cold)

Signal Lifecycle, Dashboard:
  └─► Hot Feature Store (sub-ms reads) ← primary
        └─► TimescaleDB (fallback only on miss)
```

**Implementation Details:**

1. **Hot Store Interface:**
   ```python
   class HotFeatureStore:
       """In-memory feature store with TTL eviction."""
       async def get(self, symbol: str, tf: str, ts: datetime) -> dict | None
       async def put(self, event: IntelligenceEvent) -> None
       async def get_range(self, symbol: str, tf: str, start: datetime, end: datetime) -> list[dict]
   ```

2. **TTL Management:** Evict entries older than configurable window (e.g., 2× TF duration) to keep memory bounded

3. **Metrics:** `hot_store_hit_rate`, `hot_store_memory_bytes`, `hot_store_eviction_rate`

**Trade-offs:**

| Pro | Con |
|-----|-------|
| Zero-latency real-time queries | Dual-write path (hot + cold) |
| Removes DB bottleneck on hot paths | Memory usage scales with window depth |
| Simplifies service code (no DB pooling for hot queries) | Cache invalidation complexity |

**Renaissance Fit:** High — "Never drop real-time data. Storage is cheap, compute is expensive."

**Estimated Effort:** 5-7 days implementation, 3-4 days testing

---

### Approach 3: Stateful I7 Detection

**Concept:** Revolutionize I7 from "per-bar condition scanning" to "stateful finite machines" that track conditions between bars and fire on transitions.

**Architecture Change:**

```python
# Current pattern (per-bar scanning)
class MeanReversionPlugin:
    def compute_full(self, windows: dict) -> dict:
        # Every bar: scan all conditions
        if rsi < 30 and vol_expansion > 0 and trend_confidence < 0.5:
            return {"signal": 1.0, ...}
        return {}

# New pattern (state machine)
class StatefulMeanReversionPlugin:
    """State machine tracking regime and signal transitions."""
    def compute_next(self, windows: dict) -> dict:
        # State: "idle" → "watching_oversold" → "signal" → "cooldown"
        state = self._state.get("state", "idle")
        rsi = windows["main"]["rsi_14"].iloc[-1]
        vol_exp = windows["main"]["vol_expansion"].iloc[-1]

        # Transition logic (only evaluated on state change)
        match state:
            case "idle":
                if rsi < 30:
                    self._state["state"] = "watching_oversold"
                    self._state["entered_at"] = datetime.now()
            case "watching_oversold":
                if vol_exp > 0:
                    self._state["state"] = "signal"
                    return {
                        "signal": 1.0,
                        "state_transition": "idle→watching→signal",
                        "state_duration_sec": (datetime.now() - self._state["entered_at"]).total_seconds()
                    }
            # ... more transitions

        return {}
```

**Implementation Details:**

1. **State Machine Design:** Model each I7 setup as a finite automaton with states and transitions
2. **Transition Conditions:** Only evaluate transition conditions on relevant state changes (e.g., RSI crossing threshold)
3. **Backward Compatibility:** Shadow mode runs both old and new paths to verify signal parity

**Trade-offs:**

| Pro | Con |
|-----|-------|
| 80-95% reduction in I7 compute | Paradigm shift — new mental model |
| Natural regime handling built in | More complex debugging (state graph visualization) |
| Faster signals (fire on transition, not bar close) | Requires rewriting all 17 I7 plugins |

**Renaissance Fit:** High — "Segment relentlessly. State machines encode regime-awareness by construction."

**Estimated Effort:** 2-3 weeks implementation, 1 week testing (largest change)

---

## Plugin-Level Inefficiencies: Per-Bar Full Recomputation

### Inefficiency 5: SwingDetector — Full Window Scan on Every Bar

**Impact:** Medium — Affects every symbol/timeframe
**Description:** `SwingDetector` calls `find_peaks()` and `find_troughs()` on every single 1m bar, scanning entire 120-bar window each time. Swing points change maybe 5-10 times/day per symbol.

```python
# src/intelligence/structure/swing_detector.py (lines 44-45)
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    high = df["high"].to_numpy(dtype=float)  # NUMPY CONVERSION
    low = df["low"].to_numpy(dtype=float)    # NUMPY CONVERSION
    swing_highs = find_peaks(high, self.neighbor)  # FULL WINDOW SCAN O(n)
    swing_lows = find_troughs(low, self.neighbor)  # FULL WINDOW SCAN O(n)
```

**Math:**
- Peak/trough detection: O(n) scan over 120 bars per bar
- Per 1m bar per symbol: 240 operations
- 23 syms × 4 TFs = 92 streams × 240 ops = 22,080 ops/sec

**Renaissance Lens:** "Segment relentlessly. A swing point is a regime boundary — detect it incrementally."

**Problem:** Swing points are **events**, not continuous properties. Detecting requires O(n) scan, but we scan every bar even when no swing formed.

**Proposed Fix: Incremental Swing Detection
```python
# Track last N peaks/troughs, only check new bar against them
class IncrementalSwingDetector:
    def __init__(self):
        self._recent_peaks: deque[tuple[float, int]] = deque(maxlen=5)  # (price, index)
        self._recent_troughs: deque[tuple[float, int]] = deque(maxlen=5)

    def compute_next(self, windows: dict) -> dict:
        new_high = windows["main"]["high"].iloc[-1]
        new_low = windows["main"]["low"].iloc[-1]
        new_idx = len(windows["main"]) - 1

        # Check if new high beats recent peaks
        new_swing_high = None
        for peak_price, peak_idx in self._recent_peaks:
            if new_high > peak_price:
                # New swing high formed
                new_swing_high = new_high
                self._recent_peaks.appendleft((new_high, new_idx))
                break

        # Similar for troughs
        # ...
```

**Potential Speedup:** 90-99% reduction when swings are sparse (most bars are no-ops).

---

### Inefficiency 6: SupportResistance — Redundant Peak/Trough Detection

**Impact:** Medium — Affects every symbol/timeframe
**Description:** `SupportResistance` also calls `find_peaks()`/`find_troughs()` on every bar, duplicating the work SwingDetector already did.

**Problem:** SwingDetector and SupportResistance both detect pivots (peaks/troughs), but don't share results. Each scans the window independently.

**Renaissance Lens:** "Never recompute what you've already computed. Cache derived values."

**Proposed Fix:** Pivot Cache
```python
# market_analysis_service maintains pivot cache per (symbol, tf)
self._pivot_cache: dict[str, dict[str, Any]] = {
    f"{sym}:{tf}": {
        "peaks": [(price, idx), ...],
        "troughs": [(price, idx), ...],
        "last_updated_idx": N,
    }
}

# SwingDetector updates cache on detection
# SupportResistance reads from cache instead of rescanning
```

**Potential Speedup:** 50% reduction for S/R tier (eliminate duplicate scans).

---

### Inefficiency 7: SessionContext — Per-Bar Computation for Event-Based Data

**Impact:** Medium — Affects every 1m bar
**Description:** Session flags are computed on every single 1m bar, but sessions only change at boundaries (4 times/day). Timezone conversion and window checks run on every bar.

```python
# src/intelligence/context/session_context.py (lines 91-129)
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    ts = _extract_ts(df)  # Every 1m bar
    et = _et_from_utc(ts)  # TIMEZONE CONVERSION (expensive)

    sess_asia = 1.0 if _in_window(et, *_SESSIONS["asia"]) else 0.0
    sess_london = 1.0 if _in_window(et, *_SESSIONS["london"]) else 0.0
    # ... 6 more window checks per bar
```

**Math:**
- Timezone conversion: `_et_from_utc()` → `astimezone()` + `replace()` — O(1) but per bar
- Window checks: 6 comparisons per bar
- Per 1m bar per symbol: 23 syms = 23 × (1 + 6) = 161 ops/sec

**Problem:** Session start/end are **events**, not continuous state. Computing on every bar is wasteful.

**Renaissance Lens:** "Segment relentlessly. Event-based computation vs per-bar polling."

**Proposed Fix: Event-Driven Session Flags
```python
# Compute once per session, cache result
class SessionCache:
    def __init__(self):
        self._current_session: str = "unknown"  # asia/london/ny/overlap/after
        self._session_start_idx: int = 0
        self._cached_flags: dict = {}

    def update(self, ts: datetime, bar_idx: int) -> dict:
        new_session = self._detect_session(ts)
        if new_session != self._current_session:
            # Session boundary — recompute flags
            self._cached_flags = self._compute_session_flags(ts)
            self._current_session = new_session
            self._session_start_idx = bar_idx
        return self._cached_flags
```

**Potential Speedup:** 95% reduction (only compute on session boundaries, ~4 times/day vs 1440 times/day).

---

### ~~Inefficiency 8: GARCH/HMM — Full Model Refit on Every Bar~~ ❌ INVALID

**Status:** RETRACTED after code audit (2026-03-07)

**Original Claim:** GARCH and HMM refit entire model on every bar.

**Reality:** Both plugins already implement efficient incremental updates:

- **GARCH** (`garch_volatility.py:113-163`): `compute_next()` performs O(1) recurrence update: `sigma2 = omega + alpha * epsilon² + beta * prev_sigma2`. Only cold-starts (no state) trigger full `compute_full()`. Cost: ~0.01ms/bar (single multiply-add), not 2-5ms.
- **HMM** (`hmm_regime.py:148-174`): `compute_next()` performs one forward-algorithm step: `_forward_step(obs, n_dims)` — O(K×D) where K=3 states, D=2-5 dims → ~50-100 operations. This is the mathematically correct way to run an online HMM. Not a "refit" at all.

**Lesson:** Always read the actual `compute_next()` implementation before claiming inefficiency. The code shown in the original claim (`compute_next → compute_full`) does not match the actual source.

---

### Inefficiency 9: Pandas → NumPy Conversions

**Impact:** Low — Cumulative overhead across many plugins
**Description:** Multiple plugins call `.to_numpy()` on every bar to convert pandas Series to numpy arrays. These conversions allocate new arrays.

```python
# Repeated in SwingDetector, SupportResistance, and others
high = df["high"].to_numpy(dtype=float)  # ALLOCATION
low = df["low"].to_numpy(dtype=float)    # ALLOCATION
close = df["close"].to_numpy(dtype=float)  # ALLOCATION
```

**Problem:** Each `.to_numpy()` call creates a new array copy. With ~30 plugins doing this per bar × 23 syms × 4 TFs = millions of allocations.

**Renaissance Lens:** "Data quality over model complexity — but don't pay allocation tax."

**Proposed Fix:** Use NumPy Input Directly
```python
# indicator_service already has raw numpy arrays from bars
# Pass numpy arrays downstream instead of DataFrames
# Or use pandas .values accessor which returns numpy view (no copy)
high = df["high"].values  # No allocation (numpy view)
low = df["low"].values
```

**Potential Speedup:** Eliminate 100% of numpy conversion overhead (use views instead of copies).

---

## SSE/Dashboard Patterns

### Inefficiency 10: Large IntelligenceEvent Payloads Over SSE

**Impact:** Medium — Affects dashboard real-time updates
**Description:** Each `IntelligenceEvent` sent over SSE contains ~6 sub-models with ~10-50 fields each. Every field serialized as string in JSON.

**Math:**
- Fields per IntelligenceEvent: ~200-300 (sum of all tier outputs)
- JSON size per event: ~5-10KB
- SSE bandwidth per sec: 1.5 events × 5KB = 7.5KB/sec

**Renaissance Lens:** "Degrade gracefully. Large payloads create network congestion and slow clients."

**Proposed Fix: Tiered SSE Streams
```python
# Separate streams for different update frequencies
intelligence:SYMBOL:TF   # I3/I4/I5/SMC/I6 (every bar)
intelligence_fast:SYMBOL:TF  # I1 (every bar, smaller payload)
intelligence_slow:SYMBOL:TF  # I7 signals (on change, sparse)
```

**Potential Speedup:** 50-70% reduction in SSE payload size for I1 stream.

---

## Service Startup Patterns

### Inefficiency 11: Cold Start vs Persistent State

**Impact:** High on restart — Affects signal_generator_service
**Description:** Signal generator needs ~50 live 1m bars (~50 minutes) before signals fire. During warmup, it processes bars but produces no signals.

**Math:**
- Warmup bars: 50
- Bars processed during warmup: 50 × 23 syms × 4 TFs = 4600 bars
- Time wasted: 50 minutes of compute with zero output

**Renaissance Lens:** "Let the system run. Don't make it recompute what it already knows."

**Proposed Fix: Persistent Plugin State
```python
# Save plugin state to DB on shutdown
# On startup, restore state instead of cold start
# Eliminates 50-minute warmup period
```

**Potential Speedup:** Zero-latency signals on restart (vs 50-minute warmup).

---

## Code Inefficiencies: Additive Patterns

### Inefficiency 1: Repeated `model_dump()` + JSON Serialization

**Impact:** High — Affects `signal_generator_service`, `feature_writer_service`
**Description:** Every `IntelligenceEvent` consumption calls `.model_dump()` on **each sub-model separately**, creating redundant dict allocations.

```python
# signal_generator_service.py (lines 118, 127, 135, 143, 153, 158, 163)
for k, v in event.i1.model_dump().items():  # DICT COPY #1
    features[k] = v
for k, v in event.i2.model_dump(exclude_none=True).items():  # DICT COPY #2
    features[k] = v
# ... 4 more model_dump() calls per event (i3, i4, i5, smc, i6)

# feature_writer_service.py (lines 180-187)
json.dumps(event.bar.model_dump())      # JSON SERIALIZE + DICT COPY #1
json.dumps(event.i1.model_dump())      # JSON SERIALIZE + DICT COPY #2
json.dumps(event.i2.model_dump(...))    # JSON SERIALIZE + DICT COPY #3
# ... 6 more json.dumps() per event (i3, i4, i5, smc, i6)
```

**Math:**
- Sub-models per `IntelligenceEvent`: 6 (bar, i1, i2, i3, i4, i5/smc, i6)
- `model_dump()` calls per event: 6 dict allocations
- `json.dumps()` calls per event: 6 new strings
- IntelligenceEvents per second: ~23 syms × 4 TFs / 60s ≈ 1.5 events/sec

Per day (24h):
- Dict allocations: 6 × 1.5 × 3600 × 24 ≈ **650k dicts**
- JSON strings: 6 × 1.5 × 3600 × 24 ≈ **450k strings**

**Renaissance Lens:** "Let the system run. Don't pay overhead for data that's already structured."

**Potential Speedup:** Single-pass serialization — 6× reduction in dict allocations, 6× reduction in JSON calls.

**Proposed Fix:**
```python
# Single dump of entire event, access sub-models from pre-built dict
full_event = event.model_dump()  # One dict allocation
i1_dict = full_event["i1"]
i2_dict = full_event["i2"]
# ...

# Or: Pass IntelligenceEvent directly, serialize only at DB/stream boundaries
```

---

### Inefficiency 2: Mutable Features Accumulation

**Impact:** Medium — Affects `market_analysis_service`
**Description:** Features dict grows through 6 sequential `.update()` calls, each creating a new internal hash map structure.

```python
# market_analysis_service.py (lines 221, 225, 229, 233, 237, 240)
i2_results = {}
_run_tier(TIER_I2, "I2", i2_results)
features.update(i2_results)   # MUTATION + COPY

i3_results = {}
_run_tier(TIER_I3, "I3", i3_results)
features.update(i3_results)   # MUTATION + COPY

# ... 4 more .update() calls (i4, i5, smc, i6)
```

**Problem:** `dict.update()` copies entries from source dict into target. For large feature dicts (~50+ fields), each `.update()` is O(n) and creates internal rehashing.

**Renaissance Lens:** "Data quality over model complexity — but don't pay unnecessary overhead for mutation."

**Proposed Fix:**
```python
# Build tier results separately, merge once at end
tier_results = {
    "i2": i2_results,
    "i3": i3_results,
    "i4": i4_results,
    "i5": i5_results,
    "smc": smc_results,
    "i6": i6_results,
}
# One dict merge at end (Python 3.9+ does this efficiently)
flat = {**i2_results, **i3_results, **i4_results, **i5_results, **smc_results, **i6_results}
```

**Potential Speedup:** Single dict merge vs 6 sequential updates.

---

### Inefficiency 3: DataFrame Reconstruction from Deque

**Impact:** Low-Medium — Affects `market_analysis_service`
**Description:** `bar_history[key]` is a `deque(maxlen=200)`. Converting to list then DataFrame on cache miss allocates list + DataFrame overhead.

```python
# market_analysis_service.py (lines 260-263)
def _get_df(self, key: str) -> pd.DataFrame:
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))  # DEQUE COPY
    return self._df_cache[key]
```

**Math:**
- Deque → List: O(n) allocation (n=200 rows)
- List → DataFrame: O(n) pandas allocation

Per cache miss: 400 object allocations (200 list elements + DataFrame internal structures). Cache misses happen on service restart and warmup.

**Renaissance Lens:** "Storage is cheap. Compute is expensive. Don't pay allocation tax for data you've already stored."

**Proposed Fix:**
```python
# Store DataFrames directly in cache
if key not in self._df_cache:
    # Build DF from scratch (more efficient than deque → list → DF)
    new_df = pd.DataFrame({
        "open": [...], "high": [...], "low": [...],
        "close": [...], "volume": [...]
    }, index=timestamps)
    self._df_cache[key] = new_df
# Maintain deque separately for append-only (bar appends)
self.bar_history[key].append(new_bar_data)
```

**Potential Speedup:** Eliminate deque → list → DataFrame allocation path.

---

### Inefficiency 4: "I1 Multiplied by I8" — Atomic Enrichment Pattern

**Impact:** Medium — Affects `feature_writer_service`
**Description:** Feature writer performs 3 separate database writes for what could be a single atomic operation.

```python
# Current pattern: 3 separate writes per bar
intelligence:SYMBOL:TF   → INSERT with full event (all i1-i6 JSONB)
intelligence_i7:SYMBOL:TF  → UPDATE i7 column (JSONB)
intelligence_i8:SYMBOL:TF  → UPDATE i8 column (JSONB)
```

**Problem:** For every bar, feature writer does:
1. `INSERT` intelligence_features row (from main stream)
2. `UPDATE` intelligence_features SET i7 = ... WHERE ts=... (from i7 stream)
3. `UPDATE` intelligence_features SET i8 = ... WHERE ts=... (from i8 stream)

That's **3 database round-trips per bar** (INSERT + UPDATE + UPDATE) where a single upsert could suffice.

**The "Multiplied" Aspect:**
I1 data flows through every tier and ends up at I8. The I8 narrative then flows back to feature writer to UPDATE the same row. So I1 gets "carried along" through: indicator → market_analysis → signal_gen → ai_narrative → feature_writer → DB.

This isn't inherently inefficient — I1 must be in every tier. **The inefficiency is the 3-round-trip write pattern.**

**Renaissance Lens:** "Let the system run. Don't make multiple trips when one atomic operation suffices."

**Proposed Fix:**
```python
# Buffer all 3 streams, emit single atomic upsert
buffer = {
    "main": intelligence_event,      # from intelligence:SYMBOL:TF
    "i7": i7_enrichment,         # from intelligence_i7:SYMBOL:TF
    "i8": i8_enrichment,         # from intelligence_i8:SYMBOL:TF
}

# When all 3 arrive or timeout expires: single INSERT...ON CONFLICT UPDATE
INSERT INTO intelligence_features (ts, symbol, tf, i1, i2, i3, i4, i5, smc, i6, i7, i8)
VALUES ($1, $2, $3, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb)
ON CONFLICT (ts, symbol, tf) DO UPDATE SET
    i7 = EXCLUDED.i7,
    i8 = EXCLUDED.i8
```

**Potential Speedup:** 1 DB round-trip instead of 3. Also reduces DB lock contention (single row lock vs multiple updates).

---

## Additional Opportunities (Secondary)

### Cross-TF Early Exit

**Concept:** Higher-TF computations inherit results from lower-TF where applicable.

**Example:** `GARCHVolatility` on 15m reads `GARCHVolatility` result from 5m and applies smoothing if regime hasn't shifted.

**Status:** Research phase — needs validation that regime propagation is sound.

---

### LLM Memoization

**Concept:** Cache narrative responses for similar signal fingerprints. LLM called only when novel conditions exist.

**Implementation:**
- Fingerprint: `(setup_plugin, regime_context, symbol, tf, key_features_hash)`
- Cache TTL: 1 hour (regimes can shift)
- Fallback: Template narrative on cache miss/timeout

**Status:** Low priority — narrative latency isn't blocking the core pipeline.

---

## Findings from Code Audit (2026-03-07)

> Added after line-by-line review of all service files and key plugins. These correct, supplement, or invalidate prior claims.

### Corrections to Prior Claims

#### GARCH/HMM "Full Refit" — INVALID ❌
See Inefficiency 8 (retracted). Both `garch_volatility.py:compute_next()` and `hmm_regime.py:compute_next()` already implement efficient O(1)/O(K) incremental updates. The proposed "AdaptiveGARCH" optimization was solving a problem that doesn't exist.

#### SwingDetector Inefficiency — OVERSTATED ⚠️
The document claims "22,080 ops/sec" which is technically correct but misleading. `find_peaks()` in `src/intelligence/utils.py:12-35` is fully **NumPy-vectorized** (array slicing, no Python loops). Actual wall-clock: ~0.1-0.5ms per call. The real issue is not the scan cost — it's that `compute_next()` delegates to `compute_full()` (line 91-92), so incremental detection is impossible.

#### Hot Store Latency Math — OVERSTATED ⚠️
The document claims "72ms/bar saved" assuming q=10 signals each querying DB. In practice, `signal_lifecycle_service.py:545` fetches ALL active signals per symbol in one query (not per-signal). Real savings: ~5-10ms per symbol per bar (1 query eliminated, not 10). For 23 symbols: ~115-230ms/min saved, not 72ms/bar.

---

### New Inefficiency 12: DataFrame Cache Invalidated Every Bar

**Impact:** High — Affects all services using `_get_df()` pattern
**Location:** `market_analysis_service.py:324`, `signal_generator_service.py:782`

**Description:** Every incoming bar sets `self._df_cache[key] = None`, forcing the next `_get_df()` call to reconstruct the entire DataFrame from a deque of dicts.

```python
# On every bar:
self.bar_history[key].append(bar_data)
self._df_cache[key] = None  # Invalidate — next _get_df() rebuilds from scratch

# On next plugin call:
def _get_df(self, key: str) -> pd.DataFrame:
    if self._df_cache.get(key) is None:
        self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))  # O(n)
    return self._df_cache[key]
```

**Math:**
- Deque size: 200 bars
- `list(deque)`: O(200) — copies 200 dict refs
- `pd.DataFrame(list_of_dicts)`: O(200 × fields) — builds columnar arrays from row dicts
- Per bar: 92 streams × 200-row DF rebuild = ~18,400 dict-to-column conversions
- Multiple `_get_df()` calls per bar within same service: only 1 rebuild (cache hit after first), but still 92 rebuilds per bar cycle

**Renaissance Lens:** "Storage is cheap. Don't reconstruct what you already have."

**Proposed Fix: Rolling DataFrame with Append**
```python
def _update_df(self, key: str, new_bar: dict) -> pd.DataFrame:
    existing = self._df_cache.get(key)
    if existing is None or len(existing) == 0:
        self._df_cache[key] = pd.DataFrame([new_bar])
    else:
        new_row = pd.DataFrame([new_bar])
        self._df_cache[key] = pd.concat([existing, new_row]).iloc[-200:]  # Rolling window
    return self._df_cache[key]
```

**Potential Speedup:** Eliminate O(n) full rebuild on every bar. Append + trim is O(1) amortized.

---

### New Inefficiency 13: Signal Generator Plugin Registry Lookup Every Call

**Impact:** Medium — Affects signal_generator_service per-bar performance
**Location:** `signal_generator_service.py:533`

**Description:** Unlike `market_analysis_service` (which caches plugins in `_plugin_cache` at init), signal generator calls `registry.get_pattern(name)` on every bar for every I7 plugin.

```python
# signal_generator_service.py:533 — called 17× per bar per symbol/TF
plugin = registry.get_pattern(name)  # Dict lookup + potential validation
```

Contrast with `market_analysis_service.py` which pre-builds `_plugin_cache`:
```python
# market_analysis_service.py (init)
self._plugin_cache = {name: registry.get_pattern(name) for name in all_plugins}
# Then in _run_tier:
p = self._plugin_cache[pname]  # Direct dict lookup, no registry
```

**Math:** 17 plugins × 92 streams/min = 1,564 registry lookups/min that could be 0.

**Proposed Fix:** Cache I7 plugin instances at init, same pattern as market_analysis_service.

---

### New Inefficiency 14: Feature Writer i7/i8 UPSERTs Not Batched

**Impact:** High — Affects database write throughput
**Location:** `feature_writer_service.py:459, 486`

**Description:** The base intelligence event INSERT is batched (accumulate 50 rows, flush every 5s). But i7 and i8 enrichment UPSERTs execute **individually** — one UPSERT per stream message, not batched.

```python
# feature_writer_service.py:459 — called per-message, not batched
_UPSERT_I7_SQL = """INSERT INTO intelligence_features (ts, symbol, tf, i7)
VALUES ($1, $2, $3, $4::jsonb)
ON CONFLICT (ts, symbol, tf) DO UPDATE SET i7 = EXCLUDED.i7"""

# Called via execute_batch() with a list of 1 tuple
await self.db_manager.execute_batch(_UPSERT_I7_SQL, [(ts, sym, tf, i7_json)])
```

**Math:**
- Per bar cycle: 92 i7 UPSERTs + 92 i8 UPSERTs = **184 individual DB round-trips**
- Each round-trip: ~1-3ms (local Docker socket)
- Total: 184-552ms of DB I/O per bar cycle that could be 2 batched queries (~6ms)

**Renaissance Lens:** "Let the system run. Don't make 184 trips when 2 suffice."

**Proposed Fix:** Accumulate i7/i8 enrichments in buffers, flush in batch (same pattern as base INSERT).

---

### New Inefficiency 15: Signal Lifecycle N+1 Query Pattern

**Impact:** Medium — Affects signal_lifecycle_service DB load
**Location:** `signal_lifecycle_service.py:545`

**Description:** Per 1m bar, service fetches ALL active signals for a symbol (all timeframes), then filters to matching TF in Python.

```python
# Line 545: Fetches all active signals per symbol
active = await get_active_signals(self.db_manager, symbol=symbol)

# Line 547: Then loops 4 TFs and filters in Python
for tf in self.config["service"]["timeframes"]:
    relevant = [s for s in active if s.get("timeframe") == timeframe]
```

**Math:**
- 23 symbols × 1 query/bar = 23 queries/min (at 1m bars)
- Each returns ALL active signals (pending + active + regime_suppressed) across all TFs
- Python-side filter discards ~75% of rows (only 1 of 4 TFs matches)

**Proposed Fix:** `WHERE symbol = $1 AND timeframe = $2 AND status IN (...)` — move filter to DB. Or better: cache active signals in-memory, invalidate on status change events from signal_generator.

---

### New Inefficiency 16: Regime Cache Cold Start

**Impact:** Medium on restart — First ~50 bars lack regime gating
**Location:** `signal_generator_service.py:759-767`

**Description:** `_regime_cache` starts empty on service restart. Regime data only populates as `IntelligenceEvent`s arrive from market_analysis_service. Until the authority TF (5m for 1m signals) publishes its first event, regime gating is skipped entirely.

```python
# Line 572-573: Gate skipped if absent
authority_tf = _REGIME_AUTHORITY_TF.get(timeframe, timeframe)
regime_data = self._regime_cache.get(symbol, {}).get(authority_tf)
if regime_data is None:
    pass  # No gating — signals fire unfiltered
```

**Impact:** After restart, 5-10 minutes of signals fire without regime classification. If market is in a choppy range, trend signals that should be suppressed will fire and enter the ledger.

**Renaissance Lens:** "Don't override data with intuition — but also don't run without data."

**Proposed Fix:** Warmup query on startup:
```sql
SELECT DISTINCT ON (symbol, feature_tf) symbol, feature_tf,
       (i4->>'hmm_regime')::int, (i4->>'hmm_regime_prob')::float,
       (i4->>'hmm_regime_duration')::int
FROM intelligence_features
WHERE feature_ts > now() - interval '1 hour'
ORDER BY symbol, feature_tf, feature_ts DESC
```

---

### New Inefficiency 17: CIS Scorer No Early Exit

**Impact:** Low-Medium — Affects CIS compute on every bar
**Location:** `cis_scorer.py:112-122`

**Description:** CIS computes all 6 buckets on every bar, even though ~90% of bars won't meet the minimum threshold (abs(score) > 0.35). The most expensive bucket (`_institutional`) involves 6 feature lookups + arithmetic. All 6 buckets compute fully before the threshold check.

```python
# cis_scorer.py:112-122
bucket_scores = {
    "trend": self._trend(features),           # 5 lookups + weighted sum
    "momentum": self._momentum(features, ...), # 7 lookups + weighted sum
    "structure": self._structure(...),          # 5 lookups + weighted sum
    "pattern": self._pattern(...),              # 4 lookups + weighted sum
    "institutional": self._institutional(...),  # 6 lookups + weighted sum
    "regime": self._regime(...),               # 8 lookups + weighted sum
}
cis_raw = sum(self._weights[b] * bucket_scores[b] for b in BUCKET_NAMES)
```

**Proposed Fix: Progressive Threshold Check**

Compute buckets in weight order (institutional 0.25, trend 0.20, momentum 0.20 first). After each, check if remaining buckets could possibly push score past threshold:

```python
def score_with_early_exit(self, features, plugin_outputs, threshold=0.35):
    remaining_weight = 1.0
    cumulative = 0.0
    for bucket_name in BUCKETS_BY_WEIGHT_DESC:
        w = self._weights[bucket_name]
        s = self._compute_bucket(bucket_name, features, plugin_outputs)
        cumulative += w * s
        remaining_weight -= w
        # Best possible remaining score: remaining_weight × 1.0
        if abs(cumulative) + remaining_weight < threshold:
            return None  # Cannot reach threshold — early exit
    return CISResult(score=clamp(cumulative), ...)
```

**Potential Speedup:** Skip 3-4 bucket computations on ~90% of bars.

---

### New Inefficiency 18: Redundant RR Recomputation in Stream Message

**Impact:** Low — Affects signal_generator_service stream publishing
**Location:** `signal_generator_service.py:670-676`

**Description:** Risk-reward ratio is computed in `trade_framer` (available as `frame.rr_t1`), but then recomputed from raw entry/stop/target prices when building the Redis stream message:

```python
# Line 670-676: Recomputes what trade_framer already computed
entry_p = float(sig.get("entry_price", 0))
stop_p = float(sig.get("stop_loss", 0))
risk = abs(entry_p - stop_p)
if risk > 0 and targets:
    message["risk_reward_ratio"] = str(round(abs(float(targets[0]) - entry_p) / risk, 2))
```

The `sig` dict already contains `rr_t1` from `trade_framer._build_frame()`. This recomputation risks divergence if rounding differs.

**Proposed Fix:** Use `sig.get("rr_t1")` directly.

---

### New Inefficiency 19: Dual Dict Accumulation in market_analysis_service

**Impact:** Low — Affects per-bar memory allocation
**Location:** `market_analysis_service.py:221-245`

**Description:** Tier results are accumulated into `features` via `.update()` (6 calls), then unpacked into a separate `flat` dict via `{**i2_results, **i3_results, ...}`. Both dicts contain nearly identical data and exist simultaneously in memory.

**Root cause:** I6 results are intentionally excluded from `features` (so I6 plugins can't feed back into frames), but included in `flat` for persistence. This creates the need for dual accumulation.

**Proposed Fix:** After all tiers complete, derive `flat` from `features` + i6_results in one merge:
```python
flat = {**features, **i6_results}  # Single merge, not 6 unpacks
```

---

### Correctness Issue 1: SessionContext `bars_since_session_start` Semantic Bug

**Location:** `session_context.py:114`
**Severity:** Medium — misleading field consumed by downstream plugins

```python
bars_since = float(len(df))  # Always returns lookback window size (10), NOT bars since session start
```

Field name `bars_since_session_start` implies duration tracking. Actual behavior: returns `len(df)` which is the 10-bar lookback window. If session started 120 bars ago, field still returns 10.

**Impact:** Any I5+ plugin or CIS bucket using this field for session duration calculations gets wrong data.

**Fix:** Either rename to `recent_bars_count` or compute actual bars since session boundary using timestamp comparison.

---

### Correctness Issue 2: CIS Regime Bucket Comment Inversion

**Location:** `cis_scorer.py:328-331`
**Severity:** Low — comment doesn't match code (code is correct)

```python
cp = self._fval(f, "cp_probability")
# Comment says: "When cp <= 0.5 (stable regime), reinforce HMM direction"
# But cp <= 0.5 means UNCERTAIN regime (0.5 = max entropy), not stable
cp_contribution = 0.0 if cp > 0.5 else clamp(hmm_dir) * (1.0 - cp * 2.0)
```

The formula is mathematically correct: higher changepoint probability → less regime contribution. But the comment mischaracterizes cp semantics.

---

### Correctness Issue 3: Hard-Coded TF Hierarchy

**Location:** `market_analysis_service.py:283`
**Severity:** Medium — breaks if config changes

```python
tf_hierarchy = ["1m", "5m", "15m", "1h"]  # Hard-coded, should be self.config["service"]["timeframes"]
```

If config includes `"4h"` or `"1d"`, cross-TF injection silently ignores them.

---

### Correctness Issue 4: Cross-TF Injection Threshold Mismatch

**Location:** `market_analysis_service.py:288`
**Severity:** Low — conservative but undocumented

```python
if other_key in self.bar_history and len(self.bar_history[other_key]) >= 50:
```

This requires 50 bars minimum for cross-TF injection, but `min_bars_for_tf()` returns 26 for 5m+. The 50-bar threshold is stricter than the computed minimum, meaning cross-TF data is unavailable for first ~24 extra bars after warmup.

---

## Implementation Roadmap (Renaissance-Compliant)

### Phase 1: Parallel Execution (Weeks 1-2)

**Goal:** 2-4× speedup for compute-bound tiers (I3/I4/I5/SMC)

**Steps:**

1. [ ] Add feature flag `INTELLIGENCE_PARALLEL_ENABLED=0`
2. [ ] Build within-tier dependency graph from plugin `inputs`
3. [ ] Implement `_build_independent_groups()` with topological sort
4. [ ] Replace sequential `_run_tier()` with `_run_tier_parallel()`
5. [ ] Add thread-safe state swapping (`threading.Lock` per state_key)
6. [ ] Add metrics: `plugin_execution_parallel_ms`, `plugin_queue_wait_ms`, `tier_execution_parallel_speedup`
7. [ ] Shadow mode: run both sequential and parallel, compare outputs
8. [ ] Validation: parity check (1000+ bars), latency measurement, error rate comparison
9. [ ] Promote only when: latency ↓ by ≥30% with p<0.05, N≥100 bars per symbol/TF

**Rollout:** Use `system:events` stream to signal feature flag changes. Instant rollback by disabling flag.

---

### Phase 2: Hot Feature Store (Weeks 3-5)

**Goal:** Eliminate DB round-trip for real-time queries (signal lifecycle)

**Steps:**

1. [ ] Add feature flag `HOT_FEATURE_STORE_ENABLED=0`
2. [ ] Design `HotFeatureStore` interface with TTL management
3. [ ] Implement in-memory store (pure Python dict + deque, or Redis as alternative)
4. [ ] Wire feature_writer to write both hot store and TimescaleDB (read-write-through)
5. [ ] Wire signal_lifecycle to read from hot store first, fallback to DB on miss
6. [ ] Add metrics: `hot_store_hit_rate`, `hot_store_memory_bytes`, `hot_store_eviction_rate`
7. [ ] Shadow mode: cache writes to both paths, query latency comparison
8. [ ] Validation: query latency measurement, memory usage profiling, parity check
9. [ ] Promote only when: query latency ↓ by ≥90% (sub-ms), hit rate >95%, N≥1000 queries

**Rollback:** Disable flag → all queries go to DB directly.

---

### Phase 3: Stateful I7 Detection (Weeks 6-10)

**Goal:** 80-95% reduction in I7 compute, natural regime handling

**Steps:**

1. [ ] Research phase: Model state machines for 2-3 setups (MeanReversion, TrendFollowing, SqueezeExpansion)
2. [ ] Add feature flag `STATEFUL_I7_ENABLED=0`
3. [ ] Design state machine abstraction protocol:
   ```python
   class StatefulPlugin(Protocol):
       def current_state(self) -> str
       def possible_transitions(self) -> list[str]
       def transition(self, inputs: dict) -> tuple[str, dict | None]
   ```
4. [ ] Rewrite I7 plugins as state machines (start with 2-3, validate before full rollout)
5. [ ] Add state transition logging for observability
6. [ ] Add metrics: `state_machine_transition_count`, `state_machine_avg_state_duration`, `state_fire_vs_scan_ratio`
7. [ ] Shadow mode: both old and new paths, verify signal parity (N≥500 signals)
8. [ ] Validation: same detection rate, latency reduction measurement, state graph correctness
9. [ ] Promote only when: same detection rate with latency ↓ by ≥70%, p<0.05, N≥500 signals

**Rollback:** Disable flag → per-bar scanning resumes.

---

## Open Research Questions

1. **Plugin State Thread Safety:** What's the correct pattern for concurrent state access? Per-key `threading.Lock`? Copy-on-write? Immutable state snapshots?

2. **Within-Tier Dependencies:** Are there any hidden dependencies not declared in `inputs`? Need audit of all plugin `inputs` vs actual usage.

3. **Hot Store Eviction Policy:** What's the optimal TTL strategy? Fixed time window vs. LRU vs. hybrid?

4. **State Machine Complexity:** What's the right abstraction? Per-plugin state machines or a unified state machine framework?

5. **Cross-TF Propagation:** Is it mathematically sound to inherit regime from lower-TF? Need simulation validation.

6. **LLM Cache Fingerprint:** What features actually matter for narrative similarity? `(setup, regime, key_levels)` vs. full feature vector?

---

## Math & Logic Validation

### Parallel Execution Theoretical Speedup

Given:
- `n` plugins in tier
- `t` = time per plugin (assume constant)
- `p` = parallel workers (CPU cores)
- Sequential time: `T_seq = n × t`
- Parallel time: `T_par = ceil(n/p) × t`

Speedup: `S = T_seq / T_par = n / ceil(n/p)`

For I3 (n=7 plugins):
- p=4 cores: `S = 7 / ceil(7/4) = 7 / 2 = 3.5×`
- p=8 cores: `S = 7 / ceil(7/8) = 7 / 1 = 7×` (theoretical max)

For I4 (n=7 plugins): Same as I3.

For I5 (n=14 plugins):
- p=4 cores: `S = 14 / ceil(14/4) = 14 / 4 = 3.5×`
- p=8 cores: `S = 14 / ceil(14/8) = 14 / 2 = 7×`

For SMC (n=13 plugins):
- p=4 cores: `S = 13 / ceil(13/4) = 13 / 4 = 3.25×`
- p=8 cores: `S = 13 / ceil(13/8) = 13 / 2 = 6.5×`

**Conclusion:** 3-7× speedup achievable on 8-core CPU, lower on fewer cores.

---

### Hot Store Latency Reduction

Given:
- DB round-trip: `T_db = 5-10ms` (network + query)
- Hot store read: `T_hot = 0.1-0.5ms` (dict lookup)
- Queries per bar for signal lifecycle: `q = 5-10` (depends on active signals)

Latency reduction: `ΔT = q × (T_db - T_hot)`

For q=10, T_db=7.5ms, T_hot=0.3ms:
`ΔT = 10 × 7.2ms = 72ms/bar` saved

**Conclusion:** ~70-100ms per bar saved on signal lifecycle path.

---

### State Machine Compute Reduction

Given:
- I7 plugins: `n = 17`
- Signals per day: `s ≈ 5-10` (varies by market)
- Bars per day: `b = 1m: 1440, 5m: 288, 15m: 96, 1h: 24`

Current: `C_curr = n × b` evaluations per day per TF
State machine: `C_state ≈ 2s × b` (state check + potential transition) per day per TF

For 5m (b=288):
- Current: `17 × 288 = 4,896` evaluations
- State: `2 × 288 = 576` checks (assuming 50% bars trigger transition check)

Reduction: `1 - 576/4896 ≈ 88%`

**Conclusion:** 80-90% reduction in I7 compute if state transitions are sparse (most bars are no-ops).

---

## References

- `docs/concepts/dag-execution.md` — DAG topological sort, plugin dependencies
- `docs/concepts/incremental-computation.md` — O(1) incremental vs O(n) full recompute
- `services/market_analysis_service.py` — Sequential plugin execution pattern
- `services/indicator_service.py` — Multi-stream xreadgroup pattern
- `src/intelligence/plugins.py` — Plugin protocol
- `src/intelligence/schemas.py` — IntelligenceEvent structure

---

## Revision History

| Date | Change | Author |
|-------|---------|---------|
| 2026-03-07 | Initial document with 3 approaches, Renaissance framing, math validation | Claude |
| 2026-03-07 | Added Code Inefficiencies section: model_dump/JSON overhead, mutable accumulation, deque→DF conversion, I7/I8 atomic enrichment | Claude |
| 2026-03-07 | Added Plugin-Level Inefficiencies: swing detection, S/R duplication, session per-bar compute, GARCH/HMM refit, pandas→numpy, SSE payloads, cold start, persistent state | Claude |
| 2026-03-07 | **Code audit**: Retracted GARCH/HMM refit claim (already incremental). Added 8 new inefficiencies (12-19): DF cache invalidation, plugin registry lookup, i7/i8 unbatched UPSERTs, signal lifecycle N+1, regime cold start, CIS no early exit, RR recomputation, dual dict accumulation. Added 4 correctness issues: SessionContext semantic bug, CIS comment inversion, hard-coded TF hierarchy, cross-TF threshold mismatch. Corrected overstated SwingDetector and hot store math. | Claude |
