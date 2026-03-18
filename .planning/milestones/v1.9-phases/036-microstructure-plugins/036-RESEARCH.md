# Phase 36: Microstructure Plugins - Research

**Researched:** 2026-03-18
**Domain:** Order Flow Imbalance (OFI) and Cumulative Volume Delta (CVD) — I1 features + I7 plugins
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tick Data Strategy:**
- True tick accumulation as primary path: `indicator_service` adds a second Kafka consumer on `market.ticks` (topic via `topic_market_ticks()`). Buffer ticks per `(symbol, timeframe)` during each bar window; flush OFI/CVD at bar close.
- Bar-level proxy as automatic fallback: when tick data is missing for a bar (gaps, reconnects), fall back to `(close - low) / (high - low + ε) × volume`. No manual switching required.
- Every bar logs `ofi_variant`: value is `"tick"` or `"proxy"`. Logged in I1 output and surfaced in `intelligence_features` JSONB for post-hoc auditability. Satisfies OFI-01 audit requirement.
- Tick model fields used: `Tick.price`, `Tick.size`, `Tick.bid`, `Tick.ask` from `src/providers/base.py`. Tick rule: `price > prev_price` → buy volume; `price < prev_price` → sell volume; equal → neutral (no volume assigned).

**Plugin Structure — 7 separate I7 plugins:**

OFI-based (3 plugins):
- `trad_OFIContinuation` — sustained directional OFI over N bars; institutional accumulation/distribution; `regime_type="trend"`
- `trad_OFIDivergence` — OFI direction disagrees with price direction (exhaustion); `regime_type="mean_reversion"`
- `trad_OFISpike` — single-bar OFI > 2σ above rolling mean (breakout catalyst); `regime_type="any"`

CVD-based (3 plugins):
- `trad_CVDDivergence` — CVD direction disagrees with price direction; logs `dual_divergence=True` when OFI also diverges simultaneously; `regime_type="mean_reversion"`
- `trad_CVDSpike` — single-bar CVD spike > 2σ, symmetric with `trad_OFISpike`; `regime_type="any"`
- `trad_DeltaExhaustion` — large CVD spike but price fails to follow through; `regime_type="mean_reversion"`

Dual conviction plugin (1 plugin, shadow mode):
- `trad_DualDivergence` — fires only when both OFI and CVD diverge simultaneously. Starts with `is_shadow=True`. Confidence calibrated from empirical win rates before promotion to production.

**Dual Divergence Handling:**
- `trad_DualDivergence` is a standalone plugin — not a confidence multiplier on `trad_CVDDivergence`
- Starts in shadow mode — earns production confidence through empirical win rate data
- `trad_CVDDivergence` still logs `dual_divergence=True` as a metadata field for cross-referencing in `signal_ledger`
- The two plugins are decoupled

**I1 Feature Outputs (per bar, via `I1Indicators` `extra='allow'`):**
- `ofi_ewma_5` — 5-bar EWMA of OFI values
- `ofi_ewma_20` — 20-bar EWMA of OFI values (primary per OFI-02)
- `ofi_divergence` — OFI direction vs. price direction over same window (float, signed)
- `ofi_spike_z` — current OFI vs. 100-bar rolling mean in z-score units
- `ofi_variant` — `"tick"` or `"proxy"` (which path computed this bar)
- `cvd` — running cumulative volume delta (Σ buy_vol − sell_vol, reset per session)
- `cvd_slope_5bar` — 5-bar linear slope of CVD
- `cvd_divergence` — CVD direction vs. price direction (float, signed)
- `cvd_spike_z` — current single-bar CVD vs. 100-bar rolling mean in z-score units

