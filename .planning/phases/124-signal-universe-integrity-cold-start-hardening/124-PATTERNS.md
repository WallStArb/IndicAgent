# Phase 124: Signal Universe Integrity + Cold-Start Hardening - Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 10
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `production/migrations/130_promote_ctf_columns.sql` | migration | batch | `production/migrations/124_add_i2_column.sql` | exact |
| `services/feature_writer.py` | service | request-response | itself (line 96 ON CONFLICT) | self-modify |
| `src/intelligence/trading/trend_following.py` | plugin | event-driven | `src/intelligence/trading/squeeze_expansion.py` | structural-reference |
| `src/intelligence/trading/ofi_continuation.py` | plugin | event-driven | `src/intelligence/trading/squeeze_expansion.py` | structural-reference |
| `src/intelligence/trading/liquidity_sweep_reclaim.py` | plugin | event-driven | `src/intelligence/trading/squeeze_expansion.py` | structural-reference |
| `src/intelligence/trading/pattern_completion.py` | plugin | event-driven | `src/intelligence/trading/squeeze_expansion.py` | structural-reference |
| `src/intelligence/trading/anchored_vwap_reversion.py` | plugin | event-driven | `src/intelligence/trading/squeeze_expansion.py` | structural-reference |
| `src/core/ml/training_data.py` | utility | batch-read | itself (lines 38-40) | self-modify |
| `src/core/memory/embedding.py` | utility | read | itself (lines 139-143) | self-modify |
| `production/scripts/run_historical_pipeline.py` | script | batch | itself (line 1476 skip_signals) | self-modify |

## Pattern Assignments

### `production/migrations/130_promote_ctf_columns.sql` (migration, batch)

**Analog:** `production/migrations/124_add_i2_column.sql`

**Migration structure pattern** (lines 20-22):
```sql
-- Statement 1: Add column (online DDL, no table lock at column add)
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i2 JSONB NOT NULL DEFAULT '{}';
```

**Backfill pattern** (lines 24-29):
```sql
-- Statement 2: Backfill live rows
-- I2 composite fields are all flat keys in market_context. cross_asset is the
-- only nested object and is NOT an I2 field. The subtraction operator removes it.
UPDATE intelligence_features
SET i2 = (market_context - 'cross_asset')
WHERE market_context != '{}'::jsonb;
```

**Data cleanup pattern** (lines 31-40):
```sql
-- Statement 3: Clean market_context to cross-asset only
-- After this UPDATE, market_context contains only the cross_asset nested object
-- (or '{}' if cross_asset was never present for that row). Separation is clean.
UPDATE intelligence_features
SET market_context = CASE
    WHEN market_context ? 'cross_asset'
        THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset')
    ELSE '{}'::jsonb
END
WHERE market_context != '{}'::jsonb;
```

**Decompress-before-DML pattern** (from `run_historical_pipeline.py`):
```python
# Per connection before DML on compressed chunks
cur.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
```

**Apply to migration 130:**
1. Use `ADD COLUMN IF NOT EXISTS` for 4 CTF columns (nullable, no default)
2. Backfill with `NULLIF(cross_timeframe_context->>'ctf_score','')::double precision` pattern
3. Strip keys from JSONB using `-` operator (single source of truth)
4. Add `SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0` if migration runs DML on compressed chunks

---

### `services/feature_writer.py` (service, request-response)

**Analog:** itself (current ON CONFLICT at line 96)

**Current ON CONFLICT pattern** (lines 62-96):
```python
_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, technical_indicators, market_context, pattern_detections, regime_features,
    confluence_scores, smc, cross_timeframe_context, composite_events, trading_signals,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry,
    feature_schema_version,
    ctx
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb,
    $17, $18, $19,
    $20, $21, $22,
    $23, $24, $25,
    $26, $27,
    $28, $29,
    $30, $31, $32,
    $33,
    (
        SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
        FROM ctx_snapshots
        WHERE (symbol = $2 OR symbol IS NULL)
          AND valid_from <= $1
          AND (valid_to IS NULL OR valid_to > $1)
    )
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""
```

