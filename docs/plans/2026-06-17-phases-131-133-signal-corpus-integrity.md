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

**Verification gate:** Unit tests green; targeted 2-week replay shows ≥35 of 35 eligible plugins emitting signals (CrossAssetDivergence is formally excluded as architectural live-only — it is not a fixable bug); no zero-signal instruments in active contract list from fixable bugs; all open investigation items resolved with empirical findings documented.

### A1 — POCRejection + HVNRejection: float(None) crash — **FIXED** (2026-06-17, commit 591fee51)

**Root cause (confirmed):** `dict.get(key, default)` only uses the default when the key is absent. The VP plugin outputs `va_width_atr`, `nearest_hvn_dist_atr`, `vol_regime`, and `hmm_regime` as `None` into the features dict (legacy replay path does not filter I2-I6 Nones like the live executor does). When those keys are present with `None` values, `.get(key, 2.0)` returns `None` - not `2.0` - and `float(None)` crashes.

**Fix applied:** Switched from `.get(key, default)` to `.get(key) or default` in both `trad_POCRejection` and `trad_HVNRejection` plugins. 4,756 tests green.

**Next step:** Run targeted replay `--setups trad_POCRejection,trad_HVNRejection` to generate corpus entries now that the crash is resolved.

### A4 — Rolled-contract plugin errors

**Scope:** NQU6 (103K errors, 8 plugins), YMM6 (117K errors, 4 plugins), RTYM6 (112K errors, 13 plugins). Non-fatal per-plugin try/except but bars skip entirely.
**Symptom:** `asset_class=None` in framing logs, missing market-context fields.

**Root cause (confirmed from code trace, pending empirical verification):** `run_historical_pipeline.py` calls `replay_symbol()` which calls `run_analysis_pipeline()` and `run_i7_and_persist()` directly — it does NOT use `FeaturePipelineExecutor`. The asset_class injection at `feature_pipeline_executor.py:332` (`flat_features["asset_class"] = instrument.asset_class.value`) is never reached in replay. `all_features["asset_class"]` is never populated for any symbol in replay. Rolled contracts (NQM6/YMM6/RTYM6) are not in the `instruments` table (only in `contract_metadata`), so the instrument lookup that some paths use also fails for them specifically.

**Confirmation required before implementing fix:** The research findings doc marks this "STILL UNCONFIRMED." Add a single log line to `replay_symbol()` logging `all_features.get("asset_class")` for a rolled-contract symbol and run a 10-symbol test replay to confirm asset_class is None. Do not write the fix until this is confirmed empirically.

**Fix:** In `replay_symbol()`, build a `symbol → asset_class` lookup from `contract_metadata` (for futures) and `instruments` (for equities/fx/etf), then inject `asset_class` into `all_features` before calling `run_i7_and_persist()`. Mirrors what `FeaturePipelineExecutor.execute()` does at line 332. One-time fix applies to all symbols, not just rolled contracts.

### A6 — BOCPD look-ahead bias

**File:** `src/intelligence/features/smc_context/bocpd_changepoint.py:278`
**Fix:** `np.mean(vol[-20:])` → `np.mean(vol[-21:-1])`. Matches corrected pattern in I7 plugins. One line.

### Zero-emission plugin investigation — **COMPLETE** (2026-06-17)

Root causes confirmed for all four plugins via code trace and DB verification. Summaries below; decisions on fix vs document-as-architectural are noted.

**`trad_MTFAlignment` — downstream of A7, no separate fix needed.**
Gates on `abs(ctf_score) > 0.7`. With ctf_score=0.0 corpus-wide (A7), this gate can never pass. Fix A7 → MTFAlignment fires automatically. No code change to this plugin required.

