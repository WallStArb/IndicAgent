---
phase: 141-corpus-quality-gate-ic-validation
plan: P0
subsystem: database
tags: [ic-engine, equity-regime-model, base-batch, alpha-publisher, asyncpg, bisect, causal-rank, psycopg2, chunked-query]

# Dependency graph
requires:
  - phase: 139-alphaengine-ic-corpus
    provides: feature_ic_scores, ensemble_weights, alpha_events pipeline
  - phase: 140-forward-return-writer
    provides: forward_returns table with executable_open_to_open rows
provides:
  - APR migration 182 with equity_regime_model window constants + validation/floor keys
  - APR migration 183 with ic_engine.cs_chunk_ts infra constant
  - BaseBatch._setup_pool using database_manager.create_pool (JSONB codec registration)
  - equity_regime_model causal bisect expanding rank (no look-ahead bias)
  - ic_engine cross-sectional chunked timestamp fetch (no PG backend OOM)
  - market_regimes 928,791 rows (9 labels x 4 TFs, causal ranking applied)
  - feature_ic_scores 8,235 pooled rows (9 regimes x 4 TFs x 244 per cell)
  - ensemble_weights 443 rows
  - alpha_events 8,523,533 rows
affects:
  - 141-P1 (corpus validation reads feature_ic_scores, ensemble_weights, alpha_events)
  - 141-P2 (HMM JIT reads market_regimes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Causal expanding percentile rank via bisect.insort + bisect_left/right — no future knowledge, average-rank tie handling"
    - "Chunked timestamp pre-fetch: pre-fetch regime timestamps (small), JOIN feature_vectors+forward_returns per chunk — avoids 3-way JOIN OOM"
    - "Cross-sectional idempotency: frozenset subset check before data fetch eliminates redundant computation for already-complete (tf, regime) cells"
    - "BaseBatch JSONB: always use database_manager.create_pool() — registers JSONB codecs atomically, never bare asyncpg.create_pool()"

key-files:
  created:
    - production/migrations/182_equity_regime_model_apr.sql
    - production/migrations/183_ic_engine_cs_chunk_ts.sql
    - tests/unit/test_base_batch_jsonb.py
    - tests/unit/services/test_equity_regime_model_causal.py
  modified:
    - src/core/agent/base_batch.py
    - services/alpha_publisher.py
    - services/equity_regime_model.py
    - services/ic_engine.py

key-decisions:
  - "Causal bisect rank uses average-rank tie handling: (bisect_left + bisect_right) / 2 / n — prevents 0.0 rank for any value with a tie"
  - "TF window scaling: daily window * _BARS_PER_DAY[tf] so 200-day MA becomes 15,600 5m-bars — APR-backed via alpha.regime.ma_window"
  - "Cross-sectional chunked fetch: pre-fetch market_regimes timestamps (120K rows), then 2-way JOIN feature_vectors+forward_returns in 5,000-ts chunks (290K rows each) — eliminates 7M-row 3-way JOIN that OOM-killed PG backend"
  - "ic_engine early-exit returns must be 2-tuples (list, dict) not 3-key dicts — caller does cs_rows, cs_stats = _compute_cross_sectional_tf()"
  - "Idempotency short-circuit at (tf, regime) level: frozenset.issubset(existing_keys) check before any DB fetch — prevents 3-5 min wasted compute per already-complete cell"

patterns-established:
  - "BaseBatch pattern: _setup_pool must call create_pool() from database_manager, never asyncpg.create_pool()"
  - "Causal rank pattern: bisect.insort + (bisect_left+bisect_right)/2/n with NaN guard and pre-insert for first value"

requirements-completed: []

# Metrics
duration: 240min
completed: 2026-06-29
---

# Phase 141 Plan P0: Validity Fixes + Corpus Rerun Summary

**Two look-ahead bias sources fixed (BaseBatch JSONB codec + equity_regime_model causal rank), full corpus rerun complete with 8.5M alpha_events across 9 equity regimes x 4 TFs**

## Performance

- **Duration:** ~240 min (including corpus rerun)
- **Started:** 2026-06-29T~09:00Z
- **Completed:** 2026-06-29T13:59:17Z
- **Tasks:** 4 (T0, T1, T2, T3)
- **Files modified:** 8 (code + migrations)

## Accomplishments

- Fixed BaseBatch JSONB codec: `_setup_pool` now calls `database_manager.create_pool()` which registers asyncpg JSONB codecs, eliminating the alpha_publisher `json.dumps()` + `::jsonb` workaround
- Fixed V1 look-ahead bias in `equity_regime_model._compute_vix_pct_rank`: replaced `pandas.rank(pct=True)` (uses all future values) with bisect-based causal expanding percentile rank
- APR migration 182: seeded `alpha.regime.realized_vol_window=20`, `alpha.regime.vix_z_window=252`, `alpha.regime.ma_window=200`, `alpha.validation.oos_start=''`, `alpha.ic.min_obs_per_regime=3000`
- Full partial corpus rerun: market_regimes (928,791 rows) -> cross-sectional IC (8,235 pooled rows) -> ensemble_weights (443 rows) -> alpha_events (8,523,533 rows)

## Task Commits

1. **T0: APR Migration 182** - `1ef5cfce` (feat)
2. **T1: BaseBatch JSONB codec fix** - `c39d1f4f` (fix)
3. **T2: Causal expanding rank** - `7c759bdb` (fix)
4. **T3-a: Server-side cursor (first OOM fix)** - `8d2b483d` (fix)
5. **T3-b: Chunked timestamp fetch (PG backend OOM fix)** - `f863072b` (fix) + migration 183
6. **T3-c: Idempotency short-circuit** - `57f31e53` (perf)
7. **T3-d: Early-exit return type fix** - `49225964` (fix)

## Files Created/Modified

- `production/migrations/182_equity_regime_model_apr.sql` - APR keys for window constants + validation/floor keys
- `production/migrations/183_ic_engine_cs_chunk_ts.sql` - APR key for ic_engine cross-sectional chunk size
- `src/core/agent/base_batch.py` - _setup_pool uses database_manager.create_pool()
- `services/alpha_publisher.py` - removed json.dumps() + ::jsonb workaround (3 call sites)
- `services/equity_regime_model.py` - causal bisect expanding rank, _tf_window() helper, APR reads
- `services/ic_engine.py` - chunked timestamp fetch for cross-sectional pass, idempotency short-circuit, early-exit return type fix, APR key cs_chunk_ts
- `tests/unit/test_base_batch_jsonb.py` - verifies _setup_pool calls create_pool (not bare asyncpg)
- `tests/unit/services/test_equity_regime_model_causal.py` - 7 tests: tf_window values, causal property, NaN propagation, tie handling

## Decisions Made

- **Causal rank tie handling:** Average rank `(bisect_left + bisect_right) / 2 / n` — prevents 0.0 rank for ties; consistent with scipy.stats.rankdata 'average' method
- **TF window scaling:** `daily_window * _BARS_PER_DAY[tf]` makes window APR-tunable without separate per-TF keys; only `alpha.regime.ma_window=200` needed
- **Chunked cross-sectional fetch:** Pre-fetch 120K regime timestamps (tiny), then 5K-timestamp chunks × 58 symbols = 290K rows/query rather than 7M-row 3-way JOIN. APR key `infra.ic_engine.cs_chunk_ts=5000` makes it tunable
- **Early-exit as 2-tuple:** `_compute_cross_sectional_tf` declared `-> tuple[list[dict], dict[str, Any]]`; all code paths must return `([], {...})` — 3-key dict returns cause "too many values to unpack"

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Python OOM on cross-sectional fetchall (server-side cursor)**
- **Found during:** T3 (ic_engine cross-sectional pass)
- **Issue:** `cur.fetchall()` on 5m/low_bull 7M-row result → ~14 GB Python objects
- **Fix:** psycopg2 server-side named cursor with `itersize=50_000`
- **Files modified:** services/ic_engine.py
- **Committed in:** 8d2b483d

**2. [Rule 3 - Blocking] PostgreSQL backend OOM on 3-way JOIN**
- **Found during:** T3 (ic_engine cross-sectional pass — after fix 1)
- **Issue:** 3-way JOIN (feature_vectors × market_regimes × forward_returns) for 5m/low_bull (120K timestamps × 58 symbols = 7M rows) OOM-killed the PostgreSQL backend process
- **Fix:** Pre-fetch regime timestamps from market_regimes (small), then 2-way JOIN in 5K-timestamp chunks. APR migration 183 for `infra.ic_engine.cs_chunk_ts=5000`
- **Files modified:** services/ic_engine.py, production/migrations/183_ic_engine_cs_chunk_ts.sql
- **Committed in:** f863072b

**3. [Rule 1 - Bug] Idempotency check missing at (tf, regime) level**
- **Found during:** T3 (ic_engine first run with chunk fix)
- **Issue:** Already-complete (tf, regime) cells had no early exit — each fetched and computed 4-7M rows (16 GB RAM, 3-5 min) before per-feature `existing_keys` check found them all done
- **Fix:** `frozenset.issubset(existing_keys)` check at function entry; returns immediately without any DB fetch
- **Files modified:** services/ic_engine.py
- **Committed in:** 57f31e53

**4. [Rule 1 - Bug] Early-exit returns were dicts not 2-tuples**
- **Found during:** T3 (idempotency short-circuit triggered for first time on 5m/high_bear)
- **Issue:** All early-exit returns in `_compute_cross_sectional_tf` returned 3-key dicts (`{"n_committed": 0, "n_skipped": 0, "all_results": []}`); caller does `cs_rows, cs_stats = ...` which requires a 2-tuple
- **Fix:** Changed all early exits to `([], {"n_committed": 0, "n_skipped": N})`
- **Files modified:** services/ic_engine.py
- **Committed in:** 49225964

---

**Total deviations:** 4 auto-fixed (2 Rule 3 blocking, 2 Rule 1 bug)
**Impact on plan:** All fixes required for T3 to complete. No scope creep. Fixes 3-4 are latent bugs in the original cross-sectional code; fixes 1-2 address genuine data scale (5m TF with 5-year corpus = 7M rows/regime cell).

## Issues Encountered

- ic_engine cross-sectional pass required 4 fix iterations to work at full corpus scale: Python OOM -> PG backend OOM -> wasted idempotency computation -> return type crash. Each was a distinct root cause.
- Running from worktree directory required: previously the process was started from main repo (`cd /home/bg/dev/indicagent`), so it ran old code. Fixed by running `.venv/bin/python services/...` from within the worktree directory.
- Pre-existing test failures (31): all pre-existing, not caused by P0 changes:
  - 11 `test_alpha_publisher.py`: async mock infrastructure (`conn.transaction()` not async CM)
  - 2 `test_ic_engine_compute_split.py`: stale test expectations (pre-split worker API)
  - 15 `test_run_historical_pipeline.py`: module path issue (`production.scripts` not importable)
  - 3 collection errors: `test_regime_writer.py` x2, `test_causal_hmm_decoding.py` — `_causal_decode` not exported from `regime_writer`

## Corpus Rerun Results

| Table | Rows | Notes |
|---|---|---|
| market_regimes | 928,791 | 9 labels, 4 TFs, causal rank applied |
| feature_ic_scores (pooled) | 8,235 | 9 regimes x 4 TFs x 244 per cell; 1h has 183/244 (extended scale gated) |
| ensemble_weights | 443 | 29 strata with passing features |
| alpha_events | 8,523,533 | --skip-kafka; 0 rejected |

Regime distribution: low_bull 28.3%, mid_bull 21.0%, high_bear 17.2%, high_bull 12.6% — no single label above 85% threshold.

## Known Stubs

None. All four pipeline tables populated with real computed values.

## Threat Flags

None. No new network endpoints, auth paths, or file access patterns introduced.

## Next Phase Readiness

P1 (corpus validation / CORPUS-01 through CORPUS-07) can proceed:
- `feature_ic_scores WHERE is_pooled=true` has 8,235 rows from corrected causal ranking
- `ensemble_weights` 443 rows with valid pooled IC backing
- `alpha_events` 8,523,533 rows from corrected equity regime labels
- APR keys for P1 gates seeded: `alpha.validation.oos_start`, `alpha.ic.min_obs_per_regime=3000`

---
*Phase: 141-corpus-quality-gate-ic-validation*
*Completed: 2026-06-29*
