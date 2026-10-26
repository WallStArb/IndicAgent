"""Shared test helper for FeatureVectorPipeline unit tests: the __new__() agent factory."""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from services.feature_vector_pipeline import FeatureVectorPipeline
from src.core.bar_history import BarHistory
from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.state_manager import PluginStateManager


def make_agent() -> FeatureVectorPipeline:
    """Create an FeatureVectorPipeline via __new__() with required attrs.

    Bypasses __init__ so tests can inject only the state they need without
    touching live Kafka, DB, or plugin registry.  Pattern from CLAUDE.md.
    """
    agent = FeatureVectorPipeline.__new__(FeatureVectorPipeline)
    agent.name = "feature_vector_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._state_mgr = PluginStateManager(
        checkpoint_path=pathlib.Path(tempfile.mkdtemp()) / "ckpt.json"
    )
    agent._pipeline_latency = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent._bar_history = BarHistory(maxlen=200)
    _db = AsyncMock()
    _db.execute_query = AsyncMock(return_value=[])
    # self._db is the daemon's own DB handle (Plan 151-09 Task 2's
    # _load_cross_asset_series() reads market_data_ohlcv_tradeable through it) --
    # same mock instance, execute_query([]) by default so a test that doesn't care
    # about cross-asset state gets an empty (all-0.0-default) series harmlessly.
    agent._db = _db
    agent._feature_caches = {}
    # Cross-asset daily series (Plan 151-09 Task 2) -- _cross_asset_built_on defaults
    # to "today" (matching production state right after _setup() has run) so a bare
    # _process_bar_compute() call in a pre-existing test does NOT spawn a day-rollover
    # refresh background task; tests that specifically want to exercise the rollover
    # set agent._cross_asset_built_on to a past date themselves.
    agent._cross_asset_by_date = {}
    agent._cross_asset_dates_sorted = []
    agent._cross_asset_built_on = datetime.now(UTC).date()
    agent._kafka_producer = AsyncMock()
    agent._background_tasks = set()
    agent._bar_e2e_latency = MagicMock()
    agent._out_queue = OutputQueue(producer=MagicMock(), maxsize=500)
    # FeatureFactoryConfig required by _process_bar_compute() assertion.
    # Seeded with default values matching APR defaults.
    from src.intelligence.feature_factory import FeatureFactoryConfig, invert_ctf_higher_tf_map

    agent._feature_factory_config = FeatureFactoryConfig(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=252,
        volume_zscore_window=20,
        ofi_zscore_window=20,
        cvd_slope_bars=5,
        cmf_period=20,
        vol_short_bars=5,
        vol_long_bars=20,
        hma_period=20,
        adx_period=14,
        hurst_window=252,
        garch_window=100,
        vix_zscore_window=252,
        yield_curve_zscore_window=252,
        regime_cache_refresh_bars=30,
        rsi_fast_period=7,
        rsi_mid_period=14,
        rsi_slow_period=28,
        cci_fast_period=10,
        cci_mid_period=20,
        cci_slow_period=40,
        aroon_fast_period=14,
        aroon_slow_period=25,
        amihud_zscore_window=252,
        ret_skew_window=60,
        ret_skew_zscore_window=252,
        ret_acf_window=30,
        ret_acf_zscore_window=252,
        high_52w_window=252,
        min_bars_warmup=16,
        cross_asset_rv_window=20,
        ny_session_start_utc_hour=13,
        ny_session_start_utc_minute=30,
        ny_session_end_utc_hour=20,
        overlap_start_utc_hour=12,
        overlap_end_utc_hour=15,
        london_kz_start_utc_hour=7,
        london_kz_end_utc_hour=10,
        power_hour_start_utc_hour=19,
        power_hour_end_utc_hour=21,
        opening_range_start_minute=810,
        opening_range_end_minute=900,
        ret_lag_fast=5,
        ret_lag_mid=20,
        ret_lag_slow=60,
        overnight_gap_window=20,
        dollar_vol_window=20,
        vol_range_ratio_window=20,
        vol_trend_fast=5,
        vol_trend_slow=20,
        up_vol_ratio_fast=5,
        up_vol_ratio_slow=20,
        vol_percentile_window=20,
        vol_persistence_window=20,
        vol_std_window=20,
        mfi_fast=7,
        mfi_slow=14,
        obv_window=20,
        dist_window_fast=20,
        dist_window_slow=50,
        range_window_fast=20,
        range_window_slow=50,
        stoch_window_fast=14,
        stoch_window_slow=50,
        percentile_window_fast=50,
        percentile_window_slow=200,
        efficiency_window_fast=10,
        efficiency_window_slow=50,
        ret_kurtosis_fast=10,
        ret_kurtosis_slow=40,
        ret_kurtosis_zscore_window=20,
        updown_ratio_fast=5,
        updown_ratio_slow=20,
        streak_window=20,
        realized_var_fast=5,
        realized_var_slow=20,
        vol_of_vol_window=20,
        high_low_corr_window=20,
        variance_ratio_fast=5,
        variance_ratio_slow=20,
        vol_asymmetry_window=20,
        bb_pct_b_fast=20,
        bb_pct_b_slow=50,
        hv_fast=10,
        hv_slow=30,
        hv_ratio_window=20,
        parkinson_vol_window=10,
        parkinson_vol_zscore_window=20,
        garman_klass_vol_window=10,
        garman_klass_vol_zscore_window=20,
        yang_zhang_vol_window=20,
        yang_zhang_vol_zscore_window=20,
        vol_velocity_window=20,
        intraday_noise_window=20,
        price_vol_corr_fast=10,
        price_vol_corr_slow=30,
        momentum_velocity_window=20,
        rsi_velocity_window=20,
        ofi_velocity_window=20,
        cvd_velocity_window=20,
        volume_velocity_window=20,
        vwap_velocity_window=20,
        extreme_move_sigma_threshold=2.0,
        vol_spike_threshold=2.0,
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
    )
    # Inverse of ctf_higher_tf_map -- normally derived in
    # FeatureVectorPipeline._prewarm_threshold_config() (todo 242), which __new__()
    # bypasses here, so it must be built the same way by hand via the shared helper.
    agent._ctf_lower_tfs = invert_ctf_higher_tf_map(agent._feature_factory_config.ctf_higher_tf_map)
    return agent


def deterministic_plugin(output_dict: dict):
    """Plugin that always returns a copy of output_dict — no side effects."""

    class _Plugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            return dict(output_dict)

    return _Plugin()


def signal_plugin(plugin_name: str, direction: int = 1):
    """I7 plugin that always returns a fixed signal dict."""

    class _Plugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            return {
                "direction": direction,
                "confidence": 0.75,
                "setup_plugin": plugin_name,
                "stop_distance_atr": 1.0,
                "entry_price": 100.0,
            }

    return _Plugin()
