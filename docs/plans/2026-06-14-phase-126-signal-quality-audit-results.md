# Phase 126 Signal Quality Audit Results

**Produced by:** P126-05 (Wave 4)
**Audit date:** 2026-06-15
**Script:** `production/scripts/signal_quality_audit.py`
**Design ref:** D-12, D-13 in `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md`

---

## Layer 1 - IC League Table

Per-plugin Information Coefficient (IC = Pearson corr(raw_confidence, pnl_r)), hit_rate, and bootstrap 95% CI for all plugins with >= 30 non-null pnl_r outcomes in signal_ledger.

**Thresholds (D-13):**
- VALIDATED: IC > 0.02 AND hit_rate CI lower > 0.45
- NOISE CANDIDATE: IC between -0.02 and 0.02, OR hit_rate CI includes 0.5
- ANTI-SIGNAL: IC < -0.02 OR hit_rate CI upper < 0.45

| Plugin | N | HitRate | CI Lower | CI Upper | IC | t-stat | Avg pnl_r | nFX | nEQ | AvgFX | AvgEQ | Verdict |
|--------|---|---------|----------|----------|----|--------|-----------|-----|-----|-------|-------|---------|
| trad_SqueezeExpansion | 6,803 | 0.1167 | 0.1092 | 0.1244 | +0.032 | 2.64 | -0.467 | 0 | 6,803 | N/A | -0.467 | ANTI-SIGNAL |
| trad_TrendFollowing | 2,393 | 0.2336 | 0.2169 | 0.2503 | +0.023 | 1.13 | +0.059 | 38 | 2,355 | +0.321 | +0.055 | ANTI-SIGNAL |
| trad_PatternCompletion | 77,714 | 0.1405 | 0.1381 | 0.1430 | +0.008 | 2.34 | -0.391 | 2,735 | 74,979 | -0.010 | -0.405 | ANTI-SIGNAL |
| trad_AnchoredVWAPReversion | 84,932 | 0.0907 | 0.0888 | 0.0926 | +0.004 | 1.18 | -0.127 | 1 | 84,931 | -1.000 | -0.127 | ANTI-SIGNAL |
| trad_FVGFill | 37,664 | 0.1222 | 0.1189 | 0.1254 | +0.001 | 0.28 | -0.602 | 6,327 | 31,337 | -0.381 | -0.647 | ANTI-SIGNAL |
| trad_GapAnalysisSetup | 147,238 | 0.1524 | 0.1506 | 0.1542 | -0.001 | -0.42 | -0.399 | 7,753 | 139,485 | +0.044 | -0.423 | ANTI-SIGNAL |
| trad_OFIContinuation | 48,528 | 0.1332 | 0.1302 | 0.1362 | -0.001 | -0.32 | -0.404 | 0 | 48,528 | N/A | -0.404 | ANTI-SIGNAL |
| trad_DivergenceStack | 149,873 | 0.2197 | 0.2177 | 0.2218 | -0.011 | -4.15 | -0.297 | 37,662 | 112,211 | +0.078 | -0.422 | ANTI-SIGNAL |
| trad_LiquiditySweepReclaim | 78,683 | 0.2104 | 0.2075 | 0.2132 | -0.011 | -3.18 | -0.174 | 9,480 | 69,203 | +0.056 | -0.205 | ANTI-SIGNAL |
| trad_CHoCHReversal | 38,393 | 0.2173 | 0.2132 | 0.2213 | -0.014 | -2.75 | -0.161 | 5,201 | 33,192 | +0.167 | -0.213 | ANTI-SIGNAL |
| trad_SupplyDemandSetup | 8,433 | 0.1666 | 0.1587 | 0.1744 | -0.020 | -1.83 | -0.264 | 679 | 7,754 | -0.354 | -0.256 | ANTI-SIGNAL |
| trad_CVDDivergence | 84,409 | 0.3019 | 0.2987 | 0.3049 | -0.055 | -15.99 | -0.008 | 32,597 | 51,812 | +0.065 | -0.054 | ANTI-SIGNAL |

**Key finding:** All 12 plugins with >= 30 outcomes are ANTI-SIGNAL. No plugin has hit_rate CI upper above 0.45 - the CI upper bounds peak at 0.30 (CVDDivergence). This is a corpus-level finding: the signal_ledger reflects pre-Phase-126 signals generated under broken gate conditions (Root Crimes 1-4). The clean replay (Phase 127) will regenerate signals through corrected code and produce a valid training corpus.

**Plugins with < 30 outcomes (excluded from statistical audit):**
trad_MeanReversion (10), trad_HVNRejection (6), trad_VWAPDeviation (23), trad_LiquidityHunt (13), trad_LVNBreakout (9), trad_SecondLegContinuation (9), trad_MTFAlignment (5), trad_OFIDivergence (5), trad_CandlestickPatternSetup (11), trad_POCRejection (23), and all other I7 plugins with zero corpus fires.

---

## Layer 2 - Detection Verifiability

Detection-condition verifiability audit for VALIDATED and NOISE CANDIDATE plugins. Since Layer 1 returned zero VALIDATED or NOISE CANDIDATE plugins (all 12 are ANTI-SIGNAL), Layer 2 produced no rows.

**Thresholds:**
- VERIFIABLE: >= 90% of sampled signals have required detection fields populated
- PARTIAL: 50-89%
- UNVERIFIABLE: < 50%

