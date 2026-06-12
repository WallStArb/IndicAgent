# Phase 122: I2 Tier Persistence Fix - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-06-12-i2-persistence-design.md)

<domain>
## Phase Boundary

Fix three compounding failures that make `intelligence_features.i2` untrustworthy: I2Events schema has undeclared composite fields (19) and dead MACD declarations (8), the live and historical pipelines construct `i2` differently (tier-isolated vs flat-merged), and there is no dedicated `i2` column in `intelligence_features` (I2 data buried in `market_context`).

This phase is a data integrity fix. No new plugins, no new signals, no behavioral changes — only schema correctness, pipeline symmetry, and clean column separation.

**Files touched:**
- `src/intelligence/schemas.py` — I2Events schema (A)
- `src/intelligence/register_plugins.py` — validation enablement (B)
- `production/scripts/run_historical_pipeline.py` — tiered output (C + D + G + H)
- `production/migrations/124_add_i2_column.sql` — new column + backfill (E)
- `services/feature_writer.py` — column split (F)
- `tests/unit/test_run_historical_pipeline.py` — test updates

</domain>

<decisions>
## Implementation Decisions

### D-01: I2Events Field Count = 45

Remove 8 MACD field declarations from `I2Events` — they are already declared in `I3Structure` with `extra="forbid"`. Remove 2 orphans (`macd_price_divergence_bullish`, `macd_price_divergence_bearish`) that no plugin produces. Add 19 composite plugin fields:
- `cmp_MomentumAccel` (9): rsi_accel, macd_accel, roc_accel, inflection_flag, rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel
- `cmp_DerivativeOscillator` (4): deriv_osc, deriv_osc_signal, deriv_osc_cross_bullish, deriv_osc_cross_bearish
- `cmp_ExhaustionScore` (3): exhaustion_score, exhaustion_side, exhaustion_bars
- `cmp_AccelerationRegime` (3): accel_regime, accel_score, accel_agreement

Result: 34 existing - 8 MACD + 19 composite = 45 total. All `float | None = None` except string fields.

### D-02: Remove extra="allow" from I2Events

Replace `model_config = ConfigDict(extra="allow")` with `extra="forbid"`. Startup now crashes if any I2 plugin emits a field not in the schema.

### D-03: Enable I2 validation in register_plugins.py

Remove the "I2 are skipped (extra='allow')" exemption from `_validate_tier_output_coverage()`. Add all 10 I2 plugins to `tier_checks` referencing `I2Events`.

### D-04: run_analysis_pipeline returns (intelligence_flat, tiered) 2-tuple

Return type changes from `dict[str, Any]` to `tuple[dict[str, Any], dict[str, dict[str, Any]]]`. Track per-tier outputs by inserting `tiered.setdefault(tier_key_lower, {}).update(out)` inside the existing plugin loop. Tier key mapping: `"I2"→"i2"`, `"I3"→"i3"`, `"I4"→"i4"`, `"I5"→"i5"`, `"SMC"→"smc"`, `"I6"→"i6"`. The flat `intelligence` dict is unchanged.

Update the single call site (line ~1566): `intelligence, tiered = run_analysis_pipeline(...)`.

### D-05: _build_intelligence_event uses tiered dicts

Change signature to accept `tiered: dict[str, dict]`. Replace `_pick`-based construction with direct tier-dict construction matching the live pipeline exactly:
```python
i2=I2Events(**tiered.get("i2", {})),
i3=I3Structure(**tiered.get("i3", {})),
...
```
Delete the `_pick` helper entirely — no remaining callers. Update call site (line ~1574): `event = _build_intelligence_event(bar, i1_features, tiered, symbol, tf, ts)`.

### D-06: Migration 124 — add i2 column, backfill, clean market_context

File: `production/migrations/124_add_i2_column.sql`

Steps:
1. `ALTER TABLE intelligence_features ADD COLUMN i2 JSONB NOT NULL DEFAULT '{}'` — online DDL, no table lock at column add
2. `UPDATE intelligence_features SET i2 = (market_context - 'cross_asset') WHERE market_context != '{}'::jsonb` — backfill 72,648 live rows; `cross_asset` is the only nested object and is not an I2 field
3. `UPDATE intelligence_features SET market_context = CASE WHEN market_context ? 'cross_asset' THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset') ELSE '{}'::jsonb END WHERE market_context != '{}'::jsonb` — clean market_context to cross-asset only