**`trad_PrevDayLevelTest` — fixable code bug.**
`SessionLevelsPlugin` (I3) computes `prior_session_high/low/close` by taking the block of bars before the "current session" window (`_SESSION_BARS=390`). The `bar_histories` deque in `replay_symbol()` has `maxlen=200`. With 200 bars: `sess_n = min(390, 200) = 200` (entire buffer = current session), leaving `prior_end = 0` bars for the prior session window. `prior_session_high/low/close` = None for every bar → excluded by `exclude_none=True` on `model_dump()` → PrevDayLevelTest hits the null guard at line 117 and returns `no_signal()`.

**Fix:** Increase `bar_histories` deque `maxlen` from 200 to 800 in `replay_symbol()` at `run_historical_pipeline.py:1649`. This also benefits SessionExtremesSetup and any other plugin with deep lookback requirements.

**`trad_AnchoredVWAPReversion` — logic bug in state machine ordering.**
The plugin gates on `abs(sigma) < sigma_min` early and clears departure state, returning `no_signal()` before checking reclaim confirmation. The moment of reclaim (close crossing back over VWAP) is precisely the bar where `sigma ≈ 0` — so the departure state is cleared before reclaim is detected. Verified empirically: 6,462 ESM6 1m bars have `sigma >= 1.5`, yet 0 signals fire.

**Fix:** Restructure the gate ordering — check if departure state exists and evaluate the return/reclaim condition BEFORE clearing state when `abs(sigma) < sigma_min`. The reclaim bar should be detected as the exit from departure, not silently reset. **State-clearing sequence is load-bearing:** on the reclaim bar, the correct order is (1) detect reclaim → (2) emit signal → (3) clear departure state → (4) return. Clearing state before step 2 causes the same bug. Leaving state active after emission causes a duplicate signal on the following bar when sigma stabilizes near zero.

**`trad_CrossAssetDivergence` — architectural: live-only plugin, no replay fix.**
`frames['cross_asset']` is not populated in `run_i7_and_persist()`. The frames dict at `run_historical_pipeline.py:1216-1227` has no `cross_asset` key. `xa.get("ready")` = None → immediate `no_signal()`. This plugin requires the running `cross_asset_service` (live), which is not replicated in the historical pipeline. Options: (a) wire cross-asset context into replay by pre-loading cross-instrument bar arrays, or (b) formally document as live-only and scope out of replay corpus expectations. Recommend (b) for Phase 131 — it is the only plugin that requires inter-symbol real-time state not available in single-symbol replay.

### Symbol coverage gaps

**10 OHLCV symbols with 0 signals** in rerun: EURUSD, EWZ, FXI, GDXJ, ITB, USO, VLUE, VXK6, VXM6, ZNM6.

VXK6/VXM6 (VIX futures) and ZNM6 (10-year Treasury) are regime-context instruments — their absence from the corpus is a coverage gap that ML will misread as "no signal exists here."

**Three confirmed root causes (from live DB):**

**Root cause A — Not in instruments or contract_metadata (6 ETFs):**
EWZ, FXI, GDXJ, ITB, USO, VLUE — exist in `market_data_ohlcv` but have no `instruments` row. `get_active_contracts()` never returns them; `replay_symbol()` is never called for them.
Fix: add to `instruments` table as `asset_class='equity'` instruments. Add to `settings.py` instrument config.

**Root cause B — Expired rolled contracts, same failure mode as A4:**
VXK6, VXM6, ZNM6 — `is_front_month=false` means the roll already occurred. These had OHLCV bars during their active window but produced 0 signals. This is the same root cause as A4: the `asset_class` injection gap in `replay_symbol()` applies to all rolled contracts, not just NQU6/YMM6/RTYM6. The A4 fix must be verified against VX and ZN contract series. The difference in symptom (0 signals here vs 201K plugin errors on NQ/YM/RTY) likely reflects asset-class-specific guard behavior, not a different root cause.

