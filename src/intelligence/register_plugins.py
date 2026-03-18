from __future__ import annotations

from .composites.acceleration_regime import plugin as accel_regime_plugin
from .composites.adx_events import plugin as adx_events_plugin
from .composites.derivative_oscillator import plugin as deriv_osc_plugin
from .composites.donchian_position import plugin as donchian_pos_plugin
from .composites.exhaustion_score import plugin as exhaustion_score_plugin
from .composites.ma_composites import plugin as ma_compare_plugin
from .composites.macd_events import plugin as macd_events_plugin
from .composites.momentum_accel import plugin as momentum_accel_plugin
from .composites.obv_momentum import plugin as obv_momentum_plugin
from .composites.rsi_events import plugin as rsi_events_plugin
from .composites.stochastic_events import plugin as stoch_events_plugin
from .composites.volume_events import plugin as volume_events_plugin
from .confluence.cross_timeframe import plugin as ctf_plugin
from .context.anchored_vwap import plugin as anchored_vwap_plugin
from .context.garch_volatility import plugin as garch_vol_plugin
from .context.hurst_exponent import plugin as hurst_plugin
from .context.kalman_trend import plugin as kalman_trend_plugin
from .context.momentum_context import plugin as momentum_ctx_plugin
from .context.mtf_volatility import plugin as mtf_vol_plugin
from .context.session_context import plugin as session_ctx_plugin
from .context.shannon_entropy import plugin as shannon_plugin
from .context.trend_regime import plugin as trend_regime_plugin
from .context.volatility_regime import plugin as vol_regime_plugin
from .context.volume_profile import plugin as volume_profile_plugin
from .indicators.ac_oscillator import plugin as ac_osc_plugin
from .indicators.adx import plugin as adx_plugin
from .indicators.aroon import plugin as aroon_plugin
from .indicators.atr import plugin as atr_plugin
from .indicators.bollinger import plugin as bb_plugin
from .indicators.cci import plugin as cci_plugin
from .indicators.chandelier import plugin as chandelier_plugin
from .indicators.cmf import plugin as cmf_plugin
from .indicators.cvd import plugin as cvd_plugin
from .indicators.donchian import plugin as donchian_plugin
from .indicators.historical_volatility import plugin as hv_plugin
from .indicators.hma import plugin as hma_plugin
from .indicators.keltner import plugin as keltner_plugin
from .indicators.macd import plugin as macd_plugin
from .indicators.mfi import plugin as mfi_plugin
from .indicators.moving_averages import plugin as ma_plugin
from .indicators.obv import plugin as obv_plugin
from .indicators.ofi import plugin as ofi_plugin
from .indicators.parabolic_sar import plugin as psar_plugin
from .indicators.roc_ppo import plugin as roc_ppo_plugin
from .indicators.rsi import plugin as rsi_plugin
from .indicators.stochastic import plugin as stoch_plugin
from .indicators.stochastic_rsi import plugin as stoch_rsi_plugin
from .indicators.supertrend import plugin as supertrend_plugin
from .indicators.vwap import plugin as vwap_plugin
from .indicators.williams_r import plugin as wr_plugin
from .patterns.bollinger_squeeze import plugin as squeeze_plugin
from .patterns.candlestick_patterns import plugin as candlestick_plugin
from .patterns.cmf_divergence import plugin as cmf_div_plugin
from .patterns.confluence import plugin as confluence_plugin
from .patterns.cup_handle import plugin as cup_handle_plugin
from .patterns.double_top_bottom import plugin as double_tb_plugin
from .patterns.flag_pennant import plugin as flag_pennant_plugin
from .patterns.head_shoulders import plugin as head_shoulders_plugin
from .patterns.key_level_reaction import plugin as key_level_reaction_plugin
from .patterns.macd_divergence import plugin as macd_div_plugin
from .patterns.measured_move import plugin as measured_move_plugin
from .patterns.rsi_divergence import plugin as rsi_div_plugin
from .patterns.trend_confluence import plugin as trend_confluence_plugin
from .patterns.triangle_wedge import plugin as triangle_wedge_plugin
from .patterns.volume_divergence import plugin as vol_div_plugin
from .plugins import registry
from .schemas import I3Structure, I4Context, I5Patterns, I6Confluence, SMCContext
from .smart_money.amd_cycle import plugin as amd_cycle_plugin
from .smart_money.bocpd_changepoint import plugin as bocpd_plugin
from .smart_money.bos_choch import plugin as bos_choch_plugin
from .smart_money.breaker_blocks import plugin as breaker_blocks_plugin
from .smart_money.fair_value_gap import plugin as fvg_plugin
from .smart_money.hmm_regime import plugin as hmm_plugin
from .smart_money.ict_killzones import plugin as ict_killzones_plugin
from .smart_money.liquidity_pools import plugin as liquidity_pools_plugin
from .smart_money.liquidity_sweeps import plugin as liq_sweep_plugin
from .smart_money.mitigation_blocks import plugin as mitigation_blocks_plugin
from .smart_money.order_blocks import plugin as ob_plugin
from .smart_money.premium_discount import plugin as premium_discount_plugin
from .smart_money.supply_demand_zones import plugin as supply_demand_zones_plugin
from .structure.fibonacci_zones import plugin as fib_zones_plugin
from .structure.market_profile import plugin as market_profile_plugin
from .structure.session_levels import plugin as session_levels_plugin
from .structure.support_resistance import plugin as sr_plugin
from .structure.swing_detector import plugin as swing_plugin
from .structure.swing_momentum import plugin as swing_momentum_plugin
from .structure.trend_structure import plugin as trend_plugin
from .trading.anchored_vwap_reversion import plugin as anchored_vwap_reversion_plugin
from .trading.candlestick_pattern_setup import plugin as candlestick_pattern_setup_plugin
from .trading.choch_reversal import plugin as choch_reversal_plugin
from .trading.divergence_stack import plugin as divergence_stack_plugin
from .trading.failed_breakout import plugin as failed_breakout_plugin
from .trading.fvg_fill import plugin as fvg_fill_plugin
from .trading.gap_analysis_setup import plugin as gap_analysis_setup_plugin
from .trading.hvn_rejection import plugin as hvn_rejection_plugin
from .trading.liquidity_hunt import plugin as liquidity_hunt_plugin
from .trading.liquidity_sweep_reclaim import plugin as liq_sweep_reclaim_plugin
from .trading.lvn_breakout import plugin as lvn_breakout_plugin
from .trading.mean_reversion import plugin as mean_revert_plugin
from .trading.momentum_breakout import plugin as momentum_breakout_plugin
from .trading.mtf_alignment import plugin as mtf_align_plugin
from .trading.orb15 import plugin as orb15_plugin
from .trading.orb30 import plugin as orb30_plugin
from .trading.pattern_completion import plugin as pattern_completion_plugin
from .trading.poc_rejection import plugin as poc_rejection_plugin
from .trading.prev_day_level_test import plugin as prev_day_level_test_plugin
from .trading.regime_transition import plugin as regime_transition_plugin
from .trading.second_leg_continuation import plugin as second_leg_continuation_plugin
from .trading.session_extremes_setup import plugin as session_extremes_setup_plugin
from .trading.squeeze_expansion import plugin as squeeze_exp_plugin
from .trading.supply_demand_setup import plugin as supply_demand_setup_plugin
from .trading.trend_following import plugin as trend_follow_plugin
from .trading.vcp import plugin as vcp_plugin
from .trading.vwap_deviation import plugin as vwap_deviation_plugin
from .trading.vwap_reclaim import plugin as vwap_reclaim_plugin