**_record_to_insert_params pattern** (lines 166-220):
```python
def _record_to_insert_params(
    record: BarIntelligenceRecord,
    expiry_map: dict[str, date] | None = None,
    cross_asset_snapshot: dict | None = None,
) -> tuple:
    """Build a 33-element tuple of INSERT parameters for _INSERT_FEATURE_SQL."""
    event = record.intelligence
    # ... expiry, session computations ...

    i2_data = event.i2.model_dump(exclude_none=True)
    market_ctx = cross_asset_snapshot or {}

    return (
        event.ts,  # $1 ts
        event.symbol,  # $2 symbol
        event.tf,  # $3 tf
        event.platform,  # $4 platform
        event.source,  # $5 source
        record.schema_version,  # $6 schema_version
        event.bar.model_dump(),  # $7 bar
        event.i1.model_dump(),  # $8 i1
        market_ctx,  # $9 market_context (cross_asset only)
        event.i5.model_dump(exclude_none=True),  # $10 i5
        event.i3.model_dump(exclude_none=True),  # $11 i3
        event.i4.model_dump(exclude_none=True),  # $12 i4
        event.smc.model_dump(exclude_none=True),  # $13 smc
        event.i6.model_dump(exclude_none=True),  # $14 cross_timeframe_context
        i2_data,  # $15 i2
        [s.model_dump() for s in record.ranked_signals],  # $16 trading_signals
        # ... timestamps, winner, signal counts, latency, session, expiry ...
    )
```

**Apply to feature_writer.py:**
1. Add 4 CTF columns to INSERT statement: `ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement`
2. Extract CTF values from `event.i6.model_dump()` in `_record_to_insert_params` (I6 plugin already outputs these 4 fields in dict)
3. Change ON CONFLICT from `DO NOTHING` to `DO UPDATE SET ctf_score=EXCLUDED.ctf_score, ctf_trend_alignment=EXCLUDED.ctf_trend_alignment, ctf_structure_alignment=EXCLUDED.ctf_structure_alignment, ctf_regime_agreement=EXCLUDED.ctf_regime_agreement WHERE intelligence_features.ctf_score IS NULL`

---

### `src/intelligence/trading/trend_following.py` (plugin, event-driven)

**Analog:** `src/intelligence/trading/squeeze_expansion.py` (structural-onset reference)

**Structural event gate pattern** (SqueezeExpansion lines 72-76):
```python
# Gate: squeeze must have just released
squeeze_fired = features.get("squeeze_fired", 0.0)
squeeze_active = features.get("squeeze_active", 0.0)
if squeeze_fired != 1.0 or squeeze_active != 0.0:
    return no_signal()
```

**Context filter pattern** (SqueezeExpansion lines 96-99):
```python
# Gate: block in extreme GARCH vol regime (regime=3, top 5th pctile)
vol_regime = int(features.get("garch_vol_regime", 1))
if vol_regime == 3:
    return no_signal()
```

**Current TrendFollowing problem pattern** (lines 78-89):
```python
# PROBLEM: onset_guard fires on EVERY trend onset, not structural entry
trend_regime = features.get("trend_regime", 0.0)
trend_conf = features.get("trend_confidence", 0.0)
symbol = frames.get("__symbol__", "_")
tf_key = frames.get("__timeframe__", "_")
state_key = f"{symbol}_{tf_key}"
regime_condition = abs(trend_regime) >= regime_min and trend_conf >= confidence_min
is_new_onset = onset_guard(self._state, state_key, regime_condition)
if not regime_condition or not is_new_onset:
    return no_signal()
```

