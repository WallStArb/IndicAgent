# Phase 122: I2 Tier Persistence + Data Layer Hardening - Context

**Gathered:** 2026-06-12 (expanded 2026-06-12)
**Status:** Partially planned — 4 plans exist (122-01 through 122-04); 3 new areas added
**Source:** PRD Express Path (docs/plans/2026-06-12-i2-persistence-design.md) + architectural review

<domain>
## Phase Boundary

This phase bundles four related data integrity and architectural hardening tracks. No new plugins, no new signals, no behavioral changes.

**Track 1 — I2 Tier Persistence Fix (plans 122-01 through 122-04, already written):**
Fix I2Events schema (45 fields, extra="forbid"), pipeline symmetry (live vs historical produce identical i2 content), and add dedicated `i2` JSONB column to `intelligence_features`.

**Track 2 — intelligence_features column rename:**
Rename legacy columns to match tier names: `technical_indicators→i1`, `pattern_detections→i5`, `regime_features→i3`, `confluence_scores→i4`. Column `cross_timeframe_context` (I6) and `smc` are already correct. Requires coordinated update of all read sites: `feature_writer.py`, `run_historical_pipeline.py`, `_load_precomputed_features`, dashboard API queries, and any direct SQL.

**Track 3 — Deterministic signal IDs + feature_replay.py:**
Close uuid4() fallback gaps in 5 files (TASK-2 from `docs/plans/2026-06-11-signal-replay-architecture-plan.md`). Build `feature_replay.py` — I7-only replay from intelligence_features, bypassing I1-I6 recompute (TASK-3). This reduces shadow signal regeneration from hours to minutes. Depends on Track 1 (_load_precomputed_features fix) and Track 2 (column names used in feature_replay.py SELECT).

**Track 4 — zone_engine.py ATR floor fix:**
`zone_engine.py:231` is the only remaining site in the I7 trading layer using raw `get_atr(features) or 0.5`. Replace with `get_atr_with_floor` logic (10 other I7 plugins already use `get_atr_with_floor_from_frames`). Non-trading compute plugins (I3/I5/SMC) intentionally use raw `get_atr` — no change needed there.

**Files touched (new tracks):**
- `production/migrations/125_rename_intelligence_features_columns.sql` — column rename (Track 2)
- `services/feature_writer.py` — column name updates (Track 2)
- `production/scripts/run_historical_pipeline.py` — column name updates + uuid4 fix (Tracks 2, 3)
- `src/intelligence/schemas.py` — uuid4 fallback fix in signal_dict_to_ranked (Track 3)
- `services/signal_writer.py` — uuid4 fallback fix (Track 3)
- `services/alpha_swarm.py` — uuid4 fallback fix (Track 3)
- `services/narrative_swarm.py` — uuid4 fallback fix (Track 3)
- `production/scripts/feature_replay.py` — new script (Track 3)
- `src/intelligence/trading/zone_engine.py` — ATR floor fix (Track 4)
- Dashboard API queries — column name updates (Track 2)

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

### D-11: intelligence_features column rename (Track 2)

Migration `production/migrations/125_rename_intelligence_features_columns.sql`:
```sql
ALTER TABLE intelligence_features RENAME COLUMN technical_indicators TO i1;
ALTER TABLE intelligence_features RENAME COLUMN pattern_detections TO i5;
ALTER TABLE intelligence_features RENAME COLUMN regime_features TO i3;
ALTER TABLE intelligence_features RENAME COLUMN confluence_scores TO i4;
```
`smc` and `cross_timeframe_context` (I6) are already correctly named. `market_context` (cross-asset) retains its name.

After migration, update all read sites to use new column names:
- `services/feature_writer.py` — `_INSERT_FEATURE_SQL`, `_UPDATE_MARKET_CTX_SQL` column references
- `production/scripts/run_historical_pipeline.py` — `_INSERT_FEATURE_SYNC_SQL`, `_load_precomputed_features` SELECT
- `src/api/` — any endpoint that reads `technical_indicators`, `pattern_detections`, `regime_features`, `confluence_scores` directly from `intelligence_features`
- Dashboard queries if any reference these column names directly (check `dashboard/` directory)

