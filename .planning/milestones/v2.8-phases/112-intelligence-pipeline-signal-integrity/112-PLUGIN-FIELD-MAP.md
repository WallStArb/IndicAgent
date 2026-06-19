# Plugin Field Migration Map — Phase 112

Generated as task 4-0 preflight before any plugin edits begin.

## File Count

**73 files** using `frames.get("features")` or `frames["features"]` were identified.

## Tier Key Reference

| Tier | Schema Class | Tier Key in `frames` | Producing Tier |
|------|-------------|---------------------|----------------|
| I1 | `I1Indicators` (extra='allow') | `"i1"` | I1 — indicator plugins |
| I2 | `I2Events` (extra='allow') | `"i2"` | I2 — composite event plugins |
| I3 | `I3Structure` (extra='forbid') | `"i3"` | I3 — structure plugins |
| I4 | `I4Context` (extra='forbid') | `"i4"` | I4 — context plugins |
| I5 | `I5Patterns` (extra='forbid') | `"i5"` | I5 — pattern plugins |
| SMC | `SMCContext` (extra='forbid') | `"smc"` | SMC — smart money plugins |
| I6 | `I6Confluence` (extra='forbid') | `"i6"` | I6 — confluence plugins |

## Field-to-Tier Mapping Table

| flat_field | producing_tier | tier_key | typed_access_pattern |
|-----------|---------------|---------|---------------------|
| `rsi_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("rsi_14")` |
| `atr_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("atr_14")` |
| `adx_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("adx_14")` |
| `plus_di_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("plus_di_14")` |
| `minus_di_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("minus_di_14")` |
| `stoch_k_14_3` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("stoch_k_14_3")` |
| `stoch_d_14_3` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("stoch_d_14_3")` |
| `macd_12_26_9` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("macd_12_26_9")` |
| `macd_signal_12_26_9` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("macd_signal_12_26_9")` |
| `macd_histogram_12_26_9` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("macd_histogram_12_26_9")` |
| `macd_12_26_9_hist` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("macd_12_26_9_hist")` |
| `bb_20_2_upper` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_20_2_upper")` |
| `bb_20_2_lower` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_20_2_lower")` |
| `bb_20_2_mid` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_20_2_mid")` |
| `bb_upper` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_upper")` |
| `bb_lower` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_lower")` |
| `bb_mid` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("bb_mid")` |
| `obv` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("obv")` |
| `supertrend_dir` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("supertrend_dir")` |
| `sma_20` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("sma_20")` |
| `sma_50` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("sma_50")` |
| `sma_20_gt_50` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("sma_20_gt_50")` |
| `roc_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("roc_14")` |
| `cci_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("cci_14")` |
| `mfi_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("mfi_14")` |
| `williams_r_14` | I1/indicators | `"i1"` | `frames.get("i1", {}).get("williams_r_14")` |
| `hma_20` | I1/indicators (HMA plugin) | `"i1"` | `frames.get("i1", {}).get("hma_20")` |
| `keltner_upper` | I1/indicators (KeltnerPlugin) | `"i1"` | `frames.get("i1", {}).get("keltner_upper")` |
| `keltner_lower` | I1/indicators (KeltnerPlugin) | `"i1"` | `frames.get("i1", {}).get("keltner_lower")` |
| `ema_9_slope` | I1/indicators (MA plugin extras) | `"i1"` | `frames.get("i1", {}).get("ema_9_slope")` |
| `ema_21_slope` | I1/indicators (MA plugin extras) | `"i1"` | `frames.get("i1", {}).get("ema_21_slope")` |
| `rel_volume` | I1/indicators (VolumeZScore plugin) | `"i1"` | `frames.get("i1", {}).get("rel_volume")` |
| `volume_sma_20` | I1/indicators (VolumeZScore plugin) | `"i1"` | `frames.get("i1", {}).get("volume_sma_20")` |
| `volume_std_20` | I1/indicators (VolumeZScore plugin) | `"i1"` | `frames.get("i1", {}).get("volume_std_20")` |
| `ofi_ewma_5` | I1/indicators (OFI plugin) | `"i1"` | `frames.get("i1", {}).get("ofi_ewma_5")` |
| `ofi_ewma_20` | I1/indicators (OFI plugin) | `"i1"` | `frames.get("i1", {}).get("ofi_ewma_20")` |
| `ofi_spike_z` | I1/indicators (OFI plugin) | `"i1"` | `frames.get("i1", {}).get("ofi_spike_z")` |
| `ofi_divergence` | I1/indicators (OFI plugin) | `"i1"` | `frames.get("i1", {}).get("ofi_divergence")` |
| `cvd_slope_5bar` | I1/indicators (CVD plugin) | `"i1"` | `frames.get("i1", {}).get("cvd_slope_5bar")` |
| `cvd_spike_z` | I1/indicators (CVD plugin) | `"i1"` | `frames.get("i1", {}).get("cvd_spike_z")` |
| `cvd_divergence` | I1/indicators (CVD plugin) | `"i1"` | `frames.get("i1", {}).get("cvd_divergence")` |
| `hurst_exponent` | I4/context (HurstExponent plugin) | `"i4"` | `frames.get("i4", {}).get("hurst_exponent")` |
| `hurst_trend_quality` | I4/context (HurstExponent plugin) | `"i4"` | `frames.get("i4", {}).get("hurst_trend_quality")` |
| `hurst_mr_quality` | I4/context (HurstExponent plugin) | `"i4"` | `frames.get("i4", {}).get("hurst_mr_quality")` |
| `rsi_curvature` | I2/composites (MomentumAccel) | `"i2"` | `frames.get("i2", {}).get("rsi_curvature")` |
| `macd_hist_slope` | I2/composites (MomentumAccel) | `"i2"` | `frames.get("i2", {}).get("macd_hist_slope")` |
| `price_accel` | I2/composites (MomentumAccel) | `"i2"` | `frames.get("i2", {}).get("price_accel")` |
| `hma_accel` | I2/composites (MomentumAccel) | `"i2"` | `frames.get("i2", {}).get("hma_accel")` |
| `exhaustion_score` | I2/composites (ExhaustionScore) | `"i2"` | `frames.get("i2", {}).get("exhaustion_score")` |
| `exhaustion_side` | I2/composites (ExhaustionScore) | `"i2"` | `frames.get("i2", {}).get("exhaustion_side")` |
| `exhaustion_bars` | I2/composites (ExhaustionScore) | `"i2"` | `frames.get("i2", {}).get("exhaustion_bars")` |
| `macd_cross_bullish` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_cross_bullish")` |
| `macd_cross_bearish` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_cross_bearish")` |
| `macd_cross_bars_ago` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_cross_bars_ago")` |
| `macd_hist_positive` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_hist_positive")` |
| `macd_hist_turning_up` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_hist_turning_up")` |
| `macd_negative_support_test` | I3/structure (MACDEvents) | `"i3"` | `frames.get("i3", {}).get("macd_negative_support_test")` |
| `swing_high` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_high")` |
| `swing_low` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_low")` |
| `swing_high_idx` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_high_idx")` |
| `swing_low_idx` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_low_idx")` |
| `swing_pattern` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_pattern")` |
| `swing_high_age_bars` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_high_age_bars")` |
| `swing_low_age_bars` | I3/structure (SwingDetector) | `"i3"` | `frames.get("i3", {}).get("swing_low_age_bars")` |
| `nearest_resistance` | I3/structure (SupportResistance) | `"i3"` | `frames.get("i3", {}).get("nearest_resistance")` |
| `nearest_support` | I3/structure (SupportResistance) | `"i3"` | `frames.get("i3", {}).get("nearest_support")` |
| `trend_direction` | I3/structure (TrendStructure) | `"i3"` | `frames.get("i3", {}).get("trend_direction")` |
| `trend_strength` | I3/structure (TrendStructure) | `"i3"` | `frames.get("i3", {}).get("trend_strength")` |
| `poc_level` | I3/structure (MarketProfile) | `"i3"` | `frames.get("i3", {}).get("poc_level")` |
| `va_high` | I3/structure (MarketProfile) | `"i3"` | `frames.get("i3", {}).get("va_high")` |
| `va_low` | I3/structure (MarketProfile) | `"i3"` | `frames.get("i3", {}).get("va_low")` |
| `prior_session_high` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("prior_session_high")` |
| `prior_session_low` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("prior_session_low")` |
| `prior_session_close` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("prior_session_close")` |
| `weekly_pivot` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("weekly_pivot")` |
| `asian_session_high` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("asian_session_high")` |
| `asian_session_low` | I3/structure (SessionLevels) | `"i3"` | `frames.get("i3", {}).get("asian_session_low")` |
| `fib_swing_high` | I3/structure (FibonacciZones) | `"i3"` | `frames.get("i3", {}).get("fib_swing_high")` |
| `fib_swing_low` | I3/structure (FibonacciZones) | `"i3"` | `frames.get("i3", {}).get("fib_swing_low")` |
| `vol_regime` | I4/context (VolatilityRegime) | `"i4"` | `frames.get("i4", {}).get("vol_regime")` |
| `vol_expansion` | I4/context (VolatilityRegime) | `"i4"` | `frames.get("i4", {}).get("vol_expansion")` |
| `vol_percentile` | I4/context (VolatilityRegime) | `"i4"` | `frames.get("i4", {}).get("vol_percentile")` |
| `trend_regime` | I4/context (TrendRegime) | `"i4"` | `frames.get("i4", {}).get("trend_regime")` |
| `trend_confidence` | I4/context (TrendRegime) | `"i4"` | `frames.get("i4", {}).get("trend_confidence")` |
| `momentum_bias` | I4/context (MomentumContext) | `"i4"` | `frames.get("i4", {}).get("momentum_bias")` |
| `garch_sigma` | I4/context (GARCHVolatility) | `"i4"` | `frames.get("i4", {}).get("garch_sigma")` |
| `garch_vol_regime` | I4/context (GARCHVolatility) | `"i4"` | `frames.get("i4", {}).get("garch_vol_regime")` |
| `kalman_trend` | I4/context (KalmanTrend) | `"i4"` | `frames.get("i4", {}).get("kalman_trend")` |
| `kalman_price_position` | I4/context (KalmanTrend) | `"i4"` | `frames.get("i4", {}).get("kalman_price_position")` |
| `session_ny` | I4/context (SessionContext) | `"i4"` | `frames.get("i4", {}).get("session_ny")` |
| `session_london` | I4/context (SessionContext) | `"i4"` | `frames.get("i4", {}).get("session_london")` |
| `bars_since_session_start` | I4/context (SessionContext) | `"i4"` | `frames.get("i4", {}).get("bars_since_session_start")` |
| `session_vwap` | I4/context (AnchoredVWAP) | `"i4"` | `frames.get("i4", {}).get("session_vwap")` |
| `session_vwap_deviation_sigma` | I4/context (AnchoredVWAP) | `"i4"` | `frames.get("i4", {}).get("session_vwap_deviation_sigma")` |
| `session_vwap_deviation_velocity` | I4/context (AnchoredVWAP) | `"i4"` | `frames.get("i4", {}).get("session_vwap_deviation_velocity")` |
| `avwap_upper_band` | I4/context (AnchoredVWAP) | `"i4"` | `frames.get("i4", {}).get("avwap_upper_band")` |
| `avwap_lower_band` | I4/context (AnchoredVWAP) | `"i4"` | `frames.get("i4", {}).get("avwap_lower_band")` |
| `poc_price` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("poc_price")` |
| `vah` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("vah")` |
| `val` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("val")` |
| `nearest_hvn_above` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("nearest_hvn_above")` |
| `nearest_hvn_below` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("nearest_hvn_below")` |
| `nearest_hvn_dist_atr` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("nearest_hvn_dist_atr")` |
| `nearest_lvn_above` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("nearest_lvn_above")` |
| `nearest_lvn_below` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("nearest_lvn_below")` |
| `in_lvn` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("in_lvn")` |
| `distance_to_vah_atr` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("distance_to_vah_atr")` |
| `distance_to_val_atr` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("distance_to_val_atr")` |
| `va_width_atr` | I4/context (VolumeProfile) | `"i4"` | `frames.get("i4", {}).get("va_width_atr")` |
| `htf_1h_poc_price` | I4/context (VolumeProfile HTF cache) | `"i4"` | `frames.get("i4", {}).get("htf_1h_poc_price")` |
| `htf_1h_vah` | I4/context (VolumeProfile HTF cache) | `"i4"` | `frames.get("i4", {}).get("htf_1h_vah")` |
| `htf_1h_val` | I4/context (VolumeProfile HTF cache) | `"i4"` | `frames.get("i4", {}).get("htf_1h_val")` |
| `vix_level` | I4/context (VIXRegime) | `"i4"` | `frames.get("i4", {}).get("vix_level")` |
| `vix_z` | I4/context (VIXRegime) | `"i4"` | `frames.get("i4", {}).get("vix_z")` |
| `eq_spread_z` | I4/context (CrossAssetContext) | `"i4"` | `frames.get("i4", {}).get("eq_spread_z")` |
| `eq_pairs_confirming` | I4/context (CrossAssetContext) | `"i4"` | `frames.get("i4", {}).get("eq_pairs_confirming")` |
| `entropy_quality` | I4/context (ShannonEntropy) | `"i4"` | `frames.get("i4", {}).get("entropy_quality")` |
| `hmm_regime` | SMC/smart-money (HMMRegime) | `"smc"` | `frames.get("smc", {}).get("hmm_regime")` |
| `hmm_regime_prob` | SMC/smart-money (HMMRegime) | `"smc"` | `frames.get("smc", {}).get("hmm_regime_prob")` |
| `hmm_prob_trending_up` | SMC/smart-money (HMMRegime) | `"smc"` | `frames.get("smc", {}).get("hmm_prob_trending_up")` |
| `hmm_prob_trending_down` | SMC/smart-money (HMMRegime) | `"smc"` | `frames.get("smc", {}).get("hmm_prob_trending_down")` |
| `hmm_probability` | SMC/smart-money (HMMRegime) | `"smc"` | `frames.get("smc", {}).get("hmm_probability")` |
| `bos_detected` | SMC/smart-money (BOSCHoCH) | `"smc"` | `frames.get("smc", {}).get("bos_detected")` |
| `bos_direction` | SMC/smart-money (BOSCHoCH) | `"smc"` | `frames.get("smc", {}).get("bos_direction")` |
| `bos_level` | SMC/smart-money (BOSCHoCH) | `"smc"` | `frames.get("smc", {}).get("bos_level")` |
| `choch_detected` | SMC/smart-money (BOSCHoCH) | `"smc"` | `frames.get("smc", {}).get("choch_detected")` |
| `choch_direction` | SMC/smart-money (BOSCHoCH) | `"smc"` | `frames.get("smc", {}).get("choch_direction")` |
| `fvg_type` | SMC/smart-money (FairValueGap) | `"smc"` | `frames.get("smc", {}).get("fvg_type")` |
| `fvg_top` | SMC/smart-money (FairValueGap) | `"smc"` | `frames.get("smc", {}).get("fvg_top")` |
| `fvg_bottom` | SMC/smart-money (FairValueGap) | `"smc"` | `frames.get("smc", {}).get("fvg_bottom")` |
| `fvg_midpoint` | SMC/smart-money (FairValueGap) | `"smc"` | `frames.get("smc", {}).get("fvg_midpoint")` |
| `fvg_open_count` | SMC/smart-money (FairValueGap) | `"smc"` | `frames.get("smc", {}).get("fvg_open_count")` |
| `ob_type` | SMC/smart-money (OrderBlocks) | `"smc"` | `frames.get("smc", {}).get("ob_type")` |
| `ob_top` | SMC/smart-money (OrderBlocks) | `"smc"` | `frames.get("smc", {}).get("ob_top")` |
| `ob_bottom` | SMC/smart-money (OrderBlocks) | `"smc"` | `frames.get("smc", {}).get("ob_bottom")` |
| `ob_mitigated` | SMC/smart-money (OrderBlocks) | `"smc"` | `frames.get("smc", {}).get("ob_mitigated")` |
| `sweep_detected` | SMC/smart-money (LiquiditySweeps) | `"smc"` | `frames.get("smc", {}).get("sweep_detected")` |
| `sweep_type` | SMC/smart-money (LiquiditySweeps) | `"smc"` | `frames.get("smc", {}).get("sweep_type")` |
| `sweep_level` | SMC/smart-money (LiquiditySweeps) | `"smc"` | `frames.get("smc", {}).get("sweep_level")` |
| `sweep_depth_pct` | SMC/smart-money (LiquiditySweeps) | `"smc"` | `frames.get("smc", {}).get("sweep_depth_pct")` |
| `sweep_reclaimed` | SMC/smart-money (LiquiditySweeps) | `"smc"` | `frames.get("smc", {}).get("sweep_reclaimed")` |
| `cp_probability` | SMC/smart-money (BOCPDChangePoint) | `"smc"` | `frames.get("smc", {}).get("cp_probability")` |
| `bsl_level` | SMC/smart-money (LiquidityPools) | `"smc"` | `frames.get("smc", {}).get("bsl_level")` |
| `bsl_significance` | SMC/smart-money (LiquidityPools) | `"smc"` | `frames.get("smc", {}).get("bsl_significance")` |
| `ssl_level` | SMC/smart-money (LiquidityPools) | `"smc"` | `frames.get("smc", {}).get("ssl_level")` |
| `ssl_significance` | SMC/smart-money (LiquidityPools) | `"smc"` | `frames.get("smc", {}).get("ssl_significance")` |
| `price_in_premium` | SMC/smart-money (LiquidityPools) | `"smc"` | `frames.get("smc", {}).get("price_in_premium")` |
| `in_demand_zone` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("in_demand_zone")` |
| `in_supply_zone` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("in_supply_zone")` |
| `demand_strength` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("demand_strength")` |
| `supply_strength` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("supply_strength")` |
| `demand_freshness` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("demand_freshness")` |
| `supply_freshness` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("supply_freshness")` |
| `nearest_demand_high` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("nearest_demand_high")` |
| `nearest_demand_low` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("nearest_demand_low")` |
| `nearest_supply_high` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("nearest_supply_high")` |
| `nearest_supply_low` | SMC/smart-money (SupplyDemandZones) | `"smc"` | `frames.get("smc", {}).get("nearest_supply_low")` |
| `rsi_div_bullish` | I5/patterns (RSIDivergence) | `"i5"` | `frames.get("i5", {}).get("rsi_div_bullish")` |
| `rsi_div_bearish` | I5/patterns (RSIDivergence) | `"i5"` | `frames.get("i5", {}).get("rsi_div_bearish")` |
| `rsi_div_strength` | I5/patterns (RSIDivergence) | `"i5"` | `frames.get("i5", {}).get("rsi_div_strength")` |
| `vol_div_bullish` | I5/patterns (VolumeDivergence) | `"i5"` | `frames.get("i5", {}).get("vol_div_bullish")` |
| `vol_div_bearish` | I5/patterns (VolumeDivergence) | `"i5"` | `frames.get("i5", {}).get("vol_div_bearish")` |
| `vol_div_strength` | I5/patterns (VolumeDivergence) | `"i5"` | `frames.get("i5", {}).get("vol_div_strength")` |
| `obv_div_bullish` | I5/patterns (VolumeDivergence OBV ext) | `"i5"` | `frames.get("i5", {}).get("obv_div_bullish")` |
| `obv_div_bearish` | I5/patterns (VolumeDivergence OBV ext) | `"i5"` | `frames.get("i5", {}).get("obv_div_bearish")` |
| `obv_div_strength` | I5/patterns (VolumeDivergence OBV ext) | `"i5"` | `frames.get("i5", {}).get("obv_div_strength")` |
| `macd_div_bullish` | I5/patterns (MACDDivergence) | `"i5"` | `frames.get("i5", {}).get("macd_div_bullish")` |
| `macd_div_bearish` | I5/patterns (MACDDivergence) | `"i5"` | `frames.get("i5", {}).get("macd_div_bearish")` |
| `macd_div_strength` | I5/patterns (MACDDivergence) | `"i5"` | `frames.get("i5", {}).get("macd_div_strength")` |
| `cmf_div_bullish` | I5/patterns (CMFDivergence) | `"i5"` | `frames.get("i5", {}).get("cmf_div_bullish")` |
| `cmf_div_bearish` | I5/patterns (CMFDivergence) | `"i5"` | `frames.get("i5", {}).get("cmf_div_bearish")` |
| `cmf_div_strength` | I5/patterns (CMFDivergence) | `"i5"` | `frames.get("i5", {}).get("cmf_div_strength")` |
| `squeeze_active` | I5/patterns (BollingerSqueeze) | `"i5"` | `frames.get("i5", {}).get("squeeze_active")` |
| `squeeze_fired` | I5/patterns (BollingerSqueeze) | `"i5"` | `frames.get("i5", {}).get("squeeze_fired")` |
| `squeeze_bars` | I5/patterns (BollingerSqueeze) | `"i5"` | `frames.get("i5", {}).get("squeeze_bars")` |
| `hs_pattern` | I5/patterns (HeadShoulders) | `"i5"` | `frames.get("i5", {}).get("hs_pattern")` |
| `hs_confidence` | I5/patterns (HeadShoulders) | `"i5"` | `frames.get("i5", {}).get("hs_confidence")` |
| `dt_db_pattern` | I5/patterns (DoubleTB) | `"i5"` | `frames.get("i5", {}).get("dt_db_pattern")` |
| `dt_db_confidence` | I5/patterns (DoubleTB) | `"i5"` | `frames.get("i5", {}).get("dt_db_confidence")` |
| `trend_confluence_score` | I5/patterns (TrendConfluence) | `"i5"` | `frames.get("i5", {}).get("trend_confluence_score")` |
| `trend_confluence_n_signals` | I5/patterns (TrendConfluence) | `"i5"` | `frames.get("i5", {}).get("trend_confluence_n_signals")` |
| `trend_confluence_agreement` | I5/patterns (TrendConfluence) | `"i5"` | `frames.get("i5", {}).get("trend_confluence_agreement")` |
| `tri_breakout_bias` | I5/patterns (TriangleWedge) | `"i5"` | `frames.get("i5", {}).get("tri_breakout_bias")` |
| `tri_confidence` | I5/patterns (TriangleWedge) | `"i5"` | `frames.get("i5", {}).get("tri_confidence")` |
| `engulfing_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("engulfing_bull")` |
| `engulfing_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("engulfing_bear")` |
| `pin_bar_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("pin_bar_bull")` |
| `pin_bar_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("pin_bar_bear")` |
| `hammer_detected` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("hammer_detected")` |
| `shooting_star_detected` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("shooting_star_detected")` |
| `morning_star` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("morning_star")` |
| `evening_star` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("evening_star")` |
| `three_white_soldiers` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("three_white_soldiers")` |
| `three_black_crows` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("three_black_crows")` |
| `three_inside_up` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("three_inside_up")` |
| `three_inside_down` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("three_inside_down")` |
| `harami_cross` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("harami_cross")` |
| `dark_cloud_cover` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("dark_cloud_cover")` |
| `piercing_line` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("piercing_line")` |
| `harami_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("harami_bull")` |
| `harami_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("harami_bear")` |
| `abandoned_baby_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("abandoned_baby_bull")` |
| `abandoned_baby_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("abandoned_baby_bear")` |
| `tweezer_top` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("tweezer_top")` |
| `tweezer_bottom` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("tweezer_bottom")` |
| `belt_hold_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("belt_hold_bull")` |
| `belt_hold_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("belt_hold_bear")` |
| `kicker_bull` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("kicker_bull")` |
| `kicker_bear` | I5/patterns (CandlestickPatterns) | `"i5"` | `frames.get("i5", {}).get("kicker_bear")` |
| `ctf_score` | I6/confluence (CrossTimeframe) | `"i6"` | `frames.get("i6", {}).get("ctf_score")` |
| `ctf_trend_alignment` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_trend_alignment")` |
| `ctf_structure_alignment` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_structure_alignment")` |
| `ctf_regime_agreement` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_regime_agreement")` |
| `ctf_timeframes_aligned` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_timeframes_aligned")` |
| `ctf_highest_aligned_tf` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_highest_aligned_tf")` |
| `ctf_fvg_alignment` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_fvg_alignment")` |
| `ctf_ob_alignment` | I6/confluence | `"i6"` | `frames.get("i6", {}).get("ctf_ob_alignment")` |
| `ctf_momentum_divergence` | I6/confluence (CrossTFMomentum) | `"i6"` | `frames.get("i6", {}).get("ctf_momentum_divergence")` |
| `ctf_momentum_regime` | I6/confluence (CrossTFMomentum) | `"i6"` | `frames.get("i6", {}).get("ctf_momentum_regime")` |
| `ctf_sr_confluence` | I6/confluence (CrossTFSR) | `"i6"` | `frames.get("i6", {}).get("ctf_sr_confluence")` |
| `ctf_sr_regime` | I6/confluence (CrossTFSR) | `"i6"` | `frames.get("i6", {}).get("ctf_sr_regime")` |
| `ctf_hmm_regime_agreement` | I6/confluence (CrossTFRegimeAgreement) | `"i6"` | `frames.get("i6", {}).get("ctf_hmm_regime_agreement")` |
| `ctf_hmm_regime_label` | I6/confluence (CrossTFRegimeAgreement) | `"i6"` | `frames.get("i6", {}).get("ctf_hmm_regime_label")` |
| `ctf_volatility_divergence` | I6/confluence (SqueezeExpansionDiv) | `"i6"` | `frames.get("i6", {}).get("ctf_volatility_divergence")` |
| `ctf_volatility_regime` | I6/confluence (SqueezeExpansionDiv) | `"i6"` | `frames.get("i6", {}).get("ctf_volatility_regime")` |
| `ctf_orderflow_alignment` | I6/confluence (CrossTFOrderFlow) | `"i6"` | `frames.get("i6", {}).get("ctf_orderflow_alignment")` |
| `ctf_orderflow_regime` | I6/confluence (CrossTFOrderFlow) | `"i6"` | `frames.get("i6", {}).get("ctf_orderflow_regime")` |