**Apply to trend_following.py:**
1. Demote `abs(trend_regime) >= regime_min` to context filter (must be trending, not trigger)
2. Re-anchor trigger to structural entry: pullback-to-MA reversal bar OR breakout from consolidation
3. Use `Parallel dicts → dataclass` pattern for pullback detection buffer (deque(maxlen=50) of MA history)
4. Follow SqueezeExpansion structural event pattern: binary event gate first, then context filters

---

### `src/intelligence/trading/ofi_continuation.py` (plugin, event-driven)

**Analog:** `src/intelligence/trading/squeeze_expansion.py` (structural-onset reference)

**Current OFIContinuation problem pattern** (lines 101-131):
```python
# PROBLEM: Fires on streak crossing N, not acceleration/thrust
ofi_ewma = features.get("ofi_ewma_20")
# ... magnitude threshold setup ...

current_dir = 1 if ofi_ewma > 0 else -1
direction, count = track_consecutive_state(frames, self._state, state_key, current_dir, "dir")

# PROBLEM: onset_guard fires on streak crossing min_bars (state), not acceleration
onset_key = f"{state_key}_onset"
condition_active = count >= min_bars and abs(ofi_ewma) >= mag_threshold
is_new_onset = onset_guard(self._state, onset_key, condition_active)
if not condition_active or not is_new_onset:
    return no_signal()
```

**State tracking pattern** (from `state_utils.py` lines 69-84):
```python
def track_consecutive_state(
    frames: dict[str, Any],
    state: dict[str, Any],
    state_key: str,
    current_value: int | float,
    value_type: str,
) -> tuple[int, int]:
    """Track consecutive bars where condition_value has the same sign.

    Returns:
        (direction, count) where direction is current sign (-1, 0, 1) and count
        is consecutive bars with that direction.
    """
    if state_key is None:
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

    entry = state.setdefault(state_key, {})
    prev_dir = entry.get(f"{value_type}_dir", 0)

    if current_value == 0:
        direction = 0
    elif current_value > 0:
        direction = 1
    else:
        direction = -1

    if direction == prev_dir:
        count = entry.get(f"{value_type}_count", 0) + 1
    else:
        count = 1
        entry[f"{value_type}_dir"] = direction  # Write back on sign change

    entry[f"{value_type}_count"] = count  # Always write back
    return direction, count
```

**Apply to ofi_continuation.py:**
1. Keep OFI streak as context filter (must have sustained imbalance)
2. Re-anchor trigger to OFI acceleration/thrust: EWMA gradient (second derivative) or volume spike
3. Use `Parallel dicts → dataclass` pattern for acceleration detection buffer (deque(maxlen=20) of OFI EWMA values)
4. Follow SqueezeExpansion magnitude gate pattern: threshold on acceleration, not persistence

---

### `src/intelligence/trading/liquidity_sweep_reclaim.py` (plugin, event-driven)

**Analog:** `src/intelligence/trading/squeeze_expansion.py` (rising-edge reference)

**Current LiquiditySweepReclaim problem pattern** (from RESEARCH lines 513-543):
```python
# PROBLEM: sweep_reclaimed flag stays hot for multiple bars
sweep_detected = features.get("sweep_detected", 0.0)
sweep_reclaimed = features.get("sweep_reclaimed", 0.0)
if sweep_detected != 1.0 or sweep_reclaimed != 1.0:
    return no_signal()
```

**Rising-edge detection pattern** (from `state_utils.py` lines 78-85):
```python
def onset_guard(state: dict[str, Any], state_key: str, condition_active: bool) -> bool:
    """Return True only when condition_active transitions from False to True.

    PLACEMENT: call UNCONDITIONALLY (after all gating logic but before return)
    so it sees False when condition drops — enabling proper rearm on next episode.
    """
    entry = state.setdefault(state_key, {})
    was_active = entry.get("onset_active", False)
    entry["onset_active"] = condition_active
    return condition_active and not was_active
```