### Claude's Discretion
- Exact EWMA decay factors (beyond the 5-bar and 20-bar spans specified in OFI-02)
- Session reset boundary for CVD (market open vs. continuous — default to session reset)
- Spike z-score lookback window (100-bar suggested in requirements, adjust based on data)
- Exact `trad_DualDivergence` N-bar confirmation window before firing

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope. Cross-asset intelligence (XA plugins) is Phase 37.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OFI-01 | Tick data availability audited; bar-level proxy `(close - low) / (high - low + ε) × volume` implemented as fallback; implementation variant documented | `_process_single_bar()` integration point identified; `ofi_variant` field architecture confirmed |
| OFI-02 | `ofi_ewma_20` and `ofi_divergence` computed as I1 features; EWMA spans 5-bar and 20-bar; divergence = OFI vs price direction | OBV/CMF plugin patterns confirm state accumulation approach; EWMA decay formula confirmed |
| OFI-03 | New I7 plugin `trad_OrderFlowImbalance` with continuation/divergence/spike variants; registered in `TIER_I7` | CONTEXT.md splits this into 3 separate plugins; register_plugins.py pattern confirmed |
| CVD-01 | CVD as I1 feature — `Σ(buy_vol − sell_vol)` using tick rule; outputs `cvd`, `cvd_slope_5bar`, `cvd_divergence` | OBV plugin is structural analog (cumulative accumulator); session reset pattern in ctx_VolumeProfile confirmed |
| CVD-02 | New I7 plugin `trad_CVDDivergence`; logs `dual_divergence=True` flag; CONTEXT.md extends to 4 additional plugins + 1 shadow plugin | I7 divergence pattern from `trad_DivergenceStack` confirmed |
</phase_requirements>

---

## Summary

Phase 36 adds the system's first microstructure signal layer: Order Flow Imbalance (OFI) and Cumulative Volume Delta (CVD). The architecture is split into two distinct parts.

**Part 1 — I1 Features (indicator_service):** A second Kafka consumer on `market.ticks` buffers per-`(symbol, timeframe)` tick data during each bar window. At bar close, the OFI plugin and CVD plugin flush their accumulated tick buffers into 9 new feature fields. When ticks are missing (gaps, reconnects), an automatic bar-level proxy fires with no manual intervention. The `I1Indicators` model uses `extra='allow'`, so these new fields flow through the entire I1→I7 pipeline without any schema migration.

**Part 2 — I7 Plugins (7 new):** Six production plugins (OFIContinuation, OFIDivergence, OFISpike, CVDDivergence, CVDSpike, DeltaExhaustion) plus one shadow plugin (DualDivergence). All consume the new I1 fields from `features` dict. Registration in `TIER_I7` via `register_plugins.py` is all that's needed for aggregator pickup — no other wiring changes. `trad_DualDivergence` starts with `is_shadow=True` and follows the established shadow promotion pattern.

**Primary recommendation:** Implement the tick buffer in `indicator_service` as a module-level `TickAccumulator` class (dict of per-symbol tick lists), consumed by two new I1 plugins (`OFIPlugin`, `CVDPlugin`). All 7 I7 plugins are thin consumers of the pre-computed I1 fields. No new DB migrations needed for Phase 36 — `I1Indicators.extra='allow'` handles the new fields.

---

## Standard Stack

### Core (already in use — no new dependencies)
| Component | Version | Purpose | Notes |
|-----------|---------|---------|-------|
| `aiokafka` | existing | Second Kafka consumer on `market.ticks` | `KafkaConsumerClient` wraps it |
| `numpy` | existing | EWMA, z-score, slope computations | Used by CMF, OBV, all I1 plugins |
| `pandas` | existing | DataFrame interface for `compute_full` / `compute_next` | Established pattern |
| `pydantic` | existing | `Tick` model from `src/providers/base.py` | Already serialized through tws_daemon |
| `collections.deque` | stdlib | Rolling window for OFI EWMA, CVD history | Used by CMF plugin (period-bounded deque) |

**No new dependencies required.** All computation uses existing numpy/pandas stack.

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/intelligence/indicators/
├── ofi.py                    # OFIPlugin — I1 OFI features (primary + proxy fallback)
└── cvd.py                    # CVDPlugin — I1 CVD features (tick rule accumulator)

src/intelligence/trading/
├── ofi_continuation.py       # trad_OFIContinuation
├── ofi_divergence.py         # trad_OFIDivergence
├── ofi_spike.py              # trad_OFISpike
├── cvd_divergence.py         # trad_CVDDivergence (dual_divergence flag)
├── cvd_spike.py              # trad_CVDSpike
├── delta_exhaustion.py       # trad_DeltaExhaustion
└── dual_divergence.py        # trad_DualDivergence (shadow mode)
```

Each file follows the `plugin = PluginClass()` module-level singleton pattern (all existing plugins do this).

### Pattern 1: I1 Plugin with Tick Buffer State

**What:** OFI and CVD plugins maintain a tick-list buffer in `_state` alongside the running EWMA / cumulative value. On `compute_full`, the plugin reads I1 bar OHLCV but also pulls `tick_buffer` from `_state` if populated by the tick consumer injection.

**Critical architecture insight:** The I1 plugins themselves do NOT consume from Kafka. The tick accumulation lives in `indicator_service` as a separate concern. `indicator_service._process_tick()` populates a `_tick_buffers: dict[str, list[dict]]` keyed by `symbol` (not `symbol:tf`). `_process_single_bar()` passes the tick buffer into the I1 plugin via the `frames` dict under key `"tick_buffer"`, then clears the buffer for that symbol.

```python
# Source: existing indicator_service.py _process_single_bar() pattern
# indicator_service.py — new tick consumer and buffer injection

