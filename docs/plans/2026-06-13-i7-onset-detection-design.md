# I7 Signal Onset Detection — Design Spec

**Date:** 2026-06-13
**Status:** Design approved, pending implementation plan
**Target:** Fix before Phase 126 clean replay

---

## Root Cause

Seven I7 plugins fire on **persistent state**, not **event onset**. Raw signals are the training universe. When a plugin fires on 15-30% of bars, adjacent entries in the signal ledger are not independent observations — they are 20-50 autocorrelated samples of the same regime. ML models trained on this data learn spurious temporal autocorrelation, not the structural events the plugins were designed to detect.

Jim Simons' demand: every entry in the signal ledger marks the precise bar of a structural event. Not "the regime is trending" — "the trend just confirmed." Not "the pattern confidence is high" — "the pattern just completed."

The second defect is equally fundamental: every detection threshold in these plugins is a hard-coded opinion masquerading as an empirical result. `abs(sigma) >= 1.5` is a textbook financial convention, not a validated threshold for ES vs CL vs GC. `_MIN_CONSECUTIVE_BARS = 10` was explicitly noted in Phase 118 as a starting guess when the DB query returned no rows. This is the opposite of the empirical-over-theoretical principle.

---

## The Infrastructure Finding

Before designing fixes, audit what already exists.

The Phase 109 config foundation is fully production-ready and completely unused by I7 plugins:

| Component | Status | Purpose |
|-----------|--------|---------|
| `config_state` | Live, 5 rows | Current key-value store with versioning |
| `config_schema` | Live, 10 rows | Validation rules: type, min, max, description |
| `config_history` | Live, empty | Full audit trail: changed_by, reason, timestamp |
| `config_outbox` → `topic_config_updates` | Live | Kafka hot-reload broadcast |
| `ConfigService` | Live | Transactional read/write, in-memory cache |
| `OPS_PREFIXES` | Has `"threshold."` | Plugin threshold namespace already authorized |

**Level 3 adaptive parameters are a single `ConfigService.set()` call.** When ML discovery learns a better threshold from 500 outcome-labeled signals, it writes: `ConfigService.set("threshold.trend_following.regime_min", 0.62, changed_by="ml_discovery", reason="n=847, bootstrap_ci_lower=0.58")`. The outbox broadcasts it to `topic_config_updates`. The running pipeline hot-reloads it. `config_history` captures the learned value, sample size, and confidence. Zero new infrastructure.

The delta from here to a fully operational parameter management system is:
1. A migration adding `threshold.*` keys to `config_schema`
2. Plugins reading from `ConfigService` instead of class constants
3. One dashboard page reading `config_state`

---

## Two Distinct Structural Anti-Patterns

Reading the code reveals two structurally different defects. The fix topology is not uniform.

### Anti-Pattern A: State Persistence

The gate condition is binary and stays `True` for 50+ consecutive bars. The condition itself is valid; the detection is wrong. The fix is onset detection — fire only on the `False → True` transition.

Affected: TrendFollowing, OFIContinuation, AnchoredVWAPReversion.

### Anti-Pattern B: Event Identity Persistence

The upstream plugin returns the same historical event on every subsequent bar. There is no transition to detect. The fix is event deduplication — fire once per unique event identity.

Affected: LiquiditySweepReclaim, PatternCompletion, FVGFill, CHoCHReversal.

---

## Shared Infrastructure: `state_utils.py` Extensions

Both onset fix patterns are reusable. Add two utilities alongside the existing `track_consecutive_state`.

### `onset_guard(state, state_key, condition_active) -> bool`

Returns `True` only on a `False → True` transition. Rearmed when condition goes `False`.

```python
def onset_guard(state: dict, state_key: str, condition_active: bool) -> bool:
    entry = state.setdefault(state_key, {})
    was_active = entry.get("onset_active", False)
    entry["onset_active"] = condition_active
    return condition_active and not was_active
```

### `deduplicate_event(state, state_key, event_id) -> bool`

Returns `True` only when `event_id` differs from the last fired event. Updates state on `True`.

```python
def deduplicate_event(state: dict, state_key: str, event_id: Any) -> bool:
    entry = state.setdefault(state_key, {})
    if entry.get("last_event_id") == event_id:
        return False
    entry["last_event_id"] = event_id
    return True
```

Both are pure state helpers. No signal logic. Independently unit-tested. No upstream or downstream changes.

---

## Parameter Infrastructure: `config_schema` Registration

Register all plugin detection thresholds as `threshold.*` keys. The table schema already supports everything needed: `value_type`, `min_value`, `max_value`, `description`. JSON type handles instrument-specific param dicts.

Keys to register (initial seed values = current hard-coded values, `source` noted in description):