**deduplicate_event pattern** (from `state_utils.py` lines 87-114):
```python
def deduplicate_event(
    state: dict,
    state_key: str,
    event_id: Any,
    *,
    min_bars_between_fires: int = _DEDUP_MIN_BARS,
) -> bool:
    """Return True only when event_id differs from last fired, or min_bars have elapsed.

    PLACEMENT: call AFTER all downstream gates, immediately before make_signal_from_frame.
    """
    entry = state.setdefault(state_key, {})
    entry["call_count"] = entry.get("call_count", 0) + 1
    call_count = entry["call_count"]

    last_id = entry.get("last_event_id")
    last_fire = entry.get("last_fire_call", call_count - min_bars_between_fires - 1)

    if event_id == last_id and (call_count - last_fire) < min_bars_between_fires:
        return False

    entry["last_event_id"] = event_id
    entry["last_fire_call"] = call_count
    return True
```

**Apply to liquidity_sweep_reclaim.py:**
1. Keep `sweep_detected == 1.0` gate (sweep must exist)
2. Detect rising edge of `sweep_reclaimed` (transition 0→1) using `onset_guard`
3. Add structural specificity: close-above swept level with acceptance (not wick)
4. Use `deduplicate_event` with event_id `(sweep_level, sweep_type)` for re-arm on re-sweeps

---

### `src/intelligence/trading/pattern_completion.py` (plugin, event-driven)

**Analog:** `src/intelligence/trading/squeeze_expansion.py` (structural-onset reference)

**Current PatternCompletion problem pattern** (from RESEARCH lines 453-506):
```python
# PROBLEM: Fires on confidence > threshold (continuous metric), not structural completion
dt_db_confidence = float(features.get("dt_db_confidence", 0.0))
dt_db_pattern = int(features.get("dt_db_pattern", 0))
if dt_db_confidence > confidence_min and dt_db_pattern in (1, 2):
    direction = -1 if dt_db_pattern == 1 else 1
    pattern_name = "double_top" if dt_db_pattern == 1 else "double_bottom"
    candidates.append((dt_db_confidence, direction, pattern_name))
```

**Instance tracking pattern** (from RESEARCH lines 207-250):
```python
from dataclasses import dataclass, field

@dataclass
class PatternInstanceState:
    """State for a single pattern instance."""
    pattern_name: str
    direction: int
    structural_anchor: float | int  # neckline for DT/DB, apex_bars for triangle
    fired_bars: int = 0  # Bars since fire (for re-arm logic)

class PatternCompletionPlugin:
    _state: dict = field(default_factory=dict)
    _instances: dict[str, PatternInstanceState] = field(default_factory=dict)

    def _get_instance_state(self, instance_id: str) -> PatternInstanceState:
        """Factory for lazy init of instance state."""
        if instance_id not in self._instances:
            self._instances[instance_id] = PatternInstanceState(
                pattern_name="", direction=0, structural_anchor=0
            )
        return self._instances[instance_id]
```

**Apply to pattern_completion.py:**
1. Trigger on structural completion criterion (target reached / neckline break), NOT confidence threshold
2. Demote confidence score to context filter (must have sufficient pattern quality)
3. Use `Parallel dicts → dataclass` pattern for instance registry (PatternInstanceState)
4. Mark instance as consumed after firing (never re-fire same instance)
5. Use `deduplicate_event` with structural anchor (neckline for DT/DB, apex_bars for triangle)

---

### `src/intelligence/trading/anchored_vwap_reversion.py` (plugin, event-driven)

**Analog:** `src/intelligence/trading/squeeze_expansion.py` (structural-event reference)

**Current AnchoredVWAPReversion problem pattern** (from RESEARCH lines 553-597):
```python
# PROBLEM: Fires on sigma threshold (continuous displacement), not departure+return event
sigma = features.get("session_vwap_deviation_sigma")
# ... regime, hurst, velocity checks ...

condition_active = (
    abs(sigma) >= sigma_min and hmm == 0 and hurst < hurst_max and velocity_toward_vwap
)
is_new_onset = onset_guard(self._state, state_key, condition_active)
if not condition_active or not is_new_onset:
    return no_signal()
```

