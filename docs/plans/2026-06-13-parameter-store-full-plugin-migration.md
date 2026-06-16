# Parameter Store Full Plugin Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every hard-coded detection threshold, confidence weight, and structural constant in I7 (and shared I1/utility) plugins into the Parameter Store so ML discovery can tune them without code deployments.

**Architecture:** Two injection patterns. (1) Shared module-level constants (`MIN_REGIME_WEIGHT`, `DIV_THRESHOLD`, zone geometry) get a module-level `_config_service` reference + getter functions — pipeline calls `set_config_service()` at startup, all callers in that module automatically get live values. (2) Plugin-specific thresholds get a `_config_service: Any = field(default=None, compare=False, repr=False)` dataclass field and read via `cfg.get_sync(key, default)` at the top of `compute_full()`. All new keys seeded with current hard-coded values — zero behavior change at rollout.

**Tech Stack:** Python 3.11, asyncpg, psycopg2, `ConfigService.get_sync()`, Migration SQL (psql), pytest.

---

## Parameter Key Reference

All keys follow `<namespace>.<concept>.<param>`. Seeds match current hard-coded values exactly.

### Tier A — Detection Gates (`threshold.*`, `feature.*`)

| Key | Type | Seed | Source constant |
|-----|------|------|-----------------|
| `threshold.global.min_regime_weight` | float | 0.30 | `MIN_REGIME_WEIGHT` in confidence_utils |
| `threshold.global.min_ctf_score` | float | 0.25 | `MIN_CTF_SCORE` in confidence_utils |
| `threshold.volume_profile.div_min` | float | 0.30 | `DIV_THRESHOLD` in volume_profile_utils |
| `threshold.volume_profile.stoch_oversold` | float | 30.0 | `STOCH_OVERSOLD` in volume_profile_utils |
| `threshold.volume_profile.stoch_overbought` | float | 70.0 | `STOCH_OVERBOUGHT` in volume_profile_utils |
| `threshold.hvn_rejection.proximity_atr` | float | 0.30 | `_HVN_PROXIMITY_ATR` |
| `threshold.poc_rejection.proximity_atr` | float | 0.30 | `_POC_PROXIMITY_ATR` |
| `threshold.session_extremes.proximity_atr` | float | 0.30 | `proximity_atr_mult` field |
| `threshold.session_extremes.rsi_oversold` | float | 35.0 | inline `35` in compute_full |
| `threshold.session_extremes.rsi_overbought` | float | 65.0 | inline `65` in compute_full |
| `threshold.liquidity_hunt.significance_min` | float | 0.60 | `MIN_SIGNIFICANCE` field |
| `threshold.gap_analysis.min_gap_atr` | float | 0.80 | `min_gap_atr_mult` field |
| `threshold.gap_analysis.continuation_atr` | float | 1.00 | `continuation_atr_mult` field |
| `threshold.gap_analysis.volume_confirm_ratio` | float | 1.50 | `volume_confirm_ratio` field |
| `threshold.mtf_alignment.ctf_score_min` | float | 0.70 | `ctf_score_threshold` field |
| `threshold.regime_transition.cp_min` | float | 0.50 | `cp_threshold` field |
| `threshold.dual_divergence.ofi_div_min` | float | 1.00 | `_OFI_DIV_THRESHOLD` |
| `threshold.dual_divergence.cvd_div_min` | float | 1.00 | `_CVD_DIV_THRESHOLD` |
| `threshold.orb.vol_expansion_mult` | float | 1.50 | `_VOL_EXPANSION_THRESHOLD` (shared ORB15/ORB30) |
| `threshold.vcp.min_contractions` | int | 3 | `_MIN_CONTRACTIONS` |
| `threshold.vcp.vol_expansion_mult` | float | 1.20 | `_VOL_EXPANSION_MULT` |
| `threshold.ofi_divergence.min_persistence_bars` | int | 2 | `_MIN_PERSISTENCE` |
| `threshold.aggregator.regime_tiebreak` | float | 0.40 | `_REGIME_TIEBREAK_THRESHOLD` |
| `feature.volume_zscore.window` | int | 20 | `_WINDOW` |

### Tier B — Confidence Weights (`weights.*`)

| Key | Type | Seed |
|-----|------|------|
| `weights.gap_analysis.geo` | float | 0.40 |
| `weights.gap_analysis.vol` | float | 0.25 |
| `weights.gap_analysis.timing` | float | 0.20 |
| `weights.gap_analysis.type` | float | 0.15 |
| `weights.mean_reversion.rsi_extreme` | float | 0.30 |
| `weights.mean_reversion.div_score` | float | 0.30 |
| `weights.mean_reversion.vol_stability` | float | 0.20 |
| `weights.mean_reversion.sr_proximity` | float | 0.20 |
| `weights.momentum_breakout.roc` | float | 0.40 |
| `weights.momentum_breakout.vol` | float | 0.35 |
| `weights.momentum_breakout.break_margin` | float | 0.25 |
| `weights.squeeze_expansion.squeeze_bars` | float | 0.35 |
| `weights.squeeze_expansion.vol_expansion` | float | 0.35 |
| `weights.squeeze_expansion.momentum` | float | 0.30 |
| `weights.vwap_reclaim.vol` | float | 0.30 |
| `weights.vwap_reclaim.duration` | float | 0.30 |
| `weights.vwap_reclaim.trend_align` | float | 0.20 |
| `weights.vwap_reclaim.sr_proximity` | float | 0.20 |
| `weights.liquidity_sweep.base_conf` | float | 0.40 |
| `weights.liquidity_sweep.depth_scale` | float | 0.20 |
| `weights.supply_demand.base_conf` | float | 0.35 |
| `weights.supply_demand.freshness_scale` | float | 0.23 |

### Tier C — Zone Engine Geometry (`feature.*`, `weights.*`)

| Key | Type | Seed |
|-----|------|------|
| `feature.zone_engine.cluster_radius_atr` | float | 0.50 |
| `feature.zone_engine.zone_buffer_atr` | float | 0.15 |
| `feature.zone_engine.min_width_atr` | float | 0.25 |
| `feature.zone_engine.single_level_radius_atr` | float | 0.25 |
| `weights.zone_engine.strength` | float | 0.60 |
| `weights.zone_engine.proximity` | float | 0.40 |

---

## Files Modified

| File | Change |
|------|--------|
| `production/migrations/129_plugin_param_store.sql` | Create — all 46 keys |
| `src/intelligence/trading/confidence_utils.py` | Add `set_config_service()`, `get_min_regime_weight()`, `get_min_ctf_score()` |
| `src/intelligence/trading/volume_profile_utils.py` | Add `set_config_service()`, `get_div_threshold()`, `get_stoch_oversold()`, `get_stoch_overbought()` |
| `src/intelligence/trading/zone_engine.py` | Add `set_config_service()`, replace 6 constants with getters |
| `src/intelligence/trading/aggregator.py` | Add `set_config_service()`, replace `_REGIME_TIEBREAK_THRESHOLD` with getter |
| 16 plugins importing `MIN_REGIME_WEIGHT`/`MIN_CTF_SCORE` | Call `get_min_*()` instead of constant |
| `src/intelligence/trading/hvn_rejection.py` | Add `_config_service`, read `proximity_atr` |
| `src/intelligence/trading/poc_rejection.py` | Add `_config_service`, read `proximity_atr` |
| `src/intelligence/trading/session_extremes_setup.py` | Add `_config_service`, read 3 thresholds |
| `src/intelligence/trading/liquidity_hunt.py` | Add `_config_service`, read `significance_min` |
| `src/intelligence/trading/gap_analysis_setup.py` | Add `_config_service`, read 3 gates + 4 weights |
| `src/intelligence/trading/mtf_alignment.py` | Add `_config_service`, read `ctf_score_min` |
| `src/intelligence/trading/regime_transition.py` | Add `_config_service`, read `cp_min` |
| `src/intelligence/trading/dual_divergence.py` | Add `_config_service`, read 2 div thresholds |
| `src/intelligence/trading/ofi_divergence.py` | Add `_config_service`, read `min_persistence_bars` |
| `src/intelligence/trading/orb15.py` | Add `_config_service`, read `vol_expansion_mult` |
| `src/intelligence/trading/orb30.py` | Add `_config_service`, read `vol_expansion_mult` |
| `src/intelligence/trading/vcp.py` | Add `_config_service`, read 2 thresholds |
| `src/intelligence/trading/volume_zscore.py` | Add `_config_service`, read `window` at compute time |
| `src/intelligence/trading/mean_reversion.py` | Add `_config_service`, read 4 weights |
| `src/intelligence/trading/momentum_breakout.py` | Add `_config_service`, read 3 weights |
| `src/intelligence/trading/squeeze_expansion.py` | Add `_config_service`, read 3 weights |
| `src/intelligence/trading/vwap_reclaim.py` | Add `_config_service`, read 4 weights |
| `src/intelligence/trading/liquidity_sweep_reclaim.py` | Add `_config_service`, read 2 weights |
| `src/intelligence/trading/supply_demand_setup.py` | Add `_config_service`, read 2 weights |
| `services/intelligence_pipeline.py` | Expand `_prewarm_threshold_config()` + `_THRESHOLD_KEYS` |
| `tests/unit/intelligence/test_param_store_migration.py` | Create — getter fallback + config-read tests |

