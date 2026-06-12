# I2 Tier Persistence — Renaissance-Grade Design

**Date:** 2026-06-12  
**Status:** Approved for planning

---

## Root Cause Analysis

Three independent failures compound into one systemic problem:

**Failure 1 — Two pipeline implementations, two different `i2` contents.**  
The live pipeline (`executor.py`) calls `run_tiers()` which returns `tiered[tier_key]` — tier-isolated
output dicts. It constructs `IntelligenceEvent` as `I2Events(**tiered.get("i2", {}))`.  
The historical pipeline calls `run_analysis_pipeline()` which merges all tier outputs into a single flat
`intelligence` dict with no tier isolation. It then reconstructs tier models via
`_pick(I2Events, intelligence)` — a field-name filter across the entire merged dict.

These two paths produce structurally different `i2` content for the same bar. Any ML model trained on
historical feature rows cannot be trusted to match live production features. This is a hidden
training/production bias — the exact failure mode that destroys a fund.

**Failure 2 — I2Events schema has no contract.**  
`I2Events` uses `extra="allow"` and the schema validator explicitly skips I2
(`register_plugins.py:161`). Of the 10 I2 tier plugins, 4 composite plugins produce 19 fields that
are not declared in `I2Events`. They silently pass through via `extra="allow"`. Plugin output that is
not in the schema is invisible to the type system, invisible to the validator, and unauditable.

**Failure 3 — I2Events declares fields that belong to I3.**  
`I2Events` declares 8 MACD fields (`macd_cross_bullish` etc.) but the MACDEvents plugin runs in
`TIER_I3` (it depends on I3 support/resistance data). In the live pipeline these fields land in
`tiered["i3"]` and populate `I3Structure` — which already correctly declares all 8 fields with
`extra="forbid"`. The I2Events declarations are dead code that misleads `_pick` in the historical
pipeline into placing I3 outputs into `i2`. Two of them (`macd_price_divergence_bullish/bearish`) are
orphans — declared in I2Events but produced by no plugin at all.

**Consequence — `intelligence_features` has no trustworthy `i2` column.**  
The column does not exist. Live rows have partial I2 data buried in `market_context` mixed with
cross-asset snapshot data. Historical rows have no I2 data at all. `_load_precomputed_features`
omits `market_context` from its SELECT, so the `--use-precomputed-features` path is structurally
incomplete for any I7 plugin gating on I2 composite outputs.

---

## Design Invariants

1. **One pipeline, one truth.** Live and historical pipelines must produce identical `IntelligenceEvent`
   content for the same bar. Achieved by making both use the same tiered-dict construction path.
2. **Schema placement = computation placement.** Fields live in the schema of the tier whose plugins
   produce them. No cross-tier declarations.
3. **No `extra="allow"` in any tier schema.** Every field produced by every plugin is explicitly
   declared. Undeclared output is a startup crash, not a silent pass-through.
4. **`intelligence_features` columns have single, fully-declared semantics.** Each column maps
   exactly to one tier schema. Any code path that writes a row produces the same column content.

---

## Components

### A — Fix I2Events schema (`src/intelligence/schemas.py`)

**Remove** the 8 MACD field declarations from `I2Events`. They are already correctly declared in
`I3Structure` with `extra="forbid"`. The two orphans (`macd_price_divergence_bullish/bearish`) are
deleted entirely — no plugin produces them.

**Add** explicit field declarations for the 19 undeclared composite plugin outputs:

```
# cmp_MomentumAccel (9)
rsi_accel: float | None = None
macd_accel: float | None = None
roc_accel: float | None = None
inflection_flag: float | None = None
rsi_curvature: float | None = None
macd_hist_slope: float | None = None
price_accel: float | None = None
hma_slope: float | None = None
hma_accel: float | None = None

# cmp_DerivativeOscillator (4)
deriv_osc: float | None = None
deriv_osc_signal: float | None = None
deriv_osc_cross_bullish: float | None = None
deriv_osc_cross_bearish: float | None = None

# cmp_ExhaustionScore (3)
exhaustion_score: float | None = None
exhaustion_side: str | None = None
exhaustion_bars: float | None = None

# cmp_AccelerationRegime (3)
accel_regime: str | None = None
accel_score: float | None = None
accel_agreement: float | None = None
```

