# Archived I5/I6/I7 Modules

Archived in Phase 137 Plan 6 (D-09 cutover). All files are intact and unmodified.

## Why Archived

The v3.0 ground-up rebuild (Phase 137) replaces the 138-plugin I5/I6/I7 dispatch
layer with `FeatureFactory.compute()` — a single pure-function call that produces
36 typed `FeatureVector` primitives per bar. The plugin system is retired from the
live pipeline but preserved here as institutional memory.

Phase 138 (IC discovery) will determine which I7 signal patterns have positive
expected value and deserve promotion to alpha scorers in the v3.0 AlphaEngine.

## Archived Tiers

### I5 Patterns (`i5_patterns/`)

16 pattern-detection plugins (moved from `src/intelligence/features/i5_patterns/`):

- bollinger_squeeze.py
- candlestick_patterns.py
- cmf_divergence.py
- confluence.py
- cup_handle.py
- double_top_bottom.py
- flag_pennant.py
- head_shoulders.py
- key_level_reaction.py
- macd_divergence.py
- measured_move.py
- mtf_volatility.py
- rsi_divergence.py
- trend_confluence.py
- triangle_wedge.py
- volume_divergence.py

### I6 SMC Context (`smc_context/`)

16 Smart Money Concepts plugins (moved from `src/intelligence/features/smc_context/`):

- amd_cycle.py
- bocpd_changepoint.py
- bos_choch.py
- breaker_blocks.py
- fair_value_gap.py
- hmm_regime.py
- ict_killzones.py
- liquidity_pools.py
- liquidity_sweeps.py
- mitigation_blocks.py
- order_blocks.py
- premium_discount.py
- supply_demand_zones.py

### I6 Confluence (`confluence/`)

6 cross-timeframe confluence plugins (moved from `src/intelligence/confluence/`):

- cross_tf_momentum_divergence.py
- cross_tf_orderflow_alignment.py
- cross_tf_regime_agreement.py
- cross_tf_sr_confluence.py
- cross_timeframe.py
- squeeze_expansion_divergence.py
- confluence_alignment.py
- confluence_smc.py
- confluence_weights.py

### I7 Trading Signal Plugins (`trading_i7/`)

36 signal-generation plugins (moved from `src/intelligence/trading/`).
All were registered in `TIER_I7` (or logically I7 scope):

- anchored_vwap_reversion.py
- candlestick_pattern_setup.py
- choch_reversal.py
- cross_asset_divergence.py
- cvd_divergence.py
- cvd_spike.py
- delta_exhaustion.py
- divergence_stack.py
- dual_divergence.py
- failed_breakout.py
- fvg_fill.py (removed from TIER_I7 before archival due to entry-timing defect)
- gap_analysis_setup.py
- hvn_rejection.py
- liquidity_hunt.py
- liquidity_sweep_reclaim.py
- lvn_breakout.py
- mean_reversion.py
- momentum_breakout.py
- mtf_alignment.py
- ofi_continuation.py
- ofi_divergence.py
- ofi_spike.py
- orb15.py
- orb30.py
- pattern_completion.py
- poc_rejection.py
- prev_day_level_test.py
- regime_transition.py
- second_leg_continuation.py
- session_extremes_setup.py
- squeeze_expansion.py
- supply_demand_setup.py
- trend_following.py
- vcp.py
- vwap_deviation.py
- vwap_reclaim.py

## What Stays Live

The following shared utilities remain in `src/intelligence/trading/` and are
still used by non-I7 services (lifecycle tracking, trade framing, signal schema):

- aggregator.py
- atr_utils.py
- cis_scorer.py
- confidence.py
- exhaustion_utils.py
- lifecycle_tracker.py
- lifecycle_transitions.py
- microstructure_utils.py
- plugin_utils.py
- position_sizer.py
- signal_outcome.py
- signal_schema.py
- state_utils.py
- trade_framer.py
- volume_profile_utils.py
- volume_zscore.py
- zone_engine.py

## Phase 138 Plan

IC (Information Coefficient) measurement will run on the archived I7 patterns
against the `feature_vectors` corpus. Patterns with IC > 0 and p < 0.05
at N >= 100 observations will be promoted as alpha scorers in the AlphaEngine.