---

## Task 1: Migration SQL — All 46 Keys

**Files:**
- Create: `production/migrations/129_plugin_param_store.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- Migration 129: Full plugin parameter store migration.
--
-- Seeds all hard-coded detection thresholds, confidence weights, and zone geometry
-- constants across I7 plugins + shared utilities into the parameter store.
-- All seed values match current hard-coded constants exactly (zero behaviour change at rollout).
-- All marked [initial_estimate] or [conventional] — none empirically validated.
-- ML discovery will replace them once n >= 100, p < 0.05 per instrument/regime cell.
--
-- Provenance: see docs/foundation/adaptive-parameter-registry.md#description-field.

-- ── schema entries ─────────────────────────────────────────────────────────────

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
-- Tier A: Global dual gate
('threshold.global.min_regime_weight', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Min HMM regime weight for the dual gate applied to all I7 plugins. '
 'Used by get_min_regime_weight() in confidence_utils. ML learning target.'),
('threshold.global.min_ctf_score', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] Min abs(ctf_score) for the dual gate applied to all I7 plugins. '
 'Used by get_min_ctf_score() in confidence_utils. ML learning target.'),

-- Tier A: Volume profile shared gates (used by hvn_rejection + poc_rejection)
('threshold.volume_profile.div_min', 'float', '0.30', 0.0, 1.0,
 '[conventional] Min RSI divergence confidence for reversal gate in check_reversal_gate(). '
 'Applies to both HVN and POC rejection. ML learning target per instrument.'),
('threshold.volume_profile.stoch_oversold', 'float', '30.0', 0.0, 50.0,
 '[conventional] Stochastic %K oversold threshold — momentum confirmation for long reversals. '
 'Textbook 30. ML learning target.'),
('threshold.volume_profile.stoch_overbought', 'float', '70.0', 50.0, 100.0,
 '[conventional] Stochastic %K overbought threshold — momentum confirmation for short reversals. '
 'Textbook 70. ML learning target.'),

-- Tier A: Plugin-specific detection gates
('threshold.hvn_rejection.proximity_atr', 'float', '0.30', 0.05, 2.0,
 '[initial_estimate] Max ATR-normalised distance from HVN for proximity gate. '
 'Instrument-specific calibration pending. ML learning target.'),
('threshold.poc_rejection.proximity_atr', 'float', '0.30', 0.05, 2.0,
 '[initial_estimate] Max ATR-normalised distance from POC for proximity gate. '
 'Instrument-specific calibration pending. ML learning target.'),
('threshold.session_extremes.proximity_atr', 'float', '0.30', 0.05, 2.0,
 '[initial_estimate] Max ATR-normalised distance from Asian session H/L. ML learning target.'),
('threshold.session_extremes.rsi_oversold', 'float', '35.0', 20.0, 50.0,
 '[conventional] RSI oversold threshold for long setups at session low. Textbook ~30-35. ML target.'),
('threshold.session_extremes.rsi_overbought', 'float', '65.0', 50.0, 80.0,
 '[conventional] RSI overbought threshold for short setups at session high. Textbook ~65-70. ML target.'),
('threshold.liquidity_hunt.significance_min', 'float', '0.60', 0.0, 1.0,
 '[initial_estimate] Min liquidity significance score for LiquidityHuntPlugin gate. ML target.'),
('threshold.gap_analysis.min_gap_atr', 'float', '0.80', 0.1, 5.0,
 '[initial_estimate] Min gap size in ATR multiples for GapAnalysisSetupPlugin. ML target.'),
('threshold.gap_analysis.continuation_atr', 'float', '1.00', 0.1, 5.0,
 '[initial_estimate] ATR threshold distinguishing continuation vs. reversal gaps. ML target.'),
('threshold.gap_analysis.volume_confirm_ratio', 'float', '1.50', 1.0, 5.0,
 '[initial_estimate] Min volume ratio for gap continuation confirmation. ML target.'),
('threshold.mtf_alignment.ctf_score_min', 'float', '0.70', 0.0, 1.0,
 '[initial_estimate] Min abs(ctf_score) for MTFAlignmentPlugin — stricter than global gate '
 '(0.25) because MTF setup demands strong cross-TF signal. ML target.'),
('threshold.regime_transition.cp_min', 'float', '0.50', 0.0, 1.0,
 '[conventional] Min changepoint probability for RegimeTransitionPlugin. ML target.'),
('threshold.dual_divergence.ofi_div_min', 'float', '1.00', 0.0, 5.0,
 '[initial_estimate] Min abs(ofi_divergence) for DualDivergencePlugin. ML target per instrument.'),
('threshold.dual_divergence.cvd_div_min', 'float', '1.00', 0.0, 5.0,
 '[initial_estimate] Min abs(cvd_divergence) for DualDivergencePlugin. ML target per instrument.'),
('threshold.orb.vol_expansion_mult', 'float', '1.50', 1.0, 5.0,
 '[initial_estimate] Volume expansion multiplier gate shared by ORB15Plugin and ORB30Plugin. ML target.'),
('threshold.vcp.min_contractions', 'int', '3', 2, 10,
 '[conventional] Minimum contraction bars before VCPPlugin expansion fire. Wyckoff convention. ML target.'),
('threshold.vcp.vol_expansion_mult', 'float', '1.20', 1.0, 3.0,
 '[initial_estimate] Volume expansion multiplier for VCPPlugin breakout bar. ML target.'),
('threshold.ofi_divergence.min_persistence_bars', 'int', '2', 1, 10,
 '[rca_analysis] Minimum consecutive bars of OFI/price divergence before OFIDivergencePlugin fires. '
 'Phase 118 starting guess. ML target.'),
('threshold.aggregator.regime_tiebreak', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] Min |trend_regime| to use regime direction in aggregator fallback tiebreak. ML target.'),

-- Tier A: Feature parameters
('feature.volume_zscore.window', 'int', '20', 5, 200,
 '[conventional] Rolling window for VolumeZscorePlugin z-score calculation. ML target.'),

-- Tier B: Confidence weights
('weights.gap_analysis.geo', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] Gap geometry score weight in GapAnalysisSetupPlugin raw_conf. ML learning target.'),
('weights.gap_analysis.vol', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] Volume score weight in GapAnalysisSetupPlugin raw_conf. ML learning target.'),
('weights.gap_analysis.timing', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] Session timing score weight in GapAnalysisSetupPlugin raw_conf. ML learning target.'),
('weights.gap_analysis.type', 'float', '0.15', 0.0, 1.0,
 '[initial_estimate] Gap type score weight in GapAnalysisSetupPlugin raw_conf. ML learning target.'),
('weights.mean_reversion.rsi_extreme', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] RSI extreme score weight in MeanReversionPlugin raw_conf. ML learning target.'),
('weights.mean_reversion.div_score', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Divergence score weight in MeanReversionPlugin raw_conf. ML learning target.'),
('weights.mean_reversion.vol_stability', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] Volatility stability weight in MeanReversionPlugin raw_conf. ML learning target.'),
('weights.mean_reversion.sr_proximity', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] S/R proximity weight in MeanReversionPlugin raw_conf. ML learning target.'),
('weights.momentum_breakout.roc', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] ROC score weight in MomentumBreakoutPlugin raw_conf. ML learning target.'),
('weights.momentum_breakout.vol', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Volume score weight in MomentumBreakoutPlugin raw_conf. ML learning target.'),
('weights.momentum_breakout.break_margin', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] Structure break margin weight in MomentumBreakoutPlugin. ML learning target.'),
('weights.squeeze_expansion.squeeze_bars', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Squeeze duration score weight in SqueezeExpansionPlugin. ML learning target.'),
('weights.squeeze_expansion.vol_expansion', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Volume expansion score weight in SqueezeExpansionPlugin. ML learning target.'),
('weights.squeeze_expansion.momentum', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Momentum clarity score weight in SqueezeExpansionPlugin. ML learning target.'),
('weights.vwap_reclaim.vol', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Volume score weight in VWAPReclaimPlugin raw_conf. ML learning target.'),
('weights.vwap_reclaim.duration', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Duration-below-VWAP score weight in VWAPReclaimPlugin. ML learning target.'),
('weights.vwap_reclaim.trend_align', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] Trend alignment weight in VWAPReclaimPlugin raw_conf. ML learning target.'),
('weights.vwap_reclaim.sr_proximity', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] S/R proximity weight in VWAPReclaimPlugin raw_conf. ML learning target.'),
('weights.liquidity_sweep.base_conf', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] Base confidence (floor) in LiquiditySweepReclaimPlugin. ML learning target.'),
('weights.liquidity_sweep.depth_scale', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] Sweep depth scale factor in LiquiditySweepReclaimPlugin. ML learning target.'),
('weights.supply_demand.base_conf', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Base confidence (floor) in SupplyDemandSetupPlugin. ML learning target.'),
('weights.supply_demand.freshness_scale', 'float', '0.23', 0.0, 1.0,
 '[initial_estimate] Zone freshness linear ramp scale in SupplyDemandSetupPlugin. ML learning target.'),

-- Tier C: Zone engine geometry
('feature.zone_engine.cluster_radius_atr', 'float', '0.50', 0.1, 3.0,
 '[initial_estimate] ATR-normalised radius for zone cluster formation in ZoneEngine. ML target.'),
('feature.zone_engine.zone_buffer_atr', 'float', '0.15', 0.01, 1.0,
 '[initial_estimate] ATR-normalised buffer added to zone bounds in ZoneEngine. ML target.'),
('feature.zone_engine.min_width_atr', 'float', '0.25', 0.01, 2.0,
 '[initial_estimate] Minimum zone width in ATR multiples for cluster zones. ML target.'),
('feature.zone_engine.single_level_radius_atr', 'float', '0.25', 0.01, 2.0,
 '[initial_estimate] ATR radius for single-level zone fallback in ZoneEngine. ML target.'),
('weights.zone_engine.strength', 'float', '0.60', 0.0, 1.0,
 '[initial_estimate] Level strength weight in single-level zone scoring. ML target.'),
('weights.zone_engine.proximity', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] Price proximity weight in single-level zone scoring. ML target.')
ON CONFLICT (config_key) DO NOTHING;

-- ── live state entries ──────────────────────────────────────────────────────────

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.global.min_regime_weight',          '0.30', 1),
('threshold.global.min_ctf_score',              '0.25', 1),
('threshold.volume_profile.div_min',            '0.30', 1),
('threshold.volume_profile.stoch_oversold',     '30.0', 1),
('threshold.volume_profile.stoch_overbought',   '70.0', 1),
('threshold.hvn_rejection.proximity_atr',       '0.30', 1),
('threshold.poc_rejection.proximity_atr',       '0.30', 1),
('threshold.session_extremes.proximity_atr',    '0.30', 1),
('threshold.session_extremes.rsi_oversold',     '35.0', 1),
('threshold.session_extremes.rsi_overbought',   '65.0', 1),
('threshold.liquidity_hunt.significance_min',   '0.60', 1),
('threshold.gap_analysis.min_gap_atr',          '0.80', 1),
('threshold.gap_analysis.continuation_atr',     '1.00', 1),
('threshold.gap_analysis.volume_confirm_ratio', '1.50', 1),
('threshold.mtf_alignment.ctf_score_min',       '0.70', 1),
('threshold.regime_transition.cp_min',          '0.50', 1),
('threshold.dual_divergence.ofi_div_min',       '1.00', 1),
('threshold.dual_divergence.cvd_div_min',       '1.00', 1),
('threshold.orb.vol_expansion_mult',            '1.50', 1),
('threshold.vcp.min_contractions',              '3',    1),
('threshold.vcp.vol_expansion_mult',            '1.20', 1),
('threshold.ofi_divergence.min_persistence_bars','2',   1),
('threshold.aggregator.regime_tiebreak',        '0.40', 1),
('feature.volume_zscore.window',                '20',   1),
('weights.gap_analysis.geo',                    '0.40', 1),
('weights.gap_analysis.vol',                    '0.25', 1),
('weights.gap_analysis.timing',                 '0.20', 1),
('weights.gap_analysis.type',                   '0.15', 1),
('weights.mean_reversion.rsi_extreme',          '0.30', 1),
('weights.mean_reversion.div_score',            '0.30', 1),
('weights.mean_reversion.vol_stability',        '0.20', 1),
('weights.mean_reversion.sr_proximity',         '0.20', 1),
('weights.momentum_breakout.roc',               '0.40', 1),
('weights.momentum_breakout.vol',               '0.35', 1),
('weights.momentum_breakout.break_margin',      '0.25', 1),
('weights.squeeze_expansion.squeeze_bars',      '0.35', 1),
('weights.squeeze_expansion.vol_expansion',     '0.35', 1),
('weights.squeeze_expansion.momentum',          '0.30', 1),
('weights.vwap_reclaim.vol',                    '0.30', 1),
('weights.vwap_reclaim.duration',               '0.30', 1),
('weights.vwap_reclaim.trend_align',            '0.20', 1),
('weights.vwap_reclaim.sr_proximity',           '0.20', 1),
('weights.liquidity_sweep.base_conf',           '0.40', 1),
('weights.liquidity_sweep.depth_scale',         '0.20', 1),
('weights.supply_demand.base_conf',             '0.35', 1),
('weights.supply_demand.freshness_scale',       '0.23', 1),
('feature.zone_engine.cluster_radius_atr',      '0.50', 1),
('feature.zone_engine.zone_buffer_atr',         '0.15', 1),
('feature.zone_engine.min_width_atr',           '0.25', 1),
('feature.zone_engine.single_level_radius_atr', '0.25', 1),
('weights.zone_engine.strength',                '0.60', 1),
('weights.zone_engine.proximity',               '0.40', 1)
ON CONFLICT (config_key) DO NOTHING;

-- ── seed config_history ─────────────────────────────────────────────────────────

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'threshold.global.min_regime_weight',           1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.global.min_ctf_score',               1, '0.25', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.volume_profile.div_min',             1, '0.30', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.volume_profile.stoch_oversold',      1, '30.0', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.volume_profile.stoch_overbought',    1, '70.0', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.hvn_rejection.proximity_atr',        1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.poc_rejection.proximity_atr',        1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.session_extremes.proximity_atr',     1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.session_extremes.rsi_oversold',      1, '35.0', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.session_extremes.rsi_overbought',    1, '65.0', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.liquidity_hunt.significance_min',    1, '0.60', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.gap_analysis.min_gap_atr',           1, '0.80', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.gap_analysis.continuation_atr',      1, '1.00', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.gap_analysis.volume_confirm_ratio',  1, '1.50', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.mtf_alignment.ctf_score_min',        1, '0.70', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.regime_transition.cp_min',           1, '0.50', 'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.dual_divergence.ofi_div_min',        1, '1.00', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.dual_divergence.cvd_div_min',        1, '1.00', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.orb.vol_expansion_mult',             1, '1.50', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.vcp.min_contractions',               1, '3',    'conventional',     'Migration 129 seed'),
(NOW(), 'threshold.vcp.vol_expansion_mult',             1, '1.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'threshold.ofi_divergence.min_persistence_bars',1, '2',    'rca_analysis',     'Migration 129 seed'),
(NOW(), 'threshold.aggregator.regime_tiebreak',         1, '0.40', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'feature.volume_zscore.window',                 1, '20',   'conventional',     'Migration 129 seed'),
(NOW(), 'weights.gap_analysis.geo',                     1, '0.40', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.gap_analysis.vol',                     1, '0.25', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.gap_analysis.timing',                  1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.gap_analysis.type',                    1, '0.15', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.mean_reversion.rsi_extreme',           1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.mean_reversion.div_score',             1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.mean_reversion.vol_stability',         1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.mean_reversion.sr_proximity',          1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.momentum_breakout.roc',                1, '0.40', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.momentum_breakout.vol',                1, '0.35', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.momentum_breakout.break_margin',       1, '0.25', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.squeeze_expansion.squeeze_bars',       1, '0.35', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.squeeze_expansion.vol_expansion',      1, '0.35', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.squeeze_expansion.momentum',           1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.vwap_reclaim.vol',                     1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.vwap_reclaim.duration',                1, '0.30', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.vwap_reclaim.trend_align',             1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.vwap_reclaim.sr_proximity',            1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.liquidity_sweep.base_conf',            1, '0.40', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.liquidity_sweep.depth_scale',          1, '0.20', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.supply_demand.base_conf',              1, '0.35', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.supply_demand.freshness_scale',        1, '0.23', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'feature.zone_engine.cluster_radius_atr',       1, '0.50', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'feature.zone_engine.zone_buffer_atr',          1, '0.15', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'feature.zone_engine.min_width_atr',            1, '0.25', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'feature.zone_engine.single_level_radius_atr',  1, '0.25', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.zone_engine.strength',                 1, '0.60', 'initial_estimate', 'Migration 129 seed'),
(NOW(), 'weights.zone_engine.proximity',                1, '0.40', 'initial_estimate', 'Migration 129 seed');
```