**Apply to anchored_vwap_reversion.py:**
1. Trigger on departure+return structural event: `abs(sigma) >= sigma_min` (departure) AND velocity toward VWAP (return)
2. Add rejection/reclaim candle confirmation on return (not just price touching VWAP)
3. Use `Parallel dicts → dataclass` pattern for departure window buffer (deque(maxlen=50) of sigma history)
4. Follow SqueezeExpansion pattern: binary structural event gate, then magnitude thresholds

---

### `src/core/ml/training_data.py` (utility, batch-read)

**Analog:** itself (current CTF JSONB readers at lines 38-40)

**Current JSONB read pattern** (lines 38-40):
```python
-- i6 features
(f.cross_timeframe_context->>'ctf_score')::float       AS ctf_score,
(f.cross_timeframe_context->>'ctf_trend_alignment')::float AS ctf_trend_alignment,
(f.cross_timeframe_context->>'ctf_regime_agreement')::float AS ctf_regime_agreement,
```

**Apply to training_data.py:**
1. Change JSONB reads to top-level column reads after migration 130
2. Use `f.ctf_score` instead of `(f.cross_timeframe_context->>'ctf_score')::float`
3. Add `f.ctf_structure_alignment` (new column, not in current query)
4. Update all 4 CTF fields: `ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement`

---

### `src/core/memory/embedding.py` (utility, read)

**Analog:** itself (current fallback logic at lines 139-143)

**Current fallback pattern** (lines 139-143):
```python
# CTF composite score (cross-timeframe confluence, 0-1)
ctf_score = getattr(context, "ctf_score", None)
if ctf_score is None:
    ctf_score = getattr(context, "ctf_composite", None)  # Fallback to old field
if ctf_score is not None:
    tokens.append(f"ctf:{ctf_score:.2f}")
```

**Apply to embedding.py:**
1. Remove `ctf_composite` fallback after migration 130 (single source of truth)
2. Direct read from `context.ctf_score` (top-level attribute)
3. Ensure context object has CTF fields populated from top-level columns, not JSONB

---

### `production/scripts/run_historical_pipeline.py` (script, batch)

**Analog:** itself (existing `skip_signals` parameter at line 1476)

**Current skip_signals pattern** (lines 1471-1491):
```python
def replay_symbol(
    symbol: str,
    db_conn: Any,
    timeframes: list[str] | None = None,
    since: datetime | None = None,
    skip_signals: bool = False,  # ALREADY EXISTS
    calibration_curves: dict | None = None,
    perf_weights: dict | None = None,
    precomputed_features: dict | None = None,
) -> dict[str, int]:
    """Replay bars for *symbol* through the I1→I7 pipeline.

    Args:
        skip_signals: If True, run I1→I6 and write intelligence_features but
            skip I7 and signal_ledger writes. Use for seed/warmup runs where
            you only want indicator history, not historical signals.
    """
```

**Apply to run_historical_pipeline.py:**
1. Add `--warmup` argument to `main()` parser
2. When `--warmup` is set, call `run_pipeline()` twice:
   - First call: `skip_signals=True` (warmup pass — I1→I6 only)
   - Second call: `skip_signals=False` (signal pass — I1→I7 with warm I6 cache)
3. Validate `--warmup` requires `--replay-only` (warmup is replay-only)

---

## Shared Patterns

### Structural Onset Detection (All 5 plugin rewrites)

**Source:** `src/intelligence/trading/squeeze_expansion.py` lines 72-76

**Pattern:**
```python
# Structural event gate (binary, not continuous)
structural_fired = features.get("structural_fired", 0.0)
structural_active = features.get("structural_active", 0.0)
if structural_fired != 1.0 or structural_active != 0.0:
    return no_signal()
```

