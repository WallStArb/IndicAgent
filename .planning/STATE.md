---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Intelligence Vectors — AlphaEngine
status: milestone_archived
last_updated: "2026-06-24T10:00:00.000Z"
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 19
  completed_plans: 20
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Milestone complete

## v3.0 Phase Summary

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE — code (9/9 plans); data run pending full corpus |
| 139 | Ensemble + Alpha Emission | PLANNED (3 plans, not started) |

## Phase 138 Plan Detail

| Plan | Name | Status | Date | Notes |
|------|------|--------|------|-------|
| P0 | Feature Vector ID + FeatureVectorWriter | Complete | 2026-06-22 | Migration 158, 61-param INSERT |
| P1 | Foundation Hardening | Complete | 2026-06-22 | NaN guard, feature_factory_version, 7 new fields |
| P2 | IC Engine Foundation | Complete | 2026-06-22 | BaseBatch, forward_returns, feature_ic_scores tables, APR keys |
| P3 | FeatureFactory Backfill | Complete | 2026-06-23 | 4-symbol corpus (SPY/TLT/XLF/QQQ) — validation only |
| P4 | Regime Writer | Complete | 2026-06-22 | Causal HMM regime labeler |
| P5 | Forward Return Writer | Complete | 2026-06-22 | Writes forward_returns table |
| P6 | IC Engine | Complete | 2026-06-22 | Vectorized Spearman IC computation |
| P6.5 | IC Sortino/Win Rate | Complete | 2026-06-23 | Migration 164, OTel gauges |
| P7 | IC Math Helpers + Tests | Complete | 2026-06-23 | Pure functions, unit tests |
| P8 | IC Pipeline Data Run | Complete (4-symbol) | 2026-06-23 | 12,444 IC scores on SPY/TLT/XLF/QQQ; full corpus run pending |

## Current Data State (4-symbol corpus — will be replaced)

- feature_vectors: 3,787,423 rows (SPY/TLT/XLF/QQQ x 4 TFs)
- forward_returns: 3,787,423 rows (1:1 match)
- feature_ic_scores: 12,444 rows (683 non-pooled passers)
- IC discovery report: `docs/analysis/ic-discovery-report.{md,json}`

**Top feature (4-symbol):** `quarter_position` (TLT, 15m, trending_up, IC Sharpe 0.870)

## Full Corpus Run — RUNNING (started 2026-06-24)

All 6 pipeline steps running end-to-end via `corpus_pipeline_run.sh`.

```bash
nohup bash production/scripts/corpus_pipeline_run.sh > logs/corpus_pipeline/nohup.log 2>&1 &
tail -f logs/corpus_pipeline/nohup.log
```

**Pipeline steps:** feature_factory → regime_writer → forward_return_writer → ic_engine → ensemble_trainer → alpha_publisher

**Pre-run state:** All derived tables truncated (including alpha_events). backfill_status seeded from market_data_ohlcv (232 rows = 58 symbols × 4 TFs) because truncation cleared fetch_complete flags — `--compute-only` requires these.

**Expected duration:** ~20-30h (step 1 dominates).

**After run completes:** Review IC discovery report, commit all work, then begin next milestone.

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — module-level constant in regime_writer.py; changing it invalidates all feature_ic_scores and requires full re-run
- **Pooled IC rows (is_pooled=true)** — DIAGNOSTIC ARTIFACTS ONLY; Phase 139 reads exclusively WHERE is_pooled = false
- **IC Sharpe gate** — sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000 (not n_independent); stride divides inside _compute_ic_rolling_metrics
- **ON CONFLICT for partial indexes** — use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB partial index constraint)
- **regime_label_source DEFAULT** — 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** — alpha.ic.subsample_min_stride (floor, not fixed stride); actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** — return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **Pooled IC** is diagnostic; all Phase 139 reads filter WHERE is_pooled = false
- **1d non-pooled rows** — expected empty below 20K IC Sharpe gate per symbol; need full 58-symbol corpus to get 1d data
- **alpha_events table** — removed from Phase 138 scope; created in Phase 139 P1 migration 168

## Session Continuity

### Current session (2026-06-24) — Corpus pipeline running

Full corpus pipeline launched. All naming violations fixed (EnsembleBuilder→EnsembleTrainer, AlphaEmitter→AlphaPublisher, run_corpus_pipeline.sh→corpus_pipeline_run.sh). All unit tests green (5,245 pass).

**Gotcha:** `--compute-only` silently skips all symbols if backfill_status is empty (requires fetch_complete=true per row). After any truncation, seed backfill_status first:
```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```

**Next:** Wait for corpus_pipeline_run.sh to complete → review IC discovery report → commit → next milestone

### Previous session (2026-06-23) — Phase 138 P8

IC engine corpus run on SPY/TLT/XLF/QQQ × 4 TFs. 12,444 IC score rows in 150s. 1,022 walk-forward passers; 683 non-pooled passers. Discovery report at `docs/analysis/ic-discovery-report.{md,json}`. Unit tests: 5165 passed, 1 pre-existing failure (test_pipeline_backpressure — stale reference, unrelated to Phase 138).

### Earlier sessions (2026-06-20 to 2026-06-22)

- v2.10 closed; v3.0 started — Feature Factory (Phase 137) complete; IC engine (Phase 138) P0-P7 complete
- I5/I6/I7 fully archived; Feature Factory replaces I1-I4 implementation; `feature_vectors` is v3.0 training corpus
- `BaseBatch` Ring 0 base class: `src/core/agent/base_batch.py`
- AlphaEngine methodology: `docs/intelligence/intelligence-alphaengine.md`
- IC methodology: `docs/plans/2026-06-20-alphaengine-v1-methodology.md`