- [ ] **Step 2: Apply the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f production/migrations/129_plugin_param_store.sql
```

Expected: `INSERT 0 52` (or similar — ON CONFLICT DO NOTHING means re-runs are safe).

- [ ] **Step 3: Verify keys are in DB**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'threshold.global%' OR config_key LIKE 'weights.zone_engine%' ORDER BY config_key;"
```

Expected: 8 rows including `threshold.global.min_regime_weight = 0.30` and `weights.zone_engine.strength = 0.60`.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/129_plugin_param_store.sql
git commit -m "feat(param-store): migration 129 — 46 plugin threshold/weight/geometry keys"
```

---

## Task 2: Module-Level Config Pattern — confidence_utils + volume_profile_utils

**Files:**
- Modify: `src/intelligence/trading/confidence_utils.py`
- Modify: `src/intelligence/trading/volume_profile_utils.py`
- Test: `tests/unit/intelligence/test_param_store_migration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/intelligence/test_param_store_migration.py`:

```python
"""Tests for module-level config getter functions in confidence_utils and volume_profile_utils."""
from __future__ import annotations

from unittest.mock import MagicMock

import src.intelligence.trading.confidence_utils as cu
import src.intelligence.trading.volume_profile_utils as vpu


def _make_cfg(return_val):
    cfg = MagicMock()
    cfg.get_sync.return_value = return_val
    return cfg


