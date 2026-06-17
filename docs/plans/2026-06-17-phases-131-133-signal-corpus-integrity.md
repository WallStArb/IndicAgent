# Phases 131–133: Signal & Corpus Integrity

**Created:** 2026-06-17
**Status:** approved — pending execution
**Drives:** Phases 131, 132, 133 GSD plans

---

## Context

Phase 127 produced a structurally clean corpus (zero orphans, deterministic content-addressed IDs, full ECL coverage in rerun) but surfaced a backlog of data-quality and infrastructure bugs. Phase 130 completed the 3-table schema migration. The items below are the full technical debt from that work, triaged to leave zero open items before ML training begins.

**Source documents (implementation detail lives here — do not re-derive):**
- `.planning/todos/2026-06-17-phase127-issues-master.md` — master triage list
- `.planning/todos/pending/2026-06-17-phase131-research-findings.md` — confirmed root causes from live DB
- `.planning/todos/pending/2026-06-17-poc-hvn-rejection-float-nonetype.md` — A1 exact fix
- `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md` — A2 sample data
- `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md` — A5 full constant table
- `.planning/todos/pending/2026-06-16-trade-frames-hypertable-migration.md` — C1 8-step sequence
- `docs/plans/phase-127-validation-report.md` — empirical corpus measurements

---

## Design Principles (Renaissance Council)

1. **Corpus is the product.** A biased corpus trains models that lie with confidence. No ML training until the corpus is complete, verified, and unbiased.
2. **Zero is always a bug.** Any plugin producing zero signals across 537K+ historical bars has a systematic failure, not bad luck. Treat zero-signal as a hard invariant violation until proven otherwise with empirical evidence.
3. **Fix everything, rebuild once.** Every rebuild is a multi-hour operation. Partial fixes + multiple rebuilds waste time and introduce intermediate states that confuse the audit trail.
4. **Silent wrong answers are worse than loud crashes.** Hidden survivorship bias (A3, rolled-contract gaps) corrupts ML training silently. Surface everything.
5. **No hardcoded numerics in `src/`.** Every ATR multiplier, width threshold, and RR ratio is an ML learning target. Constants in code are architecture violations that prevent tuning without deploys.

---

## Phase 131 — Signal Generation Integrity

**Objective:** Every plugin that should fire does fire. Every instrument in the active contract list produces signals. No systematic zeros from fixable bugs.

**Verification gate:** Unit tests green; targeted 2-week replay shows ≥32 plugins emitting signals; no zero-signal instruments in active contract list; all open investigation items resolved with empirical findings documented.

### A1 — POCRejection + HVNRejection: float(None) crash

**File:** `src/intelligence/trading/trade_framer.py` ~line 343
**Fix:** In `_get_htf_vp()`, guard before cast:
```python
if poc_htf is None or vah_htf is None or val_htf is None:
    return None, None, None
return float(poc_htf), float(vah_htf), float(val_htf)
```
Verify all callers handle `(None, None, None)`. Both plugins should then emit signals on 4h/1d bars where HTF VP data exists.

### A4 — Rolled-contract plugin errors

**Scope:** NQU6 (103K errors, 8 plugins), YMM6 (117K errors, 4 plugins), RTYM6 (112K errors, 13 plugins). Non-fatal per-plugin try/except but bars skip entirely.
**Symptom:** `asset_class=None` in framing logs, missing market-context fields.

**Root cause (confirmed from code trace):** `run_historical_pipeline.py` calls `replay_symbol()` which calls `run_analysis_pipeline()` and `run_i7_and_persist()` directly — it does NOT use `FeaturePipelineExecutor`. The asset_class injection at `feature_pipeline_executor.py:332` (`flat_features["asset_class"] = instrument.asset_class.value`) is never reached in replay. `all_features["asset_class"]` is never populated for any symbol in replay. Rolled contracts (NQM6/YMM6/RTYM6) are not in the `instruments` table (only in `contract_metadata`), so the instrument lookup that some paths use also fails for them specifically.

**Fix:** In `replay_symbol()`, build a `symbol → asset_class` lookup from `contract_metadata` (for futures) and `instruments` (for equities/fx/etf), then inject `asset_class` into `all_features` before calling `run_i7_and_persist()`. Mirrors what `FeaturePipelineExecutor.execute()` does at line 332. One-time fix applies to all symbols, not just rolled contracts.

### A6 — BOCPD look-ahead bias

