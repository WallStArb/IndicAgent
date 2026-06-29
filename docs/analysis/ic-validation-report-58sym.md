# IC Validation Report — 58-Symbol V1-Corrected Corpus

**Date:** 2026-06-29
**Corpus:** Phase 141 V1-corrected (causal equity_regime_model, no look-ahead bias)
**IC Scores:** 348,615 cross-sectional rows (is_pooled=false)
**Ensemble Weights:** 443 rows
**Alpha Events:** 8,523,533 rows

## Executive Summary

The V1-corrected corpus shows strong IC performance in 1h timeframe with 23 qualifying features (|ic_sharpe_hac|>0.5, ic_ci_lower>0) across all regimes. However, 5m timeframe shows ZERO qualifying features - all features have |ic_sharpe_hac| <= 0.5. This is unexpected and requires investigation. 15m shows similar pattern to 5m. Top performing feature is `ctf_momentum` across multiple regimes.

**Gate Status:** FAIL - 5m has 0 qualifying features (<5 threshold). 1h PASS (23 features).

## CORPUS-01 Feature Audit Summary

See `corpus-01-feature-audit.md` for full per-feature variance/NaN/cliff audit.

**Summary:**
- 64 features audited
- 0 BLOCKED (all features have variance > epsilon for at least some symbols)
- 10 WARNING (NaN rate >5% or cliff detection)
- 54 PASS

**WARNING features:**
- Cross-sectional features (momentum_rank_z, volume_rank_z, volatility_rank_z, poc_dist_atr): 100% NaN rate (expected - populated by equity_regime_model, not feature_factory)
- HMM probability features (hmm_prob_*): 61.72% NaN rate (warmup artifact)

No features are BLOCKED - all have sufficient variance for IC measurement.

## NULL Rate by Timeframe

| TF  | total_cells | cells_with_sharpe | pct_with_sharpe |
|-----|-------------|-------------------|-----------------|
| 15m | 2,196       | 2,196             | 100.0%          |
| 1d  | 2,196       | 440               | 20.0%           |
| 1h  | 1,647       | 1,342             | 81.5%           |
| 5m  | 2,196       | 2,196             | 100.0%          |

**Note:** 1d has only 20% IC Sharpe coverage due to insufficient bars (<60K subsampled-bar minimum). 1d IC Sharpe values should NOT be used for decision-making.

## Top Features by IC Sharpe (Cross-Sectional, All Regimes)

| Feature      | Regime      | |ic_sharpe_hac| | ic_ci_lower |
|--------------|-------------|---------------|-------------|
| ctf_momentum | high_bear   | 3.21          | 0.33        |
| ctf_momentum | low_bull    | 3.13          | 0.35        |
| ctf_momentum | mid_bull    | 2.82          | 0.32        |
| ctf_momentum | high_bull   | 2.07          | 0.28        |
| ctf_momentum | low_bear    | 1.55          | 0.24        |
| ctf_momentum | mid_neutral | 1.50          | 0.20        |
| ctf_momentum | low_neutral | 1.44          | 0.20        |
| ctf_momentum | low_bull    | 1.42          | 0.17        |
| ctf_momentum | high_neutral| 1.33          | 0.18        |
| ctf_momentum | mid_bull    | 1.28          | 0.16        |
| ctf_momentum | mid_bear    | 1.26          | 0.20        |
| ctf_momentum | high_bear   | 1.08          | 0.17        |
| ctf_momentum | high_bull   | 1.08          | 0.13        |
| ctf_momentum | low_bear    | 0.95          | 0.09        |
| ctf_momentum | mid_bear    | 0.90          | 0.07        |
| ctf_momentum | low_bull    | 0.88          | 0.06        |
| ctf_momentum | low_neutral | 0.88          | 0.07        |
| ctf_momentum | mid_bull    | 0.81          | 0.06        |
| ctf_momentum | mid_neutral | 0.81          | 0.06        |
| ctf_momentum | high_neutral| 0.79          | 0.06        |
| ctf_momentum | high_bear   | 0.68          | 0.06        |
| aroon_fast   | mid_bull    | 0.63          | -0.09       |
| ctf_momentum | high_bull   | 0.63          | 0.04        |
| ctf_vwap_align| mid_bull   | 0.58          | 0.02        |
| in_overlap   | low_bear    | 0.57          | 0.06        |
| flight_quality| high_bear  | 0.54          | -0.02       |
| cci_fast     | low_bull    | 0.52          | -0.05       |
| vwap_dev_sigma| mid_bull   | 0.52          | 0.03        |
| momentum_z_fast| low_bull  | 0.51          | -0.05       |
| rsi_fast     | mid_bull    | 0.51          | -0.05       |