## Fields Not Found in Tier Schemas (INVESTIGATION NEEDED or pipeline-internal)

These fields were found in `frames.get("features")` reads but do NOT appear in any tier Pydantic model:

| flat_field | Where Used | Notes |
|-----------|-----------|-------|
| `close` | volume_events.py, volume_profile.py, cross_tf_sr_confluence.py, others | Bar OHLCV — comes from `frames["main"].iloc[-1]["close"]` or bar.close, NOT from tier dicts. Plugins reading this from features must fall back to the DataFrame. |
| `volume` | volume_events.py, others | Bar OHLCV — same as `close`. Read from DataFrame. |
| `price` | ma_composites.py | Bar price — same pattern. Defaults to `frames["main"].iloc[-1]["close"]`. |
| `timeframe` | fvg_fill.py, poc_rejection.py, liquidity_hunt.py, trend_following.py, others | Metadata string, not a computed feature. Available from `bar.tf`. |
| `timestamp` | fvg_fill.py, poc_rejection.py, others | Bar timestamp — available from `bar.ts`. |
| `symbol` | (inferred from context) | Available from `bar.symbol`. |
| `donchian_high_20` | orb15.py, orb30.py | Dynamic I1 field (DonchianPlugin extra outputs) — tier key `"i1"` |
| `donchian_low_20` | orb15.py, orb30.py | Dynamic I1 field — tier key `"i1"` |
| `donchian_mid_20` | orb15.py, orb30.py | Dynamic I1 field — tier key `"i1"` |
| `sr_nearest_resistance` | (some patterns) | Possible alias for `nearest_resistance` in I3 |
| `sr_nearest_support` | (some patterns) | Possible alias for `nearest_support` in I3 |
| `vwap` | anchored_vwap_reversion.py | Alias — likely `session_vwap` from I4. |
| `vwap_upper_1` | (trading plugins) | AnchoredVWAP band — `avwap_upper_band` in I4 |
| `vwap_lower_1` | (trading plugins) | AnchoredVWAP band — `avwap_lower_band` in I4 |
| `vwap_std` | (trading plugins) | AnchoredVWAP std — investigate which I4 field maps |