**File:** `src/intelligence/features/smc_context/bocpd_changepoint.py:278`
**Fix:** `np.mean(vol[-20:])` → `np.mean(vol[-21:-1])`. Matches corrected pattern in I7 plugins. One line.

### Zero-emission plugin investigation

Four plugins produced zero signals across the entire corpus. The validation report labels them "structural data dependencies" — this is a hypothesis, not a finding. Zero signals across 537K bars is statistically inconsistent with correct plugin wiring.

For each plugin, execute:
1. Query: `SELECT setup_plugin, symbol, tf, COUNT(*) FROM signal_events WHERE setup_plugin = '<name>' GROUP BY 1,2,3` — if ALL zero, the plugin never reaches `frame_trade()` successfully
2. Check logs for exception type and call site
3. Trace emission path from `IntelligencePipeline` → I7 tier → plugin → `frame_trade()`

**`trad_MTFAlignment`:** Needs multi-timeframe alignment data. In replay, higher-TF bars are processed in the same run — alignment data should be available. Likely a context-assembly bug where the plugin doesn't find the HTF bars it expects. Investigate whether `htf_*` fields are populated in the `IntelligenceEvent` during replay.

**`trad_PrevDayLevelTest`:** Zero signals across months implies more than cold-start. Prior-day levels are computable from OHLCV. Investigate whether the plugin reads from a cache that is never populated in replay, or whether the day-boundary detection is broken for historical bars.

**`trad_AnchoredVWAPReversion`:** Anchored VWAP requires an anchor event (gap, earnings, etc.). These events exist in historical data. Zero signals suggests the anchor detection logic is not firing or the anchor event provider is not wired in replay mode. Investigate `AnchorEventProvider` initialization in the replay pipeline.

**`trad_CrossAssetDivergence`:** Cross-asset data is available in replay (all instruments processed together). Zero signals strongly suggests a bug in how the plugin accesses sibling-instrument bars from `IntelligenceEvent` context during replay. Investigate context assembly.

**Outcome for each:** Either (a) fix the bug and confirm signals appear, or (b) produce empirical evidence (specific field consistently None, confirmed architectural reason) explaining why the plugin cannot fire in historical replay. Undocumented zeros are not acceptable.

### Symbol coverage gaps

**10 OHLCV symbols with 0 signals** in rerun: EURUSD, EWZ, FXI, GDXJ, ITB, USO, VLUE, VXK6, VXM6, ZNM6.

VXK6/VXM6 (VIX futures) and ZNM6 (10-year Treasury) are regime-context instruments — their absence from the corpus is a coverage gap that ML will misread as "no signal exists here."

**Three confirmed root causes (from live DB):**

**Root cause A — Not in instruments or contract_metadata (6 ETFs):**
EWZ, FXI, GDXJ, ITB, USO, VLUE — exist in `market_data_ohlcv` but have no `instruments` row. `get_active_contracts()` never returns them; `replay_symbol()` is never called for them.
Fix: add to `instruments` table as `asset_class='equity'` instruments. Add to `settings.py` instrument config.

**Root cause B — Expired rolled contracts, same failure mode as A4:**
VXK6, VXM6, ZNM6 — `is_front_month=false` means the roll already occurred. These had OHLCV bars during their active window but produced 0 signals. This is the same root cause as A4: the `asset_class` injection gap in `replay_symbol()` applies to all rolled contracts, not just NQU6/YMM6/RTYM6. The A4 fix must be verified against VX and ZN contract series. The difference in symptom (0 signals here vs 201K plugin errors on NQ/YM/RTY) likely reflects asset-class-specific guard behavior, not a different root cause.

**Root cause C — Active in instruments but 0 signals:**
EURUSD — `is_active=true`, `asset_class='fx'` in instruments. Replay did process it (it was in scope) but 0 signals resulted. The FX code path in `run_historical_pipeline.py:2283` branches on `asset_class in (FX, CRYPTO)` — investigate whether this branch skips signal generation or whether FX instruments have insufficient ATR-scaled stops to pass the emission gate.

### A7 — I6 CTF universally zero (HIGH — corpus-wide, ML-blocking)

**Discovered:** 2026-06-17 via corpus audit. Memory: `project_i6_ctf_zero_bug.md`.
**Confirmed:** `intelligence_features.cross_timeframe_context->>'ctf_score'` = 0.0 for all 4,810,307 non-null rows. All 518,464 non-null `signal_events.ctf_score` = 0.0. I1/I3 data is correct.