**Apply to:** All 5 over-firing plugins (trend_following, ofi_continuation, liquidity_sweep_reclaim, pattern_completion, anchored_vwap_reversion)

**Key insight:** Structural events fire once per occurrence (squeeze release, pattern completion, sweep reclaim), not on broad continuous states (trend regime, OFI streak, confidence threshold).

---

### Parallel Dicts → Dataclass Pattern (Plugin State Management)

**Source:** CLAUDE.md rule + `src/intelligence/trading/state_utils.py`

**Pattern:**
```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class PluginState:
    """Co-located state for a single key."""
    structural_anchor: float | int
    fired_bars: int = 0
    # ... all state for this key in one place ...

class MyPlugin:
    _state: dict[str, PluginState] = field(default_factory=dict)

    def _get_state(self, key: str) -> PluginState:
        """Factory for lazy init."""
        if key not in self._state:
            self._state[key] = PluginState(structural_anchor=0)
        return self._state[key]
```

**Apply to:**
- `trend_following.py` — pullback detection buffer (deque(maxlen=50) of MA history)
- `ofi_continuation.py` — acceleration detection buffer (deque(maxlen=20) of OFI EWMA)
- `pattern_completion.py` — instance registry (PatternInstanceState dataclass)
- `anchored_vwap_reversion.py` — departure window buffer (deque(maxlen=50) of sigma history)

**Key insight:** 3+ parallel dicts → single dataclass dict. Co-located memory, impossible mismatched state.

---

### deduplicate_event Pattern (Instance Tracking)

**Source:** `src/intelligence/trading/state_utils.py` lines 87-114

**Pattern:**
```python
from src.intelligence.trading.state_utils import deduplicate_event

# AFTER all gates, immediately before make_signal_from_frame
event_id = (pattern_name, direction, round(anchor, 4))
if not deduplicate_event(self._state, state_key, event_id):
    return no_signal()
```

**Apply to:**
- `liquidity_sweep_reclaim.py` — event_id `(sweep_level, sweep_type)`
- `pattern_completion.py` — event_id `(pattern_name, direction, anchor)`
- `anchored_vwap_reversion.py` — event_id `(departure_sigma, reclaim_level)`

**Key insight:** Structural anchor + direction uniquely identifies event. Re-arm after `_DEDUP_MIN_BARS` allows re-occurrence (same level swept twice).

---

### Context Filter AFTER Structural Trigger

**Source:** `src/intelligence/trading/squeeze_expansion.py` lines 72-99

**Pattern:**
```python
# 1. Structural event gate FIRST
if structural_fired != 1.0 or structural_active != 0.0:
    return no_signal()

# 2. Magnitude threshold
if volume_ratio <= 1.3:
    return no_signal()

# 3. Context filter LAST (regime, trend alignment, etc.)
vol_regime = int(features.get("garch_vol_regime", 1))
if vol_regime == 3:
    return no_signal()
```

**Apply to:** All 5 plugin rewrites

**Key insight:** Broad continuous metrics (trend_regime, OFI streak, confidence) are context filters, not triggers. Structural event must be identified first.

---

### IS NULL-only Guard (Cold-Start Correction)

**Source:** Phase 123 decision + `services/feature_writer.py` line 96

**Pattern:**
```python
ON CONFLICT (ts, symbol, tf)
DO UPDATE SET
    ctf_score = EXCLUDED.ctf_score,
    ctf_trend_alignment = EXCLUDED.ctf_trend_alignment,
    ctf_structure_alignment = EXCLUDED.ctf_structure_alignment,
    ctf_regime_agreement = EXCLUDED.ctf_regime_agreement
WHERE intelligence_features.ctf_score IS NULL
```

**Apply to:** `services/feature_writer.py` ON CONFLICT clause