**Root cause C — FX model fitness gap:**
EURUSD — `is_active=true`, `asset_class='fx'`. Replay processed it fully (84,718 OHLCV bars → 48,595 `intelligence_features` rows across all TFs). `signals_evaluated=NULL` for all rows, meaning no I7 plugin emitted even a raw signal. Three compounding causes confirmed:
1. `hmm_regime=0` (ranging) for ALL EURUSD bars — HMM model not trained on FX dynamics, defaults to ranging.
2. `session_vwap_deviation_sigma ≈ 0.0` for most bars — FX session structure (24h trading, no clean open/close) causes the session VWAP bands to be nearly flat.
3. `DivergenceStack` requires `min_agreeing >= 3` concurrent divergences — EURUSD rarely has 3 agreeing.

This is not a single fixable bug. I7 plugins are calibrated for US equity futures. EURUSD signals require FX-specific parameter configuration (lower `min_agreeing`, FX-adapted HMM, FX session context). **Scope for Phase 131:** Document EURUSD as FX model gap; keep out of ML training corpus until FX-specific plugin tuning is addressed (future phase).

### A7 — I6 CTF universally zero (HIGH — corpus-wide, ML-blocking)

**Discovered:** 2026-06-17 via corpus audit. Memory: `project_i6_ctf_zero_bug.md`.
**Confirmed:** `intelligence_features.cross_timeframe_context->>'ctf_score'` = 0.0 for all 4,810,307 non-null rows. All 518,464 non-null `signal_events.ctf_score` = 0.0. I1/I3 data is correct.

**Root cause (confirmed, 2026-06-17):**
`extract_trend_sign()` returns 0 for None values. `model_dump()` on cached `IntelligenceEvent` objects includes None-valued I3 fields (e.g., `trend_direction=None` for early/cold-start bars where I3 has not yet produced valid output). The `intel_*` frames injected into `run_analysis_pipeline()` at `replay_symbol():1729-1731` are populated from `intelligence_cache`, which in turn comes from `model_dump()` of the cached event. So `other_intel` dicts all have `trend_direction=None` → `extract_trend_sign()` returns 0 → `score_trend_alignment()` returns 0 for all TFs → `ctf_score=0.0` for every bar corpus-wide.

The broken `--warmup` flag is NOT the fix — caches are call-local, so warmup bars do not seed the subsequent signal pass.

**Key files:**
- `src/intelligence/confluence/cross_timeframe.py:66-150` — `compute_full()`, `other_intel` build
- `src/intelligence/confluence/confluence_alignment.py:37-60` — `score_trend_alignment`
- `src/intelligence/confluence/confluence_weights.py:45-58` — `extract_trend_sign`
- `src/intelligence/pipeline/feature_pipeline_executor.py:183-194` — `_last_events` construction
- `production/scripts/run_historical_pipeline.py:1722-1731` — `intel_*` frame injection into `frames`

**Fix approach:** Seed `_last_events` in `feature_pipeline_executor.py` from `intelligence_features` DB at replay startup. Before the first bar is processed for each symbol, load the most recent `intelligence_features` row per TF and populate `_last_events[symbol][tf]` from it. This gives I6 valid I3 data (trend_direction, trend_strength) from the prior run so the first bar does not start with all-None context. This is a non-trivial change to `feature_pipeline_executor.py` (adds a DB query at replay init) and to `replay_symbol()` (must call the warmup seed before the event loop).

**Cold-start scope in Phase 133 full rebuild:** The DB seed is effective for incremental replays and for the Phase 131 verification replay (which runs against an existing corpus). In Phase 133, the rebuild opens with `TRUNCATE ... CASCADE`, leaving zero rows in `intelligence_features`. After that truncate, the seed query returns nothing. Bar 1 of each (symbol, TF) — 316 bars total (79 symbols × 4 TFs) — is a genuine cold start with `ctf_score=0`. This is correct behavior: there is no prior state to seed from. These 316 bars are excluded from the ≥85% distribution gate (see corpus acceptance criteria below).

