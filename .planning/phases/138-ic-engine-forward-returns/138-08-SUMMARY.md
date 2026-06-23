---
phase: 138-ic-engine-forward-returns
plan: 08
status: complete
completed: 2026-06-23
---

# P8 Summary: IC Pipeline Data Run

All six tasks completed. The 4-symbol IC pipeline (SPY, TLT, XLF, QQQ) ran to completion across all services; discovery report written.

## feature_vectors

100% regime coverage across all 16 cells (4 symbols x 4 TFs).

| Symbol | TF  | Rows    | Regime % |
|--------|-----|---------|----------|
| QQQ    | 5m  | 469,163 | 100.0    |
| QQQ    | 15m | 350,144 | 100.0    |
| QQQ    | 1h  | 131,099 | 100.0    |
| QQQ    | 1d  | 7,049   | 100.0    |
| SPY    | 5m  | 469,601 | 100.0    |
| SPY    | 15m | 350,386 | 100.0    |
| SPY    | 1h  | 131,207 | 100.0    |
| SPY    | 1d  | 7,049   | 100.0    |
| TLT    | 5m  | 469,403 | 100.0    |
| TLT    | 15m | 350,128 | 100.0    |
| TLT    | 1h  | 90,782  | 100.0    |
| TLT    | 1d  | 3,542   | 100.0    |
| XLF    | 5m  | 469,524 | 100.0    |
| XLF    | 15m | 350,168 | 100.0    |
| XLF    | 1h  | 131,129 | 100.0    |
| XLF    | 1d  | 7,049   | 100.0    |

**Total: 3,787,423 rows**

## forward_returns

Near-complete lookahead coverage across all TFs. Completeness degrades slightly at the slow/extended horizons due to training window end cutoff (expected).

| TF  | Total     | complete_fast | complete_mid | complete_slow |
|-----|-----------|---------------|--------------|---------------|
| 5m  | 1,877,691 | 1,877,683     | 1,877,667    | 1,877,607     |
| 15m | 1,400,826 | 1,400,818     | 1,400,802    | 1,400,742     |
| 1h  | 484,217   | 484,209       | 484,193      | 484,133       |
| 1d  | 24,689    | 24,681        | 24,665       | 24,605        |

**Total: 3,787,423 rows** (exact 1:1 match with feature_vectors)

## feature_ic_scores

12,444 total rows. 1d non-pooled produced 0 rows — bar count insufficient for the IC Sharpe gate (~24k total bars across 4 symbols, below the 20k-per-cell threshold at per-symbol granularity). 1d pooled rows computed but excluded from passing_features.

| TF  | is_pooled | Total | Passes FDR | Passes Walk-Forward |
|-----|-----------|-------|------------|---------------------|
| 5m  | false     | 2,928 | 104        | 231                 |
| 5m  | true      | 976   | 43         | 121                 |
| 15m | false     | 2,928 | 52         | 322                 |
| 15m | true      | 976   | 22         | 103                 |
| 1h  | false     | 2,928 | 13         | 130                 |
| 1h  | true      | 976   | 15         | 115                 |
| 1d  | true      | 732   | 0          | 0                   |

**1,022 total walk-forward passing rows; 683 non-pooled walk-forward passing (in JSON passing_features)**

## Top 10 Features by IC Sharpe (is_pooled=false, passes_walkforward=true)

| Feature             | TF  | Regime        | IC     | Sharpe | Passes FDR |
|---------------------|-----|---------------|--------|--------|------------|
| quarter_position    | 15m | trending_up   | 0.1081 | 0.870  | yes        |
| dow_cos             | 5m  | ranging       | 0.1127 | 0.816  | no         |
| momentum_reversal_z | 1h  | trending_up   | 0.0962 | 0.810  | no         |
| momentum_z_mid      | 1h  | trending_up   | 0.0988 | 0.781  | no         |
| momentum_z_fast     | 1h  | trending_up   | 0.1081 | 0.775  | no         |
| hmm_duration        | 5m  | trending_down | 0.0966 | 0.743  | no         |
| hmm_duration        | 5m  | trending_down | 0.1161 | 0.725  | no         |
| rsi_slow            | 1h  | trending_up   | 0.0680 | 0.683  | no         |
| cci_mid             | 15m | trending_up   | 0.0860 | 0.664  | no         |
| cci_fast            | 1h  | trending_up   | 0.0942 | 0.660  | no         |

Notable: `quarter_position` is the sole feature passing both FDR and walk-forward gates. Most walk-forward passers do not cross the stricter FDR threshold — consistent with the bootstrap CI being noisy at this corpus size.

## IC Discovery Report

- `docs/analysis/ic-discovery-report.md` — markdown with per-feature table, top-20 by IC Sharpe, pooled-vs-regime diagnostic, and below-gate cells
- `docs/analysis/ic-discovery-report.json` — machine-readable; 683 passing_features (is_pooled=false, passes_walkforward=true); training_window_end: 2026-06-23T16:00:00+00:00

## Phase 138 Data Pipeline: Complete

All three services (regime_writer, forward_return_writer, ic_engine) ran to completion and are idempotent. Phase 139 ensemble construction can consume `docs/analysis/ic-discovery-report.json` directly.