def teardown_function():
    """Reset module-level config service after each test."""
    cu.set_config_service(None)
    vpu.set_config_service(None)


def test_get_min_regime_weight_returns_config_value():
    cu.set_config_service(_make_cfg(0.45))
    assert cu.get_min_regime_weight() == 0.45


def test_get_min_regime_weight_returns_constant_when_no_config():
    assert cu.get_min_regime_weight() == cu.MIN_REGIME_WEIGHT


def test_get_min_ctf_score_returns_config_value():
    cu.set_config_service(_make_cfg(0.30))
    assert cu.get_min_ctf_score() == 0.30


def test_get_min_ctf_score_returns_constant_when_no_config():
    assert cu.get_min_ctf_score() == cu.MIN_CTF_SCORE


def test_get_div_threshold_returns_config_value():
    vpu.set_config_service(_make_cfg(0.4))
    assert vpu.get_div_threshold() == 0.4


def test_get_div_threshold_returns_constant_when_no_config():
    assert vpu.get_div_threshold() == vpu.DIV_THRESHOLD


def test_get_stoch_oversold_returns_config_value():
    vpu.set_config_service(_make_cfg(25.0))
    assert vpu.get_stoch_oversold() == 25.0


def test_get_stoch_overbought_returns_config_value():
    vpu.set_config_service(_make_cfg(75.0))
    assert vpu.get_stoch_overbought() == 75.0
```

- [ ] **Step 2: Run tests — expect failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py -v
```

Expected: `AttributeError: module ... has no attribute 'set_config_service'`

- [ ] **Step 3: Add getter functions to confidence_utils.py**

After the `MIN_CTF_SCORE` line (currently line ~38) in `src/intelligence/trading/confidence_utils.py`, add:

```python
_config_service: Any | None = None


def set_config_service(cfg: Any) -> None:
    """Inject ConfigService at pipeline startup. Called by intelligence_pipeline._prewarm()."""
    global _config_service
    _config_service = cfg


def get_min_regime_weight() -> float:
    """Return live threshold.global.min_regime_weight from config, or module constant fallback."""
    if _config_service is not None:
        return _config_service.get_sync("threshold.global.min_regime_weight", MIN_REGIME_WEIGHT)
    return MIN_REGIME_WEIGHT


def get_min_ctf_score() -> float:
    """Return live threshold.global.min_ctf_score from config, or module constant fallback."""
    if _config_service is not None:
        return _config_service.get_sync("threshold.global.min_ctf_score", MIN_CTF_SCORE)
    return MIN_CTF_SCORE
```

Also add `Any` to the imports at the top if not already present:
```python
from typing import Any
```

- [ ] **Step 4: Add getter functions to volume_profile_utils.py**

After the `STOCH_OVERBOUGHT` line (currently line ~18) in `src/intelligence/trading/volume_profile_utils.py`, add:

```python
from typing import Any

_config_service: Any | None = None


def set_config_service(cfg: Any) -> None:
    """Inject ConfigService at pipeline startup."""
    global _config_service
    _config_service = cfg


def get_div_threshold() -> float:
    """Return live threshold.volume_profile.div_min from config, or DIV_THRESHOLD constant."""
    if _config_service is not None:
        return _config_service.get_sync("threshold.volume_profile.div_min", DIV_THRESHOLD)
    return DIV_THRESHOLD


def get_stoch_oversold() -> float:
    """Return live threshold.volume_profile.stoch_oversold from config, or constant."""
    if _config_service is not None:
        return _config_service.get_sync("threshold.volume_profile.stoch_oversold", STOCH_OVERSOLD)
    return STOCH_OVERSOLD


def get_stoch_overbought() -> float:
    """Return live threshold.volume_profile.stoch_overbought from config, or constant."""
    if _config_service is not None:
        return _config_service.get_sync("threshold.volume_profile.stoch_overbought", STOCH_OVERBOUGHT)
    return STOCH_OVERBOUGHT
```

- [ ] **Step 5: Run tests — expect pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py -v
```

Expected: 8 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/trading/confidence_utils.py \
        src/intelligence/trading/volume_profile_utils.py \
        tests/unit/intelligence/test_param_store_migration.py
git commit -m "feat(param-store): add module-level config getters to confidence_utils + volume_profile_utils"
```

---

## Task 3: Update 16 Plugins — Replace Imported Constants with Getter Calls

**Files to modify** (all import `MIN_REGIME_WEIGHT` / `MIN_CTF_SCORE` from confidence_utils):

- `src/intelligence/trading/candlestick_pattern_setup.py`
- `src/intelligence/trading/delta_exhaustion.py`
- `src/intelligence/trading/dual_divergence.py`
- `src/intelligence/trading/failed_breakout.py`
- `src/intelligence/trading/liquidity_hunt.py`
- `src/intelligence/trading/lvn_breakout.py`
- `src/intelligence/trading/microstructure_utils.py`
- `src/intelligence/trading/momentum_breakout.py`
- `src/intelligence/trading/ofi_divergence.py`
- `src/intelligence/trading/orb15.py`
- `src/intelligence/trading/orb30.py`
- `src/intelligence/trading/second_leg_continuation.py`
- `src/intelligence/trading/session_extremes_setup.py`
- `src/intelligence/trading/vcp.py`
- `src/intelligence/trading/vwap_deviation.py`
- `src/intelligence/trading/vwap_reclaim.py`

- [ ] **Step 1: Update imports and call sites in all 16 files**

For every file listed above:

**Change the import line** from:
```python
from .confidence_utils import (
    ...,
    MIN_CTF_SCORE,
    MIN_REGIME_WEIGHT,
    ...
)
```
to:
```python
from .confidence_utils import (
    ...,
    get_min_ctf_score,
    get_min_regime_weight,
    ...
)
```

**Change every usage** — replace constant references with function calls:
- `MIN_REGIME_WEIGHT` → `get_min_regime_weight()`
- `MIN_CTF_SCORE` → `get_min_ctf_score()`

Example: in `delta_exhaustion.py` lines 93, 98, 139, 143:
```python
# Before
if hmm_regime_weight(features, "ranging") < MIN_REGIME_WEIGHT:
    return no_signal()
if abs(ctf_score) < MIN_CTF_SCORE:
    return no_signal()
regime_factor = (hmm_regime_weight(features, "ranging") - MIN_REGIME_WEIGHT) / (1.0 - MIN_REGIME_WEIGHT)
ctf_score_factor = clamp01((abs(ctf_score) - MIN_CTF_SCORE) / (1.0 - MIN_CTF_SCORE))

# After
if hmm_regime_weight(features, "ranging") < get_min_regime_weight():
    return no_signal()
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()
regime_factor = (hmm_regime_weight(features, "ranging") - get_min_regime_weight()) / (1.0 - get_min_regime_weight())
ctf_score_factor = clamp01((abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score()))
```

Use grep to find all call sites:
```bash
grep -rn "MIN_REGIME_WEIGHT\|MIN_CTF_SCORE" src/intelligence/trading/ --include="*.py" | grep -v "confidence_utils"
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

Expected: all pass. If any test imports `MIN_REGIME_WEIGHT` directly, update those imports too.

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/trading/
git commit -m "feat(param-store): replace MIN_REGIME_WEIGHT/MIN_CTF_SCORE with config-backed getters in 16 plugins"
```

---