**Remove** `model_config = ConfigDict(extra="allow")`.

Result: I2Events declares exactly 45 fields (34 existing event fields − 8 MACD removals + 19
composite additions). Every field maps to a real plugin output. The schema is the complete contract.

Update the docstring to list all 10 I2 plugins with field counts.

### B — Enable I2 schema validation (`src/intelligence/register_plugins.py`)

Remove the "I2 are skipped (extra='allow')" exemption from `_validate_tier_output_coverage()`.
Add all 10 I2 plugins to `tier_checks` referencing `I2Events`. Startup now crashes if any I2 plugin
emits a field not declared in the schema — plugin/schema drift becomes immediately visible.

### C — `run_analysis_pipeline` returns tier-isolated outputs
(`production/scripts/run_historical_pipeline.py`)

Change the return type from `dict[str, Any]` to `tuple[dict[str, Any], dict[str, dict[str, Any]]]`
— `(intelligence_flat, tiered)`.

Track per-tier outputs alongside the existing flat merge. The tier_sequence already carries tier
labels; map them to lowercase keys matching the live pipeline convention:
`"I2"→"i2"`, `"I3"→"i3"`, `"I4"→"i4"`, `"I5"→"i5"`, `"SMC"→"smc"`, `"I6"→"i6"`.

```python
# Inside the existing plugin loop, after intelligence.update(out):
tiered.setdefault(tier_key_lower, {}).update(out)
```

Return `(intelligence, tiered)`. Update the single call site at line 1566 to unpack:

```python
intelligence, tiered = run_analysis_pipeline(frames, intelligence_cache, symbol, tf, plugin_states)
```

`all_features = {**i1_features, **intelligence}` is unchanged — I7 still receives the full flat dict.

### D — `_build_intelligence_event` uses tiered dicts
(`production/scripts/run_historical_pipeline.py`)

Change signature to accept `tiered: dict[str, dict]` instead of `intelligence: dict`.

Replace `_pick`-based construction with direct tier-dict construction, identical to the live pipeline:

```python
i1=I1Indicators(**i1_features),
i2=I2Events(**tiered.get("i2", {})),
i3=I3Structure(**tiered.get("i3", {})),
i4=I4Context(**tiered.get("i4", {})),
i5=I5Patterns(**tiered.get("i5", {})),
smc=SMCContext(**tiered.get("smc", {})),
i6=I6Confluence(**tiered.get("i6", {})),
```

Delete the `_pick` helper — it is no longer used anywhere.

Update the call site at line 1574:
```python
event = _build_intelligence_event(bar, i1_features, tiered, symbol, tf, ts)
```

### E — Database migration (`production/migrations/124_add_i2_column.sql`)

```sql
-- Add i2 column; default '{}' ensures existing rows are valid immediately (no table lock).
ALTER TABLE intelligence_features ADD COLUMN i2 JSONB NOT NULL DEFAULT '{}';

-- Backfill live rows: I2 fields are all flat keys in market_context.
-- cross_asset is the only nested key and is not an I2 field.
UPDATE intelligence_features
SET i2 = (market_context - 'cross_asset')
WHERE market_context != '{}'::jsonb;

-- Clean market_context to cross-asset data only.
UPDATE intelligence_features
SET market_context = CASE
    WHEN market_context ? 'cross_asset'
        THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset')
    ELSE '{}'::jsonb
END
WHERE market_context != '{}'::jsonb;
```