**Root cause (hypothesis, code fix not yet applied):**
`CrossTimeframeConfluencePlugin.compute_full()` builds `other_intel` from `intel_*` frames populated by `_last_events`. At replay start, `_last_events` for other TFs is empty — no prior bar has populated the cross-TF cache. So `other_intel` entries all return `extract_trend_sign(intel)=0` (neutral), making `score_trend_alignment()` return 0 for all TFs, hence `ctf_score=0`.

The merge-loop in `replay_symbol()` processes events chronologically and does populate `intelligence_cache` as bars are processed. But I6's `intel_*` frame consumption may not be reading from the same cache. Verify whether `run_analysis_pipeline()` correctly passes populated `intel_{tf}` frames into the I6 confluence step.

**Key files:**
- `src/intelligence/confluence/cross_timeframe.py:66-150` — `compute_full()`, `other_intel` build
- `src/intelligence/confluence/confluence_alignment.py:37-60` — `score_trend_alignment`
- `src/intelligence/confluence/confluence_weights.py:45-58` — `extract_trend_sign`
- `src/intelligence/pipeline/feature_pipeline_executor.py:183-194` — `_last_events` construction
- `production/scripts/run_historical_pipeline.py:1722-1731` — `intel_*` frame injection into `frames`

**Fix approach:** Verify that `frames[f"intel_{other_tf}"]` at line 1729-1731 contains populated I3 fields (`trend_direction`, `trend_strength`). If `intelligence_cache` is empty for other TFs at the time I6 runs for the current bar, the fix is ensuring lower-TF bars always write to `intelligence_cache` before higher-TF bars read from it — which the merge-loop sort order should already guarantee. Confirm with a targeted unit test.

**Verification:** After fix, run 1-week sample replay. `ctf_score` distribution must be non-zero (expected range 0.1-0.9 for bars with real trend). Full re-replay required before corpus acceptance.

### B6 — Backfill integrity crash fix

**File:** `production/scripts/run_historical_pipeline.py` ~line 1837 (`_assert_backfill_integrity`)
**Symptom:** `psycopg2.OperationalError: server closed the connection unexpectedly` after inserting all signals, crashing in the post-commit integrity assertion. Left corpus at 537K instead of 1,036K.
**Fix:**
1. Diagnose: is the assertion query triggering a PG timeout or OOM? Check query plan with EXPLAIN ANALYZE on the integrity SQL.
2. If long-running query: batch the assertion (chunked by symbol or time window) rather than a single full-table scan.
3. REBUILD_STATUS: set to FAILED only if integrity assertion fails, not on post-commit crash. Data integrity is what matters; a post-commit crash with data intact is not a failure.

### B7 — Verify SQL fan-out overcounting

**File:** `production/scripts/lifecycle_replay.py` (`_verify_replay`)
**Bug:** LEFT JOIN on trade_frames + trade_executions inflates total count when a frame has multiple execution rows. Total showed 596K when `COUNT(*) FROM signal_events` is 537K.
**Fix:** Add `COUNT(DISTINCT se.signal_id)` as a separate line in the verify output, or restructure the query to aggregate at signal_events level before joining. The zero-checks (CASE expressions) are trustworthy; only the absolute totals are misleading.

---

## Phase 132 — Stop-Zone Geometry + APR Migration

**Objective:** Stop placement is geometrically correct for all asset classes. All 16 ATR constants in `trade_framer.py` are APR-backed and ML-tunable. The `stopped_at_entry` outcome rate drops from ~25% to <5%.

**Verification gate:** 1-month sample replay shows `stopped_at_entry` <5%; all 16 APR keys visible in `/config/parameters` dashboard with correct seed values; APR-backed code produces identical signals to prior constants at seed values (regression test).

### A2 — Stop-zone geometry: three-part fix

**Files:** `src/intelligence/trading/trade_framer.py`, `src/intelligence/trading/zone_engine.py`

All three sub-fixes ship together — they are causally linked (narrow zone → entry at edge → stop immediately behind entry):

**(a) Enforce minimum zone width at all paths**
`MIN_ZONE_WIDTH_ATR = 0.25` exists in zone_engine but fast paths in the feature layer bypass it. Every path that produces a zone must enforce the minimum. No exceptions. Add assertion in zone_engine output: `assert zone_width >= min_zone_width_atr * atr`.