Historical rows have `market_context = '{}'` so `i2` starts as `'{}'` for them — correct, populated on next replay run.

Use `ADD COLUMN IF NOT EXISTS` guard (migration 013 made a prior attempt; guard prevents failure on duplicate application).

### D-07: feature_writer splits i2 from market_context

In `_record_to_insert_params`, split:
```python
# Before: market_ctx = {**event.i2.model_dump(exclude_none=True), **(cross_asset_snapshot or {})}
# After:
i2_data = event.i2.model_dump(exclude_none=True)
market_ctx = cross_asset_snapshot or {}
```

Add `i2` to `_INSERT_FEATURE_SQL` (after `cross_timeframe_context`, before `trading_signals`). Tuple grows from 32 to 33 elements. Add `$N::jsonb` placeholder.

`_UPDATE_MARKET_CTX_SQL` is unchanged — it only patches `market_context`.

### D-08: Historical pipeline INSERT updated (G)

- `_INSERT_FEATURE_SYNC_SQL`: add `i2` to column list (14 columns total)
- `_INSERT_FEATURE_SYNC_TEMPLATE`: add `%s::jsonb` (14 placeholders)
- `_event_to_sync_params`: append `json.dumps(event.i2.model_dump(exclude_none=True))` — 14-element tuple

### D-09: _load_precomputed_features includes i2 and market_context (H)

Both columns are currently absent from the SELECT. Add both to the SELECT and merge loop. No structural change required — the loop iterates a list of dicts. After this fix, `--use-precomputed-features` is complete for I7 plugins gating on I2 composite outputs.

### D-10: Rollout order

1. Migration 124 (DDL + backfill — online, no restart needed)
2. feature_writer deploy (writes clean i2 going forward)
3. intelligence_pipeline deploy (I2Events strict — validation tightens)
4. Historical pipeline fix (available for next replay run)

No sequencing risk: new column defaults to `'{}'` so any in-flight write during deploy window is correct.

### Claude's Discretion

- Number of PLAN.md files and wave structure
- Whether schema + validation enablement (A+B) are one plan or two
- Whether G and H are bundled with C+D or separate

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Spec (authoritative)
- `docs/plans/2026-06-12-i2-persistence-design.md` — Full RCA, component specs A-H, test changes table, rollout order

### Schema
- `src/intelligence/schemas.py` — I2Events, I3Structure, and all tier event models
- `src/intelligence/register_plugins.py` — _validate_tier_output_coverage(), TIER_I2, tier_checks

### Live Pipeline (reference for symmetry)
- `services/feature_writer.py` — _record_to_insert_params(), _INSERT_FEATURE_SQL, _UPDATE_MARKET_CTX_SQL
- `src/intelligence/executor.py` — live run_tiers() + IntelligenceEvent construction

### Historical Pipeline
- `production/scripts/run_historical_pipeline.py` — run_analysis_pipeline(), _build_intelligence_event(), _pick(), _event_to_sync_params(), _load_precomputed_features(), _INSERT_FEATURE_SYNC_SQL

### Tests
- `tests/unit/test_run_historical_pipeline.py` — tuple length assertions, _build_intelligence_event tests

### Migration conventions
- `production/migrations/` — existing migrations; global max is 123; use 124

</canonical_refs>

<specifics>
## Specific Ideas

- The spec explicitly states migration 013 made a prior attempt at an `i2` column. Use `ADD COLUMN IF NOT EXISTS` guard.
- Migration number: 124 (one above current global max of 123). Note: numbers 120 and 121 have pre-existing conflicts between production/migrations/ and db/migrations/.
- `cross_asset` is the only nested object in `market_context` — the separation is unambiguous.
- 72,648 rows are affected by the backfill UPDATE.
- `_pick` helper is deleted entirely after D and G; verify no other callers exist.
</specifics>

<deferred>
## Deferred Ideas

- Renaming `technical_indicators` / `pattern_detections` / `regime_features` / `confluence_scores` columns to tier names — correct direction but separate migration with dashboard and downstream query impact.
- Backfilling historical rows via replay — historical rows correctly start with `i2='{}'` and will be populated on next replay run (no special handling needed in this phase).
</deferred>

---

*Phase: 122-i2-tier-persistence-fix*
*Context gathered: 2026-06-12 via PRD Express Path*