# At service level:
self._tick_buffers: dict[str, list[dict]] = defaultdict(list)

async def _process_tick(self, symbol: str, payload: dict) -> None:
    """Buffer incoming ticks per symbol — flushed at bar close."""
    self._tick_buffers[symbol].append(payload)

async def _process_single_bar(self, symbol, timeframe, fields, ...):
    # ... existing bar parsing ...
    # Inject tick buffer into frames for OFI/CVD plugins; clear after use
    tick_buf = self._tick_buffers.pop(symbol, [])
    frames = {"main": self._get_df(key), "tick_buffer": tick_buf}
    features = await self._run_i1_plugins(frames, symbol, timeframe)
    # tick_buf is now consumed; buffer for this symbol is reset
```

**When to use:** Every `_process_single_bar` call.

### Pattern 2: OFIPlugin — Tick-Primary with Bar-Proxy Fallback

**What:** `compute_full` checks `frames.get("tick_buffer")`. If populated and non-empty, uses tick rule to compute per-bar OFI, accumulates EWMA, z-score. If empty (missing ticks), falls back to bar proxy. Sets `ofi_variant` accordingly.

```python
# Source: structural pattern from src/intelligence/indicators/obv.py
# src/intelligence/indicators/ofi.py

@dataclass
class OFIPlugin:
    name: str = "ind_OFI"
    outputs: frozenset[str] = frozenset({
        "ofi_ewma_5", "ofi_ewma_20", "ofi_divergence",
        "ofi_spike_z", "ofi_variant"
    })
    min_lookback: int = 5
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume", "microstructure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    _PROXY_EPSILON: float = 1e-9

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        tick_buf = frames.get("tick_buffer") or []
        if df is None or len(df) < self.min_lookback:
            return {}

        # Determine this bar's raw OFI value
        if tick_buf:
            raw_ofi = self._compute_tick_ofi(tick_buf)
            variant = "tick"
        else:
            raw_ofi = self._compute_proxy_ofi(df)
            variant = "proxy"

        # Update rolling history in state
        s = self._state
        ofi_history = s.setdefault("ofi_history", deque(maxlen=100))
        ofi_history.append(raw_ofi)

        # EWMA (span=5 and span=20)
        alpha5 = 2.0 / (5 + 1)
        alpha20 = 2.0 / (20 + 1)
        ewma5 = s.get("ewma5", raw_ofi)
        ewma20 = s.get("ewma20", raw_ofi)
        s["ewma5"] = ewma5 * (1 - alpha5) + raw_ofi * alpha5
        s["ewma20"] = ewma20 * (1 - alpha20) + raw_ofi * alpha20
        s["prev_close"] = float(df["close"].iloc[-1])

        # z-score vs 100-bar rolling history
        ofi_arr = np.array(list(ofi_history), dtype=float)
        if len(ofi_arr) >= 5:
            mean_ofi = float(np.mean(ofi_arr[:-1]))  # exclude current
            std_ofi = float(np.std(ofi_arr[:-1])) + 1e-9
            spike_z = (raw_ofi - mean_ofi) / std_ofi
        else:
            spike_z = 0.0

        # OFI divergence: compare OFI direction vs. price direction
        close_arr = df["close"].to_numpy(dtype=float)
        price_dir = 1 if close_arr[-1] > close_arr[-2] else (-1 if close_arr[-1] < close_arr[-2] else 0)
        ofi_dir = 1 if raw_ofi > 0 else (-1 if raw_ofi < 0 else 0)
        ofi_divergence = float(ofi_dir - price_dir)  # signed, range [-2, 2]

        return {
            "ofi_ewma_5": round(s["ewma5"], 6),
            "ofi_ewma_20": round(s["ewma20"], 6),
            "ofi_divergence": round(ofi_divergence, 4),
            "ofi_spike_z": round(spike_z, 4),
            "ofi_variant": variant,
        }

    def _compute_tick_ofi(self, tick_buf: list[dict]) -> float:
        """Tick rule: price > prev → buy vol; price < prev → sell vol; equal → neutral."""
        buy_vol = sell_vol = 0.0
        prev_price = None
        for tick in tick_buf:
            price = float(tick.get("price", 0))
            size = float(tick.get("size") or 0)
            if prev_price is None:
                prev_price = price
                continue
            if price > prev_price:
                buy_vol += size
            elif price < prev_price:
                sell_vol += size
            prev_price = price
        return buy_vol - sell_vol

    def _compute_proxy_ofi(self, df: pd.DataFrame) -> float:
        """Bar-level OFI proxy: (close - low) / (high - low + ε) × volume."""
        row = df.iloc[-1]
        h, l, c, v = float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
        return ((c - l) / (h - l + self._PROXY_EPSILON)) * v

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)
```

### Pattern 3: CVDPlugin — Session-Reset Cumulative Accumulator

**What:** Structural twin of `OBVPlugin`. Key difference: uses tick rule buy/sell split instead of direction×volume. Resets CVD to 0 at session open (09:30 ET). `cvd_slope_5bar` uses linear regression slope over last 5 CVD values.

```python
# Source: structural pattern from src/intelligence/indicators/obv.py
# CVD resets at session open — mirrors ctx_VolumeProfile session reset pattern
# (session_context.py _et_from_utc helper available)

