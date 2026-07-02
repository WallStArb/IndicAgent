---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: in_progress
last_updated: "2026-07-02T12:01:07.794Z"
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 6
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.
**Current focus:** Phase 141.1 — measurement-and-decision-integrity-foundation-make-everythin
**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.1 Current Status

**Phase 141 — Corpus Quality Gate + IC Validation:** ✅ COMPLETE 2026-06-29

- P0: validity fixes (V1 look-ahead bias, V3 JSONB codec) + corpus rerun
- P1: IC validation — gate FAIL: 5m=0 qualifying features, 1h=23 qualifying features
- P2: HMM JIT 40x speedup shipped

**Phase A — IC Engine Methodology Fixes + Gate Redesign:** ✅ COMPLETE 2026-06-30

- A1: 5m IC failure root cause — gate design bug, not signal absence (721 cells with ic_ci_lower > 0)
- A2: IC engine methodology fixes (WF fold construction, corpus-level BH-FDR, scale-specific embargo, direct-linkage clustering)
- A3: APR compile-time binding for ic_engine + ensemble_trainer
- A4: CANCELLED — Renaissance principle: never delete signal candidates; shadow/demote/promote handles this
- A5: Renaissance IC gate redesign — ic_ci_lower > 0 AND passes_fdr = true replaces binary passes_walkforward gate

**Phase 142 — BLOCKED** — pending Phase B corpus re-run on corrected ic_engine

**Regime-label validation pending (corrected 2026-07-01):** HMM regime model (`regime_writer.py`) fits on the full corpus before its causal decode — possible look-ahead bias in regime-stratified IC. Merged into `.planning/todos/pending/026-hmm-regime-audit-optimization.md` (P4a section) — do NOT treat as an unconditional blocker; 026's own decision gate requires empirical proof of harm (baseline-separation query on `feature_ic_scores`) before any fix is warranted. Corpus rebuild currently running (regime_writer, step 2, started 06:29) should finish as-is — there's nothing to validate against until it does. Run 026's Step 1 query once `feature_ic_scores` is populated, before deciding whether this needs a fix + a third corpus rebuild.

**Next work: Phase B — corpus re-run**

- B1: `production/scripts/corpus_pipeline_run.sh` — regime_writer → forward_return_writer → ic_engine → ensemble_trainer → alpha_publisher
- B2: Empirical calibration (cost hurdle, threshold validation, gap contamination check)
- B3: IC validation analysis — how many features qualify per TF after gate redesign?

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
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans, 2026-06-29) — gate FAIL: 5m=0 features (pre-Phase-A baseline, see below) |
| 142A | Ensemble IC Measurement | PLANNED (2 plans/2 waves), reviewed 2026-07-01 — execution blocked on Phase B corpus re-run |
| 142B | Frame Simulation + Counterfactual Tracking | deliberately unplanned until 142A's EIC-04 gate passes |

**STALE — pre-Phase-A baseline, do not cite as current:** the row counts and IC gate results below are
from the 2026-06-29 corpus run, before Phase A's ic_engine methodology fixes and before the current
(2026-07-01) 3rd rebuild. Query the DB directly for current counts; this section is kept only as a
before/after comparison point once the current rebuild finishes.

- feature_vectors: 54,260,576 rows (58 symbols × 4 TFs) — forward_returns: 1:1 match
- feature_ic_scores: 402,651 rows; 5m/15m: 0 qualifying features (FAIL — root cause was a gate design bug, not signal absence, per Phase A finding); 1h: 23 qualifying; 1d: insufficient coverage
- alpha_events: 12,472,068 rows; OOS boundary: `alpha.validation.oos_start = 2025-12-24T05:15:00Z`

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

## Accumulated Context

### Roadmap Evolution

- Phase 142B.1 inserted after Phase 142B: Ensemble Weighting Methodology — from 2026-07-01 v3 architecture review (.planning/research/2026-07-01-v3-architecture-review.md). Not urgent: depends on Phase 142A complete, does not change current-focus sequencing (Phase B corpus re-run).
