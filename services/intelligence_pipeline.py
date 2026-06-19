#!/usr/bin/env python3
"""IntelligencePipeline — Unified I1-I7 in-process pipeline.

Thin DAG router: constructs all 5 extracted classes and routes to 4 output topics.
I1-I6 runs in _run_i1_to_i6; I7 runs in SignalProcessor.process().
_process_bar_inner is the explicit DAG description (D-08).
"""

from __future__ import annotations

import asyncio
import os
import signal as _signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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
from src.core.service_utils import min_bars_for_tf, normalize_session_type, parse_iso_ts
from src.core.stream_keys import (
    TF_SECONDS,
    message_key,
    topic_config_updates,
    topic_contract_updates,
    topic_cross_asset,
    topic_intelligence,
    topic_intelligence_i7_signals,
    topic_intelligence_journal,
    topic_intelligence_pipeline_dlq,
    topic_intelligence_shadow,
    topic_macro_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_signal_dlq,
    topic_signals_aggregated,
    topic_system_events,
)
from src.intelligence.pipeline import (
    CacheManager,
    FeaturePipelineExecutor,
    OutputQueue,
    PerKeyWorkerManager,
    PluginExecutor,
    PluginStateManager,
    SignalProcessor,
)
from src.intelligence.pipeline.executor import _SHADOW_CB_DEFAULTS
from src.intelligence.pipeline.output_queue import PRIORITY_HIGH, PRIORITY_LOW
from src.intelligence.pipeline.per_key_worker_manager import (
    _WORKER_COUNT_GAUGE,
    _WORKER_QUEUE_DEPTH_GAUGE,
)
from src.intelligence.pipeline.state_manager import _CHECKPOINT_PATH
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
    enroll_all_plugins,
    register_all_plugins,
)
from src.intelligence.schemas import (
    BarIntelligenceRecord,
    IntelligenceEvent,
    signal_dict_to_ranked,
)
from src.intelligence.trading.cis_scorer import CISScorer
from src.observability.circuit_breaker import CircuitBreaker
from src.observability.metrics import (
    CONTRACTS_RELOAD_TOTAL,
    PIPELINE_BACKPRESSURE_DROP_TOTAL,
    THREAD_POOL_WORKERS,
    counter,
)
from src.observability.plugin_observer import PluginObserver
from src.observability.spans import ATTR_SYMBOL, ATTR_TF, observed_span

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_STANDARD_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")
VIX_REGIME_TF: str = "1h"
I7_PLUGINS = TIER_I7
_OUTPUT_QUEUE_MAXSIZE = 500
_MAX_QUEUE_DEPTH = 500  # drop incoming bar above this depth to prevent OOM under load

# PluginTask, _timed_plugin_call, and _ANALYSIS_WAVES moved to executor.py (plan 04).
# _apply_alpha_decay, _cis_kalman_update moved to signal_processor.py (plan 05); _build_features_from_event renamed to build_flat_features and moved to feature_flattening.py.


# ---------------------------------------------------------------------------
# IntelligencePipeline
# ---------------------------------------------------------------------------