def validate_schema_coverage() -> None:
    """Verify every extra='forbid' schema declares all plugin output fields.

    Called at the end of register_all_plugins(). Raises RuntimeError immediately
    if any plugin outputs a field not declared in its tier schema — catching the
    class of bug that silently breaks seed publish on service restart.

    I1 and I2 are skipped (extra='allow').
    """
    tier_checks: list[tuple[str, list, type]] = [
        ("I3", [swing_plugin, sr_plugin, trend_plugin, market_profile_plugin,
                session_levels_plugin, fib_zones_plugin,
                swing_momentum_plugin], I3Structure),
        ("I4", [vol_regime_plugin, trend_regime_plugin, momentum_ctx_plugin,
                garch_vol_plugin, hurst_plugin, shannon_plugin,
                kalman_trend_plugin, session_ctx_plugin, mtf_vol_plugin,
                anchored_vwap_plugin, volume_profile_plugin], I4Context),
        ("I5", [rsi_div_plugin, squeeze_plugin, vol_div_plugin, confluence_plugin,
                trend_confluence_plugin, double_tb_plugin, head_shoulders_plugin,
                triangle_wedge_plugin, candlestick_plugin, flag_pennant_plugin,
                cup_handle_plugin, measured_move_plugin,
                key_level_reaction_plugin, macd_div_plugin, cmf_div_plugin], I5Patterns),
        ("SMC", [bos_choch_plugin, fvg_plugin, ob_plugin, liq_sweep_plugin,
                 bocpd_plugin, hmm_plugin, liquidity_pools_plugin,
                 supply_demand_zones_plugin, ict_killzones_plugin, amd_cycle_plugin,
                 breaker_blocks_plugin, mitigation_blocks_plugin,
                 premium_discount_plugin], SMCContext),
        ("I6", [ctf_plugin], I6Confluence),
    ]

    gaps: list[str] = []
    for tier_name, plugins, schema_cls in tier_checks:
        schema_fields = set(schema_cls.model_fields.keys())
        for plugin in plugins:
            missing = plugin.outputs - schema_fields
            if missing:
                gaps.append(
                    f"  [{tier_name}] {plugin.name}: {sorted(missing)} "
                    f"not in {schema_cls.__name__}"
                )

    if gaps:
        raise RuntimeError(
            "Schema coverage gaps detected — add missing fields to schemas.py:\n"
            + "\n".join(gaps)
        )