# State keys: cum_cvd, cvd_history (deque maxlen=100), prev_price, last_session_date

# Session reset check (same approach as ctx_VolumeProfile):
bar_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None
if bar_ts:
    et_hour, et_date = _extract_et(bar_ts)
    if et_hour == 9 and et_date != s.get("last_session_date"):
        s["cum_cvd"] = 0.0
        s["last_session_date"] = et_date
```

### Pattern 4: I7 Plugin — Consuming I1 Microstructure Features

**What:** All 7 I7 plugins receive OFI/CVD features through the standard `frames.get("features")` dict (same as all existing I7 plugins). No new data flow plumbing needed — by the time I7 runs, `ofi_ewma_20`, `cvd`, `cvd_divergence`, etc. are already in the `IntelligenceEvent.i1` dict.

```python
# Source: pattern from src/intelligence/trading/divergence_stack.py
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    features = frames.get("features") or {}
    ofi_divergence = float(features.get("ofi_divergence") or 0.0)
    cvd_divergence = float(features.get("cvd_divergence") or 0.0)
    # ... gate logic ...
    if abs(ofi_divergence) >= self._DIVERGENCE_THRESHOLD:
        # signal fires
```

### Pattern 5: Shadow Mode for trad_DualDivergence

**What:** Shadow signals use the established `is_shadow=True` pattern from Phase 31/35. The plugin fires normally; signal_generator_service writes with `is_shadow=True` based on a registry flag or a plugin-level attribute.

```python
# Source: Phase 31 shadow infrastructure (SHAD-01)
# trad_DualDivergence sets a class attribute:
IS_SHADOW: bool = True  # checked by signal_generator_service

# signal_generator_service writes:
is_shadow = getattr(plugin, "IS_SHADOW", False)
```

**Check actual shadow injection point:** `signal_generator_service.py` already handles `is_shadow` — confirm the mechanism by grepping before implementing.

### Pattern 6: Second Kafka Consumer (market.ticks)

**What:** `indicator_service` currently uses a single `KafkaConsumerClient` subscribed to `market.bars` and optionally `system.events`. For ticks, a second dedicated `KafkaConsumerClient` is added (separate consumer group to avoid offset interference).

```python
# Source: indicator_service.py start() method pattern
# Tick consumer runs concurrently with bar consumer via asyncio.create_task

self._tick_consumer = KafkaConsumerClient(
    topic_market_ticks(self.env_name),
    bootstrap_servers=...,
    group_id="indicator_service_ticks",  # separate group from "indicator_service"
    auto_offset_reset="latest",
)
await self._tick_consumer.start()