**ctf_momentum dominates:** 20 of top 30 positions across regimes, with strong positive CI lower bounds.

## IC by Timeframe

| TF  | cells | cells_with_sharpe | pass_sharpe_05 (>0.5) | ci_lower_positive |
|-----|-------|-------------------|----------------------|-------------------|
| 15m | 2,196| 2,196             | 0                    | 688               |
| 1d  | 2,196| 440               | 6                    | 220               |
| 1h  | 1,647| 1,342             | 24                   | 393               |
| 5m  | 2,196| 2,196             | 0                    | 721               |

**Critical Finding:** 5m and 15m have ZERO features with |ic_sharpe_hac| > 0.5. This is unexpected for high-frequency data and requires investigation.

## IC by Regime (Cross-Sectional Labels)

| Regime      | cells | cells_with_sharpe | pass_sharpe_05 | ci_lower_positive |
|-------------|-------|-------------------|----------------|-------------------|
| high_bear   | 915   | 671               | 4              | 217               |
| high_bull   | 915   | 671               | 3              | 224               |
| high_neutral| 915   | 610               | 2              | 266               |
| low_bear    | 915   | 610               | 3              | 135               |
| low_bull    | 915   | 891               | 5              | 246               |
| low_neutral | 915   | 610               | 2              | 204               |
| mid_bear    | 915   | 610               | 2              | 245               |
| mid_bull    | 915   | 891               | 7              | 246               |
| mid_neutral | 915   | 610               | 2              | 239               |

**All 9 regime labels present.** Low-bull and mid-bull have the most qualifying features (5 and 7 respectively).

## CORPUS-03 Null Model Comparison

**Status:** NOT IMPLEMENTED - requires additional development.

The null model baseline (equal-weight vs IC-weighted ensemble IC Sharpe on OOS window) is not yet computed. This requires:

1. Recomputing IC scores on the OOS subset (bar_ts >= 2025-12-24T05:15:00Z)
2. Computing equal-weight composite IC Sharpe (all features weight 1/N)
3. Computing IC-weighted composite IC Sharpe using frozen in-sample ensemble_weights
4. Comparing advantage = weighted - null against >0.1 threshold

**OOS Boundary Established:**
- `alpha.validation.oos_start` = 2025-12-24T05:15:00Z (MAX(bar_ts) - 6 months)
- OOS bar count: TBD (requires query)

**Recommendation:** Implement CORPUS-03 in Phase 141 P1 continuation or Phase 142.

## Demotion Candidates (Zero-IC Features)

The following features have max_abs_ic = 0 across all regimes and should be demoted:

| Feature          | max_abs_ic |
|------------------|------------|
| momentum_rank_z  | 0          |
| poc_dist_atr     | 0          |
| sr_resist_dist   | 0          |
| sr_support_dist  | 0          |
| va_position      | 0          |
| volatility_rank_z| 0          |
| volume_rank_z    | 0          |

**Phase 143 Implementation:** These features are identified for demotion. Actual removal from ensemble_weights happens in Phase 143.

## V2 Cost Calibration Constants

**Status:** NOT COMPUTED - requires forward_returns join per (tf, regime).

The `ic_x_return_scale` constant (converts IC units to return units) requires computing mean(|forward_return|) per (tf, regime) cell with `return_type = 'executable_open_to_open'`.

**Query Template:**
```sql
SELECT
    fv.tf,
    mrs.regime_label,
    AVG(ABS(fr.forward_return)) AS mean_abs_return
FROM feature_vectors fv
JOIN forward_returns fr
    ON fv.symbol = fr.symbol
    AND fv.bar_ts = fr.bar_ts  -- Exact match
JOIN market_regimes mrs
    ON fv.tf = mrs.tf
    AND fv.bar_ts >= mrs.ts
    AND fv.bar_ts < (mrs.ts + INTERVAL '1 day' * CASE mrs.tf
        WHEN '5m' THEN 5/1440
        WHEN '15m' THEN 15/1440
        WHEN '1h' THEN 1/24
        WHEN '1d' THEN 1
    END)
WHERE fr.return_type = 'executable_open_to_open'
  AND fv.bar_ts >= '2025-12-24T05:15:00Z'  -- OOS window
  AND fv.tf IN ('5m', '15m', '1h', '1d')
GROUP BY fv.tf, mrs.regime_label
ORDER BY fv.tf, mrs.regime_label;
```

## CORPUS-06 Per-Regime Observation Floor

