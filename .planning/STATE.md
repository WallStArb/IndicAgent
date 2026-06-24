---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Intelligence Vectors — AlphaEngine
status: executing
last_updated: "2026-06-23T23:00:00.000Z"
last_activity: 2026-06-23 -- Phase 138 complete; full corpus OHLCV gap fill running; truncate + re-backfill pending before Phase 139
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 20
  completed_plans: 18
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Full corpus data run — filling OHLCV gaps, then re-running backfill_feature_factory + IC pipeline across all 58 ETFs before Phase 139

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

## Full Corpus Run — In Progress

Preparing to run the complete IC pipeline across all 58 active ETFs.

**Step 1 — OHLCV gap fill (running now):**
```bash
bash production/scripts/backfill_missing_timeframes.sh
```
Filling 8 symbols with zero/missing intraday TFs: XLU, XLV, XLY, XOP, XRT (need 5m/15m/1h), VTV, IBIT (need 5m/15m), IEF (need 15m).

**Step 2 — Truncate derived tables:**
```bash
bash production/scripts/truncate_derived_tables.sh
```
Clears feature_vectors, forward_returns, feature_ic_scores, backfill_status.

**Step 3 — Full corpus IC pipeline:**
```bash
.venv/bin/python services/backfill_feature_factory.py          # ~20-30h, all 58 ETFs × 4 TFs
.venv/bin/python services/regime_writer.py --backfill
.venv/bin/python services/forward_return_writer.py --backfill
.venv/bin/python services/ic_engine.py --backfill
```

**After full corpus run:** Phase 138 P8 is complete and Phase 139 can begin.

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

### Current session (2026-06-23) — Post Phase 138, preparing full corpus

Phase 138 code complete (all 9 plans). 4-symbol validation run produced 12,444 IC scores. Found 8 symbols with zero/missing intraday TFs in market_data_ohlcv. Gap fill running now (backfill_missing_timeframes.sh). After gap fill: truncate derived tables, run full corpus pipeline (~20-30h), then Phase 139.

Created scripts:
- `production/scripts/truncate_derived_tables.sh` — truncates feature_vectors, forward_returns, feature_ic_scores, backfill_status
- `production/scripts/backfill_missing_timeframes.sh` — updated with 2026-06-23 gap audit (replaces old 6-symbol list)

**Next:** Wait for gap fill to complete → truncate → full corpus backfill → Phase 139 (`/gsd-execute-phase 139`)

### Previous session (2026-06-23) — Phase 138 P8

IC engine corpus run on SPY/TLT/XLF/QQQ × 4 TFs. 12,444 IC score rows in 150s. 1,022 walk-forward passers; 683 non-pooled passers. Discovery report at `docs/analysis/ic-discovery-report.{md,json}`. Unit tests: 5165 passed, 1 pre-existing failure (test_pipeline_backpressure — stale reference, unrelated to Phase 138).

### Earlier sessions (2026-06-20 to 2026-06-22)

- v2.10 closed; v3.0 started — Feature Factory (Phase 137) complete; IC engine (Phase 138) P0-P7 complete
- I5/I6/I7 fully archived; Feature Factory replaces I1-I4 implementation; `feature_vectors` is v3.0 training corpus
- `BaseBatch` Ring 0 base class: `src/core/agent/base_batch.py`
- AlphaEngine methodology: `docs/intelligence/intelligence-alphaengine.md`
- IC methodology: `docs/plans/2026-06-20-alphaengine-v1-methodology.md`
