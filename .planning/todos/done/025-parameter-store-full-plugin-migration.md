# COMPLETED — Phase 125 (APR Full Migration)

All 6 applicable Tier B plugins and CIS scorer wired to ConfigService. Migration 132 seeded 10 new APR keys. _validate_weights_sum guard added. Closed 2026-06-15.

---

# TODO 025: Parameter Store - Full Plugin Migration

**Created:** 2026-06-13  
**Trigger:** After signal ledger rebuild replay completes (do not start mid-replay — code changes require pipeline restart which loses position)  
**Rationale:** Every hard-coded threshold is a frozen opinion invisible to ML discovery. The learning loop can only improve what it can see.

---

## Scope

Three tiers by ML learning value. Do in order — each tier unlocks more signal quality improvement than the next.

---

### Tier A: Detection Gates (highest value — control fire/no-fire)

These directly determine whether a signal enters the ledger. Wrong values produce autocorrelated junk or suppress real events. ML discovery will converge these fastest because outcomes are directly attributable.

| File | Constants | Namespace |
|------|-----------|-----------|
| `confidence_utils.py` | `MIN_REGIME_WEIGHT = 0.30`, `MIN_CTF_SCORE = 0.25` | `threshold.global.min_regime_weight`, `threshold.global.min_ctf_score` |
| `hvn_rejection.py` | `_HVN_PROXIMITY_ATR = 0.3`, `DIV_THRESHOLD` | `threshold.hvn_rejection.proximity_atr`, `threshold.hvn_rejection.div_threshold` |
| `poc_rejection.py` | `_POC_PROXIMITY_ATR = 0.3`, `DIV_THRESHOLD` | `threshold.poc_rejection.proximity_atr`, `threshold.poc_rejection.div_threshold` |
| `session_extremes_setup.py` | `proximity_atr_mult = 0.3`, RSI 35/65 gates | `threshold.session_extremes.proximity_atr`, `threshold.session_extremes.rsi_overbought`, `threshold.session_extremes.rsi_oversold` |
| `liquidity_hunt.py` | `MIN_SIGNIFICANCE = 0.60` | `threshold.liquidity_hunt.min_significance` |
| `gap_analysis_setup.py` | `min_gap_atr_mult = 0.8`, `continuation_atr_mult = 1.0`, `volume_confirm_ratio = 1.5` | `threshold.gap_analysis.min_gap_atr`, `threshold.gap_analysis.continuation_atr`, `threshold.gap_analysis.volume_confirm_ratio` |
| `mtf_alignment.py` | `ctf_score_threshold = 0.7` | `threshold.mtf_alignment.ctf_score_min` |
| `regime_transition.py` | `cp_threshold = 0.5` | `threshold.regime_transition.cp_min` |
| `dual_divergence.py` | `_OFI_DIV_THRESHOLD = 1.0`, `_CVD_DIV_THRESHOLD = 1.0` | `threshold.dual_divergence.ofi_div_min`, `threshold.dual_divergence.cvd_div_min` |
| `orb15.py` + `orb30.py` | `_VOL_EXPANSION_THRESHOLD = 1.5` | `threshold.orb.vol_expansion_mult` (shared) |
| `vcp.py` | `_MIN_CONTRACTIONS = 3`, `_VOL_EXPANSION_MULT = 1.2` | `threshold.vcp.min_contractions`, `threshold.vcp.vol_expansion_mult` |
| `ofi_divergence.py` | `_MIN_PERSISTENCE = 2` | `threshold.ofi_divergence.min_persistence_bars` |
| `aggregator.py` | `_REGIME_TIEBREAK_THRESHOLD = 0.4` | `threshold.aggregator.regime_tiebreak` |
| `volume_zscore.py` | `_WINDOW = 20` | `feature.volume_zscore.window` |

---

### Tier B: Confidence Weights (medium value — shape signal strength, learned once N is sufficient)

These are the `raw_conf = w1 * X + w2 * Y + ...` formulas in each plugin. Wrong weights don't cause wrong signals — they distort the ranking of correct signals. ML discovery (XGBoost/logistic) will eventually produce empirical weights. Register now so history accumulates.

| File | Formula | Namespace |
|------|---------|-----------|
| `gap_analysis_setup.py` | `0.40 * geo + 0.25 * vol + 0.20 * timing + 0.15 * type` | `weights.gap_analysis.*` |
| `mean_reversion.py` | `0.3 * rsi + 0.3 * div + 0.2 * vol_stability + 0.2 * sr_prox` | `weights.mean_reversion.*` |
| `momentum_breakout.py` | `0.40 * roc + 0.35 * vol + 0.25 * break_margin` | `weights.momentum_breakout.*` |
| `squeeze_expansion.py` | `0.35 * squeeze_bars + 0.35 * vol_expansion + 0.30 * momentum` | `weights.squeeze_expansion.*` |
| `vwap_reclaim.py` | `0.30 * vol + 0.30 * duration + 0.20 * trend_align + 0.20 * sr_prox` | `weights.vwap_reclaim.*` |
| `anchored_vwap_reversion.py` | `0.40 * sigma_magnitude + 0.35 * hurst_quality + 0.25 * vol_stability` | `weights.vwap_reversion.*` |
| `liquidity_sweep_reclaim.py` | `0.40 + 0.20 * linear_ramp(sweep_depth_atr, 0, 2)` | `weights.liquidity_sweep.*` |
| `supply_demand_setup.py` | `0.35 + 0.23 * linear_ramp(freshness, 0.40, 1.0)` | `weights.supply_demand.*` |
| `cis_scorer.py` | All 5 bucket sub-weights (trend, momentum, structure, SMC, regime) | `weights.cis.*` — do last, highest coupling |

---

### Tier C: Zone Engine Geometry (lower value — shared infrastructure, harder to instrument)

Shared by HVN/POC/supply-demand/zone-based I7 plugins. Wrong values affect zone identification, not signal gates directly. Register for observability; ML learning target is longer-horizon.

| Constants | Namespace |
|-----------|-----------|
| `CLUSTER_RADIUS_ATR = 0.5`, `ZONE_BUFFER_ATR = 0.15` | `feature.zone_engine.cluster_radius_atr`, `feature.zone_engine.zone_buffer_atr` |
| `MIN_ZONE_WIDTH_ATR = 0.25`, `SINGLE_LEVEL_RADIUS_ATR = 0.25` | `feature.zone_engine.min_width_atr`, `feature.zone_engine.single_level_radius_atr` |
| `_SINGLE_STRENGTH_WEIGHT = 0.6`, `_SINGLE_PROXIMITY_WEIGHT = 0.4` | `weights.zone_engine.strength`, `weights.zone_engine.proximity` |

---

## Implementation Pattern

Follow migration 128 exactly:
1. `config_schema` + `config_state` INSERT with seed = current hard-coded value (zero behaviour change at rollout)
2. Mark all as `[initial_estimate]` or `[conventional]` in description; note ML learning target
3. Load via `config_service.get_sync(key, default)` at compute_full() time
4. For plugins not yet injected with `_config_service`: add `_config_service: Any = field(default=None, compare=False, repr=False)` and add to `_prewarm_threshold_config()` in `intelligence_pipeline.py`
5. Remove the hard-coded constant

**Do Tier A first** — one migration file, one commit. Tiers B and C can follow separately once A is validated through a replay cycle.
