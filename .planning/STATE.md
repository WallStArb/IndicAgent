---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: in_progress
last_updated: "2026-06-30T00:00:00.000Z"
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 13
  completed_plans: 12
  percent: 38
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.
**Current focus:** Phase A — 5m root cause investigation + IC engine methodology fixes
**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.1 Current Status

**Phase 141 — Corpus Quality Gate + IC Validation:** ✅ COMPLETE 2026-06-29
- P0: validity fixes (V1 look-ahead bias, V3 JSONB codec) + corpus rerun
- P1: IC validation — gate FAIL: 5m=0 qualifying features, 1h=23 qualifying features
- P2: HMM JIT 40x speedup shipped

**Phase 142 — BLOCKED** — gate FAIL on 5m prevents shadow mode deployment

**Next work: Phase A of execution plan**
- A1: 5m IC failure root cause (return_type enforcement, lookahead alignment, subsampling)
- A2: IC engine methodology fixes (028 P0/P2/P3/P4)
- A3: APR compile-time binding (008)
- A4: 7 zero-IC feature demotion (momentum_rank_z, poc_dist_atr, sr_resist_dist, sr_support_dist, va_position, volatility_rank_z, volume_rank_z)

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (IN PROGRESS)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans, 2026-06-26; 27/29 verification truths) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans, 2026-06-29) — gate FAIL: 5m=0 features |
| 142 | OOS Validation + Shadow Mode | BLOCKED — pending gate PASS on 5m |

## Current Data State (58-symbol full corpus) — 2026-06-29

- feature_vectors: 54,260,576 rows (58 symbols × 4 TFs)
- forward_returns: 54,260,576 rows (1:1 match, executable_open_to_open)
- feature_ic_scores: 402,651 rows (348,615 per-symbol non-pooled + 54,036 cross-sectional is_pooled=true)
- market_regimes: 819,020 rows (9 cross-sectional labels: {low/mid/high}_{bull/neutral/bear})
- ensemble_weights: 328 rows (12 strata × 12-18 features each)
- alpha_events: 12,472,068 rows (5m: 7.96M, 1h: 3.10M, 15m: 1.41M, 1d: 2.5K)
- context_features: 8,985 rows (2995 trading days × 3 macro features)

**IC gate results (Phase 141):**
- 5m: 0 qualifying features (FAIL — blocks Phase 142)
- 15m: 0 qualifying features
- 1h: 23 qualifying features (PASS)
- 1d: insufficient coverage (only 20% IC Sharpe coverage, excluded from decisions)
- 7 zero-IC features identified for demotion (see Phase A4 above)
- OOS boundary: `alpha.validation.oos_start = 2025-12-24T05:15:00Z`

**Dual regime system (both live):**
- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — 9 cross-sectional labels ({low/mid/high}_{bull/neutral/bear}), written by `equity_regime_model.py`; ic_engine stratifies on these

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** — diagnostic only; all ensemble reads filter WHERE is_pooled = false
- **IC Sharpe gate** — sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** — 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** — alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** — return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** — use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
- **Corpus re-run required** after Phase A ic_engine methodology fixes (028 P0/P2/P3/P4 change IC scores corpus-wide)

## Corpus Pipeline Gotcha

`--compute-only` silently skips all symbols if backfill_status is empty. After any truncation, seed first:

```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```