Migration is online DDL (column rename acquires brief lock in PostgreSQL but no table rewrite). Apply before deploying code that references new names.

### D-12: Deterministic signal IDs — close uuid4() fallbacks (Track 3)

Five sites have `or uuid4()` fallbacks that silently mask upstream omissions. Replace each with a loud failure:

| File | Line | Fix |
|------|------|-----|
| `run_historical_pipeline.py:800` | `else: sid = str(uuid4())` when `last_bar is None` | Log warning + skip signal (malformed — no bar data) |
| `src/intelligence/schemas.py:~925` | `signal_id=str(sig.get("signal_id") or uuid4())` in `signal_dict_to_ranked()` | Replace with `signal_id=str(sig["signal_id"])` + raise `ValueError` if missing |
| `services/signal_writer.py:~209` | `signal_id=str(sig.get("signal_id") or uuid4())` | Same — raise `ValueError` with signal context |
| `services/alpha_swarm.py:~491` | `signal_id = signal.signal_id or uuid4()` | Raise `ValueError` with signal_id field in message |
| `services/narrative_swarm.py:~117` | `signal_id = signal.signal_id or uuid4()` | Same |

After this fix: missing signal_id raises a loud, traceable error. No silent random IDs.

### D-13: feature_replay.py — I7-only replay from intelligence_features (Track 3)

New script: `production/scripts/feature_replay.py`

Interface:
```
python production/scripts/feature_replay.py \
    --plugins trad_FVGFill,trad_POCRejection,...
    --symbols ESM6,NQM6,...         # default: all active contracts
    --since 2025-01-01              # optional
    --workers 8
```

Core design:
- Reads `intelligence_features` rows (using new column names from D-11: `i1`, `i3`, `i4`, `i5`, `smc`, `cross_timeframe_context`, `i2`, `market_context`)
- Reconstructs `IntelligenceEvent` from stored JSONB — inverse of `_build_intelligence_event`
- Runs specified I7 plugins only — skips all I1-I6 compute
- Upserts signal_ledger via `ON CONFLICT (signal_id, timestamp) DO UPDATE` using deterministic `make_signal_id(ts, symbol, tf, plugin_name, direction)`
- `--shadow-setups` flag: reads `_SHADOW_VALIDATION_SETUPS` frozenset from run_historical_pipeline.py

Depends on: D-09 (`_load_precomputed_features` including i2+market_context), D-11 (column rename), D-12 (uuid4 fallback elimination).

Acceptance: signal counts within 1% of full pipeline re-run; runtime under 10 minutes for 22-plugin shadow set; idempotent.

### D-14: zone_engine.py ATR floor fix (Track 4)

`zone_engine.py:231` currently: `atr = get_atr(features) or 0.5`

The hardcoded `0.5` fallback is instrument-agnostic and wrong for instruments with different tick sizes (e.g., NQ ticks at 0.25, VX at 0.05). Replace with `get_atr_with_floor(features, symbol)` where `symbol` must be threaded into the call site.

Check how `zone_engine` is called — if `symbol` is not currently in scope at line 231, thread it from the calling plugin's `frames["symbol"]` down into the zone engine function signature.

Note: the 22 raw `get_atr` usages in I3/I5/SMC compute plugins are intentional — those plugins measure structural distances, not trading stop distances, and do not need the tick-size floor.

### Claude's Discretion

- Whether Track 2 (column rename) and Track 4 (ATR fix) can be a single small plan
- Wave assignment for Tracks 3 and 4 relative to the existing 4 plans
- Whether feature_replay.py is one plan or split (uuid4 fixes + feature_replay.py)

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

- Backfilling historical rows via replay — historical rows correctly start with `i2='{}'` and will be populated on next replay run via feature_replay.py (D-13).
- Vectorized lifecycle evaluation (TASK-4 from replay architecture plan) — O(signals × bars) → numpy batch; separate phase, 3-4 day effort.
- ATR fix for I3/I5/SMC compute plugins — intentionally using raw get_atr; tick-size floor is an I7 trading concern only.
</deferred>

---

*Phase: 122-i2-tier-persistence-fix*
*Context gathered: 2026-06-12 via PRD Express Path*