**Verification:** After fix, run 1-week sample replay against the existing corpus (do not truncate first). `ctf_score` distribution must show ≥85% of non-null rows with `ctf_score > 0.05`. A distribution still pegged at 0.0 indicates the seed is not wiring correctly even with prior DB rows available. Do not proceed to Phase 133 full rebuild without this verification passing. Note that the current broken corpus has `ctf_score = 0.0` (not NULL) for all rows — a fix that still produces 0.0 cannot be distinguished from the broken state by a null check alone.

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

**Objective:** Stop placement is geometrically correct for all asset classes. All APR-migratable constants in `trade_framer.py` are APR-backed and ML-tunable. The `stopped_at_entry` outcome rate is verified <5%.

**Verification gate:** 1-month sample replay + lifecycle_replay on same date range shows `stopped_at_entry` exit_reason <5% of all stop exits in `trade_executions`; all APR keys visible in `/config/parameters` dashboard with correct seed values; APR-backed code produces identical signals to prior constants at seed values (regression test).

**First task — measure current stopped_at_entry rate:** Phase 126 (commit 6fe15543) already added a zone width gate and stop distance floor in `trade_framer.py`. The 25% rate cited in the todo predates Phase 126. Before writing any Phase 132 code, run a 2-week sample replay + lifecycle_replay and measure the current stopped_at_entry rate. If it is already <5%, document and close A2; remaining work is A3 (per-asset-class floors) and A5 (APR migrations). If still elevated, proceed with the A2 fixes below.

### A2 — Stop-zone geometry: remaining gaps after Phase 126

**Files:** `src/intelligence/trading/trade_framer.py`, `src/intelligence/trading/zone_engine.py`

Phase 126 added: zone width rejection gate in `trade_framer.py` (line 1052-1077) and stop distance floor at `feature.zone_engine.min_stop_distance_atr` = 0.5 ATR (line 1099-1110). Remaining gaps:

**(a) zone_engine fast-path bypass:** Confirm whether any zone generation path in `zone_engine.py` produces zones narrower than `min_zone_width_atr * atr` without going through the trade_framer rejection gate. If yes, add a defensive assertion at zone_engine output. If all narrow zones are caught by trade_framer, this item closes.

**(b) Stop distance floor increase:** The existing floor is 0.5 ATR (`feature.zone_engine.min_stop_distance_atr`). A5 migrates `MIN_STOP_ATR_MULTIPLIER` (1.0 ATR) as `feature.trade_framer.min_stop_atr`. Raising the effective floor from 0.5 to 1.0 ATR via the A5 APR migration should further reduce stopped_at_entry. This is handled in A5, not as a separate code change.

The sample data in `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md` (QQQ entry 723.09, zone [723.14, 723.16]) reflects the pre-Phase-126 state. Do not re-implement the zone width gate or stop distance floor — they already exist.

### A3 — Per-asset-class stop geometry

**Files:** `src/intelligence/trading/trade_framer.py`, zone_engine
FX pairs and small-tick commodities (SI silver, NG natgas, HG copper, CL crude) have fundamentally different tick structures than equity ETFs. A uniform ATR multiplier is wrong for these instruments.

**Fix:** Add per-asset-class APR keys for minimum stop floor:
- `feature.trade_framer.stop_multiplier_floor.fx` — seed from tick-size analysis of FX instrument ATRs
- `feature.trade_framer.stop_multiplier_floor.commodity_small_tick` — SI/NG/HG/CL
- `feature.trade_framer.stop_multiplier_floor.equity_etf` — QQQ/SPY/IWM/XLE/SMH
- `feature.trade_framer.stop_multiplier_floor.futures_large_tick` — ES/NQ/YM/RTY

**Seed value source:** Compute `median(intelligence_features.technical_indicators->>'atr') / tick_size` grouped by asset class from `intelligence_features`. Do NOT compute from `market_data_ohlcv` directly — trade_framer uses the I1 indicator ATR (smoothed, ~14-bar), not a raw OHLCV bar-range computation. Using a different ATR definition produces seed values inconsistent with what the code sees at runtime.