```sql
-- TrendFollowing
('threshold.trend_following.regime_min',        'float', '0.5',  0.0, 1.0,  'Minimum abs(trend_regime) to qualify. Initial estimate — not empirically validated.')
('threshold.trend_following.confidence_min',    'float', '0.4',  0.0, 1.0,  'Minimum trend_confidence to qualify. Initial estimate.')

-- OFIContinuation
('threshold.ofi_continuation.min_bars',         'int',   '10',   1,   100,  'Minimum consecutive bars of directional OFI. Initial estimate (Phase 118 RCA guess — DB had no rows).')
('threshold.ofi_continuation.magnitude_floors', 'json',  '{"ES":500,"NQ":200,"CL":1000,"GC":500,"_default":500}', NULL, NULL, 'Per-instrument OFI magnitude floor. Initial estimate.')

-- PatternCompletion
('threshold.pattern_completion.confidence_min', 'float', '0.70', 0.0, 1.0,  'Minimum I5 pattern confidence to qualify. Raised from 0.50 in Phase 118 — not outcome-validated.')

-- AnchoredVWAPReversion
('threshold.vwap_reversion.sigma_min',          'float', '1.5',  0.5, 4.0,  'Minimum abs(session_vwap_deviation_sigma) to qualify. Textbook 1.5σ convention — not instrument-validated.')
('threshold.vwap_reversion.hurst_max',          'float', '0.55', 0.3, 0.7,  'Maximum hurst_exponent for mean-reversion tendency. Textbook threshold — not outcome-validated.')
```

No entry for LiquiditySweepReclaim thresholds in this pass — its fix is structural (event deduplication), not parametric.

---

## Per-Plugin Fix Design

### 1. `trad_TrendFollowing` — Anti-Pattern A

**Current:** fires every bar `abs(trend_regime) >= 0.5 AND swing_pattern confirms AND trend_conf >= 0.4`.

**Fix — onset guard on combined qualifying condition:**

```python
# Load thresholds from config at plugin init (with hard-coded fallback)
# regime_min = config.get("threshold.trend_following.regime_min", 0.5)
# confidence_min = config.get("threshold.trend_following.confidence_min", 0.4)

state_key = f"{frames.get('__symbol__', '_')}_{features.get('timeframe', '_')}"
condition_active = (
    abs(trend_regime) >= self.regime_min
    and trend_conf >= self.confidence_min
    and ((direction == 1 and swing_pattern > 0) or (direction == -1 and swing_pattern < 0))
)
if not onset_guard(self._state, state_key, condition_active):
    return no_signal()
```

Place after computing `direction`, before `extract_ohlcv` (preserves the Phase 48 optimization — onset guard is pure dict work).

**Expected:** 1-3% firing rate (one fire per trend confirmation onset, not per bar in trend).

---

### 2. `trad_OFIContinuation` — Anti-Pattern A (threshold-crossing variant)

**Current:** `count >= 10` fires on bar 10, 11, 12, 13... until streak breaks.

**Fix — onset guard on threshold crossing, streak reset on rearm:**

```python
# Load from config: min_bars = config.get("threshold.ofi_continuation.min_bars", 10)
# Load from config: mag_floors = config.get("threshold.ofi_continuation.magnitude_floors", _OFI_PARAMS_DEFAULT_DICT)

direction, count = track_consecutive_state(frames, self._state, state_key, current_dir, "dir")

if count < self.min_bars:
    return no_signal()

onset_key = f"{state_key}_onset"
if not onset_guard(self._state, onset_key, count >= self.min_bars):
    return no_signal()
```

`onset_key` uses a separate namespace from the streak counter. The onset guard rearmed automatically when the streak direction reverses (track_consecutive_state resets count to 1, making `count >= N` False).

**Expected:** 0.5-2% firing rate (one fire per distinct OFI episode).

---

### 3. `trad_LiquiditySweepReclaim` — Anti-Pattern B

**Current:** upstream `LiquiditySweepsPlugin` scans 120-bar lookback, returns most recent sweep. Same `(sweep_level, sweep_type)` appears on every subsequent bar until a newer sweep displaces it.

**Fix — deduplicate by sweep event identity:**

```python
# Flag gates first (cheap, no state needed)
if sweep_detected != 1.0 or sweep_reclaimed != 1.0 or sweep_type == 0.0:
    return no_signal()

state_key = f"{frames.get('symbol', '_')}_{features.get('timeframe', '_')}"
event_id = (float(sweep_level), float(sweep_type))
if not deduplicate_event(self._state, state_key, event_id):
    return no_signal()
```

A new sweep at a different level or direction is a genuinely distinct event and fires normally.

**Expected:** 1-3% firing rate (one fire per unique sweep-and-reclaim event).

---

### 4. `trad_PatternCompletion` — Anti-Pattern B

**Current:** I5 confidence scores persist once above threshold. Plugin fires on bar N, N+1, N+2... reading the same pattern.