Uses `IF NOT EXISTS` on the ADD COLUMN — migration 013 (`013_add_i2_column.sql`) made a prior
attempt on 2026-03-01; the column is absent from the live DB but the guard prevents failure if
it was ever applied on another instance. Numbers 120 and 121 have pre-existing conflicts between
`production/migrations/` and `db/migrations/`; this migration uses 124 (one above the global max).

72,648 rows affected. The separation is unambiguous: `cross_asset` is always the only nested object
in `market_context`; every other flat key is an I2 composite plugin output.

Historical backfill rows have `market_context = '{}'` (the historical pipeline never wrote it), so
`i2` correctly starts as `'{}'` for those rows — they will be populated on next replay run.

### F — Live feature_writer (`services/feature_writer.py`)

Split `_record_to_insert_params`:

```python
# Before (mixed):
market_ctx = {**event.i2.model_dump(exclude_none=True), **(cross_asset_snapshot or {})}

# After (separated):
i2_data = event.i2.model_dump(exclude_none=True)
market_ctx = cross_asset_snapshot or {}
```

Add `i2` to `_INSERT_FEATURE_SQL` — new column inserted after `cross_timeframe_context`,
before `trading_signals`. Tuple grows from 32 to 33 elements. Add `$N::jsonb` placeholder.

`_UPDATE_MARKET_CTX_SQL` is unchanged — it only patches `market_context` and never touches `i2`.
Its callers already pass only cross-asset data via `cross_asset_snapshot`.

### G — Historical INSERT and tuple (`production/scripts/run_historical_pipeline.py`)

- `_INSERT_FEATURE_SYNC_SQL`: add `i2` to column list (14 columns total).
- `_INSERT_FEATURE_SYNC_TEMPLATE`: add `%s::jsonb` (14 placeholders).
- `_event_to_sync_params`: append `json.dumps(event.i2.model_dump(exclude_none=True))` — 14-element
  tuple. Update docstring column-order comment.

### H — `_load_precomputed_features` (`production/scripts/run_historical_pipeline.py`)

Add `i2` and `market_context` to the SELECT and merge loop (both currently absent — pre-existing
gap that this change closes). The merge loop iterates a list of dicts; adding two more requires no
structural change.

After this fix, `--use-precomputed-features` produces a flat features dict that includes all I2
composite fields (from `i2`) and cross-asset data (from `market_context`), making the path complete
for I7 signal generation.

---

## Test Changes

| File | Change |
|------|--------|
| `test_run_historical_pipeline.py` | `_event_to_sync_params` tuple length: 13→14 |
| `test_run_historical_pipeline.py` | `_build_intelligence_event`: assert `event.i2` present; update call signature (pass tiered dict) |
| `test_run_historical_pipeline.py` | `run_analysis_pipeline` tests: assert returns 2-tuple; assert `tiered["i2"]` contains I2 plugin outputs |
| `test_run_historical_pipeline.py` | Add: `tiered["i2"]` does not contain MACD fields (they're in `tiered["i3"]`) |
| New test | `I2Events` raises `ValidationError` when an undeclared extra field is passed |
| New test | `I2Events` accepts all 19 composite fields without error |

---

## Rollout Order

1. Apply migration 124 (online DDL — adds column with default, backfills 72k rows, cleans
   `market_context`; no table lock at column add; UPDATE holds row locks briefly).
2. Deploy feature_writer (writes clean `i2` + `market_context` going forward).
3. Deploy intelligence_pipeline (I2Events now strict — validation tightens, no behavior change).
4. Historical pipeline fix is available for next replay run.

No sequencing risk: the new column has a default `'{}'`, so any in-flight feature_writer build
during the deploy window writes `'{}'` to `i2` — correct, not corrupt.

---

## Out of Scope

Renaming `technical_indicators` / `pattern_detections` / `regime_features` / `confluence_scores`
columns to match tier names (`i1`/`i5`/`i3`/`i4`) — correct direction, separate migration with
dashboard and downstream query impact.