The 1-tick gate (`stop <= entry + 1 tick`) remains correct — do not remove it. The per-asset-class floor sits above it.

### A5 — APR migrations in trade_framer.py

**File:** `src/intelligence/trading/trade_framer.py`
Full constant table with APR keys and ML-target flags is in `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`. The table has 16 named rows, but the last row covers "Adaptive buffer piecewise coefficients" (0.80, 0.70, 0.20/0.30, 0.35/0.50, 0.16) — these are multiple distinct values that may require separate APR keys. Before writing any migration SQL, read the adaptive buffer function in `trade_framer.py` and count the actual number of DB INSERT statements needed. Migrate all of them.

**Process per constant:**
1. INSERT into `config_schema` + `config_state` in a new migration
2. Load via `ConfigService.get()` at init (pattern: `_config_service` field, `get_sync()` wrapper)
3. Remove the module-level constant
4. Add `[initial_estimate]` provenance tag in `config_schema.description`
5. Flag ML learning targets in description

No hardcoded numeric thresholds, weights, or multipliers remain in `trade_framer.py` after this phase.

---

## Phase 133 — Clean Corpus Rebuild

**Objective:** One complete, verified, unbiased corpus. All active-contract instruments covered. 35 of 35 eligible plugins firing (CrossAssetDivergence excluded as architectural live-only). Correct stop geometry. Full ECL coverage. `_verify_replay` 0/0/0. Infrastructure bugs fixed. Schema ready for CounterfactualTracker.

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

**Writer update required:** Step 5 adds `signal_ts` as a non-nullable FK anchor to `trade_executions`. Every INSERT into `trade_executions` must include this column after the migration or writes will fail. Update `lifecycle_replay.py`'s INSERT at the market-track write path (line ~1044) to include `signal_ts`, looked up from the `trade_frames` record for the given `frame_id`. Verify with a dry-run INSERT on a test row before committing the migration.

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
Fix: wrap per-(symbol, tf) DB operations in `async with conn.transaction():` — asyncpg's transaction context manager. It commits on clean exit and rolls back on any exception, including exceptions during commit. Do NOT use `await conn.execute('COMMIT')` or `await conn.execute('ROLLBACK')` in `finally` blocks — if the execute itself raises (connection reset, pool timeout), the transaction remains open and the error is masked. The `async with conn.transaction():` pattern is the asyncpg-correct approach and requires no `try/finally`.

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
| `confidence_utils.py` | `git mv` → `confidence.py`; update all import sites; run `grep -r "confidence_utils" .` (not just `src/`) to catch references in CLAUDE.md files and docs before committing |
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
- Distinct plugins firing: 35 of 35 eligible (CrossAssetDivergence formally excluded as architectural live-only — `_CORPUS_EXCLUDABLE = True` marker on the plugin class; any other zero-emission plugin is a bug, not an exception)
- All active-contract symbols present in signal_events (FX model-gap instruments excluded per Phase 131 D-05)
- `context_features` coverage: ≥99%
- `ctf_score` distribution non-degenerate: ≥85% of non-null rows have `ctf_score > 0.05` — a distribution still pegged at 0.0 indicates A7 is not working correctly; note that 0.0 is NOT NULL so a null check alone does not validate the fix; the 316 cold-start bars (79 symbols × 4 TFs, bar 1 each) are expected 0.0 and are acceptable
- `stopped_at_entry` outcome rate: <5% of stop exits — query `SELECT exit_reason, COUNT(*) FROM trade_executions GROUP BY 1` AFTER `lifecycle_replay.py` completes; `stopped_at_entry` is written by lifecycle_replay as the exit_reason, not by the backfill script
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
  → all trade_framer constants in APR; ML can tune them
  → stopped_at_entry rate verified <5% (sample replay + lifecycle_replay)

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