**Fix — deduplicate by pattern identity, load threshold from config:**

```python
# Load from config: confidence_min = config.get("threshold.pattern_completion.confidence_min", 0.70)
# (replace self.confidence_threshold references with self.confidence_min)

# After computing best_confidence, direction, pattern_name (existing logic unchanged):
if not candidates:
    return no_signal()

state_key = f"{frames.get('symbol', '_')}_{features.get('timeframe', '_')}"
best_confidence, direction, pattern_name = max(candidates, key=lambda x: x[0])
event_id = (pattern_name, direction)
if not deduplicate_event(self._state, state_key, event_id):
    return no_signal()
```

If the best qualifying pattern changes (e.g., double_top loses confidence and H&S takes over), the `event_id` changes and the plugin correctly fires again.

**Expected:** 1-3% firing rate (one fire per chart pattern completion).

---

### 5. `trad_AnchoredVWAPReversion` — Anti-Pattern A (compound fix)

Two problems, both required.

**Fix 1 — Promote velocity to hard gate (structural criteria tightening):**

The signal thesis is mean reversion: not just "price is displaced" but "price is displaced AND has begun reverting." `session_vwap_deviation_velocity` already captures this but is only a soft confidence weight.

```python
# After existing sigma/hmm/hurst gates (with config-loaded thresholds):
velocity = float(features.get("session_vwap_deviation_velocity", 0.0))
velocity_toward_vwap = (velocity < 0 if direction == -1 else velocity > 0)
if not velocity_toward_vwap:
    return no_signal()
```

Remove `velocity_score` from the confidence composite (the hard gate subsumes it). Rebalance remaining 3 factors: `sigma_magnitude=0.40`, `hurst_quality=0.35`, `vol_stability=0.25`.

**Fix 2 — Onset guard on combined condition:**

Even with velocity gated, price can stay displaced and actively reverting for 3-5 bars.

```python
# Load from config: sigma_min = config.get("threshold.vwap_reversion.sigma_min", 1.5)
#                   hurst_max = config.get("threshold.vwap_reversion.hurst_max", 0.55)

state_key = f"{frames.get('symbol', '_')}_{features.get('timeframe', '_')}"
condition_active = (
    abs(sigma) >= self.sigma_min
    and hmm == 0
    and hurst < self.hurst_max
    and velocity_toward_vwap
)
if not onset_guard(self._state, state_key, condition_active):
    return no_signal()
```

The combination fires on the precise bar where displacement reaches extreme AND reversion is already underway. That is a specific structural moment, not a state.

**Expected:** 2-4% firing rate.

---

## Dashboard: Threshold Parameters Screen

Add `/config/thresholds` page to the Next.js dashboard. Reads `config_state JOIN config_schema` — no new API endpoints needed (existing config API).

Display per row: key, current value, type, min/max bounds, description, last updated, version. Include a description note when `changed_by` is `"ml_discovery"` (shows learned values vs manual vs initial estimates).

Inline edit with optimistic update + version conflict detection (the `ConfigVersionConflict` path in `ConfigService.set()` is already implemented).

---

## Level 3 Integration Path

When ML discovery is ready:

```python
# After outcome analysis on N resolved signals:
config_service.set(
    "threshold.trend_following.regime_min",
    learned_value,
    changed_by="ml_discovery",
    reason=f"n={n}, bootstrap_ci_lower={ci_lower:.3f}, p={p:.4f}",
)
```

The outbox broadcasts the new value to `topic_config_updates`. Running `intelligence_pipeline` receives it and reloads the threshold on the next config poll cycle. `config_history` preserves the full provenance: what was learned, from how many samples, with what confidence.

Zero new infrastructure required for Level 3.

---

## Per-Plugin Fix Design (continued)

### 6. `trad_FVGFill` — Anti-Pattern B

**Current:** upstream `FairValueGapPlugin` scans the full lookback for all unfilled FVGs and returns the oldest unfilled zone. That `(fvg_type, fvg_top, fvg_bottom)` triple persists in the output on every bar until price fills the gap. The I7 plugin fires every bar the zone is open.

**Fix — deduplicate by FVG zone identity:**

```python
# Flag gate first (cheap)
if fvg_type == 0 or fvg_open_count < 1.0:
    return no_signal()

state_key = f"{frames.get('symbol', '_')}_{features.get('timeframe', '_')}"
fvg_top = float(features.get("fvg_top", 0.0))
fvg_bottom = float(features.get("fvg_bottom", 0.0))
event_id = (int(fvg_type), round(fvg_top, 4), round(fvg_bottom, 4))
if not deduplicate_event(self._state, state_key, event_id):
    return no_signal()
```

A new FVG at different zone boundaries (old one filled, new one appeared) fires normally.

No `config_schema` threshold registration needed — the gate (`fvg_open_count >= 1.0`) is structural, not a tunable threshold. `fvg_open_count` is a count of open zones, not a model parameter.