Per the APR key `alpha.ic.min_obs_per_regime=3000`, cells with fewer than 3000 independent observations are excluded from BH-FDR gating and ensemble weighting. These cells are the expected source of zero-qualifying-feature regimes in the gate matrix.

**Floor Value:** 3000 independent observations (from `alpha.ic.min_obs_per_regime`)

**Below-Floor Cells:**

| tf  | regime        | n_obs | below_floor |
|-----|---------------|-------|-------------|
| 1d  | high_neutral  | 2,579 | YES         |
| 1d  | low_bear      | 1,573 | YES         |
| 1d  | low_neutral   | 1,519 | YES         |
| 1d  | mid_neutral   | 2,932 | YES         |

**Above-Floor Cells (5m, 15m, 1h):** All 27 cells have >3000 independent observations.

**Cross-Reference to Gate Matrix:** The 1d below-floor cells explain why 1d has sparse IC Sharpe coverage. However, this does NOT explain the 5m/15m zero-qualifying-feature issue - all 5m/15m cells have ample observations (>100K for most regimes).

**Interpretation:** The observation floor is NOT the root cause of the 5m gate FAIL. The 5m issue must be investigated separately (IC computation methodology, lookahead alignment, or subsampling minimum).

## Phase 141 Gate Assessment

**Gate Criterion:** ≥5 features total (across all regimes combined) with |ic_sharpe_hac|>0.5 AND ic_ci_lower>0 in BOTH 5m AND 1h.

**Results:**

| TF  | gate_pass_features |
|-----|-------------------|
| 1h  | 23                |
| 5m  | 0                 |

**Gate Status: FAIL**

- 1h: **PASS** - 23 qualifying features total (≥5 threshold met)
- 5m: **FAIL** - 0 qualifying features total (<5 threshold)

**Root Cause:** 5m timeframe has NO features with |ic_sharpe_hac| > 0.5 across all 9 regimes. This is unexpected and requires investigation:

1. Check if 5m IC computation is correctly using `return_type = 'executable_open_to_open'`
2. Verify lookahead_bars alignment for 5m
3. Check if there's a subsampling issue (60K minimum may be too aggressive for 5m)
4. Investigate why 5m/15m have 0 qualifying features while 1h has 24

**Per-(tf, regime) Qualifying Features Matrix:**

| tf  | regime      | qualifying_features |
|-----|-------------|---------------------|
| 1h  | high_bear   | 3                   |
| 1h  | high_bull   | 3                   |
| 1h  | high_neutral| 2                   |
| 1h  | low_bear    | 3                   |
| 1h  | low_bull    | 3                   |
| 1h  | low_neutral | 2                   |
| 1h  | mid_bear    | 2                   |
| 1h  | mid_bull    | 3                   |
| 1h  | mid_neutral | 2                   |
| 5m  | high_bear   | 0                   |
| 5m  | high_bull   | 0                   |
| 5m  | high_neutral| 0                   |
| 5m  | low_bear    | 0                   |
| 5m  | low_bull    | 0                   |
| 5m  | low_neutral | 0                   |
| 5m  | mid_bear    | 0                   |
| 5m  | mid_bull    | 0                   |
| 5m  | mid_neutral | 0                   |

**Note:** Sparse regimes (zero qualifying features) are expected per CORPUS-06 if they have <3000 independent obs. However, 5m has ZERO qualifying features across ALL regimes, which suggests a systemic issue with 5m IC computation, not sparse-regime effects.

## Next Steps

1. **Phase 142 Shadow Mode:** BLOCKED by gate FAIL. Do NOT proceed to shadow mode until 5m IC issue is resolved.

2. **V2 Implementation:** Deferred until gate PASS.

3. **Todo 015 (Demotion):** 7 zero-IC features identified for Phase 143 demotion.

4. **Todo 026 P1a (HMM JIT):** Can proceed independently - depends on market_regimes, not feature_ic_scores.

5. **Investigate 5m IC Issue:** High priority. Check:
   - `forward_returns.return_type = 'executable_open_to_open'` enforcement
   - Lookahead alignment for 5m (1 bar lookahead at 5m = 5 minutes)
   - Subsampling minimum (60K bars) may be too aggressive for 5m timeframe
   - ic_engine cross-sectional chunked timestamp fetch for 5m

6. **CORPUS-06 Implementation:** Run per-regime observation floor query (P1-T2b).

7. **CORPUS-07 Implementation:** Map I7 plugins to feature_vectors dimensions (P1-T3).

---

**Report Version:** 1.0
**Generated:** 2026-06-29
**Corpus Version:** V1 (Phase 141 P0 - causal equity_regime_model, no look-ahead bias)