**(b) Calculate stop from entry price, not zone edge**
Current: `stop = zone_low - 1xATR`. Correct: `stop = entry - max(zone_low - entry, min_stop_atr * ATR)`. The stop must be measured from the actual entry, not the zone boundary. Sample data from the todo confirms entries below zone_low (QQQ: entry 723.09, zone [723.14, 723.16]).

**(c) Add emission gate**
`stop_distance = entry - stop`. Gate: `stop_distance >= feature.trade_framer.min_stop_atr * ATR`. Seed value: `1.0` ATR (current `MIN_STOP_ATR_MULTIPLIER`). This is an ML learning target — it goes into APR, not as a constant.

### A3 — Per-asset-class stop geometry

**Files:** `src/intelligence/trading/trade_framer.py`, zone_engine
FX pairs and small-tick commodities (SI silver, NG natgas, HG copper, CL crude) have fundamentally different tick structures than equity ETFs. A uniform ATR multiplier is wrong for these instruments.

**Fix:** Add per-asset-class APR keys for minimum stop floor:
- `feature.trade_framer.stop_multiplier_floor.fx` — seed from tick-size analysis of FX instrument ATRs
- `feature.trade_framer.stop_multiplier_floor.commodity_small_tick` — SI/NG/HG/CL
- `feature.trade_framer.stop_multiplier_floor.equity_etf` — QQQ/SPY/IWM/XLE/SMH
- `feature.trade_framer.stop_multiplier_floor.futures_large_tick` — ES/NQ/YM/RTY

Seed values: compute `median_ATR / tick_size` per asset class from the actual bar data. Use empirical numbers, not guesses.

The 1-tick gate (`stop <= entry + 1 tick`) remains correct — do not remove it. The per-asset-class floor sits above it.

### A5 — 16 APR migrations in trade_framer.py

**File:** `src/intelligence/trading/trade_framer.py`
Full constant table with APR keys and ML-target flags is in `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`. Migrate all 16.

**Process per constant:**
1. INSERT into `config_schema` + `config_state` in a new migration
2. Load via `ConfigService.get()` at init (pattern: `_config_service` field, `get_sync()` wrapper)
3. Remove the module-level constant
4. Add `[initial_estimate]` provenance tag in `config_schema.description`
5. Flag ML learning targets in description

No hardcoded numeric thresholds, weights, or multipliers remain in `trade_framer.py` after this phase.

---

## Phase 133 — Clean Corpus Rebuild

**Objective:** One complete, verified, unbiased corpus. All active-contract instruments covered. ≥32 plugins firing. Correct stop geometry. Full ECL coverage. `_verify_replay` 0/0/0. Infrastructure bugs fixed. Schema ready for CounterfactualTracker.

**Execution order matters — follow it exactly.**

### C1 — trade_frames → hypertable (Migration 142)

**Do first, while tables will be empty after TRUNCATE.**
8-step sequence from `.planning/todos/pending/2026-06-16-trade-frames-hypertable-migration.md`:
1. Drop FK `fk_trade_executions_frame` from trade_executions → trade_frames
2. Drop `trade_frames_pkey` (UUID-only PK)
3. Create hypertable on `signal_ts`, chunk_time_interval = 7 days
4. Recreate PK as `(frame_id, signal_ts)`
5. Add `signal_ts` to `trade_executions` as FK anchor
6. Recreate FK: `trade_executions(frame_id, signal_ts) → trade_frames(frame_id, signal_ts)`
7. Enable compression: `compress_segmentby = 'symbol,tf'`, `compress_orderby = 'signal_ts DESC'`
8. Add compression policy: INTERVAL '7 days'

### B4 — TRUNCATE CASCADE fix

**File:** `production/scripts/reset_pipeline_data.py`
Replace per-table TRUNCATE loop with: `TRUNCATE TABLE signal_events, trade_frames, trade_executions, intelligence_features [+ remaining tables] CASCADE;`
PostgreSQL resolves intra-set FKs in one statement. Test with a dry-run before the corpus rebuild.

### B5 — Remove dead --warmup flag

**File:** `production/scripts/run_historical_pipeline.py`
Remove: `--warmup` argparse arg, the two-pass loop in the workers==1 branch, the parallel-mode NOTE.
Sweep: `grep -rn "warmup" tests/ docs/ production/` — remove all references.
The warmup-noop finding (Phase 127) confirmed this is a provable no-op.