## Task 4: Update check_reversal_gate Callers — DIV_THRESHOLD + STOCH Constants

**Files:**
- Modify: `src/intelligence/trading/volume_profile_utils.py` (the `check_reversal_gate` function itself)
- Modify: `src/intelligence/trading/hvn_rejection.py`
- Modify: `src/intelligence/trading/poc_rejection.py`

The strategy: update `check_reversal_gate()` and all direct usages of `DIV_THRESHOLD`, `STOCH_OVERSOLD`, `STOCH_OVERBOUGHT` to call the getters added in Task 2.

- [ ] **Step 1: Update volume_profile_utils.py — check_reversal_gate body**

Replace the constant references inside `check_reversal_gate()`:
```python
# Before (inside function body)
rsi_div_ok = rsi_div_bullish > DIV_THRESHOLD
stoch_ok = stoch_k < STOCH_OVERSOLD
...
rsi_div_ok = rsi_div_bearish > DIV_THRESHOLD
stoch_ok = stoch_k > STOCH_OVERBOUGHT

# After
rsi_div_ok = rsi_div_bullish > get_div_threshold()
stoch_ok = stoch_k < get_stoch_oversold()
...
rsi_div_ok = rsi_div_bearish > get_div_threshold()
stoch_ok = stoch_k > get_stoch_overbought()
```

- [ ] **Step 2: Update hvn_rejection.py**

Change import from:
```python
from .volume_profile_utils import DIV_THRESHOLD, ...
```
to:
```python
from .volume_profile_utils import get_div_threshold, get_stoch_overbought, get_stoch_oversold, ...
```

Replace all direct uses of `DIV_THRESHOLD`, `STOCH_OVERSOLD`, `STOCH_OVERBOUGHT` in `hvn_rejection.py` with `get_div_threshold()`, `get_stoch_oversold()`, `get_stoch_overbought()`.

Also add `_config_service` field and read `proximity_atr` from config:

Add to `HVNRejectionPlugin` dataclass:
```python
_config_service: Any = field(default=None, compare=False, repr=False)
```

At the top of `compute_full()`, before any feature reads:
```python
cfg = self._config_service
proximity_atr = (
    cfg.get_sync("threshold.hvn_rejection.proximity_atr", _HVN_PROXIMITY_ATR)
    if cfg else _HVN_PROXIMITY_ATR
)
```

Replace all uses of `_HVN_PROXIMITY_ATR` in the method body with `proximity_atr`.

- [ ] **Step 3: Update poc_rejection.py** (identical pattern)

Add `_config_service` field, read `threshold.poc_rejection.proximity_atr`. Replace `DIV_THRESHOLD`, `STOCH_*` with getter calls. Replace `_POC_PROXIMITY_ATR` with local `proximity_atr` variable.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/volume_profile_utils.py \
        src/intelligence/trading/hvn_rejection.py \
        src/intelligence/trading/poc_rejection.py
git commit -m "feat(param-store): wire threshold.hvn_rejection + poc_rejection + volume_profile getters"
```

---

## Task 5: Session Extremes, Liquidity Hunt, MTF Alignment

**Files:**
- Modify: `src/intelligence/trading/session_extremes_setup.py`
- Modify: `src/intelligence/trading/liquidity_hunt.py`
- Modify: `src/intelligence/trading/mtf_alignment.py`

- [ ] **Step 1: session_extremes_setup.py**

Add `_config_service` field to `SessionExtremesSetupPlugin`:
```python
_config_service: Any = field(default=None, compare=False, repr=False)
```

At top of `compute_full()` (after features dict assembly, before gates):
```python
cfg = self._config_service
proximity_atr = (
    cfg.get_sync("threshold.session_extremes.proximity_atr", self.proximity_atr_mult)
    if cfg else self.proximity_atr_mult
)
rsi_oversold = (
    cfg.get_sync("threshold.session_extremes.rsi_oversold", 35.0)
    if cfg else 35.0
)
rsi_overbought = (
    cfg.get_sync("threshold.session_extremes.rsi_overbought", 65.0)
    if cfg else 65.0
)
```

Replace `self.proximity_atr_mult` usage in distance gate with `proximity_atr`.
Replace the inline `35` and `65` in the RSI gate:
```python
# Before
(direction == -1 and rsi > 65) or (direction == 1 and rsi < 35)

# After
(direction == -1 and rsi > rsi_overbought) or (direction == 1 and rsi < rsi_oversold)
```

- [ ] **Step 2: liquidity_hunt.py**

Add `_config_service` field. Change `MIN_SIGNIFICANCE` from a class variable to reading from config at compute time:
```python
_config_service: Any = field(default=None, compare=False, repr=False)
```

At top of `compute_full()`:
```python
cfg = self._config_service
significance_min = (
    cfg.get_sync("threshold.liquidity_hunt.significance_min", self.MIN_SIGNIFICANCE)
    if cfg else self.MIN_SIGNIFICANCE
)
```

Replace `self.MIN_SIGNIFICANCE` in the gate check and confidence ramp:
```python
# Before
if significance < self.MIN_SIGNIFICANCE:
    return no_signal()
...
(significance - self.MIN_SIGNIFICANCE) / (1.0 - self.MIN_SIGNIFICANCE)

# After
if significance < significance_min:
    return no_signal()
...
(significance - significance_min) / (1.0 - significance_min)
```

- [ ] **Step 3: mtf_alignment.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
ctf_score_min = (
    cfg.get_sync("threshold.mtf_alignment.ctf_score_min", self.ctf_score_threshold)
    if cfg else self.ctf_score_threshold
)
```

Replace `abs(ctf_score) > self.ctf_score_threshold` with `abs(ctf_score) > ctf_score_min`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/session_extremes_setup.py \
        src/intelligence/trading/liquidity_hunt.py \
        src/intelligence/trading/mtf_alignment.py
git commit -m "feat(param-store): wire threshold.session_extremes + liquidity_hunt + mtf_alignment"
```

---

## Task 6: Gap Analysis, Regime Transition

**Files:**
- Modify: `src/intelligence/trading/gap_analysis_setup.py`
- Modify: `src/intelligence/trading/regime_transition.py`

- [ ] **Step 1: gap_analysis_setup.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
min_gap_atr = (
    cfg.get_sync("threshold.gap_analysis.min_gap_atr", self.min_gap_atr_mult)
    if cfg else self.min_gap_atr_mult
)
continuation_atr = (
    cfg.get_sync("threshold.gap_analysis.continuation_atr", self.continuation_atr_mult)
    if cfg else self.continuation_atr_mult
)
volume_confirm_ratio = (
    cfg.get_sync("threshold.gap_analysis.volume_confirm_ratio", self.volume_confirm_ratio)
    if cfg else self.volume_confirm_ratio
)
w_geo = cfg.get_sync("weights.gap_analysis.geo", 0.40) if cfg else 0.40
w_vol = cfg.get_sync("weights.gap_analysis.vol", 0.25) if cfg else 0.25
w_timing = cfg.get_sync("weights.gap_analysis.timing", 0.20) if cfg else 0.20
w_type = cfg.get_sync("weights.gap_analysis.type", 0.15) if cfg else 0.15
```

Replace:
- `self.min_gap_atr_mult` → `min_gap_atr`
- `self.continuation_atr_mult` → `continuation_atr`
- `self.volume_confirm_ratio` → `volume_confirm_ratio`
- `raw_conf = 0.40 * geo_score + 0.25 * vol_score + 0.20 * timing_score + 0.15 * type_score` →
  `raw_conf = w_geo * geo_score + w_vol * vol_score + w_timing * timing_score + w_type * type_score`

- [ ] **Step 2: regime_transition.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
cp_min = (
    cfg.get_sync("threshold.regime_transition.cp_min", self.cp_threshold)
    if cfg else self.cp_threshold
)
```

Replace `self.cp_threshold` in gate: `if cp_probability <= cp_min or choch_detected != 1.0:`

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 4: Commit**

```bash
git add src/intelligence/trading/gap_analysis_setup.py \
        src/intelligence/trading/regime_transition.py
git commit -m "feat(param-store): wire threshold+weights.gap_analysis + threshold.regime_transition"
```

---

## Task 7: Dual Divergence, OFI Divergence, ORB15, ORB30

**Files:**
- Modify: `src/intelligence/trading/dual_divergence.py`
- Modify: `src/intelligence/trading/ofi_divergence.py`
- Modify: `src/intelligence/trading/orb15.py`
- Modify: `src/intelligence/trading/orb30.py`

- [ ] **Step 1: dual_divergence.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
ofi_div_min = (
    cfg.get_sync("threshold.dual_divergence.ofi_div_min", _OFI_DIV_THRESHOLD)
    if cfg else _OFI_DIV_THRESHOLD
)
cvd_div_min = (
    cfg.get_sync("threshold.dual_divergence.cvd_div_min", _CVD_DIV_THRESHOLD)
    if cfg else _CVD_DIV_THRESHOLD
)
```