**Resolution for OHLCV pipeline-internal fields:** When a plugin reads `close`, `volume`, `price`, `timeframe`, `timestamp` from features, these should be read from the DataFrame (`frames.get("main")`) or from the bar context passed to the plugin. Since plugins receive `frames` which includes the `"main"` key, the correct migration is: `frames.get("main", pd.DataFrame()).iloc[-1].get("close")` or rely on `OHLCVBar` fields already in `frames`.

**Note:** The `timeframe` and `timestamp` fields are pipeline-internal metadata injected by the framework before plugin execution. They are not tier-schema fields. Plugins using them should read from `bar.tf` and `bar.ts` respectively (passed via context, not via features flat dict).

## Authoritative File List (grep output)

Files containing `frames.get("features"` or `frames["features"]` as of 2026-06-02:

```
src/intelligence/composites/acceleration_regime.py
src/intelligence/composites/adx_events.py
src/intelligence/composites/derivative_oscillator.py
src/intelligence/composites/donchian_position.py
src/intelligence/composites/exhaustion_score.py
src/intelligence/composites/ma_composites.py
src/intelligence/composites/momentum_accel.py
src/intelligence/composites/rsi_events.py
src/intelligence/composites/stochastic_events.py
src/intelligence/composites/volume_events.py
src/intelligence/confluence/cross_tf_sr_confluence.py
src/intelligence/confluence/cross_timeframe.py
src/intelligence/context/anchored_vwap.py
src/intelligence/context/kalman_trend.py
src/intelligence/context/momentum_context.py
src/intelligence/context/trend_regime.py
src/intelligence/context/volume_profile.py
src/intelligence/features/i3_structure/fibonacci_zones.py
src/intelligence/features/i3_structure/macd_events.py
src/intelligence/features/i3_structure/market_profile.py
src/intelligence/features/i3_structure/session_levels.py
src/intelligence/features/i3_structure/swing_momentum.py
src/intelligence/features/i3_structure/trend_structure.py
src/intelligence/features/i5_patterns/candlestick_patterns.py
src/intelligence/features/i5_patterns/confluence.py
src/intelligence/features/i5_patterns/key_level_reaction.py
src/intelligence/features/i5_patterns/measured_move.py
src/intelligence/features/i5_patterns/mtf_volatility.py
src/intelligence/features/i5_patterns/trend_confluence.py
src/intelligence/features/smc_context/bocpd_changepoint.py
src/intelligence/features/smc_context/bos_choch.py
src/intelligence/features/smc_context/breaker_blocks.py
src/intelligence/features/smc_context/hmm_regime.py
src/intelligence/features/smc_context/mitigation_blocks.py
src/intelligence/features/smc_context/premium_discount.py
src/intelligence/features/smc_context/supply_demand_zones.py
src/intelligence/trading/anchored_vwap_reversion.py
src/intelligence/trading/atr_utils.py
src/intelligence/trading/candlestick_pattern_setup.py
src/intelligence/trading/choch_reversal.py
src/intelligence/trading/confidence_utils.py
src/intelligence/trading/cross_asset_divergence.py
src/intelligence/trading/cvd_divergence.py
src/intelligence/trading/delta_exhaustion.py
src/intelligence/trading/divergence_stack.py
src/intelligence/trading/dual_divergence.py
src/intelligence/trading/exhaustion_utils.py
src/intelligence/trading/failed_breakout.py
src/intelligence/trading/fvg_fill.py
src/intelligence/trading/gap_analysis_setup.py
src/intelligence/trading/hvn_rejection.py
src/intelligence/trading/liquidity_hunt.py
src/intelligence/trading/liquidity_sweep_reclaim.py
src/intelligence/trading/lvn_breakout.py
src/intelligence/trading/mean_reversion.py
src/intelligence/trading/microstructure_utils.py
src/intelligence/trading/momentum_breakout.py
src/intelligence/trading/mtf_alignment.py
src/intelligence/trading/ofi_continuation.py
src/intelligence/trading/ofi_divergence.py
src/intelligence/trading/orb15.py
src/intelligence/trading/orb30.py
src/intelligence/trading/pattern_completion.py
src/intelligence/trading/poc_rejection.py
src/intelligence/trading/prev_day_level_test.py
src/intelligence/trading/regime_transition.py
src/intelligence/trading/second_leg_continuation.py
src/intelligence/trading/session_extremes_setup.py
src/intelligence/trading/squeeze_expansion.py
src/intelligence/trading/supply_demand_setup.py
src/intelligence/trading/trend_following.py
src/intelligence/trading/vcp.py
src/intelligence/trading/vwap_deviation.py
src/intelligence/trading/vwap_reclaim.py
src/intelligence/pipeline/executor.py  (dual-write producer — removed in task 4-1A)
src/intelligence/pipeline/feature_pipeline_executor.py  (hmm_regime read — migrated in task 4-1A)
```

**Total: 73 files** (71 plugin files + 2 pipeline infrastructure files).
The plan's files_modified list covers all plugin files correctly.

## Notes for Migration (4-1B)

1. **Most plugins** use the pattern `features = frames.get("features") or {}` — replace with `features = {**frames.get("i1", {}), **frames.get("i2", {}), ...}` only for the tiers the plugin actually reads from. Better: replace individual `features.get("field_x")` calls with `frames.get("tier_key", {}).get("field_x")` directly.

2. **Simpler approach**: Instead of replacing the assignment, replace the downstream `features.get("X")` calls with `frames.get(tier, {}).get("X")`. This is more targeted and avoids unnecessary dict merging.

3. **OHLCV pipeline-internal fields** (`close`, `volume`, `price`, `timeframe`, `timestamp`): these are in the `"main"` DataFrame. Read from `frames.get("main")` — the df is already in frames. Specific migration: `df = frames.get("main"); close = df["close"].iloc[-1] if df is not None and len(df) else None`.

4. **Cross-tier reads** (a plugin reading from multiple tiers): each field access should use its specific tier key. No merging needed.