tasks = [
    asyncio.create_task(self._process_market_data()),   # existing bar loop
    asyncio.create_task(self._process_tick_data()),      # new tick loop
    asyncio.create_task(self._health_monitor_loop()),
]
```

The tick loop simply buffers: `await self._process_tick(symbol, payload)`.

### Anti-Patterns to Avoid

- **Don't add OFI/CVD accumulation inside the I1 plugin `_state` directly from Kafka** — plugins are stateless w.r.t. Kafka; `indicator_service` owns the buffer, injects via `frames["tick_buffer"]`.
- **Don't reset CVD on every bar** — CVD is cumulative within a session. Only reset at session open. Resetting at every bar degrades it to a single-bar OFI proxy.
- **Don't use `return {}` for early exits in I7 plugins** — always use `self._no_signal()`. Inconsistent shape breaks callers (see Phase 34 lesson).
- **Don't declare `_state` on stateless I7 plugins** — only needed when tracking cross-bar history (see Phase 34 lesson: stateless I7s should NOT have `_state`). `trad_OFISpike` and `trad_CVDSpike` are stateless if they rely only on pre-computed z-scores from I1. `trad_OFIContinuation` needs state (N-bar directional tracking).
- **Don't block the tick consumer loop with heavy computation** — tick processing must be O(1) append. All OFI/CVD math happens at bar close in `_process_single_bar`.
- **Don't add `ofi_variant` as a `float`** — it's a string (`"tick"` or `"proxy"`). `build_i1_message` serializes `isinstance(v, (str, int, float, bool))` — strings pass through correctly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EWMA computation | Custom exponential smoothing | Standard `alpha = 2/(N+1)` formula with state | Dead simple, same as all TA libraries; numpy not needed for scalar update |
| Z-score over rolling window | Custom normalization | `deque(maxlen=100)` + `np.mean` + `np.std` | CMF plugin uses same pattern for period windows |
| CVD session reset timing | Custom clock | `session_context.py` `_et_from_utc` helper | Already used in `ctx_VolumeProfile` for 09:30 ET detection |
| Shadow signal plumbing | Per-plugin shadow logic | `IS_SHADOW = True` class attribute + existing signal_generator_service handler | Phase 31 infrastructure already handles this |
| Tick rule classification | Custom bid/ask spread analysis | Simple price comparison: `price > prev_price → buy; price < prev_price → sell` | Academic literature agrees; tick rule is standard for non-Level-2 data |
| Linear slope (cvd_slope_5bar) | Polynomial fitting | `np.polyfit(np.arange(5), last_5_cvd, 1)[0]` | One line; no custom slope estimator needed |

**Key insight:** All math is elementary. The complexity in this phase is the Kafka wiring (tick consumer + bar synchronization), not the signal computation.

---

## Common Pitfalls

### Pitfall 1: Tick Buffer Race Condition
**What goes wrong:** Ticks for bar T+1 arrive in the buffer before bar T's `_process_single_bar` fires. Those ticks contaminate bar T's OFI computation.
**Why it happens:** Kafka tick consumer and bar consumer are separate asyncio tasks; ordering is not guaranteed at the millisecond level.
**How to avoid:** `_process_single_bar` pops the entire buffer with `self._tick_buffers.pop(symbol, [])` atomically. Asyncio is single-threaded — a coroutine cannot be preempted mid-pop. This is safe as long as both tasks run in the same event loop (they do).
**Warning signs:** OFI values that seem implausibly large for a single bar; `ofi_variant="tick"` on a bar that had no tick activity.

### Pitfall 2: ofi_variant is a String Field — Serialization
**What goes wrong:** `build_i1_message` in `indicator_service` checks `isinstance(v, (str, int, float, bool))` before including in the flat message dict. Strings pass through. But downstream `parse_indicators_message` casts all non-OHLCV fields to `float` — string `"tick"` becomes a cast error, field is silently dropped.
**Why it happens:** `parse_indicators_message` assumes all feature fields are numeric.
**How to avoid:** `ofi_variant` must be treated as a passthrough string field. In `parse_indicators_message`, the try/except around `float(val)` catches the cast failure and falls back to `features[key] = val` (string). Verify this fallback actually runs and the field reaches downstream plugins.
**Warning signs:** `ofi_variant` not appearing in `intelligence_features` JSONB after a replay.

### Pitfall 3: CVD Cumulative Drift Over Long Sessions
**What goes wrong:** CVD accumulates indefinitely if session reset logic fires at wrong time (timezone bug, DST flip). By end of session, CVD value is so large that z-score gate never fires.
**Why it happens:** ET timezone requires `pytz` or `zoneinfo` — naive comparison to hour=9 fails during DST.
**How to avoid:** Reuse `ctx_VolumeProfile`'s `_et_from_utc` pattern which handles DST via `zoneinfo`. Reset on `et_hour == 9 AND et_minute == 30 AND et_date != last_session_date` (not just `et_hour == 9`). Also set `last_session_date` in `_state` to prevent re-triggering every bar of the 9 AM hour.
**Warning signs:** CVD values exceeding 1e7 on ES 1m by midday; `cvd_spike_z` permanently near zero.

### Pitfall 4: Missing Tick Data on Paper Account
**What goes wrong:** IBKR paper account does not deliver real-time ticks for crypto (BTCUSD, ETHUSD) and some commodities (BZ, NG already documented as paper-skip). The tick consumer receives nothing for these symbols.
**Why it happens:** Paper trading subscription limitations (documented in `PRICE_SENSITIVE_PLUGINS` notes and `PAPER_SKIP_CONTRACTS` in tws_daemon).
**How to avoid:** The bar-level proxy fallback handles this automatically — when `tick_buf` is empty, proxy fires and `ofi_variant="proxy"` is logged. No special casing needed. The startup audit (OFI-01) should log which symbols use proxy most frequently.
**Warning signs:** All symbols showing `ofi_variant="proxy"` on every bar — indicates tick consumer not subscribing or ticks not arriving.

### Pitfall 5: I7 Plugin State Confusion — Stateless vs Stateful
**What goes wrong:** `trad_OFIContinuation` needs to track N consecutive bars of directional OFI (state required). `trad_OFISpike` only checks the pre-computed `ofi_spike_z` from I1 (stateless). If `trad_OFISpike` is given a `_state` dict, test helper that uses `__new__` pattern must also inject it — easy to forget.
**Why it happens:** Phase 34 lesson: stateless I7 plugins should NOT declare `_state: dict = field(default_factory=dict)`.
**How to avoid:** Only `trad_OFIContinuation`, `trad_CVDDivergence` (for N-bar confirmation), and `trad_DualDivergence` need `_state`. The spike and point-in-time divergence plugins are stateless — they consume fully pre-computed I1 fields.
**Warning signs:** `pytest` test for OFISpike fails with `AttributeError: 'MagicMock' object has no attribute '_state'` after `__new__` instantiation.

### Pitfall 6: Plugin Count Tests Will Fail
**What goes wrong:** Adding 7 new I7 plugins will break hardcoded count assertions in tests.
**Why it happens:** `test_cis_plugins.py` or similar tests assert `len(TIER_I7) == 28`. After adding 7 new plugins, count is 35.
**How to avoid:** Update the hardcoded count constant in any test that checks `len(TIER_I7)`, `len(TIER_I1)`, or `total_plugin_count` as part of the registration wave.
**Warning signs:** `AssertionError: 28 != 35` in `test_cis_plugins.py` after registration.

### Pitfall 7: Tick Consumer Group ID Conflict
**What goes wrong:** Using the same `group_id="indicator_service"` for both consumers causes one to starve — Kafka assigns partitions to one consumer per group.
**Why it happens:** Kafka consumer groups control partition ownership.
**How to avoid:** Tick consumer uses `group_id="indicator_service_ticks"` (distinct from the bar consumer's `"indicator_service"`). Each consumer independently tracks its offset.
**Warning signs:** Tick loop receives no messages while bar loop is active.

---

## Code Examples

### EWMA Alpha Calculation
```python
# Standard TA EWMA: span=N → alpha = 2/(N+1)
# Source: pandas EWM documentation, standard technical analysis
alpha5 = 2.0 / (5 + 1)   # = 0.3333
alpha20 = 2.0 / (20 + 1)  # = 0.0952