Replace `abs(ofi_div) >= _OFI_DIV_THRESHOLD` → `abs(ofi_div) >= ofi_div_min` and `abs(cvd_div) >= _CVD_DIV_THRESHOLD` → `abs(cvd_div) >= cvd_div_min`.

- [ ] **Step 2: ofi_divergence.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
min_persistence = (
    cfg.get_sync("threshold.ofi_divergence.min_persistence_bars", _MIN_PERSISTENCE)
    if cfg else _MIN_PERSISTENCE
)
```

Replace `_MIN_PERSISTENCE` references in the persistence gate with `min_persistence`.

- [ ] **Step 3: orb15.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
vol_expansion_threshold = (
    cfg.get_sync("threshold.orb.vol_expansion_mult", _VOL_EXPANSION_THRESHOLD)
    if cfg else _VOL_EXPANSION_THRESHOLD
)
```

Replace `_VOL_EXPANSION_THRESHOLD` with `vol_expansion_threshold` in the gate check.

- [ ] **Step 4: orb30.py** (identical to orb15 step)

Same pattern as orb15: `threshold.orb.vol_expansion_mult` (same key — both ORB variants share one parameter).

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/trading/dual_divergence.py \
        src/intelligence/trading/ofi_divergence.py \
        src/intelligence/trading/orb15.py \
        src/intelligence/trading/orb30.py
git commit -m "feat(param-store): wire threshold.dual_divergence + ofi_divergence + orb"
```

---

## Task 8: VCP, Volume Z-Score, Aggregator

**Files:**
- Modify: `src/intelligence/trading/vcp.py`
- Modify: `src/intelligence/trading/volume_zscore.py`
- Modify: `src/intelligence/trading/aggregator.py`

- [ ] **Step 1: vcp.py**

Add `_config_service` field. At top of `compute_full()`:
```python
cfg = self._config_service
min_contractions = (
    cfg.get_sync("threshold.vcp.min_contractions", _MIN_CONTRACTIONS)
    if cfg else _MIN_CONTRACTIONS
)
vol_expansion_mult = (
    cfg.get_sync("threshold.vcp.vol_expansion_mult", _VOL_EXPANSION_MULT)
    if cfg else _VOL_EXPANSION_MULT
)
```

Replace `_MIN_CONTRACTIONS` and `_VOL_EXPANSION_MULT` with the local variables.

- [ ] **Step 2: volume_zscore.py**

Add `_config_service` field. The `_WINDOW` constant is used in `min_lookback = _WINDOW + 1` at class definition time (static). Keep that static. Add dynamic window at compute time:

Add field:
```python
_config_service: Any = field(default=None, compare=False, repr=False)
```

At top of `_compute_full_core()` and `_compute_next_core()`:
```python
cfg = self._config_service
window = cfg.get_sync("feature.volume_zscore.window", _WINDOW) if cfg else _WINDOW
```

Replace `_WINDOW` usage inside the computation methods with `window`. (Leave `min_lookback: int = _WINDOW + 1` unchanged — it's a data requirement guard, not the active window.)

- [ ] **Step 3: aggregator.py — module-level config pattern**

`aggregator.py` exports standalone functions, not a plugin class. Use module-level pattern.

Add after `_REGIME_TIEBREAK_THRESHOLD` definition:
```python
from typing import Any as _Any

_config_service: _Any | None = None


def set_config_service(cfg: _Any) -> None:
    """Inject ConfigService at pipeline startup."""
    global _config_service
    _config_service = cfg


def _get_regime_tiebreak() -> float:
    if _config_service is not None:
        return _config_service.get_sync(
            "threshold.aggregator.regime_tiebreak", _REGIME_TIEBREAK_THRESHOLD
        )
    return _REGIME_TIEBREAK_THRESHOLD
```

Replace `_REGIME_TIEBREAK_THRESHOLD` in the `_winner_by_regime_tiebreak()` / fallback functions with `_get_regime_tiebreak()`.

- [ ] **Step 4: Add tests for aggregator getter to test_param_store_migration.py**

Append to `tests/unit/intelligence/test_param_store_migration.py`:

```python
import src.intelligence.trading.aggregator as agg


def teardown_function():
    cu.set_config_service(None)
    vpu.set_config_service(None)
    agg.set_config_service(None)


def test_get_regime_tiebreak_returns_config_value():
    agg.set_config_service(_make_cfg(0.55))
    assert agg._get_regime_tiebreak() == 0.55


def test_get_regime_tiebreak_returns_constant_when_no_config():
    assert agg._get_regime_tiebreak() == agg._REGIME_TIEBREAK_THRESHOLD
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py tests/unit/intelligence/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/trading/vcp.py \
        src/intelligence/trading/volume_zscore.py \
        src/intelligence/trading/aggregator.py \
        tests/unit/intelligence/test_param_store_migration.py
git commit -m "feat(param-store): wire threshold.vcp + feature.volume_zscore + threshold.aggregator"
```

---

## Task 9: Confidence Weights — Mean Reversion, Momentum Breakout, Squeeze Expansion

**Files:**
- Modify: `src/intelligence/trading/mean_reversion.py`
- Modify: `src/intelligence/trading/momentum_breakout.py`
- Modify: `src/intelligence/trading/squeeze_expansion.py`

- [ ] **Step 1: mean_reversion.py**

Add `_config_service` field. At top of `compute_full()` weight reads:
```python
cfg = self._config_service
w_rsi = cfg.get_sync("weights.mean_reversion.rsi_extreme", 0.30) if cfg else 0.30
w_div = cfg.get_sync("weights.mean_reversion.div_score",   0.30) if cfg else 0.30
w_vol = cfg.get_sync("weights.mean_reversion.vol_stability",0.20) if cfg else 0.20
w_sr  = cfg.get_sync("weights.mean_reversion.sr_proximity", 0.20) if cfg else 0.20
```

Replace:
```python
# Before
raw_conf = 0.3 * rsi_extreme + 0.3 * div_score + 0.2 * vol_stability + 0.2 * sr_prox

# After
raw_conf = w_rsi * rsi_extreme + w_div * div_score + w_vol * vol_stability + w_sr * sr_prox
```

- [ ] **Step 2: momentum_breakout.py**

Add `_config_service` field. Read weights and replace `raw_conf`:
```python
cfg = self._config_service
w_roc    = cfg.get_sync("weights.momentum_breakout.roc",          0.40) if cfg else 0.40
w_vol    = cfg.get_sync("weights.momentum_breakout.vol",          0.35) if cfg else 0.35
w_margin = cfg.get_sync("weights.momentum_breakout.break_margin", 0.25) if cfg else 0.25
```

```python
# Before
raw_conf = 0.40 * roc_score + 0.35 * vol_score + 0.25 * break_margin

# After
raw_conf = w_roc * roc_score + w_vol * vol_score + w_margin * break_margin
```

- [ ] **Step 3: squeeze_expansion.py**

Add `_config_service` field. Read weights and replace `raw_conf`:
```python
cfg = self._config_service
w_sq  = cfg.get_sync("weights.squeeze_expansion.squeeze_bars",  0.35) if cfg else 0.35
w_vol = cfg.get_sync("weights.squeeze_expansion.vol_expansion", 0.35) if cfg else 0.35
w_mom = cfg.get_sync("weights.squeeze_expansion.momentum",      0.30) if cfg else 0.30
```

```python
# Before
raw_conf = 0.35 * squeeze_bars_score + 0.35 * vol_expansion_score + 0.30 * momentum_score

# After
raw_conf = w_sq * squeeze_bars_score + w_vol * vol_expansion_score + w_mom * momentum_score
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/mean_reversion.py \
        src/intelligence/trading/momentum_breakout.py \
        src/intelligence/trading/squeeze_expansion.py
git commit -m "feat(param-store): wire weights.mean_reversion + momentum_breakout + squeeze_expansion"
```

---

## Task 10: Confidence Weights — VWAP Reclaim, Liquidity Sweep, Supply Demand

**Files:**
- Modify: `src/intelligence/trading/vwap_reclaim.py`
- Modify: `src/intelligence/trading/liquidity_sweep_reclaim.py`
- Modify: `src/intelligence/trading/supply_demand_setup.py`

- [ ] **Step 1: vwap_reclaim.py**

Add `_config_service` field. Read weights:
```python
cfg = self._config_service
w_vol      = cfg.get_sync("weights.vwap_reclaim.vol",         0.30) if cfg else 0.30
w_duration = cfg.get_sync("weights.vwap_reclaim.duration",    0.30) if cfg else 0.30
w_trend    = cfg.get_sync("weights.vwap_reclaim.trend_align", 0.20) if cfg else 0.20
w_sr       = cfg.get_sync("weights.vwap_reclaim.sr_proximity",0.20) if cfg else 0.20
```

Replace:
```python
# Before
raw_conf = 0.30 * vol_score + 0.30 * duration_score + 0.20 * trend_align + 0.20 * sr_prox