**Key insight:** `ctf_score IS NULL` = cold-start (correctable). `ctf_score = 0.0` = genuine neutral (NOT correctable). Phase 123 semantics.

---

### ADD COLUMN IF NOT EXISTS Guard

**Source:** `production/migrations/124_add_i2_column.sql` lines 20-22

**Pattern:**
```sql
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i2 JSONB NOT NULL DEFAULT '{}';
```

**Apply to:** `production/migrations/130_promote_ctf_columns.sql`

**Key insight:** Prevents failure on duplicate application. Migration 013 made a prior attempt at i2 column; guard prevents conflict.

---

### Decompress-Before-DML Pattern

**Source:** `production/scripts/run_historical_pipeline.py`

**Pattern:**
```python
# Per connection before DML on compressed chunks
cur.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
```

**Apply to:** `production/migrations/130_promote_ctf_columns.sql` if migration runs DML on compressed chunks

**Key insight:** TimescaleDB decompresses chunks before DML. Setting to 0 forces decompression (slower but safe for large backfills).

---

### JSONB Backfill with NULLIF Pattern

**Source:** `production/migrations/124_add_i2_column.sql` lines 24-29

**Pattern:**
```sql
UPDATE intelligence_features
SET i2 = (market_context - 'cross_asset')
WHERE market_context != '{}'::jsonb;
```

**Apply to:** `production/migrations/130_promote_ctf_columns.sql` backfill statement

**Key insight:** Handle null/missing/empty string in JSONB. Use `NULLIF(cross_timeframe_context->>'ctf_score','')::double precision` to convert empty string to NULL.

---

### JSONB Key Strip Pattern (Single Source of Truth)

**Source:** `production/migrations/124_add_i2_column.sql` lines 31-40

**Pattern:**
```sql
UPDATE intelligence_features
SET market_context = CASE
    WHEN market_context ? 'cross_asset'
        THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset')
    ELSE '{}'::jsonb
END
WHERE market_context != '{}'::jsonb;
```

**Apply to:** `production/migrations/130_promote_ctf_columns.sql` strip statement

**Key insight:** After promoting columns to top-level, strip keys from JSONB to prevent dual source of truth. Use `-` operator for key removal.

---

## No Analog Found

**None** — all 10 files have exact or role-match analogs in the codebase.

## Metadata

**Analog search scope:**
- `production/migrations/` (120-129)
- `src/intelligence/trading/` (I7 plugins)
- `services/` (feature_writer)
- `src/core/ml/` (training_data)
- `src/core/memory/` (embedding)
- `production/scripts/` (run_historical_pipeline)

**Files scanned:** 15
**Pattern extraction date:** 2026-06-14

---

## PATTERN MAPPING COMPLETE

**Phase:** 124 - Signal Universe Integrity + Cold-Start Hardening
**Files classified:** 10
**Analogs found:** 10 / 10

### Coverage
- Files with exact analog: 5 (migration, feature_writer, training_data, embedding, run_historical_pipeline)
- Files with role-match analog: 5 (all 5 plugin rewrites reference SqueezeExpansion structural pattern)
- Files with no analog: 0

### Key Patterns Identified
- **Structural onset detection:** All 5 plugins must gate on binary structural events (squeeze release, pattern completion, sweep reclaim), not broad continuous states (trend regime, OFI streak, confidence threshold)
- **Parallel dicts → dataclass:** Plugin state management (pullback buffers, acceleration detection, instance tracking) via consolidated dataclass dict
- **IS NULL-only guard:** Cold-start correction mechanism (NULL = correctable, 0.0 = genuine neutral)
- **Single source of truth:** After promoting CTF to columns, strip JSONB keys to prevent drift
- **Context filter AFTER trigger:** Broad metrics (regime, trend) are filters, not primary triggers

### File Created
`.planning/phases/124-signal-universe-integrity-cold-start-hardening/124-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files for Wave A (migration + guard + warmup) and Wave B (5 plugin rewrites).