def register_all_plugins() -> None:
    registry.register_indicator(rsi_plugin)
    registry.register_indicator(ma_plugin)
    registry.register_indicator(ma_compare_plugin)
    registry.register_indicator(macd_plugin)
    registry.register_indicator(atr_plugin)
    registry.register_indicator(bb_plugin)
    registry.register_indicator(stoch_plugin)
    registry.register_indicator(cci_plugin)
    registry.register_indicator(wr_plugin)
    registry.register_indicator(mfi_plugin)
    registry.register_indicator(obv_plugin)
    registry.register_indicator(vwap_plugin)
    registry.register_indicator(supertrend_plugin)
    registry.register_indicator(adx_plugin)
    registry.register_indicator(keltner_plugin)
    registry.register_indicator(donchian_plugin)
    registry.register_indicator(roc_ppo_plugin)
    registry.register_indicator(aroon_plugin)
    registry.register_indicator(chandelier_plugin)
    registry.register_indicator(cmf_plugin)
    registry.register_indicator(hv_plugin)
    registry.register_indicator(psar_plugin)
    registry.register_indicator(stoch_rsi_plugin)
    registry.register_indicator(ac_osc_plugin)
    registry.register_indicator(hma_plugin)
    registry.register_indicator(ofi_plugin)
    registry.register_indicator(cvd_plugin)

    # I2: Composite event plugins — run on I1 features, before I3
    registry.register_pattern(macd_events_plugin)
    registry.register_pattern(rsi_events_plugin)
    registry.register_pattern(stoch_events_plugin)
    registry.register_pattern(adx_events_plugin)
    registry.register_pattern(volume_events_plugin)
    registry.register_pattern(momentum_accel_plugin)
    registry.register_pattern(donchian_pos_plugin)
    registry.register_pattern(obv_momentum_plugin)
    registry.register_pattern(deriv_osc_plugin)
    registry.register_pattern(exhaustion_score_plugin)
    registry.register_pattern(accel_regime_plugin)

    registry.register_pattern(rsi_div_plugin)
    registry.register_pattern(squeeze_plugin)
    registry.register_pattern(vol_div_plugin)
    registry.register_pattern(macd_div_plugin)
    registry.register_pattern(cmf_div_plugin)
    registry.register_pattern(confluence_plugin)
    registry.register_pattern(trend_confluence_plugin)

    registry.register_pattern(swing_plugin)
    registry.register_pattern(sr_plugin)
    registry.register_pattern(trend_plugin)
    registry.register_pattern(market_profile_plugin)
    registry.register_pattern(session_levels_plugin)
    registry.register_pattern(anchored_vwap_plugin)
    registry.register_pattern(fib_zones_plugin)
    registry.register_pattern(swing_momentum_plugin)

    registry.register_pattern(vol_regime_plugin)
    registry.register_pattern(trend_regime_plugin)
    registry.register_pattern(momentum_ctx_plugin)
    registry.register_pattern(garch_vol_plugin)
    registry.register_pattern(hurst_plugin)
    registry.register_pattern(shannon_plugin)
    registry.register_pattern(kalman_trend_plugin)
    registry.register_pattern(session_ctx_plugin)
    registry.register_pattern(mtf_vol_plugin)

    registry.register_pattern(bos_choch_plugin)
    registry.register_pattern(fvg_plugin)
    registry.register_pattern(ob_plugin)
    registry.register_pattern(liq_sweep_plugin)
    registry.register_pattern(bocpd_plugin)
    registry.register_pattern(hmm_plugin)
    registry.register_pattern(liquidity_pools_plugin)
    registry.register_pattern(supply_demand_zones_plugin)
    registry.register_pattern(ict_killzones_plugin)
    registry.register_pattern(amd_cycle_plugin)
    registry.register_pattern(breaker_blocks_plugin)
    registry.register_pattern(mitigation_blocks_plugin)
    registry.register_pattern(premium_discount_plugin)

    registry.register_pattern(ctf_plugin)

    # I5 Chart Patterns
    registry.register_pattern(double_tb_plugin)
    registry.register_pattern(head_shoulders_plugin)
    registry.register_pattern(triangle_wedge_plugin)
    registry.register_pattern(candlestick_plugin)
    registry.register_pattern(flag_pennant_plugin)
    registry.register_pattern(cup_handle_plugin)
    registry.register_pattern(measured_move_plugin)
    registry.register_pattern(volume_profile_plugin)
    registry.register_pattern(key_level_reaction_plugin)

    # I7 Trading Setups
    registry.register_pattern(trend_follow_plugin)
    registry.register_pattern(mean_revert_plugin)
    registry.register_pattern(liq_sweep_reclaim_plugin)
    registry.register_pattern(mtf_align_plugin)
    registry.register_pattern(squeeze_exp_plugin)
    registry.register_pattern(vwap_deviation_plugin)
    registry.register_pattern(momentum_breakout_plugin)
    registry.register_pattern(liquidity_hunt_plugin)
    registry.register_pattern(supply_demand_setup_plugin)
    registry.register_pattern(choch_reversal_plugin)
    registry.register_pattern(fvg_fill_plugin)
    registry.register_pattern(pattern_completion_plugin)
    registry.register_pattern(divergence_stack_plugin)
    registry.register_pattern(regime_transition_plugin)
    registry.register_pattern(gap_analysis_setup_plugin)
    registry.register_pattern(candlestick_pattern_setup_plugin)
    registry.register_pattern(session_extremes_setup_plugin)
    registry.register_pattern(failed_breakout_plugin)
    registry.register_pattern(orb15_plugin)
    registry.register_pattern(orb30_plugin)
    registry.register_pattern(prev_day_level_test_plugin)
    registry.register_pattern(second_leg_continuation_plugin)
    registry.register_pattern(vcp_plugin)
    registry.register_pattern(anchored_vwap_reversion_plugin)
    registry.register_pattern(vwap_reclaim_plugin)
    registry.register_pattern(poc_rejection_plugin)
    registry.register_pattern(hvn_rejection_plugin)
    registry.register_pattern(lvn_breakout_plugin)

    validate_schema_coverage()