# After
raw_conf = w_vol * vol_score + w_duration * duration_score + w_trend * trend_align + w_sr * sr_prox
```

- [ ] **Step 2: liquidity_sweep_reclaim.py**

Add `_config_service` field. Read weights:
```python
cfg = self._config_service
base_conf   = cfg.get_sync("weights.liquidity_sweep.base_conf",   0.40) if cfg else 0.40
depth_scale = cfg.get_sync("weights.liquidity_sweep.depth_scale", 0.20) if cfg else 0.20
```

Replace:
```python
# Before
confidence = 0.40 + 0.20 * linear_ramp(sweep_depth_atr, 0.0, 2.0)

# After
confidence = base_conf + depth_scale * linear_ramp(sweep_depth_atr, 0.0, 2.0)
```

- [ ] **Step 3: supply_demand_setup.py**

Add `_config_service` field. Read weights:
```python
cfg = self._config_service
base_conf       = cfg.get_sync("weights.supply_demand.base_conf",       0.35) if cfg else 0.35
freshness_scale = cfg.get_sync("weights.supply_demand.freshness_scale", 0.23) if cfg else 0.23
```

Replace:
```python
# Before
confidence = 0.35 + 0.23 * linear_ramp(freshness, 0.40, 1.0)

# After
confidence = base_conf + freshness_scale * linear_ramp(freshness, 0.40, 1.0)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/vwap_reclaim.py \
        src/intelligence/trading/liquidity_sweep_reclaim.py \
        src/intelligence/trading/supply_demand_setup.py
git commit -m "feat(param-store): wire weights.vwap_reclaim + liquidity_sweep + supply_demand"
```

---

## Task 11: Zone Engine — Tier C Geometry

**Files:**
- Modify: `src/intelligence/trading/zone_engine.py`

`zone_engine.py` is a utility module with standalone functions (not a plugin class). Use the module-level config pattern.

- [ ] **Step 1: Add module-level config pattern and getter functions**

After the existing module-level constants (after line ~34), add:

```python
from typing import Any as _Any

_config_service: _Any | None = None


def set_config_service(cfg: _Any) -> None:
    """Inject ConfigService at pipeline startup. Called by intelligence_pipeline._prewarm()."""
    global _config_service
    _config_service = cfg


def _cluster_radius_atr() -> float:
    if _config_service is not None:
        return _config_service.get_sync("feature.zone_engine.cluster_radius_atr", CLUSTER_RADIUS_ATR)
    return CLUSTER_RADIUS_ATR


def _zone_buffer_atr() -> float:
    if _config_service is not None:
        return _config_service.get_sync("feature.zone_engine.zone_buffer_atr", ZONE_BUFFER_ATR)
    return ZONE_BUFFER_ATR


def _min_width_atr() -> float:
    if _config_service is not None:
        return _config_service.get_sync("feature.zone_engine.min_width_atr", MIN_ZONE_WIDTH_ATR)
    return MIN_ZONE_WIDTH_ATR


def _single_level_radius_atr() -> float:
    if _config_service is not None:
        return _config_service.get_sync(
            "feature.zone_engine.single_level_radius_atr", SINGLE_LEVEL_RADIUS_ATR
        )
    return SINGLE_LEVEL_RADIUS_ATR


def _strength_weight() -> float:
    if _config_service is not None:
        return _config_service.get_sync("weights.zone_engine.strength", _SINGLE_STRENGTH_WEIGHT)
    return _SINGLE_STRENGTH_WEIGHT


def _proximity_weight() -> float:
    if _config_service is not None:
        return _config_service.get_sync("weights.zone_engine.proximity", _SINGLE_PROXIMITY_WEIGHT)
    return _SINGLE_PROXIMITY_WEIGHT
```

- [ ] **Step 2: Replace constant usages inside zone_engine.py functions**

Find every usage of the 6 constants inside zone_engine.py functions and replace with getter calls:
```bash
grep -n "CLUSTER_RADIUS_ATR\|ZONE_BUFFER_ATR\|MIN_ZONE_WIDTH_ATR\|SINGLE_LEVEL_RADIUS_ATR\|_SINGLE_STRENGTH_WEIGHT\|_SINGLE_PROXIMITY_WEIGHT" src/intelligence/trading/zone_engine.py
```

Replace each usage (inside functions only — keep module-level constant definitions):
- `CLUSTER_RADIUS_ATR` → `_cluster_radius_atr()`
- `ZONE_BUFFER_ATR` → `_zone_buffer_atr()`
- `MIN_ZONE_WIDTH_ATR` → `_min_width_atr()`
- `SINGLE_LEVEL_RADIUS_ATR` → `_single_level_radius_atr()`
- `_SINGLE_STRENGTH_WEIGHT` → `_strength_weight()`
- `_SINGLE_PROXIMITY_WEIGHT` → `_proximity_weight()`

- [ ] **Step 3: Add zone engine tests to test_param_store_migration.py**

Append:
```python
import src.intelligence.trading.zone_engine as ze


def teardown_function():
    cu.set_config_service(None)
    vpu.set_config_service(None)
    agg.set_config_service(None)
    ze.set_config_service(None)


def test_zone_cluster_radius_returns_config_value():
    ze.set_config_service(_make_cfg(0.75))
    assert ze._cluster_radius_atr() == 0.75


def test_zone_cluster_radius_returns_constant_when_no_config():
    assert ze._cluster_radius_atr() == ze.CLUSTER_RADIUS_ATR


def test_zone_strength_weight_returns_config_value():
    ze.set_config_service(_make_cfg(0.7))
    assert ze._strength_weight() == 0.7
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py tests/unit/intelligence/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/zone_engine.py \
        tests/unit/intelligence/test_param_store_migration.py
