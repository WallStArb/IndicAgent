# I2 Tier Persistence — Design Spec

**Date:** 2026-06-12
**Status:** Approved for planning

## Problem Statement

`I2Events` has no schema contract (`extra="allow"`, validator skipped) and the `intelligence_features`
table has no `i2` column. As a result:

- Live pipeline: 19 composite plugin outputs slip through `extra="allow"` into `market_context` mixed
  with cross-asset snapshot data — wrong column, no type enforcement.
- Historical pipeline: `_pick(I2Events, intelligence)` drops all undeclared fields; `_INSERT_FEATURE_SYNC_SQL`
  has no `market_context` column at all — I2 is fully absent from every backfill row.
- `_load_precomputed_features` omits `market_context` from its SELECT — `--use-precomputed-features`
  produces structurally incomplete feature vectors, causing silent wrong answers for any I7 plugin
  gating on I2 composite outputs (exhaustion, acceleration regime).
- Schema validator explicitly skips I2 (`register_plugins.py:161`), so plugin/schema drift is
  permanently invisible.

## Design

### Invariants

- Every column in `intelligence_features` has a single, fully-declared semantic.
- No tier schema uses `extra="allow"`. All plugin outputs are declared.
- Schema validator covers all tiers including I2.
- `market_context` contains only cross-asset snapshot data.
- `_load_precomputed_features` produces feature vectors that are complete enough to reproduce
  I7 signal generation without rerunning I1-I6.

### Change 1 — I2Events schema contract (`src/intelligence/schemas.py`)

Remove `model_config = ConfigDict(extra="allow")`. Add explicit field declarations for the 19
currently undeclared composite plugin outputs:

**cmp_MomentumAccel (9):** `rsi_accel`, `macd_accel`, `roc_accel`, `inflection_flag`,
`rsi_curvature`, `macd_hist_slope`, `price_accel`, `hma_slope`, `hma_accel`

**cmp_DerivativeOscillator (4):** `deriv_osc`, `deriv_osc_signal`,
`deriv_osc_cross_bullish`, `deriv_osc_cross_bearish`

**cmp_ExhaustionScore (3):** `exhaustion_score`, `exhaustion_side`, `exhaustion_bars`

**cmp_AccelerationRegime (3):** `accel_regime`, `accel_score`, `accel_agreement`

All new fields typed `float | None = None` except `exhaustion_side: str | None = None`
and `accel_regime: str | None = None`.

Result: I2Events fully declares all 53 fields (34 existing + 19 new). Any undeclared output
from an I2 plugin will raise `ValidationError` at construction — loud crash, not silent wrong answer.

### Change 2 — Enable I2 schema validation (`src/intelligence/register_plugins.py`)

Remove the "I2 are skipped (extra='allow')" exemption from `_validate_tier_output_coverage()`.
Add all 10 I2 plugins to the tier_checks list, referencing `I2Events` as the target schema.
This makes plugin/schema drift a startup crash, not a runtime mystery.

### Change 3 — Database migration (`production/migrations/124_add_i2_column.sql`)

```sql
ALTER TABLE intelligence_features ADD COLUMN i2 JSONB NOT NULL DEFAULT '{}';

-- Backfill: I2 fields are all flat keys in market_context; cross_asset is the only nested key.
UPDATE intelligence_features
SET i2 = (market_context - 'cross_asset')
WHERE market_context != '{}'::jsonb;

-- Clean market_context to cross-asset only.
UPDATE intelligence_features
SET market_context = CASE
    WHEN market_context ? 'cross_asset'
        THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset')
    ELSE '{}'::jsonb
END
WHERE market_context != '{}'::jsonb;
```

72,648 rows affected. Safe: the `cross_asset` nested key is the only non-I2 content;
every other flat key in `market_context` is an I2 plugin output.

### Change 4 — Live feature_writer (`services/feature_writer.py`)

Split `_record_to_insert_params`:
- `i2`: `event.i2.model_dump(exclude_none=True)` — pure I2 tier output
- `market_context`: `cross_asset_snapshot or {}` — cross-asset only

Add `i2 $N::jsonb` to `_INSERT_FEATURE_SQL` (33-element tuple, new column after
`cross_timeframe_context`). `_UPDATE_MARKET_CTX_SQL` is unchanged — it only updates
the cross-asset portion and does not touch `i2`.

### Change 5 — Historical pipeline (`production/scripts/run_historical_pipeline.py`)

**`_build_intelligence_event`:** Add `i2=I2Events(**_pick(I2Events, intelligence))`.
With all composite fields now declared in I2Events, `_pick` will correctly extract them
from the merged `intelligence` flat dict (which contains all tier outputs including I2
composite plugin results).

**`_event_to_sync_params`:** Add `json.dumps(event.i2.model_dump(exclude_none=True))`
→ 14-element tuple. Update docstring column order comment.

**`_INSERT_FEATURE_SYNC_SQL`:** Add `i2` to column list (14 columns).

**`_INSERT_FEATURE_SYNC_TEMPLATE`:** Add `%s::jsonb` → 14 placeholders.

**`_load_precomputed_features`:** Add `i2` AND `market_context` to the SELECT and merge
loop. Currently omits both — this is a separate pre-existing bug that this change fixes.
The merge loop already handles any iterable of dicts, so no structural change needed.

### Change 6 — Tests

- `test_run_historical_pipeline.py`: update tuple-length assertion 13→14; add `i2` presence
  check to `_build_intelligence_event` test; verify no `AttributeError` on `event.i2`.
- Add unit test for I2Events: confirm `ValidationError` is raised when an undeclared field
  is passed (guards against `extra="allow"` accidentally being re-added).
- No changes needed to `test_feature_writer.py` — the separation of i2/market_context
  is covered by the existing `_record_to_insert_params` parameter count assertions once updated.

## Rollout

1. Apply migration 124 (adds column with default `'{}'`, backfills existing rows — online, no lock).
2. Deploy feature_writer fix (writes to new `i2` column going forward).
3. Deploy intelligence_pipeline (I2Events now strict — no change in behavior, validation tightens).
4. Historical pipeline fix is available for next replay run.

No service restart sequencing risk: the new column has a default, so old feature_writer builds
write `'{}'` to `i2` until the new build deploys (seconds-level gap at most).

## Out of Scope

- Renaming `technical_indicators`/`pattern_detections`/`regime_features`/`confluence_scores`
  columns to match tier names (`i1`/`i3`/`i4`/`i5`) — correct direction but a separate migration
  with dashboard and query impact.
- Moving MACDEvents fields out of I2Events declarations — they exist there for the historical
  pipeline's flat-dict `_pick` path. Removing them would silently drop MACD fields from historical
  `i2` rows. Left as-is pending a dedicated cleanup.
