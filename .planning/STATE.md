---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: in_progress
last_updated: "2026-06-27T11:29:08.392Z"
progress:
  total_phases: 8
  completed_phases: 2
  total_plans: 9
  completed_plans: 9
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Every intelligence output flows through one canonical typed bus that both consumers can trust.
**Current focus:** Phase 141 — Corpus Quality Gate + IC Validation (blocked on corpus pipeline)

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25; no verification file) |

## v3.1 Phase Summary (IN PROGRESS)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans, 2026-06-26; 27/29 verification truths — 2 gaps resolved by corpus pipeline) |
| 141 | Corpus Quality Gate + IC Validation | PLANNED — blocked on corpus pipeline completion |

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

## Current Data State (58-symbol full corpus)

- feature_vectors: 54,260,576 rows (58 symbols × 4 TFs — COMPLETE)
- forward_returns: 54,260,576 rows (1:1 match — COMPLETE)
- feature_ic_scores: 382,271 rows (330,890 non-pooled; 58 distinct symbols, 58 distinct features)
- market_regimes: 819,020 rows (9 cross-sectional labels: {low/mid/high}_{bull/neutral/bear})
- alpha_events: 0 rows (ensemble_trainer + alpha_publisher not yet run)
- context_features: 8,985 rows (2995 trading days × 3 macro features)

**Dual regime system (both live):**

- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — 9 cross-sectional labels ({low/mid/high}_{bull/neutral/bear}), written by `equity_regime_model.py` (VIX proxy percentile × ETF breadth above 200MA); ic_engine stratifies on these; `feature_ic_scores` already has all 9 buckets populated

## Corpus Pipeline — IN PROGRESS (started 2026-06-24)

Steps 1-4 complete. Steps 5-6 pending.

**Pipeline steps:**

- [x] feature_factory — 54M rows
- [x] regime_writer --refit (K=5) — labels confirmed in feature_vectors
- [x] forward_return_writer — 54M rows
- [x] ic_engine — 382K IC scores
- [ ] ensemble_trainer — not yet run (alpha_ensemble table does not exist)
- [ ] alpha_publisher — not yet run (alpha_events = 0)

**regime_writer also running** (new workers PID 1003466+ started 2026-06-27 06:04 — separate from --refit run)

**After pipeline completes:** Run Phase 141 (Corpus Quality Gate + IC Validation).

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

### Current session (2026-06-27) — GSD state sync

Phases 139, 140, 140.5 completed since STATE.md was last updated. STATE.md and ROADMAP.md reconciled. Corpus pipeline steps 1-4 complete; steps 5-6 (ensemble_trainer, alpha_publisher) pending. regime_writer still has active workers (PID 1003466+, started 06:04).

**Next:** Wait for corpus pipeline completion (ensemble_trainer + alpha_publisher) → commit all work → begin Phase 141 (Corpus Quality Gate + IC Validation).

**Gotcha:** `--compute-only` silently skips all symbols if backfill_status is empty (requires fetch_complete=true per row). After any truncation, seed backfill_status first:

```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```

### Previous sessions (2026-06-24 to 2026-06-26) — Phases 140, 140.5

- Phase 140 (IC Engine Correctness): per-scale stride fix, overnight gap contamination, BH-FDR meta-level gate, feature collinearity clustering, sharpe_min_windows raised to 30
- Phase 140.5 (Corpus Foundations): batch primitives fix (CTF/VP/HMM), K=5 BIC validation, Feature Registry, cross-sectional equity regime model, context_features table
- Full 58-symbol corpus pipeline launched; K=5 regime refit run; ic_engine produced 382K scores
