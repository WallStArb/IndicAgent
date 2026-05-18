#!/usr/bin/env python3
"""IntelligencePipelineComputeAgent — Unified I1-I7 in-process pipeline.

Merges FeatureComputeAgent (I1-I6) and SignalGeneratorAgent (I7) into a single
agent that runs the full intelligence pipeline without Kafka between I6 and I7.

Key design decisions:
- I6 output feeds directly into I7 in-process (no Kafka round-trip)
- Async output buffer (asyncio.Queue maxsize=500) — hot path never blocks
- Hot state (plugin_states, kalman, tod_priors) checkpointed to local file on shutdown
- Bar history seeded from TimescaleDB (intelligence_features) on startup
- Attribution capture: pre_quality_confidence + pre_calibration_confidence
- Shadow mode via INTELLIGENCE_PIPELINE_SHADOW env var
"""

from __future__ import annotations

import asyncio
import os
import signal as _signal
import time
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog
from pydantic import ValidationError

from src.config.settings import get_active_contracts, get_settings
from src.core.agent.base import BaseAgent
from src.core.bar_history import BarHistory
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient

# TransformRecorder archived in Phase 78 (D-04) — import deferred to _setup()
# to avoid top-level production import of archived module.
from src.core.schemas.bar_message import BarMessage
from src.core.service_utils import (
    format_iso_ts,
    min_bars_for_tf,
    normalize_session_type,
)
from src.core.stream_keys import (
    TF_SECONDS,
    message_key,
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
from src.intelligence.context.vix_context import compute_vix_context
from src.intelligence.cross_asset_features import resolve_eq_index_base

# Re-import I1-I6 tiers from register_plugins (shared source of truth)
from src.intelligence.pipeline import (
    CacheManager,
    OutputQueue,
    PluginExecutor,
    PluginStateManager,
    apply_calibration,
    apply_quality_gate,
    apply_regime_gate,
    apply_tod_adjustment,
    rank_signals,
    select_winner,
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
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
    signal_dict_to_ranked,
)
from src.intelligence.trading.cis_scorer import CISScorer
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION
from src.observability.metrics import (
    INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL,
    REGIME_GATE_SUPPRESSIONS_TOTAL,
    THREAD_POOL_WORKERS,
    counter,
    gauge,
)
from src.observability.spans import ATTR_SYMBOL, ATTR_TF, observed_span

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

AGENT_VERSION = "v1"

_STANDARD_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

VIX_REGIME_TF: str = "1h"

I7_PLUGINS = TIER_I7

# Minimum bars between published signals per timeframe
MIN_BARS_BETWEEN_SIGNALS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}

# Per-setup cooldown — prevents same setup/direction recycling within N bars
_SIGNAL_COOLDOWN_BARS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}

# HMM regime integer -> semantic label
_HMM_REGIME_LABEL: dict[int, str] = {0: "ranging", 1: "trending", 2: "trending"}

# Alpha decay half-life bars
ALPHA_HALF_LIFE_BARS: dict[str, int] = {"1m": 10, "5m": 8, "15m": 8, "1h": 6}

# Phase 35: Eastern Time zone for hour extraction
_ET = zoneinfo.ZoneInfo("America/New_York")


def _apply_alpha_decay(sig: dict, tf: str, last_fire_state: dict | None) -> None:
    """QUAL-02: Apply alpha decay to signal confidence in-place."""
    if last_fire_state is None:
        return
    bars_since = last_fire_state.get("bars_since", 0)
    half_life = ALPHA_HALF_LIFE_BARS.get(tf, 6)
    multiplier = max(0.0, 1.0 - bars_since / half_life)
    sig["confidence"] = round(float(sig.get("confidence", 0.0)) * multiplier, 4)


def _cis_kalman_update(
    raw_cis: float, x_est: float, P_est: float, Q: float, R: float
) -> tuple[float, float]:
    """One predict+update step of the local-level 1D Kalman filter on CIS score."""
    P_pred = P_est + Q
    K = P_pred / (P_pred + R)
    x_new = x_est + K * (raw_cis - x_est)
    P_new = (1.0 - K) * P_pred
    return x_new, P_new


def _build_features_from_event(event: IntelligenceEvent) -> dict[str, Any]:
    """Build a features dict from a typed IntelligenceEvent for I7 plugins."""
    f: dict[str, Any] = {}
    for k, v in event.i1.model_dump().items():
        if v is not None:
            f[k] = v
    f["bb_middle"] = event.i1.bb_20_2_mid
    f["bb_upper"] = event.i1.bb_20_2_upper
    f["bb_lower"] = event.i1.bb_20_2_lower
    for tier_key in ("i2", "i3", "i4", "i5", "smc", "i6"):
        sub = getattr(event, tier_key, None)
        if sub is not None:
            for k, v in sub.model_dump().items():
                if v is not None:
                    f[k] = v
    f["vix"] = getattr(event, "vix", None)
    # HMM label separation: numeric hmm_regime stays as-is; hmm_regime_label is semantic string.
    # regime_type is NOT set here — it comes from plugin class attribute in _run_i7.
    hmm_val = f.get("hmm_regime")
    hmm_int = int(hmm_val) if hmm_val is not None else None
    f["hmm_regime_label"] = (
        _HMM_REGIME_LABEL.get(hmm_int, "unknown") if hmm_int is not None else None
    )
    return f


logger = structlog.get_logger(__name__)


def _extract_live_quote(live_quotes: dict, symbol: str) -> dict[str, float | None]:
    """Extract live bid/ask from _live_quotes dict."""
    entry = live_quotes.get(symbol)
    if not entry:
        return {"bid": None, "ask": None}

    def _parse(key: str) -> float | None:
        val = entry.get(key)
        if val is None:
            return None
        try:
            f = float(val)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    return {"bid": _parse("bid"), "ask": _parse("ask")}