class IntelligencePipeline(BaseDaemon):
    """Unified I1-I7 in-process pipeline agent — thin DAG router.

    Constructs all 5 extracted classes and routes to 4 output topics.
    _process_bar_inner is the D-08 DAG description with explicit 4-way output routing.
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
                "intelligence_pipeline_agent: no active instruments at startup. "
                "DB unreachable or instruments table empty. Check DB connectivity "
                "and ensure production/scripts/migrate_instruments.py has been run."
            )
        self._symbols = [c.symbol for c in self._contracts]
        self._timeframes = list(_STANDARD_TFS)

        register_all_plugins()
        for tier_list, tier_name in (
            (TIER_I1, "I1"),
            (TIER_I2, "I2"),
            (TIER_I3, "I3"),
            (TIER_I4, "I4"),
            (TIER_I5, "I5"),
            (TIER_SMC, "SMC"),
            (TIER_I6, "I6"),
            (TIER_I7, "I7"),
        ):
            registry.validate_tier(tier_list, tier_name)

        from src.intelligence.plugin_validator import PluginValidator

        PluginValidator().validate_all()

        # Plugin cache — used by PluginExecutor (the orchestrator's copy was redundant with
        # PluginExecutor's own copy; deleted D-24). Build once for PluginExecutor constructor.
        self._plugin_cache: dict[str, Any] = {n: registry.get_indicator(n) for n in TIER_I1}
        for n in TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6 + TIER_I7:
            self._plugin_cache[n] = registry.get_pattern(n)

        self._instrument_map: dict[str, Any] = {c.symbol: c for c in self._contracts}

        self._bar_history = BarHistory(maxlen=200)
        self._last_bar_offset: dict = {}

        # Transient (not checkpointed)
        self._live_quotes: dict = {}
        self._last_bar_ts: dict = {}

        # Thread pool — cap removed (D-29). Default: max(4, cpu_count // 2).
        cpu_count = os.cpu_count() or 24
        _configured = self.settings.intelligence_thread_pool_workers
        _workers = _configured if _configured > 0 else max(4, cpu_count // 2)
        self._thread_pool = ThreadPoolExecutor(max_workers=_workers, thread_name_prefix="intel_")
        THREAD_POOL_WORKERS.add(_workers)

        self._config_service: ConfigService | None = None  # initialised in _setup()
        self._regime_prob_min: float = self.settings.regime_prob_min
        self._regime_prob_soft_max: float = self.settings.REGIME_PROB_SOFT_MAX
        self._regime_dur_min: int = self.settings.regime_dur_min

        self._shadow_mode: bool = os.environ.get("INTELLIGENCE_PIPELINE_SHADOW", "0") == "1"
        self._consumer_group = "intelligence_pipeline_group"
        self._background_tasks: set = set()

        self._bars_processed = counter(
            "intelligence_pipeline_bars_processed_total",
            "Bars processed through I1-I7 pipeline",
        )
        self._i1_latency_ms = self._meter.create_histogram(
            "intelligence_pipeline_i1_latency_ms",
            description="I1 tier execution time in milliseconds",
        )
        self._i7_latency_ms = self._meter.create_histogram(
            "intelligence_pipeline_i7_latency_ms",
            description="I7 tier execution time in milliseconds",
        )
        self._pipeline_errors = counter(
            "intelligence_pipeline_pipeline_errors_total",
            "Pipeline processing errors",
        )
        self._bar_timeout_total = counter(
            "intelligence_pipeline_bar_timeout_total",
            "Bars that exceeded the 500ms hard outer timeout and were DLQ'd with reason bar_tier_timeout",
        )
        self._pipeline_latency = self._meter.create_histogram(
            "intelligence_pipeline_pipeline_latency_ms",
            description="Per-bar pipeline latency in milliseconds",
        )
        self._bar_e2e_latency = self._meter.create_histogram(
            "bar_e2e_latency_ms",
            description="End-to-end bar latency from arrival to signal enqueue",
        )

        self._vix_symbol: str | None = (
            "VX" if any(c.symbol == "VX" for c in self._contracts) else None
        )

    async def stop(self) -> None:
        self.logger.info("agent.shutdown_initiated", agent=self.name)
        if hasattr(self, "_executor"):
            self._executor.shutdown()
        self.logger.info("agent.thread_pool_shutdown", agent=self.name)
        await super().stop()

    def _build_plugin_circuit_breakers(self) -> dict[str, CircuitBreaker]:
        """Build a shadow-mode CircuitBreaker for every plugin in the registry.

        Each breaker is constructed with enabled=False (shadow mode) so
        allow_request() always returns True and live routing is unaffected.
        record_success() / record_failure() run unconditionally, accumulating
        real failure data before any decision to flip PLUGIN_CB_ENABLED=true.

        The failure_threshold and timeout_sec match the lazy-init defaults in
        PluginExecutor._get_plugin_cb() so pre-populated and lazily-created
        breakers are equivalent in behaviour.
        """
        all_plugins = TIER_I1 + TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6 + TIER_I7
        return {name: CircuitBreaker(**_SHADOW_CB_DEFAULTS, name=name) for name in all_plugins}

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        # ConfigService: shared pool, pre-warm threshold.* cache, inject into plugins.
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

        # TransformRecorder archived in Phase 78 (D-04). Pass recorder=None;
        # signal_processor.py guards all call sites with `if recorder is not None`.
        # graduation_analyzer still reads signal_transform_log — see #33 for migration plan.
        _symbol_filter_list = self.settings.intelligence_pipeline_symbol_filter
        symbol_filter = frozenset(_symbol_filter_list) if _symbol_filter_list else None
        self._cache_mgr = CacheManager(
            db=self._db,
            settings=self.settings,
            symbols=symbol_filter,
            on_instruments_changed=invalidate_active_contracts_cache,
        )
        async with self._db.pool.acquire() as conn:
            await enroll_all_plugins(conn)
        await self._cache_mgr.load_initial()
        for task in self._cache_mgr.start_refresh_loops():
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        await self._db.ensure_instruments_trigger()
        listener_task = self._cache_mgr.start_instruments_listener()
        self._background_tasks.add(listener_task)
        listener_task.add_done_callback(self._background_tasks.discard)
        self.logger.info("intelligence_pipeline.instruments_listener_started")

        self._executor = PluginExecutor(
            thread_pool=self._thread_pool,
            plugin_cache=self._plugin_cache,
            instrument_map=self._instrument_map,
            circuit_breakers=self._build_plugin_circuit_breakers(),
            observer=PluginObserver(),
        )

        # FeaturePipelineExecutor — 6th DAG node (D-18, Plan 01 Task 5)
        self._feature_pipeline = FeaturePipelineExecutor(
            bar_history=self._bar_history,
            executor=self._executor,
            state_mgr=self._state_mgr,
            instrument_map=self._instrument_map,
            vix_symbol=self._vix_symbol,
            settings=self.settings,
        )

        # Construct SignalProcessor (plan 05). Receives CacheSnapshot per bar, not CacheManager.
        self._sig_proc = SignalProcessor(
            cis_scorer=CISScorer(),
            settings=self.settings,
            transform_recorder=None,
        )

        # Restore cross-owned checkpoint fields into SignalProcessor
        if extra is not None:
            self._sig_proc.restore_kalman_state(extra.get("kalman_state", {}))
            self._sig_proc.restore_setup_last_fire(extra.get("setup_last_fire", {}))

        # CB open transition tracking (Phase 108 HEAL-03)
        self._cb_open_reported: set[str] = set()

        # Per-key concurrency — PERF-07 (D-01, D-03, D-16, D-28)
        self._worker_manager = PerKeyWorkerManager(
            processor=self._process_bar_inner,
            symbol_filter=symbol_filter,
            queue_maxsize=self.settings.intelligence_pipeline_queue_maxsize,
        )
        self._worker_manager.start_per_key_workers()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(_signal.SIGUSR1, self._on_hmm_sigusr1)
        self.logger.info(
            "agent.setup_complete",
            shadow=self._shadow_mode,
            symbols=self._symbols,
            timeframes=self._timeframes,
        )

    # Threshold keys owned by the 4 configurable I7 plugins.
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
        # --- migration 132: Phase 125 zone entry width gate (consumed by Phase 126) ---
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
        # --- migration 147: Phase 132 adaptive buffer coefficients (coupled piecewise — tune as a group) ---
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
    )

    async def _prewarm_threshold_config(self) -> None:
        """Pre-warm config cache and inject ConfigService into all configurable plugins."""
        assert self._config_service is not None
        for key, default in self._THRESHOLD_KEYS:
            await self._config_service.get(key, default)

        # Inject into module-level utility singletons (shared helpers, not plugins).
        from src.intelligence.trading import (  # noqa: PLC0415
            aggregator,
            cis_scorer,
            confidence,
            microstructure_utils,
            state_utils,
            trade_framer,
            volume_profile_utils,
            zone_engine,
        )

        confidence.set_config_service(self._config_service)
        microstructure_utils.set_config_service(self._config_service)
        state_utils.set_config_service(self._config_service)
        volume_profile_utils.set_config_service(self._config_service)
        zone_engine.set_config_service(self._config_service)
        trade_framer.set_config_service(self._config_service)
        aggregator.set_config_service(self._config_service)
        cis_scorer.set_config_service(self._config_service)

        # Inject config service into all plugins that opted in via the _config_service field.
        # Self-healing: as more plugins migrate, no changes here are needed.
        plugin_count = 0
        for p in self._plugin_cache.values():
            if hasattr(p, "_config_service"):
                p._config_service = self._config_service
                plugin_count += 1

        self.logger.info(
            "intelligence_pipeline.threshold_config_loaded",
            plugin_count=plugin_count,
            key_count=len(self._THRESHOLD_KEYS),
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
        self.logger.info("intelligence_pipeline.config_reloaded", config_key=key)

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
        # drain_task is always gathered below; no need to also track in _background_tasks
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
        """Override to also stop the Kafka consumer on SIGTERM/SIGINT.

        The base handler only sets _stop_event, which has no effect while
        _process_loop is blocked inside the async-for over messages(). Stopping
        the consumer closes it and causes StopAsyncIteration, unblocking the loop.
        """
        super()._register_signal_handlers()

        loop = asyncio.get_running_loop()

        async def _shutdown_consumer() -> None:
            self._stop_event.set()
            if hasattr(self, "_kafka_consumer"):
                try:
                    await self._kafka_consumer.stop()
                except Exception as error:
                    self.logger.warning(
                        "intelligence_pipeline.shutdown_consumer_error", error=str(error)
                    )

        def _signal_handler() -> None:
            loop.create_task(_shutdown_consumer())

        for sig in (_signal.SIGTERM, _signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

    def _on_hmm_sigusr1(self) -> None:
        self.logger.info("intelligence_pipeline.sigusr1_received")
        task = asyncio.create_task(self._reload_hmm_parameters())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        def _log_exc(t: asyncio.Task) -> None:
            if not t.cancelled() and (error := t.exception()):
                self.logger.error("intelligence_pipeline.hmm_reload_failed", error=str(error))

        task.add_done_callback(_log_exc)

    async def _reload_hmm_parameters(self) -> None:
        reloaded_names = self._executor.reload_hmm_parameters()
        self.logger.info(
            "intelligence_pipeline.hmm_reload_complete",
            hmm_reload=True,
            reloaded_plugin_names=reloaded_names,
        )

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
                            # MEDIUM-02: atomic contract hot-reload — never mutate in place.
                            # Preserve last-known-good on failure; emit telemetry on both paths.
                            try:
                                new_contracts = get_active_contracts(self.settings)
                                self._contracts = new_contracts  # atomic reference swap
                                CONTRACTS_RELOAD_TOTAL.add(1, {"status": "success"})
                                self.logger.info("contracts_reloaded", count=len(self._contracts))
                            except Exception as error:
                                CONTRACTS_RELOAD_TOTAL.add(1, {"status": "failure"})
                                self.logger.error("contracts_reload_failed", error=str(error))
                                # Last-known-good preserved — no assignment on failure
                        elif _topic == self._config_updates_topic:
                            await self._handle_config_update(payload)
                        else:
                            bar = self._parse_bar(payload)
                            if bar is None:
                                await self._send_to_dlq(payload, Exception("Parse failed"))
                                continue
                            # STRUCTURAL: backpressure circuit breaker — drop INCOMING bar
                            # (newest) when the per-key queue is full. try_enqueue uses
                            # put_nowait so a full queue never stalls the Kafka consumer loop.
                            # Dropping oldest would corrupt rolling windows and Kalman state.
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
        # PERF-08: model_construct skips Pydantic validation on the hot path.
        # Bars arrive from an internal trusted producer (bar-aggregator), so
        # field shapes are guaranteed by the upstream contract. Falls back to
        # full validation on error to surface schema violations via DLQ.
        # ts arrives as ISO string from Kafka; model_construct won't coerce it.
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
        """D-08 DAG router: gap detect → FPE → I7 → SignalProcessor → 4-way routing."""
        t0 = time.perf_counter()
        # Gap detection — PERF-09: flag tracked as explicit parameter, not via model_copy.
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
                # Hard 500ms outer timeout (D-12, 3-D): if the entire bar compute
                # exceeds 500ms, DLQ the bar with reason bar_tier_timeout rather than
                # blocking the consumer loop.
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
                # Enqueue to DLQ — short 1s timeout so the handler cannot
                # stall the consumer loop indefinitely.
                await self._out_queue.enqueue_blocking(
                    topic_signal_dlq(env),
                    msg_key,
                    dlq_payload,
                    timeout_sec=1.0,
                    priority=PRIORITY_HIGH,
                )

    async def _process_bar_compute(self, bar: BarMessage, *, t0: float, gap: bool = False) -> None:
        """Core I1-I7 compute and output routing — called from inside observed_span."""
        cache_snapshot = self._cache_mgr.snapshot()
        i1_start = time.perf_counter()
        try:
            fp_result = await self._feature_pipeline.run(bar, cache_snapshot, gap=gap)
        except Exception as error:
            self.logger.error(
                "pipeline.i1_i6_error", symbol=bar.symbol, tf=bar.tf, error=str(error)
            )
            self._pipeline_errors.add(1)
            return
        i1_duration_ms = (time.perf_counter() - i1_start) * 1000
        self._i1_latency_ms.record(i1_duration_ms, {"symbol": bar.symbol, "tf": bar.tf})
        if fp_result.event is None:
            return
        self._cache_mgr.update_hmm_regime(fp_result.hmm_regime)  # D-25
        event_dict = fp_result.event.model_dump()
        # Cache HTF intel for lower-TF bars to use as cross-tf context (D-19)
        if bar.tf in ("15m", "1h", "4h", "1d"):
            await self._cache_mgr.update_htf_intel(bar.tf, event_dict)
        msg_key = message_key(bar.symbol, bar.tf)
        env = self.settings.env_name
        intel_topic = (
            topic_intelligence_shadow(env) if self._shadow_mode else topic_intelligence(env)
        )
        # I7 via run_i7_complete (D-20); alpha decay in SignalProcessor (D-21)
        i7_start = time.perf_counter()
        plugin_states = self._state_mgr.get_all_states_for(bar.symbol, bar.tf)
        lock = self._state_mgr.get_lock((bar.symbol, bar.tf))
        raw_signals = await self._executor.run_i7_complete(
            fp_result.event, bar, cache_snapshot, plugin_states, lock, main_df=fp_result.main_df
        )
        if self._executor._last_i7_state_updates:
            self._state_mgr.update_batch(self._executor._last_i7_state_updates)
        i7_duration_ms = (time.perf_counter() - i7_start) * 1000
        self._i7_latency_ms.record(i7_duration_ms, {"symbol": bar.symbol, "tf": bar.tf})
        result = await self._sig_proc.process(
            fp_result.event,
            fp_result.tiered,
            bar,
            bar.symbol,
            bar.tf,
            raw_signals=raw_signals,
            cache_snapshot=cache_snapshot,
            flat_features=fp_result.flat_features,  # 3-E: precomputed once per bar
        )
        # 3-C batched enqueue: collect all non-None output payloads and submit via
        # a single enqueue_many() call, replacing sequential enqueue_blocking calls.
        # Intel: 3-B serialization fix — model_dump(mode="json") dict, not model_dump_json() string.
        # i7_signals XOR dlq (mutually exclusive): success path vs DLQ path.
        # winner: optional (absent when no winner this bar).
        # journal: LOW priority — collected here, LOW priority item in batch.
        i7_result = result.i7_result or {}
        journal_record = await self._build_journal_record(
            bar, fp_result.event, t0, msg_key, i7_result
        )
        _i7_signals_payload = result.signals_payload if result.success else None
        _dlq_payload = result.dlq_payload if not result.success else None
        _batch: list[tuple] = [
            # Intel event (HIGH) — 3-B: dict payload not nested JSON string
            (intel_topic, msg_key, fp_result.event.model_dump(mode="json"), PRIORITY_HIGH),
            # i7 signals or DLQ (HIGH) — mutually exclusive
            (
                (
                    topic_intelligence_i7_signals(env),
                    msg_key,
                    _i7_signals_payload,
                    PRIORITY_HIGH,
                )
                if _i7_signals_payload
                else (
                    (topic_signal_dlq(env), msg_key, _dlq_payload, PRIORITY_HIGH)
                    if _dlq_payload
                    else None
                )
            ),
            # Winner (HIGH) — None when no winner this bar
            (
                (topic_signals_aggregated(env), msg_key, result.winner_payload, PRIORITY_HIGH)
                if result.winner_payload
                else None
            ),
            # Journal (LOW) — silently dropped on timeout, never stalls pipeline
            (
                (
                    topic_intelligence_journal(env),
                    msg_key,
                    journal_record,
                    PRIORITY_LOW,
                )
                if journal_record
                else None
            ),
        ]
        await self._out_queue.enqueue_many(_batch, timeout_sec=5.0)
        pipeline_latency_ms = (time.perf_counter() - t0) * 1000
        self._pipeline_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
        self._bar_e2e_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
        self._bars_processed.add(1)
        try:
            for plugin_name, cb in self._executor.circuit_breakers.items():
                state = getattr(getattr(cb, "state", None), "value", None)
                if state == "open" and plugin_name not in self._cb_open_reported:
                    self._cb_open_reported.add(plugin_name)
                    self.logger.warning(
                        "intelligence_pipeline.cb_open",
                        plugin_id=plugin_name,
                        failure_count=getattr(cb, "failures", -1),
                    )
                elif state != "open" and plugin_name in self._cb_open_reported:
                    self._cb_open_reported.discard(plugin_name)
                    self.logger.info("intelligence_pipeline.cb_closed", plugin_id=plugin_name)
        except Exception as e:
            self.logger.warning("intelligence_pipeline.cb_scan_failed", error=str(e))
        # Journal enqueue is now part of the batched enqueue_many call above (3-C).
        # _enqueue_intel_journal is replaced by _build_journal_record + enqueue_many.

    def _assemble_checkpoint_extra(self) -> dict:
        """Build the cross-owned extra_state dict (HIGH finding 5: no plugin_states key).

        Final form (plan 05): kalman_state and setup_last_fire read from SignalProcessor.
        """
        return {
            "kalman_state": self._sig_proc.get_kalman_state(),
            "setup_last_fire": self._sig_proc.get_setup_last_fire(),
            "last_bar_offset": self._last_bar_offset,
        }

    async def _build_journal_record(
        self,
        bar: BarMessage,
        event: IntelligenceEvent,
        t0: float,
        msg_key: str,
        i7_result: dict | None,
    ) -> dict | None:
        """Build a BarIntelligenceRecord dict for the intelligence journal topic.

        Returns the record as a serialized dict (model_dump mode='json') so it can be
        included in the batched enqueue_many call (3-C). Returns None on any error.

        Journal is LOW priority — silently dropped by enqueue_many on timeout.
        Previously this method also enqueued; now it only builds (3-C refactor).
        """
        try:
            i7 = i7_result or {}
            ranked_dicts: list[dict] = i7.get("ranked", [])
            winner: dict | None = i7.get("winner")
            i7_computed_at: datetime = i7.get("i7_computed_at", datetime.now(UTC))

            ranked_signals = [signal_dict_to_ranked(s) for s in ranked_dicts]

            if winner is None:
                winner_plugin = None
                winner_confidence = None
                winner_direction = None
            else:
                winner_plugin = winner.get("setup_plugin")
                winner_direction = winner.get("direction")
                winner_confidence = winner.get("calibrated_confidence")
                if winner_confidence is None:
                    winner_confidence = winner.get("confidence")

            record = BarIntelligenceRecord(
                intelligence=event,
                ranked_signals=ranked_signals,
                winner_plugin=winner_plugin,
                winner_confidence=winner_confidence,
                winner_direction=winner_direction,
                signals_evaluated=i7.get("signals_evaluated", 0),
                signals_after_quality=i7.get("signals_after_quality", 0),
                signals_after_regime=i7.get("signals_after_regime", 0),
                signals_after_tod=i7.get("signals_after_tod", 0),
                signals_after_calibration=i7.get("signals_after_calibration", 0),
                ledger_written=len(ranked_dicts) > 0,
                session_type=normalize_session_type(event.session_type),
                i7_computed_at=i7_computed_at,
                pipeline_latency_ms=(time.perf_counter() - t0) * 1000,
            )
            return record.model_dump(mode="json")
        except Exception as error:
            self.logger.warning(
                "pipeline.journal_build_failed",
                symbol=bar.symbol,
                tf=bar.tf,
                error=str(error),
            )
            return None

    async def _health_monitor_loop(self) -> None:
        """Emit per-key worker queue gauges every 10 seconds.

        Gauges are DEFINED in per_key_worker_manager.py (single source of truth, D-25).
        This loop IMPORTS and reuses them — it does NOT create new gauge objects.
        """
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
    agent = IntelligencePipeline()
    asyncio.run(agent.start())
