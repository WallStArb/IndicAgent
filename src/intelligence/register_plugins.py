from __future__ import annotations

from .composites.ma_composites import plugin as ma_compare_plugin
from .confluence.cross_timeframe import plugin as ctf_plugin
from .context.garch_volatility import plugin as garch_vol_plugin
from .context.kalman_trend import plugin as kalman_trend_plugin
from .context.momentum_context import plugin as momentum_ctx_plugin
from .context.trend_regime import plugin as trend_regime_plugin
from .context.volatility_regime import plugin as vol_regime_plugin
from .indicators.adx import plugin as adx_plugin
from .indicators.atr import plugin as atr_plugin
from .indicators.bollinger import plugin as bb_plugin
from .indicators.cci import plugin as cci_plugin
from .indicators.donchian import plugin as donchian_plugin
from .indicators.keltner import plugin as keltner_plugin
from .indicators.aroon import plugin as aroon_plugin
from .indicators.chandelier import plugin as chandelier_plugin
from .indicators.cmf import plugin as cmf_plugin
from .indicators.historical_volatility import plugin as hv_plugin
from .indicators.macd import plugin as macd_plugin
from .indicators.parabolic_sar import plugin as psar_plugin
from .indicators.stochastic_rsi import plugin as stoch_rsi_plugin
from .indicators.mfi import plugin as mfi_plugin
from .indicators.moving_averages import plugin as ma_plugin
from .indicators.obv import plugin as obv_plugin
from .indicators.roc_ppo import plugin as roc_ppo_plugin
from .indicators.rsi import plugin as rsi_plugin
from .indicators.stochastic import plugin as stoch_plugin
from .indicators.supertrend import plugin as supertrend_plugin
from .indicators.vwap import plugin as vwap_plugin
from .indicators.williams_r import plugin as wr_plugin
from .patterns.bollinger_squeeze import plugin as squeeze_plugin
from .patterns.confluence import plugin as confluence_plugin
from .patterns.double_top_bottom import plugin as double_tb_plugin
from .patterns.head_shoulders import plugin as head_shoulders_plugin
from .patterns.rsi_divergence import plugin as rsi_div_plugin
from .patterns.trend_confluence import plugin as trend_confluence_plugin
from .patterns.triangle_wedge import plugin as triangle_wedge_plugin
from .patterns.volume_divergence import plugin as vol_div_plugin
from .plugins import registry
from .smart_money.bocpd_changepoint import plugin as bocpd_plugin
from .smart_money.bos_choch import plugin as bos_choch_plugin
from .smart_money.fair_value_gap import plugin as fvg_plugin
from .smart_money.hmm_regime import plugin as hmm_plugin
from .smart_money.liquidity_sweeps import plugin as liq_sweep_plugin
from .smart_money.order_blocks import plugin as ob_plugin
from .structure.support_resistance import plugin as sr_plugin
from .structure.swing_detector import plugin as swing_plugin
from .structure.trend_structure import plugin as trend_plugin
from .trading.liquidity_sweep_reclaim import plugin as liq_sweep_reclaim_plugin
from .trading.mean_reversion import plugin as mean_revert_plugin
from .trading.mtf_alignment import plugin as mtf_align_plugin
from .trading.squeeze_expansion import plugin as squeeze_exp_plugin
from .trading.trend_following import plugin as trend_follow_plugin


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

    registry.register_pattern(rsi_div_plugin)
    registry.register_pattern(squeeze_plugin)
    registry.register_pattern(vol_div_plugin)
    registry.register_pattern(confluence_plugin)
    registry.register_pattern(trend_confluence_plugin)

    registry.register_pattern(swing_plugin)
    registry.register_pattern(sr_plugin)
    registry.register_pattern(trend_plugin)

    registry.register_pattern(vol_regime_plugin)
    registry.register_pattern(trend_regime_plugin)
    registry.register_pattern(momentum_ctx_plugin)
    registry.register_pattern(garch_vol_plugin)
    registry.register_pattern(kalman_trend_plugin)

    registry.register_pattern(bos_choch_plugin)
    registry.register_pattern(fvg_plugin)
    registry.register_pattern(ob_plugin)
    registry.register_pattern(liq_sweep_plugin)
    registry.register_pattern(bocpd_plugin)
    registry.register_pattern(hmm_plugin)

    registry.register_pattern(ctf_plugin)

    # I5 Chart Patterns
    registry.register_pattern(double_tb_plugin)
    registry.register_pattern(head_shoulders_plugin)
    registry.register_pattern(triangle_wedge_plugin)

    # I7 Trading Setups
    registry.register_pattern(trend_follow_plugin)
    registry.register_pattern(mean_revert_plugin)
    registry.register_pattern(liq_sweep_reclaim_plugin)
    registry.register_pattern(mtf_align_plugin)
    registry.register_pattern(squeeze_exp_plugin)
