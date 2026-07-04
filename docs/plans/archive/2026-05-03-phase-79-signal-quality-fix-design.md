# Phase 79: Signal Quality Fix — Design Spec

**Date:** 2026-05-03
**Status:** Draft
**Milestone:** v2.5 Data Quality & Persistence Reliability
**Impact:** Fixes 99.7% signal never-activated rate + negative-PnL-on-target-hit bug

---

## Problem Statement

Two critical bugs in the signal pipeline:

1. **Zero-width activation zones (99.7% never-activated):** I7 plugins call `frame_trade()` which correctly computes `zone_low`/`zone_high` with ATR-based widths, but never include these fields in signal dicts. `signal_writer_agent` never maps them to DB. `lifecycle_tracker` falls back to `entry_price` for both bounds, creating a zero-width zone that requires a bar to exactly touch one price point.

2. **Wrong entry_price (negative PnL on target hits):** 20 I7 plugins store raw `close` as `entry_price` instead of resolved `tf.entry` from `frame_trade()`. For `at_pullback`/`at_limit` entry types, the resolved entry differs from raw close. Stop/target computed from resolved entry, PnL calculated against stored entry → wrong sign on PnL.

### Evidence

- 565,293 non-regime-suppressed signals, 563,744 (99.7%) outcome = `never_activated`
- All 8 `target_3_hit` signals have negative PnL (-0.52 to -0.60 R) — mathematically impossible for a full target hit
- Zero plugins use `make_signal()` — all 37 build signal dicts manually
- 20 plugins use `round(entry, 2)` instead of `round(tf.entry, 2)`

---

## Design

### Component 1: `make_signal_from_frame()` in `signal_schema.py`

New function that auto-extracts all TradeFrame fields:

```python
def make_signal_from_frame(
    tf: TradeFrame,
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    setup_plugin: str,
    direction: int,
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int = 10,
    features_snapshot: dict | None = None,
) -> dict:
```

Behavior:
- Asserts `tf.viable` is True (caller must check viability before calling)
- Auto-populates `entry_price` from `tf.entry` (resolved entry)
- Auto-populates `stop_loss` from `tf.stop`
- Auto-populates `targets` from `tf.targets`
- Auto-populates `zone_low`, `zone_high`, `entry_type` from TradeFrame
- Auto-populates `stop_type`, `framing_method`, `rr_t1/t2/t3`
- Auto-populates `target_labels` and `target_types` from TradeTarget objects
- Delegates to existing `make_signal()` for validation
- Adds `signal_schema_version = "v1"` field for lineage

`zone_low`, `zone_high`, `entry_type` are **NOT** added to `REQUIRED_SIGNAL_FIELDS` — they remain optional so v0 signals from unmigrated paths still pass validation. `make_signal_from_frame()` always includes them, so v1 signals always have them.

### Component 2: I7 Plugin Migration (37 plugins)

All plugins calling `frame_trade()` migrate from manual dict construction:

**Before (buggy):**
```python
tf = frame_trade(signal_type, direction, entry, features, atr)
if not tf.viable:
    return no_signal()
stop = tf.stop
targets = [round(t.price, 2) for t in tf.targets]
signal = {
    "signal_type": signal_type,
    "direction": direction,
    "entry_price": round(entry, 2),  # BUG: raw close
    "stop_loss": round(stop, 2),
    "targets": targets,
    ...
}
```

**After (fixed):**
```python
tf = frame_trade(signal_type, direction, entry, features, atr)
if not tf.viable:
    return no_signal()
signal = make_signal_from_frame(
    tf,
    symbol=symbol,
    timeframe=timeframe,
    timestamp=iso_ts,
    setup_plugin=self.name,
    direction=direction,
    confidence=confidence,
    regime_context=regime_ctx,
    confluence_score=confluence_score,
    supporting_factors=supporting,
    invalidation_conditions=invalidation,
)
signal["features_snapshot"] = capture_signal_features(...)
return signal
```

This simultaneously fixes entry_price, zone propagation, and missing framing fields.

Plugins that don't call `frame_trade()` (if any) remain unchanged but should be audited for manual entry/stop/target construction that may have the same entry_price bug.

Also fix `microstructure_utils.py` line 86 — shared utility with same `round(entry, 2)` bug.

### Component 3: `signal_writer_agent.py` mapping

Add to `_payload_to_ledger_entries()`:
- `entry_zone_low = signal.get("zone_low")`
- `entry_zone_high = signal.get("zone_high")`
- `entry_type = signal.get("entry_type", "at_close")`
- `signal_schema_version = signal.get("signal_schema_version", "v0")`
- `co_fire_count = signal.get("co_fire_count", 1)`
- `co_fire_partners = signal.get("co_fire_partners", [])`

### Component 4: DB Migration

```sql
-- 079_signal_quality_zones.sql
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_zone_low float;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_zone_high float;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_type text DEFAULT 'at_close';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS signal_schema_version text DEFAULT 'v0';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_count int DEFAULT 1;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_partners text[] DEFAULT '{}';
```

No backfill — `v0` signals retain NULL zones. `v1` signals get proper zones.

### Component 5: Prometheus Metrics

Add to `src/observability/metrics.py`:

```python
SIGNAL_OUTCOME_TOTAL = Counter(
    "signal_outcome_total",
    "Signal outcomes by plugin and result",
    ["setup_plugin", "outcome"],
)

SIGNAL_ACTIVATION_RATE = Gauge(
    "signal_activation_rate",
    "Activation rate per plugin (rolling 1h)",
    ["setup_plugin"],
)

SIGNAL_HIT_RATE = Gauge(
    "signal_hit_rate",
    "Target hit rate per plugin (rolling 1h)",
    ["setup_plugin"],
)
```

Updated by `lifecycle_tracker.py` on each signal resolution. Gauges computed from rolling 1h window of outcomes stored in a module-level deque.

### Component 6: Co-Fire Tracking (replaces dedup)

In the signal aggregator (`intelligence_pipeline_agent.py`):

1. After `_build_all_ranked()`, group signals by `(symbol, feature_ts, feature_tf, round(entry_price, 4), round(stop_loss, 4), tuple(round(t, 4) for t in targets))`.
2. For groups of size > 1, tag all members with `co_fire_count = len(group)` and `co_fire_partners = [p.name for p in group if p != current]`.
3. All co-firing signals are kept in `all_ranked` — none are removed.
4. The aggregator winner selection still picks the highest `adjusted_rank`, but the co-fire metadata is available for ML training.

Co-fire data flows through to `signal_ledger` via the writer (Component 3).

### Component 7: Signal Lineage Tag

Every signal gets `signal_schema_version`:
- `"v0"` — pre-fix signals (zero-width zones, potentially wrong entry_price)
- `"v1"` — post-fix signals (proper zones, correct entry_price)

ML training queries filter by version:
```sql
-- Clean training data only
SELECT * FROM signal_ledger
WHERE signal_schema_version = 'v1'
AND outcome IS NOT NULL;
```

The `signal_schema_version` is set by `make_signal_from_frame()` and falls back to `"v0"` in the writer for signals built by unmigrated code paths.

### Component 8: Historical Replay Validation

New script: `scripts/replay_signal_validation.py`

Purpose: Replay historical bars through the fixed pipeline and compare outcomes.

Flow:
1. Load last N days of `market_data_ohlcv` from TimescaleDB (default: 7 days)
2. For each bar, run the I7 pipeline with fixed code
3. Collect: total signals fired, activation count, target hit count, PnL distribution
4. Compare against historical `signal_ledger` for same period
5. Produce comparison report:
   - Activation rate: v0 vs v1
   - Hit rate: v0 vs v1
   - PnL distribution: v0 vs v1
   - Per-plugin breakdown
6. Statistical test: chi-squared on activation counts, Kolmogorov-Smirnov on PnL distributions

This provides instant validation without waiting for live data.

### Component 9: Lifecycle Tracker Verification

After Components 1-4 are deployed:
1. Verify zone fields are populated in `signal_ledger` for new signals
2. Monitor activation rate over first 4 hours of live trading
3. Verify no more negative PnL on target hits
4. Verify `signal_schema_version = 'v1'` on all new signals

---

## File Change Summary

| File | Change |
|------|--------|
| `src/intelligence/trading/signal_schema.py` | Add `make_signal_from_frame()`, add zone fields to `REQUIRED_SIGNAL_FIELDS` |
| `src/intelligence/trading/trade_framer.py` | No changes (zones already correct) |
| `src/intelligence/trading/lifecycle_tracker.py` | Add Prometheus metric updates on signal resolution (note: metrics may also need wiring in `services/signal_tracker_compute_service.py` if that's where resolution happens) |
| `src/intelligence/trading/microstructure_utils.py` | Fix `entry_price` to use `tf.entry` |
| 20 I7 plugins in `src/intelligence/trading/` | Migrate to `make_signal_from_frame()` |
| Remaining 17 I7 plugins | Audit for `frame_trade()` usage; migrate if applicable |
| `services/signal_writer_agent.py` | Add zone/version/co-fire field mapping |
| `src/intelligence/intelligence_pipeline_agent.py` | Add co-fire detection in aggregator |
| `src/observability/metrics.py` | Add signal quality metrics |
| `scripts/replay_signal_validation.py` | New: historical replay comparison |
| `production/migrations/079_signal_quality_zones.sql` | New: DB migration |

## Testing

1. **Unit tests:** `make_signal_from_frame()` validates all TradeFrame fields propagate correctly
2. **Unit tests:** Each migrated plugin tested with mock TradeFrame
3. **Integration test:** Full pipeline run with fixture data → verify zone fields in output
4. **Replay validation:** Historical replay script (Component 8)
5. **Live verification:** Monitor activation rate for first 4 hours post-deploy

## Success Criteria

1. Activation rate > 20% (up from 0.3%) within first trading day
2. Zero negative-PnL target hits
3. All new signals have `signal_schema_version = 'v1'` and non-NULL `entry_zone_low`/`entry_zone_high`
4. Replay script shows statistically significant improvement in activation rate (p < 0.05)
5. 3395+ unit tests pass (no regressions)

## Risks

- **Migration scope (37 plugins):** High-touch change. Mitigate with `make_signal_from_frame()` centralizing the fix — if the helper is correct, all plugins inherit correctness.
- **Zone width tuning:** Current ATR multipliers may produce zones that are too wide or too narrow post-fix. Monitor activation rate and tune if needed.
- **Co-fire false positives:** Grouping by exact entry/stop/target may miss near-duplicate signals. Tighten grouping key if co-fire noise is high.
- **Historical data contamination:** Pre-fix signals (v0) have wrong entry_price. ML training must filter to v1 only. Document in CLAUDE.md.
