#!/usr/bin/env python3
"""FeatureVectorPipeline — v3.0 FeatureFactory pipeline.

Computes all 36 FeatureVector primitives via FeatureFactory.compute() per bar,
wraps in FeatureVectorRecord, and publishes to topic_feature_vectors.

D-09 cutover: I5/I6/I7 plugin dispatch removed. feature.* APR keys prewarmed
at init. FeatureCache refreshed every regime_cache_refresh_bars bars.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import signal as _signal
import time
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.config_service import ConfigService
from src.config.settings import (
    get_active_contracts,
    get_settings,
    invalidate_active_contracts_cache,
)
from src.core.agent.base import BaseDaemon
from src.core.bar_history import BarHistory
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage
from src.core.service_utils import (
    format_iso_ts,
    min_bars_for_tf,
    parse_iso_ts,
)
from src.core.stream_keys import (
    TF_SECONDS,
    message_key,
    topic_config_updates,
    topic_contract_updates,
    topic_cross_asset,
    topic_feature_vectors,
    topic_intelligence_pipeline_dlq,
    topic_macro_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_signal_dlq,
    topic_system_events,
)
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FEATURE_FACTORY_VERSION,
    FeatureFactory,
    FeatureFactoryConfig,
)
from src.intelligence.pipeline import (
    CacheManager,
    OutputQueue,
    PerKeyWorkerManager,
    PluginStateManager,
)
from src.intelligence.pipeline.output_queue import PRIORITY_HIGH
from src.intelligence.pipeline.per_key_worker_manager import (
    _WORKER_COUNT_GAUGE,
    _WORKER_QUEUE_DEPTH_GAUGE,
)
from src.intelligence.pipeline.state_manager import _CHECKPOINT_PATH
from src.intelligence.schemas import FeatureVectorRecord
from src.observability.metrics import (
    CONTRACTS_RELOAD_TOTAL,
    PIPELINE_BACKPRESSURE_DROP_TOTAL,
    counter,
)
from src.observability.spans import ATTR_SYMBOL, ATTR_TF, observed_span

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_STANDARD_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")
_OUTPUT_QUEUE_MAXSIZE = 500
_MAX_QUEUE_DEPTH = 500
_PIPELINE_VERSION = "3.0.0"


# ---------------------------------------------------------------------------
# FeatureVectorPipeline
# ---------------------------------------------------------------------------


class FeatureVectorPipeline(BaseDaemon):
    """v3.0 pipeline: FeatureFactory.compute() per bar, publish to topic_feature_vectors.

    D-09 cutover: replaces I5/I6/I7 PluginExecutor dispatch with a single
    FeatureFactory.compute() call. Zero plugin dispatch remains in compute path.
    feature.* APR keys prewarmed at init. FeatureCache per (symbol, tf).
    """

    def __init__(self) -> None:
        _log_file = os.environ.get("LOG_FILE")
        if _log_file:
            from src.core.service_utils import setup_service_logging

            setup_service_logging(_log_file)

        _settings = get_settings()
        super().__init__(
            max_idle_seconds=300,
            settings=_settings,
        )

        self._contracts = get_active_contracts(self.settings)
        if not self._contracts:
            raise RuntimeError(
                "feature_vector_pipeline_agent: no active instruments at startup. "
                "DB unreachable or instruments table empty. Check DB connectivity "
                "and ensure TODO: migrate_instruments.py (not found - may be deprecated) has been run."
            )
        self._symbols = [c.symbol for c in self._contracts]
        self._timeframes = list(_STANDARD_TFS)
        self._instrument_map: dict[str, Any] = {c.symbol: c for c in self._contracts}

        self._bar_history = BarHistory(maxlen=200)
        self._last_bar_offset: dict = {}

        # Transient (not checkpointed)
        self._live_quotes: dict = {}
        self._last_bar_ts: dict = {}

        # Per-(symbol, tf) FeatureCache — lazily created via _get_cache()
        self._feature_caches: dict[str, FeatureCache] = {}

        self._config_service: ConfigService | None = None  # initialised in _setup()
        self._feature_factory_config: FeatureFactoryConfig | None = None
        self._feature_factory = FeatureFactory()

        self._shadow_mode: bool = os.environ.get("INTELLIGENCE_PIPELINE_SHADOW", "0") == "1"
        self._consumer_group = "feature_vector_pipeline_group"
        self._background_tasks: set = set()

        self._bars_processed = counter(
            "feature_vector_pipeline_bars_processed_total",
            "Bars processed through FeatureFactory pipeline",
        )
        self._pipeline_errors = counter(
            "feature_vector_pipeline_errors_total",
            "Pipeline processing errors",
        )
        self._bar_timeout_total = counter(
            "feature_vector_pipeline_bar_timeout_total",
            "Bars that exceeded the 500ms hard outer timeout and were DLQ'd",
        )
        self._pipeline_latency = self._meter.create_histogram(
            "feature_vector_pipeline_latency_ms",
            description="Per-bar pipeline latency in milliseconds",
        )
        self._bar_e2e_latency = self._meter.create_histogram(
            "bar_e2e_latency_ms",
            description="End-to-end bar latency from arrival to feature publish",
        )

        self._vix_symbol: str | None = (
            "VX" if any(c.symbol == "VX" for c in self._contracts) else None
        )

    def _get_cache(self, symbol: str, tf: str) -> FeatureCache:
        """Return the FeatureCache for (symbol, tf), creating one on first access."""
        key = f"{symbol}:{tf}"
        if key not in self._feature_caches:
            self._feature_caches[key] = FeatureCache()
        return self._feature_caches[key]

    async def stop(self) -> None:
        self.logger.info("agent.shutdown_initiated", agent=self.name)
        await super().stop()

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        # ConfigService: shared pool, prewarm feature.* and threshold.* keys.
        self._config_service = ConfigService(self.settings.database_url, pool=self._db.pool)
        await self._prewarm_threshold_config()

        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._contracts_topic = topic_contract_updates(self.settings.env_name)
        self._config_updates_topic = topic_config_updates(self.settings.env_name)
        topics = [
            topic_market_bars(self.settings.env_name),
            topic_market_bars_htf(self.settings.env_name),
            topic_system_events(self.settings.env_name),
            topic_cross_asset(self.settings.env_name),
            topic_macro_signals(self.settings.env_name),
            self._contracts_topic,
            self._config_updates_topic,
        ]
        self._kafka_consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self._consumer_group,
            enable_auto_commit=False,
        )
        await self._kafka_consumer.start()
        await self._kafka_consumer.skip_lag_if_needed(max_lag=1000)
        self.logger.info("kafka.subscribed", topics=topics)

        self._out_queue = OutputQueue(
            producer=self._kafka_producer,
            maxsize=_OUTPUT_QUEUE_MAXSIZE,
            drain_batch_size=self.settings.intelligence_output_drain_batch_size,
            drain_ratio=self.settings.output_queue_drain_ratio,
        )

        _CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state_mgr = PluginStateManager(checkpoint_path=_CHECKPOINT_PATH)
        extra = await self._state_mgr.read_checkpoint()
        if extra is not None:
            self._last_bar_offset = extra.get("last_bar_offset", {})

        ckpt_task = self._state_mgr.start_checkpoint_loop(300, self._assemble_checkpoint_extra)
        self._background_tasks.add(ckpt_task)
        ckpt_task.add_done_callback(self._background_tasks.discard)

        await self._seed_bar_history_from_db()

        _symbol_filter_list = self.settings.feature_vector_pipeline_symbol_filter
        symbol_filter = frozenset(_symbol_filter_list) if _symbol_filter_list else None
        self._cache_mgr = CacheManager(
            db=self._db,
            settings=self.settings,
            symbols=symbol_filter,
            on_instruments_changed=invalidate_active_contracts_cache,
        )
        await self._cache_mgr.load_initial()
        for task in self._cache_mgr.start_refresh_loops():
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        await self._db.ensure_instruments_trigger()
        listener_task = self._cache_mgr.start_instruments_listener()
        self._background_tasks.add(listener_task)
        listener_task.add_done_callback(self._background_tasks.discard)
        self.logger.info("feature_vector_pipeline.instruments_listener_started")

        # Per-key concurrency (PERF-07)
        self._worker_manager = PerKeyWorkerManager(
            processor=self._process_bar_inner,
            symbol_filter=symbol_filter,
            queue_maxsize=self.settings.feature_vector_pipeline_queue_maxsize,
        )
        self._worker_manager.start_per_key_workers()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(_signal.SIGUSR1, self._on_feature_config_reload)
        self.logger.info(
            "agent.setup_complete",
            shadow=self._shadow_mode,
            symbols=self._symbols,
            timeframes=self._timeframes,
        )

    # ---------------------------------------------------------------------------
    # APR prewarm: all threshold.* and feature.* keys loaded at init
    # ---------------------------------------------------------------------------

    _THRESHOLD_KEYS: tuple[tuple[str, Any], ...] = (
        ("threshold.trend_following.regime_min", 0.5),
        ("threshold.trend_following.confidence_min", 0.4),
        ("threshold.ofi_continuation.min_bars", 10),
        (
            "threshold.ofi_continuation.magnitude_floors",
            {"ES": 500, "NQ": 200, "CL": 1000, "GC": 500, "_default": 500},
        ),
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
        # --- migration 132: Phase 125 CIS gate constants ---
        ("threshold.cis.fire_threshold", 0.35),
        ("threshold.cis.bucket_agree_min", 3),
        ("threshold.cis.bucket_noise_floor", 0.1),
        # --- migration 132: Phase 125 zone entry width gate ---
        ("feature.zone_engine.min_zone_width_atr", 1.5),
        ("feature.zone_engine.min_zone_width_atr.equity", 1.5),
        ("feature.zone_engine.min_zone_width_atr.fx", 1.0),
        ("feature.zone_engine.min_zone_width_atr.futures", 1.5),
        # --- migration 132: Phase 125 anchored_vwap_reversion Tier B weights ---
        ("weights.vwap_reversion.sigma_magnitude", 0.40),
        ("weights.vwap_reversion.hurst_quality", 0.35),
        ("weights.vwap_reversion.vol_stability", 0.25),
        # --- migration 136: lvn_breakout, ofi_divergence, failed_breakout APR ---
        ("threshold.lvn_breakout.vol_threshold", 1.5),
        ("weights.lvn_breakout.vol", 0.30),
        ("weights.lvn_breakout.trend_clarity", 0.25),
        ("weights.lvn_breakout.lvn_inverse", 0.25),
        ("weights.lvn_breakout.close_strength", 0.20),
        ("threshold.ofi_divergence.min_divergence_sigma", 1.5),
        ("weights.ofi_divergence.magnitude", 0.40),
        ("weights.ofi_divergence.alignment", 0.25),
        ("weights.ofi_divergence.persistence", 0.20),
        ("weights.ofi_divergence.volume", 0.15),
        ("threshold.failed_breakout.max_reversal_bars", 3),
        ("weights.failed_breakout.break_magnitude", 0.35),
        ("weights.failed_breakout.rejection_strength", 0.30),
        ("weights.failed_breakout.volume", 0.20),
        ("weights.failed_breakout.structure_quality", 0.15),
        # --- migration 138: remaining module-level and plugin APR params ---
        ("threshold.global.conf_ceil", 0.95),
        ("threshold.microstructure.spike_z", 2.0),
        ("feature.state.dedup_min_bars", 20),
        ("threshold.delta_exhaustion.spike_z", 1.5),
        ("threshold.delta_exhaustion.price_follow_atr", 0.3),
        ("weights.delta_exhaustion.cvd_z", 0.35),
        ("weights.delta_exhaustion.price_fail", 0.30),
        ("weights.delta_exhaustion.hmm_ranging", 0.25),
        ("weights.delta_exhaustion.persistence", 0.10),
        ("feature.cvd_divergence.confirmation_bars", 5),
        ("threshold.cvd_divergence.div_threshold", 1.0),
        ("feature.cvd_divergence.div_upper_ref", 2.0),
        ("threshold.cvd_divergence.ofi_dual_threshold", 1.0),
        ("feature.dual_divergence.confirmation_bars", 3),
        ("threshold.divergence_stack.score_threshold", 0.40),
        ("feature.divergence_stack.min_agreeing", 3),
        ("feature.divergence_stack.confidence_norm", 0.60),
        ("weights.divergence_stack.rsi", 0.30),
        ("weights.divergence_stack.macd", 0.25),
        ("weights.divergence_stack.vol", 0.20),
        ("weights.divergence_stack.obv", 0.15),
        ("weights.divergence_stack.cmf", 0.10),
        ("threshold.vwap_reclaim.vol_threshold", 1.2),
        # --- migration 146: Phase 132 trade_framer module-level constants ---
        ("feature.trade_framer.stop_demand_buffer_atr", 0.25),
        ("feature.trade_framer.stop_sweep_buffer_atr", 0.30),
        ("feature.trade_framer.stop_ob_buffer_atr", 0.20),
        ("feature.trade_framer.stop_swing_buffer_atr", 0.25),
        ("feature.trade_framer.stop_sr_buffer_atr", 0.50),
        ("feature.trade_framer.stop_fallback_atr", 2.0),
        ("feature.trade_framer.zone_sweep_atr", 0.76),
        ("feature.trade_framer.zone_low_atr", 1.0),
        ("feature.trade_framer.zone_high_atr", 0.5),
        ("feature.trade_framer.target_min_atr", 0.5),
        ("feature.trade_framer.zone_plugin_fallback_atr", 0.2),
        ("feature.trade_framer.vp_proximity_atr", 0.5),
        ("feature.trade_framer.fallback_t1_atr", 2.0),
        ("feature.trade_framer.fallback_t2_atr", 3.5),
        ("feature.trade_framer.fallback_t3_atr", 5.5),
        ("feature.trade_framer.min_stop_atr", 1.0),
        ("threshold.trade_framer.min_rr_t1", 1.5),
        ("feature.trade_framer.adaptive_buffer_hard_cap", 1.40),
        ("feature.trade_framer.structure_snap_proximity_atr", 1.5),
        # --- migration 147: Phase 132 adaptive buffer coefficients ---
        ("feature.trade_framer.adaptive_buffer_vol_ratio_min", 0.70),
        ("feature.trade_framer.adaptive_buffer_vol_ratio_max", 1.50),
        ("feature.trade_framer.adaptive_buffer_low_vol_base", 0.80),
        ("feature.trade_framer.adaptive_buffer_low_vol_slope_num", 0.20),
        ("feature.trade_framer.adaptive_buffer_low_vol_slope_den", 0.30),
        ("feature.trade_framer.adaptive_buffer_high_vol_slope_num", 0.35),
        ("feature.trade_framer.adaptive_buffer_high_vol_slope_den", 0.50),
        ("feature.trade_framer.adaptive_buffer_hurst_trend_threshold", 0.55),
        ("feature.trade_framer.adaptive_buffer_hurst_mr_threshold", 0.45),
        ("feature.trade_framer.adaptive_buffer_hurst_tighten_rate", 0.16),
        ("feature.trade_framer.adaptive_buffer_garch_shock_threshold", 3.0),
        ("feature.trade_framer.adaptive_buffer_garch_shock_mult", 1.35),
        # --- migration 148: Phase 132 A3 per-asset-class stop floors ---
        ("feature.trade_framer.stop_multiplier_floor.fx", 1.0),
        ("feature.trade_framer.stop_multiplier_floor.commodity_small_tick", 1.5),
        ("feature.trade_framer.stop_multiplier_floor.equity_etf", 1.0),
        ("feature.trade_framer.stop_multiplier_floor.futures_large_tick", 1.0),
        # --- migration 153: GARCH and Kalman plugin APR keys ---
        ("feature.garch.omega", 0.00001),
        ("feature.garch.alpha", 0.10),
        ("feature.garch.beta", 0.85),
        ("feature.kalman.garch_r_scale", 10_000.0),
        # --- v3.0 Phase 137: FeatureFactory APR keys (D-09 cutover) ---
        ("feature.momentum.window_short", 5),
        ("feature.momentum.window_long", 20),
        ("feature.momentum.zscore_window", 252),
        ("feature.volume.zscore_window", 20),
        ("feature.ofi.zscore_window", 20),
        ("feature.cvd.slope_bars", 5),
        ("feature.cmf.period", 20),
        ("feature.vol.short_bars", 5),
        ("feature.vol.long_bars", 20),
        ("feature.hma.period", 20),
        ("feature.adx.period", 14),
        ("feature.hurst.window", 252),
        ("feature.garch.window", 100),
        ("feature.vix.zscore_window", 252),
        ("feature.yield_curve.zscore_window", 252),
        ("feature.regime.cache_refresh_bars", 30),
        # --- migration 156: Phase 137 P7 oscillator + statistical/liquidity APR keys ---
        ("feature.period.rsi.fast", 7),
        ("feature.period.rsi.mid", 14),
        ("feature.period.rsi.slow", 28),
        ("feature.period.cci.fast", 10),
        ("feature.period.cci.mid", 20),
        ("feature.period.cci.slow", 40),
        ("feature.period.aroon.fast", 14),
        ("feature.period.aroon.slow", 25),
        ("feature.amihud.zscore_window", 252),
        ("feature.ret_skew.window", 60),
        ("feature.ret_skew.zscore_window", 252),
        ("feature.ret_acf.window", 30),
        ("feature.ret_acf.zscore_window", 252),
        ("feature.high_52w.window", 252),
        # --- migration 157: cache warmup, cross-asset, session ---
        ("feature.cache.min_bars_warmup", 16),
        ("feature.cross_asset.rv_window", 20),
        ("feature.session.ny_start_utc_hour", 13),
        ("feature.session.ny_start_utc_minute", 30),
        ("feature.session.ny_end_utc_hour", 20),
        ("feature.session.overlap_start_utc_hour", 12),
        ("feature.session.overlap_end_utc_hour", 15),
        ("feature.session.london_kz_start_utc_hour", 7),
        ("feature.session.london_kz_end_utc_hour", 10),
        ("feature.session.power_hour_start_utc_hour", 19),
        ("feature.session.power_hour_end_utc_hour", 21),
        ("feature.session.opening_range_start_minute", 810),
        ("feature.session.opening_range_end_minute", 900),
        ("threshold.backfill.coverage_gate", 0.80),
    )

    async def _prewarm_threshold_config(self) -> None:
        """Prewarm config cache and build FeatureFactoryConfig from feature.* keys."""
        assert self._config_service is not None
        for key, default in self._THRESHOLD_KEYS:
            await self._config_service.get(key, default)

        # Build FeatureFactoryConfig from prewarmed feature.* values (APR contract).
        # All get_sync() calls hit the warm cache — no DB round-trips on compute path.
        cs = self._config_service

        def _int(key: str, default: int) -> int:
            v = cs.get_sync(key, default)
            return int(v) if v is not None else default

        self._feature_factory_config = FeatureFactoryConfig(
            momentum_window_fast=_int("feature.momentum.window_fast", 5),
            momentum_window_mid=_int("feature.momentum.window_mid", 20),
            momentum_window_slow=_int("feature.momentum.window_slow", 60),
            momentum_zscore_window=_int("feature.momentum.zscore_window", 252),
            volume_zscore_window=_int("feature.volume.zscore_window", 20),
            ofi_zscore_window=_int("feature.ofi.zscore_window", 20),
            cvd_slope_bars=_int("feature.cvd.slope_bars", 5),
            cmf_period=_int("feature.cmf.period", 20),
            vol_short_bars=_int("feature.vol.short_bars", 5),
            vol_long_bars=_int("feature.vol.long_bars", 20),
            hma_period=_int("feature.hma.period", 20),
            adx_period=_int("feature.adx.period", 14),
            hurst_window=_int("feature.hurst.window", 252),
            garch_window=_int("feature.garch.window", 100),
            vix_zscore_window=_int("feature.vix.zscore_window", 252),
            yield_curve_zscore_window=_int("feature.yield_curve.zscore_window", 252),
            regime_cache_refresh_bars=_int("feature.regime.cache_refresh_bars", 30),
            rsi_fast_period=_int("feature.period.rsi.fast", 7),
            rsi_mid_period=_int("feature.period.rsi.mid", 14),
            rsi_slow_period=_int("feature.period.rsi.slow", 28),
            cci_fast_period=_int("feature.period.cci.fast", 10),
            cci_mid_period=_int("feature.period.cci.mid", 20),
            cci_slow_period=_int("feature.period.cci.slow", 40),
            aroon_fast_period=_int("feature.period.aroon.fast", 14),
            aroon_slow_period=_int("feature.period.aroon.slow", 25),
            amihud_zscore_window=_int("feature.amihud.zscore_window", 252),
            ret_skew_window=_int("feature.ret_skew.window", 60),
            ret_skew_zscore_window=_int("feature.ret_skew.zscore_window", 252),
            ret_acf_window=_int("feature.ret_acf.window", 30),
            ret_acf_zscore_window=_int("feature.ret_acf.zscore_window", 252),
            high_52w_window=_int("feature.high_52w.window", 252),
            min_bars_warmup=_int("feature.cache.min_bars_warmup", 16),
            cross_asset_rv_window=_int("feature.cross_asset.rv_window", 20),
            ny_session_start_utc_hour=_int("feature.session.ny_start_utc_hour", 13),
            ny_session_start_utc_minute=_int("feature.session.ny_start_utc_minute", 30),
            ny_session_end_utc_hour=_int("feature.session.ny_end_utc_hour", 20),
            overlap_start_utc_hour=_int("feature.session.overlap_start_utc_hour", 12),
            overlap_end_utc_hour=_int("feature.session.overlap_end_utc_hour", 15),
            london_kz_start_utc_hour=_int("feature.session.london_kz_start_utc_hour", 7),
            london_kz_end_utc_hour=_int("feature.session.london_kz_end_utc_hour", 10),
            power_hour_start_utc_hour=_int("feature.session.power_hour_start_utc_hour", 19),
            power_hour_end_utc_hour=_int("feature.session.power_hour_end_utc_hour", 21),
            opening_range_start_minute=_int("feature.session.opening_range_start_minute", 810),
            opening_range_end_minute=_int("feature.session.opening_range_end_minute", 900),
        )

        self.logger.info(
            "feature_vector_pipeline.feature_config_loaded",
            key_count=len(self._THRESHOLD_KEYS),
            regime_cache_refresh_bars=self._feature_factory_config.regime_cache_refresh_bars,
        )

    async def _handle_config_update(self, payload: dict) -> None:
        """Hot-reload a config key: invalidate cache entry then re-fetch from DB."""
        assert self._config_service is not None
        key = payload.get("config_key")
        if not key or not any(key.startswith(pfx) for pfx in ConfigService.OPS_PREFIXES):
            return
        self._config_service.invalidate(key)
        default = next((d for k, d in self._THRESHOLD_KEYS if k == key), None)
        await self._config_service.get(key, default)
        self.logger.info("feature_vector_pipeline.config_reloaded", config_key=key)

    async def _seed_bar_history_from_db(self) -> None:
        try:
            from src.intelligence.services.bar_history_seeder import (
                BarHistorySeeder,  # noqa: PLC0415
            )

            config = {"service": {"timeframes": list(self._timeframes)}}
            seeder = BarHistorySeeder(self.settings, config, self._kafka_producer)
            await seeder.seed(self._bar_history)
        except Exception as error:
            self.logger.warning("bar_history.seed_failed", error=str(error))

    async def _run(self) -> None:
        drain_task = asyncio.create_task(self._out_queue.drain_loop(lambda: self.running))
        tasks = [
            asyncio.create_task(self._process_loop()),
            drain_task,
            asyncio.create_task(self._health_monitor_loop()),
            asyncio.create_task(self._report_consumer_lag()),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        task_names = [
            "_process_loop",
            "_out_queue.drain_loop",
            "_health_monitor_loop",
            "_report_consumer_lag",
        ]
        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "task.failed_silent",
                    task=name,
                    error=str(result),
                    error_type=type(result).__name__,
                )

    async def _teardown(self) -> None:
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._out_queue.join(), timeout=10.0)
        except TimeoutError:
            self.logger.warning("teardown.output_drain_timeout")
        if hasattr(self, "_worker_manager"):
            await self._worker_manager.stop()
        if hasattr(self, "_state_mgr"):
            self._state_mgr.write_checkpoint(self._assemble_checkpoint_extra())
        if hasattr(self, "_kafka_consumer"):
            await self._kafka_consumer.stop()
        if hasattr(self, "_kafka_producer"):
            await self._kafka_producer.stop()
        if hasattr(self, "_db"):
            await self._db.close()
        self.logger.info("agent.teardown_complete")

    def _register_signal_handlers(self) -> None:
        """Override to also stop the Kafka consumer on SIGTERM/SIGINT."""
        super()._register_signal_handlers()

        loop = asyncio.get_running_loop()

        async def _shutdown_consumer() -> None:
            self._stop_event.set()
            if hasattr(self, "_kafka_consumer"):
                try:
                    await self._kafka_consumer.stop()
                except Exception as error:
                    self.logger.warning(
                        "feature_vector_pipeline.shutdown_consumer_error", error=str(error)
                    )

        def _signal_handler() -> None:
            loop.create_task(_shutdown_consumer())

        for sig in (_signal.SIGTERM, _signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

    def _on_feature_config_reload(self) -> None:
        """SIGUSR1 handler: log receipt (config hot-reload via config_updates topic)."""
        self.logger.info("feature_vector_pipeline.sigusr1_received")

    async def _process_loop(self) -> None:
        _cross_asset_topic = topic_cross_asset(self.settings.env_name)
        _macro_topic = topic_macro_signals(self.settings.env_name)
        _system_topic = topic_system_events(self.settings.env_name)
        _contracts_topic = self._contracts_topic
        COMMIT_BATCH_SIZE = 100
        msg_count = 0
        while self.running:
            try:
                async for _topic, _key, payload in self._kafka_consumer.messages():
                    if not isinstance(payload, dict):
                        continue
                    self._record_message_consumed()
                    if not self.running:
                        break
                    try:
                        if _topic == _cross_asset_topic:
                            tf = payload.get("tf", "1m")
                            await self._cache_mgr.update_cross_asset(tf, payload)
                        elif _topic == _macro_topic:
                            tf = payload.get("timeframe", payload.get("tf", "1m"))
                            macro_fields = {
                                k: payload[k]
                                for k in (
                                    "yield_curve_slope",
                                    "yield_curve_regime",
                                    "ftq_score",
                                    "ftq_regime",
                                )
                                if k in payload
                            }
                            await self._cache_mgr.update_macro(tf, macro_fields)
                        elif _topic == _system_topic:
                            await self._handle_system_event(payload)
                        elif _topic == _contracts_topic:
                            try:
                                new_contracts = get_active_contracts(self.settings)
                                self._contracts = new_contracts
                                CONTRACTS_RELOAD_TOTAL.add(1, {"status": "success"})
                                self.logger.info("contracts_reloaded", count=len(self._contracts))
                            except Exception as error:
                                CONTRACTS_RELOAD_TOTAL.add(1, {"status": "failure"})
                                self.logger.error("contracts_reload_failed", error=str(error))
                        elif _topic == self._config_updates_topic:
                            await self._handle_config_update(payload)
                        else:
                            bar = self._parse_bar(payload)
                            if bar is None:
                                await self._send_to_dlq(payload, Exception("Parse failed"))
                                continue
                            if not self._worker_manager.try_enqueue(bar):
                                PIPELINE_BACKPRESSURE_DROP_TOTAL.add(
                                    1, {"symbol": bar.symbol, "tf": bar.tf}
                                )
                                self.logger.warning(
                                    "pipeline_backpressure_drop",
                                    symbol=bar.symbol,
                                    tf=bar.tf,
                                )

                        msg_count += 1
                        if msg_count >= COMMIT_BATCH_SIZE:
                            await self._kafka_consumer.commit()
                            msg_count = 0
                    except Exception as error:
                        self.logger.error("bar.process_error", error=str(error))
                        self._pipeline_errors.add(1)
            except Exception as error:
                self.logger.warning("process_loop.consumer_error", error=str(error))
                await asyncio.sleep(1)

    def _dlq_topic(self) -> str | None:
        return topic_intelligence_pipeline_dlq(self.settings.env_name)

    def _parse_bar(self, msg: dict) -> BarMessage | None:
        try:
            if isinstance(msg.get("ts"), str):
                msg = {**msg, "ts": parse_iso_ts(msg["ts"])}
            return BarMessage.model_construct(**msg)
        except (ValueError, TypeError):
            try:
                return BarMessage(**msg)
            except Exception:
                return None

    async def _process_bar_inner(self, bar: BarMessage, *, gap: bool = False) -> None:
        """DAG router: gap detect -> FeatureFactory.compute() -> publish."""
        t0 = time.perf_counter()
        key = f"{bar.symbol}:{bar.tf}"
        prev_ts = self._last_bar_ts.get(key)
        if (
            prev_ts is not None
            and (bar.ts.timestamp() - prev_ts) > TF_SECONDS.get(bar.tf, 60) * 1.5
        ):
            gap = True
        self._last_bar_ts[key] = bar.ts.timestamp()
        self._bar_history.append(bar)
        if not self._bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
            return
        async with observed_span(
            "pipeline.process_bar_inner",
            **{ATTR_SYMBOL: bar.symbol, ATTR_TF: bar.tf},
        ):
            try:
                await asyncio.wait_for(self._process_bar_compute(bar, t0=t0, gap=gap), timeout=5.0)
            except TimeoutError:
                env = self.settings.env_name
                msg_key = message_key(bar.symbol, bar.tf)
                dlq_payload = {
                    "reason": "bar_tier_timeout",
                    "symbol": bar.symbol,
                    "tf": bar.tf,
                    "ts": bar.ts.isoformat(),
                }
                self._bar_timeout_total.add(1, {"symbol": bar.symbol, "tf": bar.tf})
                self.logger.warning(
                    "pipeline.bar_timeout",
                    symbol=bar.symbol,
                    tf=bar.tf,
                    timeout_ms=500,
                )
                await self._out_queue.enqueue_blocking(
                    topic_signal_dlq(env),
                    msg_key,
                    dlq_payload,
                    timeout_sec=1.0,
                    priority=PRIORITY_HIGH,
                )

    async def _process_bar_compute(self, bar: BarMessage, *, t0: float, gap: bool = False) -> None:
        """FeatureFactory compute and publish -- DB-ignorant hot path (D-09).

        FeatureFactory.compute() is pure: bars list + cache + frozen config.
        FeatureCache refreshed every regime_cache_refresh_bars bars (slow path).
        Publish via asyncio.create_task() -- fire-and-forget, non-blocking.
        msg= kwarg (NOT value=) per KafkaProducerClient contract.
        """
        assert self._feature_factory_config is not None, "FeatureFactoryConfig not prewarmed"

        config = self._feature_factory_config
        cache = self._get_cache(bar.symbol, bar.tf)

        # Build bars list from history (list of dicts for FeatureFactory.compute())
        raw_bars = self._bar_history.get(bar.symbol, bar.tf)
        if not raw_bars:
            return

        bars_dicts = [
            {
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "ts": b.ts,
            }
            for b in raw_bars
        ]

        # Refresh regime features every N bars (slow path; compute() reads from cache)
        cache.bars_since_regime_refresh += 1
        if cache.bars_since_regime_refresh >= config.regime_cache_refresh_bars:
            cache.refresh_regime(bars_dicts, config)

        # Update CTF cache when HTF bar arrives
        if bar.tf in ("15m", "1h", "4h", "1d"):
            self._update_ctf_cache_from_bar(bar, cache)

        try:
            vector = FeatureFactory.compute(bars_dicts, bar.symbol, bar.tf, cache, config)
        except Exception as error:
            self.logger.error(
                "pipeline.feature_factory_error",
                symbol=bar.symbol,
                tf=bar.tf,
                error=str(error),
            )
            self._pipeline_errors.add(1)
            return

        # Regime label from HMM dominant state probability
        # High hmm_regime_prob + low entropy = dominant regime active
        hmm_prob = cache.hmm_regime_prob
        if hmm_prob >= 0.6:
            regime: str | None = "ranging" if cache.hmm_entropy < 0.5 else "trending_up"
        elif hmm_prob >= 0.4:
            regime = "ranging"
        else:
            regime = None  # uncertain / cold start

        record = FeatureVectorRecord(
            symbol=bar.symbol,
            tf=bar.tf,
            bar_ts=bar.ts,
            pipeline_version=_PIPELINE_VERSION,
            feature_factory_version=FEATURE_FACTORY_VERSION,
            regime=regime,
            regime_label_source="filtered",
            vector=vector,
        )

        # Serialize: dataclasses.asdict() recursively converts FeatureVector to dict.
        # bar_ts datetime must be ISO string for JSON Kafka transport.
        record_dict = dataclasses.asdict(record)
        record_dict["bar_ts"] = format_iso_ts(bar.ts)

        # Fire-and-forget publish -- non-blocking hot path
        # aiokafka batches internally via linger_ms; create_task keeps compute async.
        env = self.settings.env_name
        topic = topic_feature_vectors(env)
        msg_key = message_key(bar.symbol, bar.tf)
        task = asyncio.create_task(
            self._kafka_producer.publish(
                topic,
                msg=record_dict,
                key=msg_key,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        pipeline_latency_ms = (time.perf_counter() - t0) * 1000
        self._pipeline_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
        self._bar_e2e_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
        self._bars_processed.add(1)

    def _update_ctf_cache_from_bar(self, bar: BarMessage, cache: FeatureCache) -> None:
        """Update CTF fields in FeatureCache when an HTF bar arrives.

        CTF primitives are read by lower-TF compute() calls. Simple proxy:
        bar intra-bar return as ctf_momentum; other fields hold prior cached values.
        """
        if bar.open > 0:
            cache.ctf_momentum = (bar.close - bar.open) / bar.open

    def _assemble_checkpoint_extra(self) -> dict:
        return {
            "last_bar_offset": self._last_bar_offset,
        }

    async def _health_monitor_loop(self) -> None:
        """Emit per-key worker queue gauges every 10 seconds."""
        while self.running:
            await asyncio.sleep(10)
            try:
                mgr = getattr(self, "_worker_manager", None)
                if mgr is None:
                    continue
                queues = getattr(mgr, "_queues", {})
                depth_max = max((q.qsize() for q in queues.values()), default=0)
                worker_count = len(queues)
                _WORKER_QUEUE_DEPTH_GAUGE.set(depth_max, {})
                _WORKER_COUNT_GAUGE.set(worker_count, {})
            except Exception as error:
                self.logger.warning(
                    "health_monitor.gauge_emit_failed",
                    error=str(error),
                )

    async def _handle_system_event(self, payload: dict) -> None:
        event_type = payload.get("type", "")
        if event_type == "pipeline_reset":
            self.logger.info("system.pipeline_reset_received")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = FeatureVectorPipeline()
    asyncio.run(agent.start())