### B2 — asyncpg transaction hygiene

**File:** `production/scripts/lifecycle_replay.py`
`ERROR Resetting connection with an active transaction` fires at every symbol/tf boundary.
Fix: every `async with pool.acquire() as conn:` block in the per-(symbol, tf) worker must have an explicit `await conn.execute('COMMIT')` or `await conn.execute('ROLLBACK')` in all exit paths (including exception paths). Add `try/finally` where missing.

### B3 — feature_replay stateful coverage

**File:** `production/scripts/feature_replay.py`
Current `compute_full()` is stateless (single-bar). Original corpus used `incremental_compute()` (stateful — GARCH/Kalman/HMM/BOCPD state accumulates across bars). Dry-run produces 0 signals.
**Fix:** Use `incremental_compute()` with per-symbol state accumulation in feature_replay. Maintain a `Dict[str, PluginState]` keyed by `(symbol, tf)`, pass state into each bar computation, update after each bar. This is the architecturally correct path — stateless shortcuts produce wrong outputs for stateful plugins.

### C2 — intelligence_features column naming

**Tables:** `intelligence_features` columns `i1`/`i3`/`i4`/`i5`/`composite_events`
**Decision:** Search phases 95-116 CONTEXT/SUMMARY docs for the functional-names decision. If functional names were decided, execute the rename migration in this phase. If tier-code names were deliberately re-chosen in 122, document the decision and close the open item.
This must be resolved before any future phase touches these columns.

### Layer D — Code hygiene

| Item | Action |
|------|--------|
| `_cfg()` in zone_engine.py | Rename to `_read_config()` + update call sites |
| `confidence_utils.py` | `git mv` → `confidence.py`; update 39 import sites; run grep to confirm |
| `phase_127_before_snapshot.py`, `phase_127_monitor_replay.py` | Delete + test sweep |
| `migrate_signal_ledger.py` | Move to `production/scripts/archive/` |

### Full corpus rebuild

Execute in this exact order after all fixes above are committed and tests are green:

1. **TRUNCATE** using fixed `reset_pipeline_data.py`
2. **Backfill:** `run_historical_pipeline.py --replay-only --include-rolled --client-id 40 --workers 8` (B6 crash fix applied)
3. **Lifecycle:** `lifecycle_replay.py --workers 8 --commit-every 500`
4. **Verify:** `_verify_replay` must pass with `stale_unresolved=0`, `target_no_pnl=0`, `orphan_signal_events=0`

**Corpus acceptance criteria:**
- `signal_events` count: ~1,036,513 (within 2% of baseline)
- Distinct plugins firing: ≥32 of 36
- All active-contract symbols present in signal_events
- `context_features` coverage: ≥99%
- `ctf_score` non-null: ≥96%
- `stopped_at_entry` outcome rate: <5%
- `trade_frames` confirmed as hypertable: `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'trade_frames'`
- `setup_performance`: 0 rows expected (populated post-CounterfactualTracker v2.11)
- `counterfactual_pnl_r`: 0 non-null expected (v2.11 dependency)

---

## Sequencing Summary

```
Phase 131 (Signal Generation Integrity)
  → all signal-generation bugs fixed
  → all zero-signal plugins either fixed or empirically documented
  → replay infrastructure crash fixed
  → corpus rebuild is now reliable

Phase 132 (Stop-Zone Geometry + APR)
  → stop geometry correct for all asset classes
  → 16 constants in APR; ML can tune them
  → stopped_at_entry rate verified <5% on sample

Phase 133 (Clean Corpus Rebuild)
  → schema migrated (hypertable)
  → scripts cleaned (B2/B3/B4/B5/D)
  → one full rebuild produces complete, verified corpus
  → corpus acceptance criteria all green
  → ML training unblocked
```

**Do not begin ML training until Phase 133 corpus acceptance criteria are all green.**

---

## What This Does Not Cover

- **CounterfactualTracker (Phase 130+ v2.11):** Populates `counterfactual_pnl_r` on live signals. This is the ML training target. Not in scope here.
- **`setup_performance` refresh:** Requires 30+ labeled signals per setup. Happens post-CounterfactualTracker.
- **Phase 129 verification gaps:** Row-count drift and superuser-bypass of read-only on `signal_ledger` are documented architectural constraints, not bugs to fix. `signal_ledger` will be dropped when the migration is confirmed stable.