ewma_new = ewma_prev * (1 - alpha) + raw_value * alpha
```

### Z-Score Over Rolling Deque
```python
# Source: pattern from src/intelligence/indicators/cmf.py (deque pattern)
# deque(maxlen=100) automatically evicts oldest entry
from collections import deque
import numpy as np

ofi_history = deque(maxlen=100)
ofi_history.append(raw_ofi)

arr = np.array(list(ofi_history), dtype=float)
if len(arr) >= 5:
    mean = float(np.mean(arr[:-1]))
    std = float(np.std(arr[:-1])) + 1e-9
    spike_z = (raw_ofi - mean) / std
```

### 5-Bar CVD Slope
```python
# Linear regression slope over last 5 CVD values
# Source: numpy polyfit standard pattern
cvd_history = list(s.get("cvd_history", []))[-5:]
if len(cvd_history) >= 5:
    slope = float(np.polyfit(np.arange(len(cvd_history)), cvd_history, 1)[0])
else:
    slope = 0.0
```

### Tick Buffer Injection in _process_single_bar
```python
# Source: indicator_service.py _process_single_bar pattern
# Inject tick buffer into frames; buffer cleared here (pop = atomic in asyncio)
tick_buf = self._tick_buffers.pop(symbol, [])
frames = {"main": self._get_df(key), "tick_buffer": tick_buf}
features = await self._run_i1_plugins(frames, symbol, timeframe)
# ofi_variant, ofi_ewma_20, cvd, etc. now in features dict
# Flows into build_i1_message → Kafka → intelligence_features
```

### trad_CVDDivergence dual_divergence flag
```python
# Source: pattern from src/intelligence/trading/divergence_stack.py
# trad_CVDDivergence.compute_full():
ofi_div = float(features.get("ofi_divergence") or 0.0)
cvd_div = float(features.get("cvd_divergence") or 0.0)