# ---------------------------------------------------------------------------
# IntelligencePipelineComputeAgent
# ---------------------------------------------------------------------------

_OUTPUT_QUEUE_MAXSIZE = 500

# PluginTask, _timed_plugin_call, and _ANALYSIS_WAVES moved to executor.py (plan 04).


class IntelligencePipelineComputeAgent(BaseAgent):
    """Unified I1-I7 in-process pipeline agent.

    Replaces FeatureComputeAgent (I1-I6) and SignalGeneratorAgent (I7) with
    a single agent that runs the full pipeline per bar.

    Pipeline flow (per bar):
        BarMessage → gap_detection → BarHistory.append
        → I1 → [I2+I3+I4] → [I5+SMC] → I6
        → IntelligenceEvent enqueued to output buffer
        → I7 plugins → attribution capture → quality_gate → regime_gate
        → tod_adjust → calibration → rank → select_winner
        → SignalResult + StateSnapshot enqueued to output buffer
    """

    def __init__(self) -> None:

        # Override convention-based log path if LOG_FILE env var is set
        # Must call setup_service_logging BEFORE super().__init__() to override default
        _log_file = os.environ.get("LOG_FILE")
        if _log_file:
            from src.core.service_utils import setup_service_logging

            setup_service_logging(_log_file)

        _settings = get_settings()
        super().__init__(
            name="intelligence_pipeline_agent",
            max_idle_seconds=300,
            settings=_settings,
        )

        self._contracts = get_active_contracts(self.settings)
        self._symbols = [c.symbol for c in self._contracts]
        self._timeframes = list(_STANDARD_TFS)

        # Plugin registry
        register_all_plugins()
        for tier_list, tier_name in [
            (TIER_I1, "I1"),
            (TIER_I2, "I2"),
            (TIER_I3, "I3"),
            (TIER_I4, "I4"),
            (TIER_I5, "I5"),
            (TIER_SMC, "SMC"),
            (TIER_I6, "I6"),
            (TIER_I7, "I7"),
        ]:
            registry.validate_tier(tier_list, tier_name)

        # Full plugin validation — hard-crashes on misconfiguration
        from src.core.plugin_validator import PluginValidator

        PluginValidator().validate_all()

        # Plugin caches
        self._plugin_cache: dict[str, Any] = {}
        for n in TIER_I1:
            self._plugin_cache[n] = registry.get_indicator(n)
        for n in TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6 + TIER_I7:
            self._plugin_cache[n] = registry.get_pattern(n)

        self._instrument_map: dict[str, Any] = {c.symbol: c for c in self._contracts}

        # --- State dicts (cross-owned checkpointed fields — plugin_states owned by PluginStateManager) ---
        self._kalman_state: dict = {}  # (symbol, tf) -> {x, P, Q, R}
        self._bar_history = BarHistory(maxlen=200)
        self._last_bar_offset: dict = {}  # (symbol, tf) -> int (Kafka offset)

        # --- Transient state (NOT checkpointed) ---
        self._signal_gate: dict = {}  # (symbol, tf) -> gate dict
        self._setup_cooldown: dict = {}  # (symbol, tf, plugin, direction) -> datetime
        self._setup_last_fire: dict = {}  # (symbol, tf, plugin, direction) -> {bars_since}
        self._cross_asset_cache: dict = {}
        self._macro_cache: dict = {}
        self._htf_intel_cache: dict = {}
        self._live_quotes: dict = {}
        self._df_cache: dict = {}
        self._prev_i1_features: dict = {}
        self._last_bar_ts: dict = {}
        self._last_events: dict = {}

        # Create thread pool — capped at 12 workers to reduce GIL contention.
        # CPU-bound Python plugins can't parallelize under GIL; 48 workers just
        # adds context-switching overhead. 8-12 is optimal for numpy/pandas ops
        # that do release the GIL.
        # NOTE: self._thread_pool is owned by PluginExecutor; constructed here so
        # THREAD_POOL_WORKERS metric can fire before _setup(). D-06: self._executor
        # is reserved for the PluginExecutor instance (constructed in _setup()).
        cpu_count = os.cpu_count() or 24
        _configured = self.settings.intelligence_thread_pool_workers
        _workers = _configured if _configured > 0 else min(12, max(4, cpu_count // 2))
        self._thread_pool = ThreadPoolExecutor(max_workers=_workers, thread_name_prefix="intel_")
        THREAD_POOL_WORKERS.add(_workers)

        # CIS / aggregator state
        self._cis_scorer = CISScorer()
        # CIS scorer mediation: orchestrator syncs scorer when cis_weights_version changes.
        # After plan 05 this moves into SignalProcessor.sync_cis_weights.
        self._last_synced_cis_version: int = 0

        # I7 config — wired to Settings (not hardcoded)
        self._regime_prob_min: float = self.settings.regime_prob_min
        self._regime_prob_soft_max: float = self.settings.REGIME_PROB_SOFT_MAX
        self._regime_dur_min: int = self.settings.regime_dur_min

        # Per-plugin circuit breakers and call counts moved to PluginExecutor (plan 04).

        # Shadow mode
        self._shadow_mode: bool = os.environ.get("INTELLIGENCE_PIPELINE_SHADOW", "0") == "1"

        # Consumer group
        self._consumer_group = "intelligence_pipeline_group"

        # Background tasks — prevent GC before completion (matches alpha_swarm pattern)
        self._background_tasks: set = set()

        # --- Prometheus metrics ---
        self._bars_processed = counter(
            "intelligence_pipeline_bars_processed_total",
            "Bars processed through I1-I7 pipeline",
        )
        self._i1_latency_ms = gauge(
            "intelligence_pipeline_i1_latency_ms", "I1 tier execution time in milliseconds"
        )
        self._i7_latency_ms = gauge(
            "intelligence_pipeline_i7_latency_ms", "I7 tier execution time in milliseconds"
        )
        self._signals_generated = counter(
            "intelligence_pipeline_signals_generated_total",
            "Raw signals generated by I7 plugins",
        )
        self._signals_selected = counter(
            "intelligence_pipeline_signals_selected_total",
            "Winner signals selected by aggregator",
        )
        self._signal_dlq_total = counter(
            "intelligence_pipeline_signal_dlq_total",
            "Bars dropped to DLQ due to CIS assertion failure (one count per bar)",
        )
        self._pipeline_errors = counter(
            "intelligence_pipeline_pipeline_errors_total",
            "Pipeline processing errors",
        )
        self._pipeline_latency = gauge(
            "intelligence_pipeline_pipeline_latency_ms",
            "Per-bar pipeline latency in milliseconds",
        )
        # _plugin_call_counts and _plugin_skipped_total moved to PluginExecutor (plan 04).

        self._vix_symbol: str | None = None
        for c in self._contracts:
            if c.symbol == "VX":
                self._vix_symbol = "VX"
                break

    async def stop(self) -> None:
        """Shutdown PluginExecutor (which owns the thread pool) before stopping."""
        self.logger.info("agent.shutdown_initiated", agent=self.name)
        # Delegate shutdown to PluginExecutor — it calls self._thread_pool.shutdown(wait=True).
        # Do NOT also call self._thread_pool.shutdown() here to avoid double-shutdown.
        if hasattr(self, "_executor"):
            self._executor.shutdown()
        self.logger.info("agent.thread_pool_shutdown", agent=self.name)
        await super().stop()

    # ------------------------------------------------------------------
    # _setup: DB connect, state restore, Kafka setup, cache loading
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        # 1. Connect DB
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        # 2. Setup Kafka clients (must come before checkpoint restore + seed)
        # (moved to here so kafka_producer is available for BarHistorySeeder)
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        topics = [
            topic_market_bars(self.settings.env_name),
            topic_market_bars_htf(self.settings.env_name),
            topic_system_events(self.settings.env_name),
            topic_cross_asset(self.settings.env_name),
            topic_macro_signals(self.settings.env_name),
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

        # 2b. Construct OutputQueue now that producer is available
        self._out_queue = OutputQueue(producer=self._kafka_producer, maxsize=_OUTPUT_QUEUE_MAXSIZE)

        # 3. Ensure checkpoint dir exists, construct PluginStateManager, restore hot state
        _CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state_mgr = PluginStateManager(checkpoint_path=_CHECKPOINT_PATH)
        extra = await self._state_mgr.read_checkpoint()
        if extra is not None:
            # Restore cross-owned fields onto orchestrator attributes
            # tod_priors migrated to CacheManager (plan 03); applied via seed_tod_priors below.
            self._last_bar_offset = extra.get("last_bar_offset", {})
            self._kalman_state = extra.get("kalman_state", {})
            self._setup_last_fire = extra.get("setup_last_fire", {})

        # Start background checkpoint loop — orchestrator calls once; PluginStateManager owns timing
        ckpt_task = self._state_mgr.start_checkpoint_loop(300, self._assemble_checkpoint_extra)
        self._background_tasks.add(ckpt_task)
        ckpt_task.add_done_callback(self._background_tasks.discard)

        # 4. Seed bar_history from DB — always authoritative, not a fallback
        await self._seed_bar_history_from_db()

        # 5. Construct TransformRecorder (shared across all pipeline runs)
        # Deferred import: TransformRecorder archived in Phase 78 (D-04).
        # Will be replaced by LineageRecorder in a future plan.
        from src.core.ml.transform_recorder import TransformRecorder  # noqa: PLC0415

        self._transform_recorder = TransformRecorder(
            pool=self._db.pool, batch_size=100, flush_interval_s=2.0
        )

        # 6. Construct CacheManager; enroll shadow registry BEFORE load_initial (MEDIUM finding).
        # load_initial() runs _load_shadow_cache last — it reads the now-populated registry.
        self._cache_mgr = CacheManager(db=self._db, settings=self.settings)
        # Shadow registry must be seeded BEFORE _load_shadow_cache runs inside load_initial.
        async with self._db.pool.acquire() as conn:
            await enroll_all_plugins(conn)
        # Eager load all 6 caches (HIGH finding 3 — preserves god-class _setup behavior).
        # Without this the service starts cold for up to 4 hours.
        await self._cache_mgr.load_initial()
        # Start background refresh loops AFTER load_initial so loops sleep-first without cold gap.
        for task in self._cache_mgr.start_refresh_loops():
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # Apply checkpointed tod_priors ON TOP of DB-loaded values (merge semantics).
        # Order: enroll_all_plugins -> load_initial (loads tod from DB) -> seed checkpoint priors.
        if extra is not None:
            self._cache_mgr.seed_tod_priors(extra.get("tod_priors", {}))

        # 7. Construct PluginExecutor (D-06: stored as self._executor).
        # Receives self._thread_pool; PluginExecutor.shutdown() will shut it down.
        # self._plugin_cache and self._instrument_map are owned by the executor after this.
        self._executor = PluginExecutor(
            thread_pool=self._thread_pool,
            plugin_cache=self._plugin_cache,
            instrument_map=self._instrument_map,
            circuit_breakers={},
        )

        # 8. SIGUSR1 hot-reload: triggered by HMMTrainingAgent after writing new parameter files.
        # asyncio.get_running_loop() MUST be used here (not get_event_loop()) — this is
        # inside an async function so the running loop is guaranteed to be the right one.
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(_signal.SIGUSR1, self._on_hmm_sigusr1)
        self.logger.info("intelligence_pipeline.sigusr1_handler_registered")

        self.logger.info(
            "agent.setup_complete",
            shadow=self._shadow_mode,
            symbols=self._symbols,
            timeframes=self._timeframes,
        )

    async def _seed_bar_history_from_db(self) -> None:
        """Seed BarHistory from intelligence_features (fallback)."""
        try:
            from src.core.bar_history_seeder import BarHistorySeeder

            config = {"service": {"timeframes": list(self._timeframes)}}
            seeder = BarHistorySeeder(self.settings, config, self._kafka_producer)
            await seeder.seed(self._bar_history)
        except Exception as exc:
            self.logger.warning("bar_history.seed_failed", error=str(exc))

    # ------------------------------------------------------------------
    # _run: main event loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Main loop: consume bars, run I1-I7, drain output."""
        drain_task = asyncio.create_task(self._out_queue.drain_loop(lambda: self.running))
        self._background_tasks.add(drain_task)
        drain_task.add_done_callback(self._background_tasks.discard)
        tasks = [
            asyncio.create_task(self._process_loop()),
            drain_task,
            asyncio.create_task(self._health_monitor_loop()),
            asyncio.create_task(self._report_consumer_lag()),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Log any task exceptions (swallowed by return_exceptions=True)
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
        """Drain output queue, persist hot state, close connections."""
        self._stop_event.set()
        # Wait for output queue to drain (10s timeout)
        try:
            await asyncio.wait_for(self._out_queue.join(), timeout=10.0)
        except TimeoutError:
            self.logger.warning("teardown.output_drain_timeout")
        if hasattr(self, "_state_mgr"):
            self._state_mgr.write_checkpoint(self._assemble_checkpoint_extra())
        if hasattr(self, "_kafka_consumer"):
            await self._kafka_consumer.stop()
        if hasattr(self, "_kafka_producer"):
            await self._kafka_producer.stop()
        if hasattr(self, "_transform_recorder"):
            try:
                await self._transform_recorder.flush()
            except Exception as exc:
                self.logger.warning("teardown.transform_recorder_flush_failed", error=str(exc))
        if hasattr(self, "_db"):
            await self._db.close()
        self.logger.info("agent.teardown_complete")

    # ------------------------------------------------------------------
    # SIGUSR1 hot-reload for HMM parameters
    # ------------------------------------------------------------------

    def _on_hmm_sigusr1(self) -> None:
        """Sync SIGUSR1 handler — schedules HMM parameter hot-reload via asyncio task.

        Signal handlers must be synchronous; async work is scheduled via create_task.
        The task is stored in self._background_tasks to prevent GC before completion.
        Matches the pattern used in alpha_swarm_agent.py.
        """
        self.logger.info("intelligence_pipeline.sigusr1_received")
        task = asyncio.create_task(self._reload_hmm_parameters())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        def _log_exc(t: asyncio.Task) -> None:
            if not t.cancelled() and (exc := t.exception()):
                self.logger.error("intelligence_pipeline.hmm_reload_failed", error=str(exc))

        task.add_done_callback(_log_exc)

    async def _reload_hmm_parameters(self) -> None:
        """Reload parameters on all HMM instances in TIER_SMC (SIGUSR1 trigger).

        Delegates to PluginExecutor.reload_hmm_parameters() which owns the plugin cache.
        """
        reloaded_names = self._executor.reload_hmm_parameters()
        self.logger.info(
            "intelligence_pipeline.hmm_reload_complete",
            hmm_reload=True,
            reloaded_plugin_names=reloaded_names,
        )

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        """Consume all topics and route: bar → I1-I7 pipeline; non-bar → caches."""
        _cross_asset_topic = topic_cross_asset(self.settings.env_name)
        _macro_topic = topic_macro_signals(self.settings.env_name)
        _system_topic = topic_system_events(self.settings.env_name)
        COMMIT_BATCH_SIZE = 100  # Batch commits to avoid per-message network latency
        msg_count = 0
        while self.running:
            try:
                async for _topic, _key, payload in self._kafka_consumer.messages():
                    if not isinstance(payload, dict):
                        continue
                    self._record_message_consumed()
                    try:
                        if _topic == _cross_asset_topic:
                            tf = payload.get("tf", "1m")
                            self._cross_asset_cache[tf] = payload
                        elif _topic == _macro_topic:
                            tf = payload.get("timeframe", payload.get("tf", "1m"))
                            self._macro_cache.setdefault(tf, {}).update(
                                {
                                    k: payload[k]
                                    for k in (
                                        "yield_curve_slope",
                                        "yield_curve_regime",
                                        "ftq_score",
                                        "ftq_regime",
                                    )
                                    if k in payload
                                }
                            )
                        elif _topic == _system_topic:
                            await self._handle_system_event(payload)
                        else:
                            bar = self._parse_bar(payload)
                            if bar is None:
                                # Parse failed — route to DLQ for analysis
                                await self._send_to_dlq(payload, Exception("Parse failed"))
                                continue
                            await self._process_bar(bar)

                        # Commit offset in batches to avoid hot-path latency
                        # Manual commit ensures deterministic offset persistence (fixes 32h reprocessing bug)
                        msg_count += 1
                        if msg_count >= COMMIT_BATCH_SIZE:
                            await self._kafka_consumer.commit()
                            msg_count = 0
                    except Exception as exc:
                        self.logger.error(
                            "bar.process_error",
                            error=str(exc),
                        )
                        self._pipeline_errors.add(1)
            except Exception as exc:
                self.logger.warning("process_loop.consumer_error", error=str(exc))
                await asyncio.sleep(1)

    def _dlq_topic(self) -> str | None:
        """Route unparseable bar payloads to DLQ."""
        return topic_intelligence_pipeline_dlq(self.settings.env_name)

    def _parse_bar(self, msg: dict) -> BarMessage | None:
        """Parse a Kafka message into BarMessage."""
        try:
            return BarMessage(**msg)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Per-bar pipeline (I1 → I7)
    # ------------------------------------------------------------------

    async def _process_bar(self, bar: BarMessage) -> None:
        """Core per-bar processing: gap detection → I1-I7 → output."""
        async with observed_span(
            "pipeline.process_bar",
            **{ATTR_SYMBOL: bar.symbol, ATTR_TF: bar.tf},
        ):
            await self._process_bar_inner(bar)

    async def _process_bar_inner(self, bar: BarMessage) -> None:
        """Inner implementation of _process_bar (called inside OTel span)."""
        t0 = time.perf_counter()

        # 1. Gap detection
        key = f"{bar.symbol}:{bar.tf}"
        prev_ts = self._last_bar_ts.get(key)
        if prev_ts is not None:
            tf_seconds = TF_SECONDS.get(bar.tf, 60)
            if (bar.ts.timestamp() - prev_ts) > tf_seconds * 1.5:
                bar = bar.model_copy(update={"gap_preceding": True})
        self._last_bar_ts[key] = bar.ts.timestamp()

        # 2. Append to BarHistory
        self._bar_history.append(bar)

        # 3. Check warm
        if not self._bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
            return

        # 4. Run I1-I6 pipeline
        try:
            intel_event, tiered = await self._run_i1_to_i6(bar, t0)
        except Exception as exc:
            self.logger.error("pipeline.i1_i6_error", symbol=bar.symbol, tf=bar.tf, error=str(exc))
            self._pipeline_errors.add(1)
            return

        if intel_event is None:
            return

        # 5. Enqueue IntelligenceEvent to output buffer
        msg_key = message_key(bar.symbol, bar.tf)
        output_topic = (
            topic_intelligence_shadow(self.settings.env_name)
            if self._shadow_mode
            else topic_intelligence(self.settings.env_name)
        )
        self._out_queue.enqueue(output_topic, msg_key, {"event": intel_event.model_dump_json()})

        # 6. Run I7 pipeline (in-process, no Kafka)
        i7_result: dict | None = None
        try:
            i7_result = await self._run_i7(bar, intel_event, tiered)
        except Exception as exc:
            self.logger.error("pipeline.i7_error", symbol=bar.symbol, tf=bar.tf, error=str(exc))
            self._pipeline_errors.add(1)

        # Publish BarIntelligenceRecord to journal (after I7 so ranked_signals are available)
        self._enqueue_intel_journal(bar, intel_event, t0, msg_key, i7_result)

        self._bars_processed.add(1)

    # ------------------------------------------------------------------
    # I1-I6 pipeline (from FeatureComputeAgent)
    # ------------------------------------------------------------------

    async def _run_i1_to_i6(
        self, bar: BarMessage, t0: float
    ) -> tuple[IntelligenceEvent | None, dict | None]:
        """Run I1→I2→I3→I4→I5→SMC→I6 and return (IntelligenceEvent, tiered)."""
        symbol, tf = bar.symbol, bar.tf
        key = f"{symbol}:{tf}"

        # Build frames dict
        main_df = self._bar_history.to_dataframe(symbol, tf)
        frames: dict[str, Any] = {"main": main_df, "__symbol__": symbol, "__timeframe__": tf}

        # Inject cross-TF data
        for other_tf in _STANDARD_TFS:
            if other_tf == tf:
                continue
            other_deque = self._bar_history.get(symbol, other_tf)
            if len(other_deque) >= 50:
                frames[f"tf_{other_tf}"] = self._bar_history.to_dataframe(symbol, other_tf)
            cached_evt = self._last_events.get(f"{symbol}:{other_tf}")
            if cached_evt:
                intel_dict = cached_evt.model_dump()
                flattened = {}
                for tier_name, tier_data in intel_dict.items():
                    if tier_name in ("i1", "i2", "i3", "i4", "i5", "smc", "i6") and isinstance(
                        tier_data, dict
                    ):
                        flattened.update(tier_data)
                    else:
                        flattened[tier_name] = tier_data
                frames[f"intel_{other_tf}"] = flattened

        instrument = self._instrument_map.get(symbol)
        if instrument:
            frames["__instrument__"] = instrument

        # Inject prev I1 features
        frames["prev_features"] = self._prev_i1_features.get(key, {})

        # Cross-asset (merge macro factors in so I7 plugins see a unified context)
        if resolve_eq_index_base(symbol) is not None:
            cross_asset = {**self._cross_asset_cache.get(tf, {"ready": False})}
            cross_asset.update(self._macro_cache.get(tf, {}))
            frames["cross_asset"] = cross_asset
            cross_asset_5m = {**self._cross_asset_cache.get("5m", {"ready": False})}
            cross_asset_5m.update(self._macro_cache.get("5m", {}))
            frames["cross_asset_5m"] = cross_asset_5m

        # VIX context
        if self._vix_symbol:
            vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
            frames["vix"] = compute_vix_context(vix_deque)
        else:
            frames["vix"] = {"ready": False}

        # HTF intelligence cache injection
        htf_cache = self._htf_intel_cache.get(tf)
        if htf_cache:
            frames["htf_intel"] = htf_cache

        # Get per-bar plugin states and lock once (HIGH finding 1)
        plugin_states = self._state_mgr.get_all_states_for(symbol, tf)
        lock = self._state_mgr.get_lock((symbol, tf))

        # I1 — executor returns (outputs, state_updates)
        i1_result, i1_state_updates = await self._executor.run_i1(
            plugin_states,
            lock,
            frames,
            symbol,
            tf,
            shadow_cache=self._cache_mgr.shadow_cache,
        )
        if i1_state_updates:
            self._state_mgr.update_batch(i1_state_updates)
        frames["features"] = dict(i1_result)
        self._prev_i1_features[key] = dict(i1_result)
        self._last_events[key + "_i1"] = i1_result

        # I2-I6 — executor returns (tiered, state_updates)
        tiered, tier_state_updates = await self._executor.run_tiers(
            plugin_states,
            lock,
            bar,
            symbol,
            tf,
            frames,
            shadow_cache=self._cache_mgr.shadow_cache,
        )
        if tier_state_updates:
            self._state_mgr.update_batch(tier_state_updates)
        if not tiered:
            return None, None

        pipeline_latency_ms = (time.perf_counter() - t0) * 1000

        self._pipeline_latency.add(pipeline_latency_ms)

        # Construct IntelligenceEvent
        try:
            event = IntelligenceEvent(
                ts=bar.ts,
                symbol=symbol,
                tf=tf,
                bar=OHLCVBar(o=bar.open, h=bar.high, l=bar.low, c=bar.close, v=bar.volume),
                i1=I1Indicators(**{k: v for k, v in i1_result.items() if v is not None}),
                i2=I2Events(**{k: v for k, v in tiered.get("i2", {}).items() if v is not None}),
                i3=I3Structure(**{k: v for k, v in tiered.get("i3", {}).items() if v is not None}),
                i4=I4Context(**{k: v for k, v in tiered.get("i4", {}).items() if v is not None}),
                i5=I5Patterns(**{k: v for k, v in tiered.get("i5", {}).items() if v is not None}),
                smc=SMCContext(**{k: v for k, v in tiered.get("smc", {}).items() if v is not None}),
                i6=I6Confluence(**{k: v for k, v in tiered.get("i6", {}).items() if v is not None}),
                source="live",
                session_type=bar.session_type,
                pipeline_latency_ms=pipeline_latency_ms,
                computed_at=datetime.now(UTC),
                bar_id=bar.bar_id,
            )
        except ValidationError as exc:
            self.logger.error(
                "IntelligenceEvent validation failed",
                symbol=symbol,
                tf=tf,
                error=str(exc),
            )
            self._pipeline_errors.add(1)
            return None, None

        self._last_events[key] = event
        return event, tiered

    # ------------------------------------------------------------------
    # I7 signal generation pipeline
    # ------------------------------------------------------------------

    async def _run_i7(self, bar: BarMessage, event: IntelligenceEvent, tiered: dict) -> dict:
        """Run I7 plugins → quality gate → regime gate → calibration → rank → select.

        Returns a dict of I7 results for BarIntelligenceRecord construction:
            ranked, winner, n_raw, n_quality, n_regime, n_tod, n_calibrated, i7_computed_at
        """
        async with observed_span(
            "pipeline.run_i7",
            **{ATTR_SYMBOL: bar.symbol, ATTR_TF: bar.tf},
        ):
            return await self._run_i7_inner(bar, event, tiered)

    async def _run_i7_inner(self, bar: BarMessage, event: IntelligenceEvent, tiered: dict) -> dict:
        """Inner implementation of _run_i7 (called inside OTel span)."""
        symbol, tf = bar.symbol, bar.tf
        features = _build_features_from_event(event)
        i7_computed_at = datetime.now(UTC)

        # Track last-known HMM regime for regime-conditioned perf_weights loading
        hmm_val = features.get("hmm_regime")
        if isinstance(hmm_val, (int, float)):
            self._cache_mgr.update_hmm_regime(int(hmm_val))

        # CIS scorer mediation: sync weights when version changes (Pitfall 4 / D-07).
        # CacheManager never calls update_weights; orchestrator mediates here.
        # After plan 05 this moves into SignalProcessor.sync_cis_weights().
        if self._cache_mgr.cis_weights_version != self._last_synced_cis_version:
            self._cis_scorer.update_weights(
                self._cache_mgr.cis_weights, self._cache_mgr.cis_weights_version
            )
            self._last_synced_cis_version = self._cache_mgr.cis_weights_version

        # Run all I7 plugins in parallel via executor
        i7_start = time.perf_counter()

        main_df = self._bar_history.to_dataframe(symbol, tf)
        plugin_input = {
            "main": main_df,
            "features": features,
            "__symbol__": symbol,
            "__timeframe__": tf,
            "timeframe": tf,
        }

        # Per-bar state view and lock (HIGH finding 1)
        i7_plugin_states = self._state_mgr.get_all_states_for(symbol, tf)
        lock = self._state_mgr.get_lock((symbol, tf))

        tasks, outputs, sig_state_updates = await self._executor.run_i7_plugins(
            i7_plugin_states,
            lock,
            bar,
            symbol,
            tf,
            plugin_input,
            shadow_cache=self._cache_mgr.shadow_cache,
        )
        if sig_state_updates:
            self._state_mgr.update_batch(sig_state_updates)

        # Process I7-specific signal generation — also build plugin_outputs for CIS scoring
        raw_signals: list[dict] = []
        plugin_outputs: dict[str, dict] = {}
        for task, output in zip(tasks, outputs):  # noqa: B905 — lengths differ on plugin exceptions
            output.pop("_tier_key", None)
            if output.get("direction", 0) != 0:
                sig = output
                sig["setup_plugin"] = task.plugin_name
                sig["symbol"] = symbol
                sig["tf"] = tf
                # regime_type from plugin class attribute — NOT from HMM numeric value
                plugin_inst = self._executor._plugin_cache.get(task.plugin_name)
                sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")

                # Alpha decay
                fire_key = (symbol, tf, task.plugin_name, sig.get("direction", 0))
                _apply_alpha_decay(sig, tf, self._setup_last_fire.get(fire_key))

                raw_signals.append(sig)
                plugin_outputs[task.plugin_name] = sig
                self._signals_generated.add(1)

        # Record timing metric
        i7_latency_ms = (time.perf_counter() - i7_start) * 1000
        self._i7_latency_ms.add(i7_latency_ms)

        if not raw_signals:
            return {
                "ranked": [],
                "winner": None,
                "signals_evaluated": 0,
                "signals_after_quality": 0,
                "signals_after_regime": 0,
                "signals_after_tod": 0,
                "signals_after_calibration": 0,
                "i7_computed_at": i7_computed_at,
            }

        # Compute CIS score once per bar (bar-level, not signal-level)
        cis_result = self._cis_scorer.score(features, plugin_outputs)
        raw_cis = cis_result.cis_score

        # Kalman-filter the CIS score to smooth bar-to-bar noise
        kalman_key = (symbol, tf)
        if kalman_key not in self._kalman_state:
            kp = (
                self._cache_mgr.cis_kalman_params.get(tf)
                or self._cache_mgr.cis_kalman_params["default"]
            )
            self._kalman_state[kalman_key] = {"x": raw_cis, "P": 1.0, "Q": kp["Q"], "R": kp["R"]}
        ks = self._kalman_state[kalman_key]
        filtered_cis, new_P = _cis_kalman_update(raw_cis, ks["x"], ks["P"], ks["Q"], ks["R"])
        self._kalman_state[kalman_key]["x"] = filtered_cis
        self._kalman_state[kalman_key]["P"] = new_P

        # Attribution capture: BEFORE quality gate
        for sig in raw_signals:
            sig["pre_quality_confidence"] = sig.get("confidence", 0.0)

        # Pipeline stages
        hour_et = bar.ts.astimezone(_ET).hour
        quality_gated = await apply_quality_gate(
            raw_signals, features, tf=tf, recorder=self._transform_recorder
        )

        # Attribution capture: AFTER quality gate, BEFORE regime gate
        for sig in quality_gated:
            sig["pre_regime_confidence"] = sig.get("confidence", 0.0)

        regime_gated = await apply_regime_gate(
            quality_gated,
            features,
            prob_min=self._regime_prob_min,
            prob_soft_max=self._regime_prob_soft_max,
            dur_min=self._regime_dur_min,
            tf=tf,
            recorder=self._transform_recorder,
        )

        # Regime suppression metric
        for sig in regime_gated:
            if not sig.get("regime_eligible", True):
                REGIME_GATE_SUPPRESSIONS_TOTAL.add(
                    1,
                    {
                        "reason": "regime_type",
                        "plugin": sig.get("setup_plugin", ""),
                        "tf": tf,
                    },
                )

        # Attribution capture: AFTER regime gate, BEFORE TOD adjustment
        for sig in regime_gated:
            sig["pre_tod_confidence"] = sig.get("confidence", 0.0)

        tod_adjusted = await apply_tod_adjustment(
            regime_gated,
            self._cache_mgr.tod_priors,
            tf,
            hour_et,
            symbol=symbol,
            recorder=self._transform_recorder,
        )

        # Attribution capture: BEFORE calibration
        for sig in tod_adjusted:
            sig["pre_calibration_confidence"] = sig.get("confidence", 0.0)

        calibrated = await apply_calibration(
            tod_adjusted,
            self._cache_mgr.calibration_curves,
            tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )
        ranked = await rank_signals(
            calibrated,
            self._cache_mgr.perf_weights,
            tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )

        # Annotate each ranked signal with ledger metadata before publishing
        num_signals = len(ranked)
        for rank_idx, sig in enumerate(ranked, start=1):
            sig["composite_rank"] = rank_idx
            sig["num_signals_bar"] = num_signals
            sig["was_selected"] = False  # filled in after winner selection below
            sig["status"] = "pending" if sig.get("regime_eligible", True) else "regime_suppressed"
            # Regime context — regime_type already set from plugin class attribute above
            sig["hmm_regime_at_fire"] = features.get("hmm_regime")
            sig["is_shadow"] = self._executor._is_shadow(
                sig.get("setup_plugin", ""), self._cache_mgr.shadow_cache
            )
            # Stamp CIS fields (bar-level score, same for all signals in this bar)
            sig["raw_cis_score"] = round(raw_cis, 4)
            sig["filtered_cis_score"] = round(filtered_cis, 4)
            sig["bucket_scores"] = cis_result.bucket_scores
            sig["weights_version"] = cis_result.weights_version
            # bar_id traceability — flows to signal_ledger via writer (Phase 68-03)
            sig["bar_id"] = str(bar.bar_id)

        # Select winner — pass all ranked signals (select_winner filters active internally)
        winner, _, resolution_method = select_winner(
            ranked, cis_result, long_bias=self.settings.winner_long_bias
        )

        # Stamp resolution_method on every ranked signal (not just the winner)
        for sig in ranked:
            sig["resolution_method"] = resolution_method

        winner_plugin = winner.get("setup_plugin") if winner else None

        # Mark the winner
        if winner_plugin is not None:
            for sig in ranked:
                if sig.get("setup_plugin") == winner_plugin and sig.get("regime_eligible", True):
                    sig["was_selected"] = True
                    break

        # Publish ALL ranked signals — assertion + DLQ gating inside
        published = await self._publish_signals_or_dlq(ranked, symbol, tf, bar)
        if not published:
            return {
                "ranked": [],
                "winner": None,
                "signals_evaluated": len(raw_signals),
                "signals_after_quality": len(quality_gated),
                "signals_after_regime": len(regime_gated),
                "signals_after_tod": len(tod_adjusted),
                "signals_after_calibration": len(calibrated),
                "i7_computed_at": i7_computed_at,
            }

        # Publish winner to signals.aggregated for signal_tracker_agent
        if winner:
            self._signals_selected.add(1)
            await self._out_queue.enqueue_blocking(
                topic_signals_aggregated(self.settings.env_name),
                message_key(symbol, tf),
                winner,
            )

        return {
            "ranked": ranked,
            "winner": winner,
            "signals_evaluated": len(raw_signals),
            "signals_after_quality": len(quality_gated),
            "signals_after_regime": len(regime_gated),
            "signals_after_tod": len(tod_adjusted),
            "signals_after_calibration": len(calibrated),
            "i7_computed_at": i7_computed_at,
        }

    # ------------------------------------------------------------------
    # Checkpoint extra-state assembly (cross-owned fields only)
    # ------------------------------------------------------------------

    def _assemble_checkpoint_extra(self) -> dict:
        """Build the cross-owned extra_state dict for PluginStateManager.write_checkpoint.

        CRITICAL (HIGH finding 5): this dict MUST NOT contain a 'plugin_states' key.
        PluginStateManager owns that field internally.

        Post-plan-03 form: tod_priors reads from self._cache_mgr.tod_priors.
        - Plan 05 will migrate kalman_state / setup_last_fire -> self._sig_proc.get_*()
        """
        return {
            "kalman_state": self._kalman_state,
            "tod_priors": self._cache_mgr.tod_priors,
            "last_bar_offset": self._last_bar_offset,
            "setup_last_fire": self._setup_last_fire,
        }

    async def _publish_signals_or_dlq(
        self,
        ranked: list[dict],
        symbol: str,
        tf: str,
        bar: BarMessage,
    ) -> bool:
        """Assert all ranked signals have non-null CIS before publishing.

        Returns True if signals were published to intelligence.i7.signals.
        Returns False and publishes to intelligence.signal.dlq if CIS assertion fails.
        This prevents null-CIS signals from entering the Kafka pipeline or signal_ledger.
        """
        # CIS assertion — every signal must have been stamped by _run_i7_pipeline
        for sig in ranked:
            if sig.get("raw_cis_score") is None or sig.get("filtered_cis_score") is None:
                self._signal_dlq_total.add(1)
                await self._out_queue.enqueue_blocking(
                    topic_signal_dlq(self.settings.env_name),
                    message_key(symbol, tf),
                    {
                        "symbol": symbol,
                        "tf": tf,
                        "bar_ts": bar.ts.isoformat(),
                        "reason": "cis_score_null",
                        "signal_count": len(ranked),
                        "ts": datetime.now(UTC).isoformat(),
                    },
                )
                self.logger.error(
                    "intelligence_pipeline_agent.cis_assertion_failed",
                    symbol=symbol,
                    tf=tf,
                    signal_count=len(ranked),
                )
                return False

        # Assertion passed — stamp bar close as market_entry_price for dual-track lifecycle.
        # bar.close is the fill price for an "at signal" entry; ask/bid from _live_quotes
        # would be more precise but that feed is not yet wired.
        close_price = bar.close
        for sig in ranked:
            sig["market_price_at_signal"] = close_price
            sig["market_entry_price"] = close_price

        # Phase 81 D-01: Publisher-side normalization. Consumers no longer infer.
        bar_ts = bar.ts  # tz-aware UTC datetime; never ""
        computed_at = datetime.now(UTC)
        tf_secs = TF_SECONDS.get(tf, 60)
        try:
            is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
        except Exception:
            # bar_ts/computed_at must be tz-aware UTC datetimes; if not, default to live
            is_backfill = False
        for sig in ranked:
            sig["timestamp"] = format_iso_ts(bar_ts)
            sig["is_backfill"] = is_backfill
            # signal_schema_version comes from make_signal_from_frame();
            # apply defensive defaults if a plugin returned a stripped dict.
            sig.setdefault("signal_schema_version", SIGNAL_SCHEMA_VERSION)
            sig.setdefault("signal_id", str(uuid4()))
        if is_backfill and ranked:
            INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL.add(
                len(ranked), {"symbol": symbol, "timeframe": tf}
            )

        await self._out_queue.enqueue_blocking(
            topic_intelligence_i7_signals(self.settings.env_name),
            message_key(symbol, tf),
            {
                "symbol": symbol,
                "tf": tf,
                "bar_ts": format_iso_ts(bar_ts),
                "computed_at": format_iso_ts(computed_at),
                "signals": ranked,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Intelligence journal
    # ------------------------------------------------------------------

    def _enqueue_intel_journal(
        self,
        bar: BarMessage,
        event: IntelligenceEvent,
        t0: float,
        msg_key: str,
        i7_result: dict | None,
    ) -> None:
        """Build and enqueue BarIntelligenceRecord to the intelligence journal topic."""
        i7 = i7_result or {}
        ranked_dicts: list[dict] = i7.get("ranked", [])
        winner: dict | None = i7.get("winner")
        i7_computed_at: datetime = i7.get("i7_computed_at", datetime.now(UTC))

        ranked_signals = [signal_dict_to_ranked(s) for s in ranked_dicts]

        record = BarIntelligenceRecord(
            intelligence=event,
            ranked_signals=ranked_signals,
            winner_plugin=winner.get("setup_plugin") if winner else None,
            winner_confidence=(
                (
                    winner.get("calibrated_confidence")
                    if winner.get("calibrated_confidence") is not None
                    else winner.get("confidence")
                )
                if winner
                else None
            ),
            winner_direction=winner.get("direction") if winner else None,
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
        self._out_queue.enqueue(
            topic_intelligence_journal(self.settings.env_name),
            msg_key,
            record.model_dump(mode="json"),
        )

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def _health_monitor_loop(self) -> None:
        """Periodic health check and metric reporting."""
        while self.running:
            await asyncio.sleep(10)

    async def _handle_system_event(self, payload: dict) -> None:
        """Handle system events (pipeline reset, roll, etc.)."""
        event_type = payload.get("type", "")
        if event_type == "pipeline_reset":
            self.logger.info("system.pipeline_reset_received")

    # DB cache refresh loops and loaders were removed in Plan 03 — extracted to CacheManager.


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = IntelligencePipelineComputeAgent()
    asyncio.run(agent.start())
