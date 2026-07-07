"""Shared test helpers for intelligence pipeline unit tests.

Provides the __new__() agent factory and plugin stubs used across
test_pipeline_parallelization, test_pipeline_determinism, and
test_pipeline_exception_isolation.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock

from services.feature_vector_pipeline import FeatureVectorPipeline
from src.core.bar_history import BarHistory
from src.intelligence.pipeline.cache_manager import CacheManager
from src.intelligence.pipeline.executor import PluginExecutor
from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.signal_processor import SignalProcessor
from src.intelligence.pipeline.state_manager import PluginStateManager
from src.intelligence.trading.cis_scorer import CISScorer
from src.observability.plugin_observer import NoOpPluginObserver


def make_agent() -> FeatureVectorPipeline:
    """Create an FeatureVectorPipeline via __new__() with required attrs.

    Bypasses __init__ so tests can inject only the state they need without
    touching live Kafka, DB, or plugin registry.  Pattern from CLAUDE.md.

    Cache state is seeded via the public seed_* API on agent._cache_mgr.
    Never mutate agent._cache_mgr._* private attributes directly.
    """
    agent = FeatureVectorPipeline.__new__(FeatureVectorPipeline)
    agent.name = "feature_vector_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._plugin_cache = {}
    agent._state_mgr = PluginStateManager(
        checkpoint_path=pathlib.Path(tempfile.mkdtemp()) / "ckpt.json"
    )
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    agent._i1_latency_ms = MagicMock()
    agent._i7_latency_ms = MagicMock()
    agent._pipeline_latency = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent.settings.intelligence_thread_pool_workers = 0
    agent._bar_history = BarHistory(maxlen=200)
    # CacheManager with an async mock DB — queries return [] by default.
    # Seed cache state via the public seed_* API: agent._cache_mgr.seed_perf_weights({...})
    _db = AsyncMock()
    _db.execute_query = AsyncMock(return_value=[])
    agent._cache_mgr = CacheManager(db=_db, settings=agent.settings)
    agent._regime_cache = {}
    agent._feature_caches = {}
    agent._kafka_producer = AsyncMock()
    agent._background_tasks = set()
    agent._bar_e2e_latency = MagicMock()
    agent._out_queue = OutputQueue(producer=MagicMock(), maxsize=500)
    agent._transform_recorder = MagicMock()
    agent._regime_prob_min = 0.7
    agent._regime_prob_soft_max = 0.55
    agent._regime_dur_min = 12
    cpu_count = os.cpu_count() or 24
    # D-06: self._thread_pool is the underlying ThreadPoolExecutor;
    # self._executor is the PluginExecutor instance.
    agent._thread_pool = ThreadPoolExecutor(
        max_workers=cpu_count * 2,
        thread_name_prefix="test_intel_",
    )
    agent._executor = PluginExecutor(
        thread_pool=agent._thread_pool,
        plugin_cache=agent._plugin_cache,
        instrument_map=agent._instrument_map,
        circuit_breakers={},
        observer=NoOpPluginObserver(),
    )
    # SignalProcessor owns kalman_state, setup_last_fire, and the I7 signal pipeline stages.
    agent._sig_proc = SignalProcessor(
        cis_scorer=CISScorer(),
        settings=agent.settings,
        transform_recorder=None,
    )
    # FeatureFactoryConfig required by _process_bar_compute() assertion.
    # Seeded with default values matching APR defaults.
    from src.intelligence.feature_factory import FeatureFactoryConfig

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
    )
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