# Divergence condition: both disagree with price
dual_divergence = abs(ofi_div) >= self._OFI_THRESHOLD and abs(cvd_div) >= self._CVD_THRESHOLD

# Always include in return dict (instruments everything per Renaissance principle)
return {
    **base_signal_fields,
    "dual_divergence": dual_divergence,
}
```

### Checking shadow flag injection (verify before implementing)
```python
# Before coding the IS_SHADOW mechanism, grep for existing pattern:
# grep -n "is_shadow\|IS_SHADOW" services/signal_generator_service.py
# The Phase 35 implementation of shadow Kalman signals uses _kalman_shadow bool.
# trad_DualDivergence should use the same mechanism or a dedicated plugin attribute.
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| OFI via bid-ask spread (Level 2) | Tick rule (price vs prev price) | IBKR RTVolume provides trade price+size, not full book. Tick rule is correct fallback. |
| CVD without session reset | Session-reset CVD | Intraday CVD is more meaningful; resets prevent multi-session drift |
| Single OFI plugin with variants | 3 separate plugins (continuation/divergence/spike) | Renaissance SoC principle: independently tunable |
| Manual shadow promotion | Statistical promotion gate (promote_shadow.py) | Phase 31 infrastructure handles this |

---

## Open Questions

1. **Where does signal_generator_service inject `is_shadow=True` for plugin-level shadow mode?**
   - What we know: `signal_ledger.is_shadow` column exists. Phase 35 uses `_kalman_shadow` boolean in the service.
   - What's unclear: Whether there's a plugin-level class attribute mechanism or if shadow is always service-side.
   - Recommendation: `grep -n "is_shadow\|kalman_shadow\|IS_SHADOW" services/signal_generator_service.py` before implementing `trad_DualDivergence`. Use whatever pattern Phase 35 established.

2. **Does `parse_indicators_message` handle string fields correctly?**
   - What we know: The function has `try: features[key] = float(val); except: features[key] = val` fallback.
   - What's unclear: Whether downstream I3-I7 plugins or `intelligence_features` writer will accept non-numeric I1 fields.
   - Recommendation: Confirm `feature_writer_service` writes all I1 fields to `intelligence_features.i1` JSONB without type filtering. If it does float-only, `ofi_variant` needs a numeric encoding (0=proxy, 1=tick) as a companion field.

3. **Tick message format from tws_daemon**
   - What we know: tws_daemon publishes `{k: str(v) for k, v in tick.model_dump(mode="json").items()}` — all values are strings.
   - What's unclear: Whether `size` is always populated on RTVolume ticks for futures. Some ticks may have `size=None`.
   - Recommendation: `_compute_tick_ofi` must guard `float(tick.get("size") or 0)` — already shown in example above.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` or `pyproject.toml` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_ofi_plugin.py tests/unit/test_cvd_plugin.py -x -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OFI-01 | Bar-proxy fires when tick_buffer empty; `ofi_variant="proxy"` | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py::test_proxy_fallback_when_no_ticks -x` | Wave 0 |