git commit -m "feat(param-store): wire feature/weights.zone_engine geometry constants"
```

---

## Task 12: Expand intelligence_pipeline.py — Prewarm All New Plugins + Module Setters

**Files:**
- Modify: `services/intelligence_pipeline.py`

The pipeline's `_prewarm_threshold_config()` currently handles only the 4 original plugins. Expand it to cover all plugins added in Tasks 4–11 and call the module-level setters for confidence_utils, volume_profile_utils, zone_engine, and aggregator.

- [ ] **Step 1: Expand `_THRESHOLD_KEYS` tuple**

Locate `_THRESHOLD_KEYS` (currently a class-level tuple in `IntelligencePipeline`). Add all new Tier A keys:

```python
_THRESHOLD_KEYS: tuple[tuple[str, Any], ...] = (
    # --- existing (migration 128) ---
    ("threshold.trend_following.regime_min", 0.5),
    ("threshold.trend_following.confidence_min", 0.4),
    ("threshold.ofi_continuation.min_bars", 10),
    ("threshold.ofi_continuation.magnitude_floors",
     {"ES": 500, "NQ": 200, "CL": 1000, "GC": 500, "_default": 500}),
    ("threshold.pattern_completion.confidence_min", 0.70),
    ("threshold.vwap_reversion.sigma_min", 1.5),
    ("threshold.vwap_reversion.hurst_max", 0.55),
    # --- migration 129: Tier A detection gates ---
    ("threshold.global.min_regime_weight", 0.30),
    ("threshold.global.min_ctf_score", 0.25),
    ("threshold.volume_profile.div_min", 0.30),
    ("threshold.volume_profile.stoch_oversold", 30.0),
    ("threshold.volume_profile.stoch_overbought", 70.0),
    ("threshold.hvn_rejection.proximity_atr", 0.30),
    ("threshold.poc_rejection.proximity_atr", 0.30),
    ("threshold.session_extremes.proximity_atr", 0.30),
    ("threshold.session_extremes.rsi_oversold", 35.0),
    ("threshold.session_extremes.rsi_overbought", 65.0),
    ("threshold.liquidity_hunt.significance_min", 0.60),
    ("threshold.gap_analysis.min_gap_atr", 0.80),
    ("threshold.gap_analysis.continuation_atr", 1.00),
    ("threshold.gap_analysis.volume_confirm_ratio", 1.50),
    ("threshold.mtf_alignment.ctf_score_min", 0.70),
    ("threshold.regime_transition.cp_min", 0.50),
    ("threshold.dual_divergence.ofi_div_min", 1.00),
    ("threshold.dual_divergence.cvd_div_min", 1.00),
    ("threshold.orb.vol_expansion_mult", 1.50),
    ("threshold.vcp.min_contractions", 3),
    ("threshold.vcp.vol_expansion_mult", 1.20),
    ("threshold.ofi_divergence.min_persistence_bars", 2),
    ("threshold.aggregator.regime_tiebreak", 0.40),
    ("feature.volume_zscore.window", 20),
    # --- migration 129: Tier B weights ---
    ("weights.gap_analysis.geo", 0.40),
    ("weights.gap_analysis.vol", 0.25),
    ("weights.gap_analysis.timing", 0.20),
    ("weights.gap_analysis.type", 0.15),
    ("weights.mean_reversion.rsi_extreme", 0.30),
    ("weights.mean_reversion.div_score", 0.30),
    ("weights.mean_reversion.vol_stability", 0.20),
    ("weights.mean_reversion.sr_proximity", 0.20),
    ("weights.momentum_breakout.roc", 0.40),
    ("weights.momentum_breakout.vol", 0.35),
    ("weights.momentum_breakout.break_margin", 0.25),
    ("weights.squeeze_expansion.squeeze_bars", 0.35),
    ("weights.squeeze_expansion.vol_expansion", 0.35),
    ("weights.squeeze_expansion.momentum", 0.30),
    ("weights.vwap_reclaim.vol", 0.30),
    ("weights.vwap_reclaim.duration", 0.30),
    ("weights.vwap_reclaim.trend_align", 0.20),
    ("weights.vwap_reclaim.sr_proximity", 0.20),
    ("weights.liquidity_sweep.base_conf", 0.40),
    ("weights.liquidity_sweep.depth_scale", 0.20),
    ("weights.supply_demand.base_conf", 0.35),
    ("weights.supply_demand.freshness_scale", 0.23),
    # --- migration 129: Tier C zone engine ---
    ("feature.zone_engine.cluster_radius_atr", 0.50),
    ("feature.zone_engine.zone_buffer_atr", 0.15),
    ("feature.zone_engine.min_width_atr", 0.25),
    ("feature.zone_engine.single_level_radius_atr", 0.25),
    ("weights.zone_engine.strength", 0.60),
    ("weights.zone_engine.proximity", 0.40),
)
```

- [ ] **Step 2: Expand `_prewarm_threshold_config()` — inject new per-plugin singletons and call module setters**

Replace (or extend) the existing `_prewarm_threshold_config()` body:

```python
async def _prewarm_threshold_config(self) -> None:
    """Pre-warm config cache + inject ConfigService into all configurable plugins and modules."""
    assert self._config_service is not None
    for key, default in self._THRESHOLD_KEYS:
        await self._config_service.get(key, default)

    # --- Module-level setters (shared constants used by many plugins) ---
    from src.intelligence.trading import (  # noqa: PLC0415
        aggregator,
        confidence_utils,
        volume_profile_utils,
        zone_engine,
    )
    confidence_utils.set_config_service(self._config_service)
    volume_profile_utils.set_config_service(self._config_service)
    zone_engine.set_config_service(self._config_service)
    aggregator.set_config_service(self._config_service)

    # --- Per-plugin instance injection (migration 128 original 4) ---
    from src.intelligence.trading.anchored_vwap_reversion import (  # noqa: PLC0415
        plugin as avwap_plugin,
    )
    from src.intelligence.trading.ofi_continuation import plugin as ofi_plugin  # noqa: PLC0415
    from src.intelligence.trading.pattern_completion import (  # noqa: PLC0415
        plugin as pattern_plugin,
    )
    from src.intelligence.trading.trend_following import plugin as tf_plugin  # noqa: PLC0415

    # --- Per-plugin instance injection (migration 129 new plugins) ---
    from src.intelligence.trading.dual_divergence import plugin as dd_plugin  # noqa: PLC0415
    from src.intelligence.trading.gap_analysis_setup import plugin as gap_plugin  # noqa: PLC0415
    from src.intelligence.trading.hvn_rejection import plugin as hvn_plugin  # noqa: PLC0415
    from src.intelligence.trading.liquidity_hunt import plugin as lh_plugin  # noqa: PLC0415
    from src.intelligence.trading.liquidity_sweep_reclaim import plugin as lsr_plugin  # noqa: PLC0415
    from src.intelligence.trading.mean_reversion import plugin as mr_plugin  # noqa: PLC0415
    from src.intelligence.trading.momentum_breakout import plugin as mb_plugin  # noqa: PLC0415
    from src.intelligence.trading.mtf_alignment import plugin as mtf_plugin  # noqa: PLC0415
    from src.intelligence.trading.ofi_divergence import plugin as ofid_plugin  # noqa: PLC0415
    from src.intelligence.trading.orb15 import plugin as orb15_plugin  # noqa: PLC0415
    from src.intelligence.trading.orb30 import plugin as orb30_plugin  # noqa: PLC0415
    from src.intelligence.trading.poc_rejection import plugin as poc_plugin  # noqa: PLC0415
    from src.intelligence.trading.regime_transition import plugin as rt_plugin  # noqa: PLC0415
    from src.intelligence.trading.session_extremes_setup import plugin as se_plugin  # noqa: PLC0415
    from src.intelligence.trading.squeeze_expansion import plugin as sq_plugin  # noqa: PLC0415
    from src.intelligence.trading.supply_demand_setup import plugin as sd_plugin  # noqa: PLC0415
    from src.intelligence.trading.vcp import plugin as vcp_plugin  # noqa: PLC0415
    from src.intelligence.trading.volume_zscore import plugin as vz_plugin  # noqa: PLC0415
    from src.intelligence.trading.vwap_reclaim import plugin as vwap_r_plugin  # noqa: PLC0415

    for p in (
        tf_plugin, ofi_plugin, avwap_plugin, pattern_plugin,
        hvn_plugin, poc_plugin, se_plugin, lh_plugin,
        gap_plugin, mtf_plugin, rt_plugin, dd_plugin,
        ofid_plugin, orb15_plugin, orb30_plugin, vcp_plugin,
        vz_plugin, mr_plugin, mb_plugin, sq_plugin,
        vwap_r_plugin, lsr_plugin, sd_plugin,
    ):
        p._config_service = self._config_service

    self.logger.info(
        "intelligence_pipeline.threshold_config_loaded",
        keys=[k for k, _ in self._THRESHOLD_KEYS],
        plugin_count=23,
        module_setters=["confidence_utils", "volume_profile_utils", "zone_engine", "aggregator"],
    )
```

**Note:** Each plugin module must expose a `plugin` singleton at module level (matching the pattern already used by `trend_following.py: plugin = TrendFollowingPlugin()`). Verify each new plugin has `plugin = <PluginClass>()` at the bottom of its file. If any don't, add it.

- [ ] **Step 3: Verify plugin singletons exist**

```bash
grep -l "^plugin = " src/intelligence/trading/hvn_rejection.py \
  src/intelligence/trading/poc_rejection.py \
  src/intelligence/trading/session_extremes_setup.py \
  src/intelligence/trading/liquidity_hunt.py \
  src/intelligence/trading/gap_analysis_setup.py \
  src/intelligence/trading/mtf_alignment.py \
  src/intelligence/trading/regime_transition.py \
  src/intelligence/trading/dual_divergence.py \
  src/intelligence/trading/ofi_divergence.py \
  src/intelligence/trading/orb15.py \
  src/intelligence/trading/orb30.py \
  src/intelligence/trading/vcp.py \
  src/intelligence/trading/volume_zscore.py \
  src/intelligence/trading/mean_reversion.py \
  src/intelligence/trading/momentum_breakout.py \
  src/intelligence/trading/squeeze_expansion.py \
  src/intelligence/trading/vwap_reclaim.py \
  src/intelligence/trading/liquidity_sweep_reclaim.py \
  src/intelligence/trading/supply_demand_setup.py
```

Any file NOT listed in the output needs `plugin = <ClassName>()` added at the bottom.

- [ ] **Step 4: Run all unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/intelligence_pipeline.py src/intelligence/trading/
git commit -m "feat(param-store): expand pipeline prewarm — 23 plugins + 4 module-level config setters"
```

---

## Self-Review

**Spec coverage:**
- Migration 129 SQL: ✓ all 46 keys (24 Tier A, 22 Tier B + C)
- Module-level getters: ✓ confidence_utils, volume_profile_utils, zone_engine, aggregator
- Plugin injection: ✓ 23 plugins via `_config_service` field
- MIN_REGIME_WEIGHT/MIN_CTF_SCORE propagation: ✓ 16 plugins updated to call getters
- Pipeline prewarm: ✓ covers all modules and all plugin singletons
- Tests: ✓ getter fallback tests for all module-level patterns

**Placeholder scan:** None found.

**Type consistency:** All `cfg.get_sync(key, default)` calls use the same default as the module constant seed. All `_config_service: Any = field(default=None, compare=False, repr=False)` patterns are consistent across all plugin dataclasses.

**Plugin singleton check:** Step 3 of Task 12 explicitly verifies singletons exist before assuming imports work.