**Expected:** 1-3% firing rate (one fire per distinct FVG zone).

---

### 7. `trad_CHoCHReversal` — Anti-Pattern B

**Current:** upstream `BOSCHoCHPlugin` scans bars after the most recent swing for a price close beyond the swing level. Once CHoCH is detected at bar `i`, the same historical bar remains in the lookback window on subsequent bars, the same `bos_level` is still broken, so `choch_detected=1.0` persists until the swing structure changes.

**Fix — deduplicate by structural break identity `(choch_direction, bos_level)`:**

```python
if choch_detected != 1.0 or choch_direction == 0:
    return no_signal()

state_key = f"{frames.get('symbol', '_')}_{features.get('timeframe', '_')}"
bos_level = float(features.get("bos_level", 0.0))
event_id = (int(choch_direction), round(bos_level, 4))
if not deduplicate_event(self._state, state_key, event_id):
    return no_signal()
```

A genuine new CHoCH at a different broken swing level fires normally.

No new `config_schema` keys needed for this plugin — no tunable detection thresholds in the gate logic.

**Expected:** 1-3% firing rate (one fire per distinct structural break event).

---

## config_schema Registrations (All 7 Plugins)

Register all tunable detection thresholds as `threshold.*` keys. FVGFill and CHoCHReversal have no tunable threshold parameters — their fixes are purely structural (event identity). The five original plugins all get config registration.

```sql
-- TrendFollowing
('threshold.trend_following.regime_min',        'float', '0.5',  0.0, 1.0,  'Minimum abs(trend_regime). Initial estimate — not empirically validated.')
('threshold.trend_following.confidence_min',    'float', '0.4',  0.0, 1.0,  'Minimum trend_confidence. Initial estimate.')

-- OFIContinuation
('threshold.ofi_continuation.min_bars',         'int',   '10',   1,   100,  'Minimum consecutive directional OFI bars. Phase 118 RCA guess — DB had no rows at calibration time.')
('threshold.ofi_continuation.magnitude_floors', 'json',  '{"ES":500,"NQ":200,"CL":1000,"GC":500,"_default":500}', NULL, NULL, 'Per-instrument OFI magnitude floor. Initial estimate.')

-- PatternCompletion
('threshold.pattern_completion.confidence_min', 'float', '0.70', 0.0, 1.0,  'Minimum I5 pattern confidence. Raised from 0.50 in Phase 118 — not outcome-validated.')

-- AnchoredVWAPReversion
('threshold.vwap_reversion.sigma_min',          'float', '1.5',  0.5, 4.0,  'Minimum abs(session_vwap_deviation_sigma). Textbook 1.5σ — not instrument-validated.')
('threshold.vwap_reversion.hurst_max',          'float', '0.55', 0.3, 0.7,  'Maximum hurst_exponent for mean-reversion. Textbook threshold — not outcome-validated.')
```

Each plugin loads its thresholds via `ConfigService.get(key, default=X)` at init and stores them as instance attributes. Hard-coded class constants are removed. The fallback default keeps the plugin functional if the config DB is unavailable at startup.

## Implementation Order

1. `state_utils.py` — add `onset_guard` + `deduplicate_event` with unit tests
2. Migration — register `threshold.*` keys in `config_schema`, seed `config_state`
3. Plugin fixes (7 total):
   - Anti-Pattern A: TrendFollowing, OFIContinuation, AnchoredVWAPReversion
   - Anti-Pattern B: LiquiditySweepReclaim, PatternCompletion, FVGFill, CHoCHReversal
4. Dashboard — `/config/thresholds` page
5. Validate firing rates against reference anchors before Phase 126 replay

---

## Observability

After fixes, verify firing rates via:

```sql
SELECT
    setup_plugin,
    feature_tf,
    COUNT(*) AS total_signals,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY feature_tf), 1) AS pct_of_tf
FROM signal_ledger
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY setup_plugin, feature_tf
ORDER BY feature_tf, total_signals DESC;
```

Target: all five plugins below 5% per timeframe.
Reference anchors: SqueezeExpansion ~0.3%, SupplyDemand ~0.1%, CVDDivergence 1-2.5%.

---

## What This Does NOT Change

- Upstream I4/I5/SMC plugin logic
- Downstream aggregator, persistence, lifecycle tracker
- Signal schema
- Shadow governance thresholds or promotion criteria
- The 25 remaining I7 plugins not in the 7-plugin scope. The rebuild data shows 12 plugins active so far; DivergenceStack (4%), GapAnalysisSetup (5%), CVDDivergence (2%), SqueezeExpansion (0.3%), SupplyDemandSetup (0.1%) are all within acceptable bounds. The remaining plugins will be evaluated once the rebuild completes and full firing rate data is available.