| OFI-01 | Tick path fires when tick_buffer populated; `ofi_variant="tick"` | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py::test_tick_path_when_buffer_populated -x` | Wave 0 |
| OFI-02 | `ofi_ewma_20` converges over 20 bars | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py::test_ewma_20_convergence -x` | Wave 0 |
| OFI-02 | `ofi_divergence` sign correct (OFI up, price down → negative divergence) | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py::test_divergence_sign -x` | Wave 0 |
| OFI-03 | `trad_OFISpike` fires when `ofi_spike_z > 2.0` | unit | `.venv/bin/pytest tests/unit/test_ofi_plugins.py::test_ofi_spike_fires -x` | Wave 0 |
| OFI-03 | `trad_OFIContinuation` fires after N consecutive directional bars | unit | `.venv/bin/pytest tests/unit/test_ofi_plugins.py::test_continuation_n_bars -x` | Wave 0 |
| CVD-01 | CVD resets at session open (09:30 ET) | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_cvd.py::test_session_reset -x` | Wave 0 |
| CVD-01 | `cvd_slope_5bar` positive when CVD rising | unit | `.venv/bin/pytest tests/unit/intelligence/indicators/test_cvd.py::test_slope_sign -x` | Wave 0 |
| CVD-02 | `trad_CVDDivergence` fires; `dual_divergence=True` when both diverge | unit | `.venv/bin/pytest tests/unit/test_cvd_divergence.py::test_dual_divergence_flag -x` | Wave 0 |
| CVD-02 | `trad_DualDivergence` has `IS_SHADOW=True`; appears in TIER_I7 | unit | `.venv/bin/pytest tests/unit/test_plugin_registration.py::test_dual_divergence_shadow -x` | Wave 0 |
| All | `TIER_I7` count = 35 after adding 7 plugins; `validate_tier()` passes | unit | `.venv/bin/pytest tests/unit/test_cis_plugins.py -x` | Exists — update count |
| All | All 7 plugins appear in `TIER_I7`; `registry.validate_tier()` does not crash | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | Exists |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/ -x -q` (full unit suite, ~30s)
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/indicators/test_ofi.py` — covers OFI-01, OFI-02 (proxy fallback, tick path, EWMA convergence, divergence sign)
- [ ] `tests/unit/intelligence/indicators/test_cvd.py` — covers CVD-01 (session reset, slope sign, cumulative accumulation)
- [ ] `tests/unit/test_ofi_plugins.py` — covers OFI-03 variants (spike, continuation, divergence I7 plugins)
- [ ] `tests/unit/test_cvd_divergence.py` — covers CVD-02 (`dual_divergence` flag, shadow mode)
- [ ] Update `tests/unit/test_cis_plugins.py` (or equivalent) — update `TIER_I7` count from 28 → 35

---

## Sources

### Primary (HIGH confidence)
- `src/intelligence/indicators/obv.py` — CVD plugin structural analog (incremental accumulator with `_state`)
- `src/intelligence/indicators/cmf.py` — rolling deque pattern for period-bounded windows
- `src/intelligence/trading/divergence_stack.py` — always-log pattern, `dual_divergence` metadata field design
- `src/intelligence/trading/momentum_breakout.py` — canonical `_no_signal()` pattern, `regime_type` declaration
- `services/indicator_service.py` — `_process_single_bar()` injection point, tick buffer architecture, `_handle_roll_event()` migration pattern
- `src/intelligence/register_plugins.py` — `TIER_I7` list, `validate_schema_coverage()`, registration pattern
- `src/intelligence/schemas.py` — `I1Indicators` `extra='allow'` (confirms no schema migration needed)
- `src/providers/base.py` — `Tick` model fields (`price`, `size`, `bid`, `ask`, `bid_size`, `ask_size`, `source`)
- `src/core/stream_keys.py` — `topic_market_ticks()` already exists; confirmed correct topic name
- `src/core/kafka_utils.py` — `KafkaConsumerClient` pattern for second consumer
- `services/tws_daemon.py` — tick publishing format (`str(v)` for all fields, key=symbol)
- `.planning/phases/036-microstructure-plugins/036-CONTEXT.md` — locked decisions

### Secondary (MEDIUM confidence)
- `src/intelligence/trading/exhaustion_utils.py` — `apply_exhaustion_guard` usable in `trad_DeltaExhaustion`
- Phase 34 notes in STATE.md — stateless I7 plugin state anti-pattern lesson
- Phase 35 notes in STATE.md — shadow signal `_kalman_shadow` mechanism reference

---

## Metadata

**Confidence breakdown:**
- I1 plugin architecture: HIGH — direct code inspection of OBV/CMF patterns + indicator_service injection points
- Kafka tick consumer wiring: HIGH — `KafkaConsumerClient` pattern confirmed in codebase; `topic_market_ticks` already in stream_keys.py
- I7 plugin patterns: HIGH — divergence_stack.py + momentum_breakout.py are direct reference implementations
- Session reset for CVD: HIGH — ctx_VolumeProfile uses identical pattern already in production
- Shadow mode mechanism: MEDIUM — Phase 35 `_kalman_shadow` is service-side; plugin-level `IS_SHADOW` attribute needs verification
- String field serialization of `ofi_variant`: MEDIUM — `build_i1_message` passes strings but `parse_indicators_message` downstream behavior needs verification

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable codebase; 30 days)