| Plugin | Samples | Fields Populated Rate | Verdict | Notes |
|--------|---------|----------------------|---------|-------|
| (none) | - | - | - | All Layer 1 qualifying plugins classified ANTI-SIGNAL; Layer 2 only audits VALIDATED/NOISE CANDIDATE survivors |

**Feature field mapping (defined for Layer 2, applicable when corpus improves post Phase 127):**

| Plugin | Detection Fields | Source Column |
|--------|-----------------|---------------|
| trad_DivergenceStack | rsi_div_bullish, rsi_div_bearish, macd_div_bullish, macd_div_bearish | pattern_detections |
| trad_GapAnalysisSetup | OHLCV arithmetic (open[-1] vs close[-2]) | N/A - MANUAL |
| trad_AnchoredVWAPReversion | session_vwap_deviation_sigma, session_vwap | technical_indicators |
| trad_CVDDivergence | cvd_divergence, cvd_slope_5bar | pattern_detections, technical_indicators |
| trad_LiquiditySweepReclaim | sweep_detected, sweep_reclaimed, sweep_type | smc |
| trad_PatternCompletion | dt_db_pattern, hs_pattern, tri_breakout_bias | pattern_detections |
| trad_OFIContinuation | ofi_ewma_20 | technical_indicators |
| trad_CHoCHReversal | choch_detected, choch_direction | smc |
| trad_FVGFill | fvg_type, fvg_top, fvg_bottom | smc |
| trad_SupplyDemandSetup | in_demand_zone, in_supply_zone, nearest_demand_high, nearest_demand_low | smc |
| trad_SqueezeExpansion | squeeze_fired, squeeze_active | pattern_detections |
| trad_TrendFollowing | trend_regime, trend_confidence | technical_indicators |

---

## Summary

**Layer 1 - IC League Table:**
- Plugins with >= 30 outcomes: **12**
- VALIDATED: **0**
- NOISE CANDIDATE: **0**
- ANTI-SIGNAL: **12**

**Layer 2 - Detection Verifiability:**
- Plugins audited: **0** (none eligible - all Layer 1 qualifiers were ANTI-SIGNAL)
- VERIFIABLE: 0
- PARTIAL: 0
- UNVERIFIABLE: 0

**Interpretation:** The 100% ANTI-SIGNAL result is expected and consistent with Phase 126 root crime diagnosis. The existing signal_ledger corpus was generated under:
1. Zone-too-narrow defect (Root Crime 1): 47.6% of signals stopped at entry
2. Missing I6 confluence annotation on 8 plugins (Root Crime 2)
3. FVGFill entry-timing defect (Root Crime 3): 86% of entries outside FVG zone
4. MeanReversion dual-gate conflict (Root Crime 4): 0.005% bar activation

Hit rates range from 0.09 to 0.30 (none approaching 0.45 floor) because the corpus is contaminated with mechanically broken signals. Statistical validation must be re-run on Phase 127 clean replay data.

---

## Dispositions Applied

### D-12: shadow_only=True added to 5 plugins (4 missing field, 1 formalizing existing comment)

Per D-12: plugins are never removed from TIER_I7. Every firing is training data. Anti-signal dispositions are shadow_only=True with documented rationale.

| Plugin | IC | hit_rate CI upper | Rationale | File |
|--------|----|--------------------|-----------|------|
| trad_CHoCHReversal | -0.014 | 0.221 | statistically anti-predictive (IC=-0.014, hit_rate CI upper=0.221, n=38393); redesign required | choch_reversal.py |
| trad_LiquiditySweepReclaim | -0.011 | 0.213 | statistically anti-predictive (IC=-0.011, hit_rate CI upper=0.213, n=78683); redesign required | liquidity_sweep_reclaim.py |
| trad_SupplyDemandSetup | -0.020 | 0.175 | statistically anti-predictive (IC=-0.020, hit_rate CI upper=0.175, n=8433); redesign required | supply_demand_setup.py |
| trad_TrendFollowing | +0.023 | 0.250 | hit_rate CI upper=0.250 below 0.45 floor (n=2393); redesign required | trend_following.py |
| trad_FVGFill | +0.001 | 0.126 | entry-timing defect (Wave 2) + IC=+0.001, hit_rate CI upper=0.126, n=37664; redesign required | fvg_fill.py |

### Already shadow_only=True (pre-existing, audit confirms disposition)

| Plugin | IC | hit_rate CI upper | Note |
|--------|----|--------------------|------|
| trad_SqueezeExpansion | +0.032 | 0.124 | shadow_only pre-existing; audit confirms |
| trad_PatternCompletion | +0.008 | 0.143 | shadow_only pre-existing; audit confirms |
| trad_AnchoredVWAPReversion | +0.004 | 0.093 | shadow_only pre-existing; audit confirms |
| trad_GapAnalysisSetup | -0.001 | 0.154 | shadow_only pre-existing; audit confirms |
| trad_OFIContinuation | -0.001 | 0.136 | shadow_only pre-existing; audit confirms |
| trad_DivergenceStack | -0.011 | 0.222 | shadow_only pre-existing; audit confirms |
| trad_CVDDivergence | -0.055 | 0.305 | shadow_only pre-existing; audit confirms |

**No plugins removed from TIER_I7** (D-12 enforced).

### Note on Wave 2 overlap

trad_FVGFill and trad_MeanReversion were already parked in Wave 2 (Phase 126-02) with entry-timing and dual-gate diagnoses respectively. The IC audit independently confirms trad_FVGFill's disposition (IC=+0.001, hit_rate CI upper=0.126). trad_MeanReversion has < 30 outcomes and is excluded from statistical audit.