# ---------------------------------------------------------------------------
# Canonical tier plugin lists — single source of truth.
# Built from plugin.name attributes so any rename propagates automatically.
# Services import these instead of maintaining their own string lists.
# ---------------------------------------------------------------------------

TIER_I1: list[str] = [
    rsi_plugin.name,
    ma_plugin.name,
    ma_compare_plugin.name,
    macd_plugin.name,
    atr_plugin.name,
    bb_plugin.name,
    stoch_plugin.name,
    cci_plugin.name,
    wr_plugin.name,
    mfi_plugin.name,
    obv_plugin.name,
    vwap_plugin.name,
    supertrend_plugin.name,
    adx_plugin.name,
    keltner_plugin.name,
    donchian_plugin.name,
    roc_ppo_plugin.name,
    aroon_plugin.name,
    chandelier_plugin.name,
    cmf_plugin.name,
    hv_plugin.name,
    psar_plugin.name,
    stoch_rsi_plugin.name,
    ac_osc_plugin.name,
    hma_plugin.name,  # 'HMA'
    ofi_plugin.name,  # 'ind_OFI'
    cvd_plugin.name,  # 'ind_CVD'
]

TIER_I2: list[str] = [
    macd_events_plugin.name,
    rsi_events_plugin.name,
    stoch_events_plugin.name,
    adx_events_plugin.name,
    volume_events_plugin.name,
    momentum_accel_plugin.name,
    donchian_pos_plugin.name,
    obv_momentum_plugin.name,
    deriv_osc_plugin.name,
    exhaustion_score_plugin.name,  # "cmp_ExhaustionScore"
    accel_regime_plugin.name,  # "cmp_AccelerationRegime"
]

TIER_I3: list[str] = [
    swing_plugin.name,
    sr_plugin.name,
    trend_plugin.name,
    market_profile_plugin.name,
    session_levels_plugin.name,
    fib_zones_plugin.name,
    swing_momentum_plugin.name,  # "struct_SwingMomentum"
]

TIER_I4: list[str] = [
    vol_regime_plugin.name,
    trend_regime_plugin.name,
    momentum_ctx_plugin.name,
    garch_vol_plugin.name,
    hurst_plugin.name,
    shannon_plugin.name,
    kalman_trend_plugin.name,
    session_ctx_plugin.name,
    mtf_vol_plugin.name,
    anchored_vwap_plugin.name,  # "ctx_AnchoredVWAP"
    volume_profile_plugin.name,  # "ctx_VolumeProfile"
]

TIER_I5: list[str] = [
    rsi_div_plugin.name,
    squeeze_plugin.name,
    vol_div_plugin.name,
    macd_div_plugin.name,
    cmf_div_plugin.name,
    confluence_plugin.name,
    trend_confluence_plugin.name,
    double_tb_plugin.name,
    head_shoulders_plugin.name,
    triangle_wedge_plugin.name,
    candlestick_plugin.name,
    flag_pennant_plugin.name,
    cup_handle_plugin.name,
    measured_move_plugin.name,
    key_level_reaction_plugin.name,
]

TIER_SMC: list[str] = [
    bos_choch_plugin.name,
    fvg_plugin.name,
    ob_plugin.name,
    liq_sweep_plugin.name,
    bocpd_plugin.name,
    hmm_plugin.name,
    liquidity_pools_plugin.name,
    supply_demand_zones_plugin.name,
    ict_killzones_plugin.name,
    amd_cycle_plugin.name,
    breaker_blocks_plugin.name,
    mitigation_blocks_plugin.name,
    premium_discount_plugin.name,
]

TIER_I6: list[str] = [
    ctf_plugin.name,
]

TIER_I7: list[str] = [
    trend_follow_plugin.name,
    mean_revert_plugin.name,
    liq_sweep_reclaim_plugin.name,
    mtf_align_plugin.name,
    squeeze_exp_plugin.name,
    vwap_deviation_plugin.name,
    momentum_breakout_plugin.name,
    liquidity_hunt_plugin.name,
    supply_demand_setup_plugin.name,
    choch_reversal_plugin.name,
    fvg_fill_plugin.name,
    pattern_completion_plugin.name,
    divergence_stack_plugin.name,
    regime_transition_plugin.name,
    gap_analysis_setup_plugin.name,
    candlestick_pattern_setup_plugin.name,
    session_extremes_setup_plugin.name,  # "trad_SessionExtremesSetup"
    failed_breakout_plugin.name,         # "trad_FailedBreakout"
    orb15_plugin.name,                   # "trad_ORB15"
    orb30_plugin.name,                   # "trad_ORB30"
    prev_day_level_test_plugin.name,     # "trad_PrevDayLevelTest"
    second_leg_continuation_plugin.name, # "trad_SecondLegContinuation"
    vcp_plugin.name,                     # "trad_VCP"
    anchored_vwap_reversion_plugin.name, # "trad_AnchoredVWAPReversion"
    vwap_reclaim_plugin.name,            # "trad_VWAPReclaim"
    poc_rejection_plugin.name,           # "trad_POCRejection"
    hvn_rejection_plugin.name,           # "trad_HVNRejection"
    lvn_breakout_plugin.name,            # "trad_LVNBreakout"
]
