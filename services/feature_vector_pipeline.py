#!/usr/bin/env python3
"""FeatureVectorPipeline — v3.0 FeatureFactory pipeline.

Computes all 249 FeatureVector primitives via FeatureFactory.compute() per bar,
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
import numpy as np

from services._batch_utils import get_dict_config as _get_dict_config
from services._batch_utils import get_list_config as _get_list_config
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
from src.intelligence.feature_cache import (
    _CTF_HIGHER_TF,
    CrossAssetState,
    FeatureCache,
    _rsi_simple,
)
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

# Cross-asset proxy roles for FeatureCache.update_cross_asset() (todo 221) -- APR fallback
# default only, in (equity, long_bond, short_bond) role order. Which tickers play each role
# is a behavioral list (CLAUDE.md APR mandate category 2: "lists controlling WHAT the
# algorithm processes"), so the live driver is feature.cross_asset.role_symbols
# (migration 279), loaded into self._cross_asset_symbols during _prewarm_threshold_config().
_CROSS_ASSET_SYMBOLS_DEFAULT: tuple[str, str, str] = ("SPY", "TLT", "SHY")

# Inverse of feature_cache._CTF_HIGHER_TF: which LTF caches read ctf_momentum from a
# given HTF timeframe when a bar on that HTF arrives (todo 241). e.g. a "1h" bar updates
# both "5m" and "15m" caches; a "1d" bar updates "1h" (and its own, self-referential --
# see _CTF_HIGHER_TF's docstring) cache.
_CTF_LOWER_TFS: dict[str, list[str]] = {
    htf: [ltf for ltf, mapped_htf in _CTF_HIGHER_TF.items() if mapped_htf == htf]
    for htf in set(_CTF_HIGHER_TF.values())
}


def _assert_rsi_mid_period_fits_bar_history(rsi_mid_period: int, bar_history_maxlen: int) -> None:
    """ctf_momentum's live-path RSI (todo 241, _update_ctf_cache_from_htf_bar) reads
    rsi_mid_period bars from self._bar_history (BarHistory(maxlen=200) by default,
    __init__). _wilder_rsi_series returns an all-50.0 (-> ctf_momentum=0.0) series when
    n < period + 1 -- an operator raising this APR key at/above the buffer size would
    silently zero ctf_momentum for every symbol with no error, no metric, no log. Fail
    loud at config-load time instead (CLAUDE.md: silent wrong answers are worse than loud
    crashes; same pattern _prewarm_threshold_config's _check_prewarmed uses). Same
    systemic BarHistory-cap class of gap todo 177 tracks for other >200 window fields --
    not duplicating that todo's broader fix-shape decision, just failing loud for this one
    APR-tunable field rather than letting it join the list silently. Extracted as a plain
    function (no self, no config service) so it's unit-testable without mocking DB/Kafka.
    """
    if rsi_mid_period + 1 > bar_history_maxlen:
        raise AssertionError(
            f"feature.period.rsi.mid={rsi_mid_period} would exceed BarHistory's "
            f"maxlen={bar_history_maxlen} -- ctf_momentum would silently compute as 0.0 "
            f"for every symbol (see todo 177/241)"
        )


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

        # Per-tf cross-asset broadcast state (todo 221/222) — lazily created via
        # _get_cross_asset_state(); see _refresh_cross_asset_state()'s docstring for why
        # this is a single shared per-tf state rather than being computed directly on
        # each symbol's own FeatureCache.
        self._cross_asset_state: dict[str, CrossAssetState] = {}
        # (equity, long_bond, short_bond) role order -- APR default until
        # _prewarm_threshold_config() loads feature.cross_asset.role_symbols.
        self._cross_asset_symbols: tuple[str, str, str] = _CROSS_ASSET_SYMBOLS_DEFAULT

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

    def _get_cache(self, symbol: str, tf: str, *, exclude_last: bool = True) -> FeatureCache:
        """Return the FeatureCache for (symbol, tf), creating one on first access.

        A newly created cache is warmed from already-seeded/buffered bar history
        (todo 159) so `above_wk_vwap` reflects real week-to-date volume-weighted price
        instead of starting cold after every restart. Warm-up calls `update_wk_vwap()`
        directly rather than the bundled `advance_bar()`, keeping this warm-up path
        decoupled from whatever else `advance_bar()` accumulates per bar (today: only
        `update_wk_vwap()` itself -- `advance_bar()`'s prior `hmm_duration += 1.0`
        increment was removed 2026-07-30, todo 207, since its only reset was removed
        the same day as dead compute; see `feature_cache.py`'s `advance_bar()`).
        The most recent bar in history is excluded by default since it is normally the
        bar currently being processed, which receives its own `advance_bar()` call
        after `compute()` below.

        `exclude_last=False` (todo 241 follow-up): the CTF propagation path
        (`_update_ctf_cache_from_htf_bar`) calls this for LTF caches that are NOT the
        tf currently being processed -- every buffered bar for that other tf is
        genuinely historical, none of it will get a separate `advance_bar()` call, so
        excluding the last one would silently and permanently lose one bar's
        contribution to `_wk_tp_vol_sum`/session-VP/overnight-range/session-levels
        state for any cache first created via that path.

        Also replays `update_session_vp()` over the same buffered history (Phase 163
        code review CR-01) -- without this, `_sess_bars` starts empty on every restart
        that doesn't land exactly at a session boundary, degrading all 12 VP-derived
        FeatureVector fields until the accumulator naturally refills or the next
        session reset fires. Same warm-up source and exclusion as `update_wk_vwap()`
        above; `self._feature_factory_config` is asserted non-None at this method's
        only call site (bars are already flowing, so `_prewarm_threshold_config()` has
        already run in `_setup()`).

        Also replays `update_overnight_range()` over the same buffered history
        (Phase 164 Plan 04) -- without this, AMD's overnight-range state would
        cold-start on every restart while VP/S-R state does not (T-164-07),
        silently freezing amd_phase/amd_manipulation_detected/
        amd_distribution_direction/manip_strength at neutral defaults until a
        full new accumulation cycle passes. Same warm-up source and exclusion
        as `update_wk_vwap()`/`update_session_vp()` above.

        Also replays the `update_session_levels` mutator over the same buffered
        history (Phase 165 Plan 04) -- without this, the session/overnight/Asian/
        weekly-adjacent state built for `session_levels.py`'s rewrite would
        cold-start on every restart that does not land exactly on a session
        boundary, silently freezing all 16 Plan 05 FeatureVector columns at
        NULL until a full session and a full ISO week have elapsed -- the
        same T-164-07 cold-start gap Phase 164 had to fix retroactively. Same
        warm-up source and exclusion as `update_wk_vwap()`/
        `update_session_vp()`/`update_overnight_range()` above.
        """
        key = f"{symbol}:{tf}"
        if key not in self._feature_caches:
            assert self._feature_factory_config is not None, "FeatureFactoryConfig not prewarmed"
            cache = FeatureCache()
            history = list(self._bar_history.get(symbol, tf))
            buffered = history[:-1] if exclude_last else history
            for bar in buffered:
                cache.update_wk_vwap(bar.ts, bar.high, bar.low, bar.close, float(bar.volume))
                cache.update_session_vp(
                    bar.ts,
                    bar.high,
                    bar.low,
                    bar.close,
                    float(bar.volume),
                    self._feature_factory_config,
                )
                cache.update_overnight_range(
                    bar.ts, bar.high, bar.low, self._feature_factory_config
                )
                cache.update_session_levels(
                    bar.ts, bar.open, bar.high, bar.low, bar.close, self._feature_factory_config
                )
            self._feature_caches[key] = cache
        return self._feature_caches[key]

    @staticmethod
    def _bars_to_dicts(bars: object) -> list[dict]:
        """Convert a BarHistory deque to the list-of-dicts shape FeatureCache expects."""
        return [
            {
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "ts": b.ts,
            }
            for b in bars
        ]

    def _cross_asset_role_bars(self, tf: str) -> tuple[list[dict], list[dict], list[dict]]:
        """Return (equity, long_bond, short_bond) bar-history dicts for self._cross_asset_symbols."""
        equity, long_bond, short_bond = self._cross_asset_symbols
        return (
            self._bars_to_dicts(self._bar_history.get(equity, tf)),
            self._bars_to_dicts(self._bar_history.get(long_bond, tf)),
            self._bars_to_dicts(self._bar_history.get(short_bond, tf)),
        )

    def _refresh_cross_asset_state(self, state: CrossAssetState, tf: str) -> None:
        """Recompute vix_z/flight_quality/yield_slope_z from current role-symbol history.

        Call only on a genuinely new bar for the equity role symbol (self._cross_asset_symbols[0])
        -- see _cross_asset_state_for_bar(). update_cross_asset() appends to an internal
        realized-vol deque on every call, so triggering on all 3 role symbols' bars instead of
        just one would append the same observation up to 3x per bar period and corrupt the
        trailing z-score window. That is why cross-asset state lives in a single shared per-tf
        CrossAssetState, broadcast onto every symbol's own cache, instead of being computed
        directly on each symbol's own FeatureCache.
        """
        assert self._feature_factory_config is not None, "FeatureFactoryConfig not prewarmed"
        equity_bars, long_bond_bars, short_bond_bars = self._cross_asset_role_bars(tf)
        state.update_cross_asset(
            equity_bars, long_bond_bars, short_bond_bars, self._feature_factory_config
        )

    def _warm_cross_asset_state(self, state: CrossAssetState, tf: str) -> None:
        """Replay buffered role-symbol history bar-by-bar so vix_z/yield_slope_z's rolling
        z-score windows are populated on first access after a restart, instead of cold-starting
        at the 0.0 dataclass default for `window` bars (mirrors _get_cache()'s buffered-history
        replay, T-164-07) -- a single _refresh_cross_asset_state() call over the whole buffer
        would append only ONE observation, not one per historical bar.
        """
        assert self._feature_factory_config is not None, "FeatureFactoryConfig not prewarmed"
        equity_bars, long_bond_bars, short_bond_bars = self._cross_asset_role_bars(tf)
        for i in range(2, max(len(equity_bars), len(long_bond_bars), len(short_bond_bars)) + 1):
            state.update_cross_asset(
                equity_bars[:i],
                long_bond_bars[:i],
                short_bond_bars[:i],
                self._feature_factory_config,
            )

    def _get_cross_asset_state(self, tf: str) -> CrossAssetState:
        """Return the shared per-tf cross-asset broadcast state, creating and warming it
        from buffered role-symbol history on first access. Read-only accessor -- see
        _cross_asset_state_for_bar() for the refresh-or-reuse decision.
        """
        if tf not in self._cross_asset_state:
            state = CrossAssetState()
            self._warm_cross_asset_state(state, tf)
            self._cross_asset_state[tf] = state
        return self._cross_asset_state[tf]

    def _cross_asset_state_for_bar(self, bar: BarMessage) -> CrossAssetState:
        """Return bar.tf's cross-asset broadcast state, refreshing it first if `bar` is a
        genuinely new bar for the equity role symbol (see _refresh_cross_asset_state()).
        Single call site for the "when to refresh" rule -- callers never need to know which
        symbol triggers it.
        """
        state = self._get_cross_asset_state(bar.tf)
        if bar.symbol == self._cross_asset_symbols[0]:
            self._refresh_cross_asset_state(state, bar.tf)
        return state

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

        # [todo 061] The trigger is schema bootstrap (migration 220), not a runtime
        # concern — a compute daemon must never own schema mutation (DAG Invariants
        # 2/3). LISTEN succeeds even with no trigger installed (it just never fires),
        # which would silently degrade cache staleness instead of erroring — check and
        # fail loudly instead, per "silent wrong answers are worse than loud crashes."
        if not await self._db.instruments_trigger_exists():
            raise RuntimeError(
                "instruments pg_notify trigger (trg_instruments_notify) is missing — "
                "apply production/migrations/213_instruments_notify_trigger.sql before "
                "starting FeatureVectorPipeline"
            )
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
        # todo 103 (2026-07-27): window_short/window_long were dead keys that don't
        # exist in config_state -- FeatureFactoryConfig actually reads window_fast/
        # mid/slow (below), so every read of those three silently cache-missed and
        # fell through to hardcoded Python defaults regardless of config_state.
        ("feature.momentum.window_fast", 5),
        ("feature.momentum.window_mid", 20),
        ("feature.momentum.window_slow", 60),
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
        # --- migration 206: Phase 142.5 Plan 01 Renaissance primitives (lagged returns + overnight gap) ---
        ("feature.ret_lag.fast", 5),
        ("feature.ret_lag.mid", 20),
        ("feature.ret_lag.slow", 60),
        ("feature.overnight_gap.window", 20),
        # --- migration 206: Phase 142.5 Plan 02 Renaissance primitives (volume structure) ---
        ("feature.dollar_vol.window", 20),
        ("feature.vol_range_ratio.window", 20),
        ("feature.vol_trend.fast", 5),
        ("feature.vol_trend.slow", 20),
        ("feature.up_vol_ratio.fast", 5),
        ("feature.up_vol_ratio.slow", 20),
        ("feature.vol_percentile.window", 20),
        ("feature.vol_persistence.window", 20),
        ("feature.vol_std.window", 20),
        ("feature.mfi.fast", 7),
        ("feature.mfi.slow", 14),
        ("feature.obv.window", 20),
        # --- migration 206: Phase 142.5 Plan 05 Renaissance primitives (breakout distance) ---
        ("feature.breakout.dist_window_fast", 20),
        ("feature.breakout.dist_window_slow", 50),
        ("feature.breakout.range_window_fast", 20),
        ("feature.breakout.range_window_slow", 50),
        ("feature.breakout.stoch_window_fast", 14),
        ("feature.breakout.stoch_window_slow", 50),
        ("feature.breakout.percentile_window_fast", 50),
        ("feature.breakout.percentile_window_slow", 200),
        ("feature.breakout.efficiency_window_fast", 10),
        ("feature.breakout.efficiency_window_slow", 50),
        # --- migration 206: Phase 142.5 Plan 03 Renaissance primitives (return
        # distribution + realized variance/volatility) ---
        ("feature.ret_kurtosis.fast", 10),
        ("feature.ret_kurtosis.slow", 40),
        ("feature.ret_kurtosis.zscore_window", 20),
        ("feature.updown_ratio.fast", 5),
        ("feature.updown_ratio.slow", 20),
        ("feature.streak.window", 20),
        ("feature.realized_var.fast", 5),
        ("feature.realized_var.slow", 20),
        ("feature.vol_of_vol.window", 20),
        ("feature.high_low_corr.window", 20),
        ("feature.variance_ratio.fast", 5),
        ("feature.variance_ratio.slow", 20),
        ("feature.vol_asymmetry.window", 20),
        ("feature.bb_pct_b.fast", 20),
        ("feature.bb_pct_b.slow", 50),
        ("feature.hv.fast", 10),
        ("feature.hv.slow", 30),
        ("feature.hv.ratio_window", 20),
        ("feature.parkinson_vol.window", 10),
        ("feature.parkinson_vol.zscore_window", 20),
        ("feature.garman_klass_vol.window", 10),
        ("feature.garman_klass_vol.zscore_window", 20),
        ("feature.yang_zhang_vol.window", 20),
        ("feature.yang_zhang_vol.zscore_window", 20),
        ("feature.vol_velocity.window", 20),
        ("feature.intraday_noise.window", 20),
        ("feature.price_vol_corr.fast", 10),
        ("feature.price_vol_corr.slow", 30),
        # --- migration 286: Phase 151 Plan 01 Task 2 velocity primitives ---
        ("feature.momentum_velocity.window", 14),
        ("feature.vwap_velocity.window", 14),
        ("alpha.ic.canary_rng_seed", 90042),
        ("feature.session_vp.value_area_pct", 0.70),
        ("feature.session_vp.n_buckets", 50),
        ("feature.session_vp.hvn_threshold", 0.80),
        ("feature.session_vp.lvn_threshold", 0.20),
        ("feature.session_vp.rolling_window", 480),
        ("feature.sr.window", 10),
        ("feature.sr.cluster_atr_mult", 0.5),
        (
            "feature.sr.lookback_by_tf",
            {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60},
        ),
        # --- migration 266: Phase 164 Plan 01 SMC Institutional Footprint (contract
        # only -- consumed by Plans 02-04) ---
        ("feature.smc.order_blocks.lookback", 100),
        ("feature.smc.order_blocks.impulse_bars", 3),
        ("feature.smc.order_blocks.significant_move_pct", 0.003),
        ("feature.smc.order_blocks.opposing_candle_lookback", 10),
        ("feature.smc.order_blocks.strength_fallback", 0.5),
        ("feature.smc.breaker.lookback", 10),
        ("feature.smc.mitigation.lookback", 10),
        ("feature.smc.fvg.lookback", 100),
        ("feature.smc.liquidity_sweeps.lookback", 120),
        ("feature.smc.liquidity_sweeps.swing_neighbor", 5),
        ("feature.smc.liquidity_sweeps.reclaim_bars", 3),
        ("feature.smc.liquidity_sweeps.depth_ramp_max_pct", 2.0),
        ("feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max", 0.5),
        ("feature.smc.liquidity_pools.lookback", 150),
        ("feature.smc.liquidity_pools.swing_neighbor", 5),
        ("feature.smc.liquidity_pools.atr_fallback_pct", 0.002),
        ("feature.smc.liquidity_pools.equal_level_tolerance_atr_mult", 0.75),
        ("feature.smc.liquidity_pools.session_bars", 390),
        (
            "feature.smc.liquidity_pools.significance_weights",
            {
                "eq_highs_3": 0.75,
                "eq_lows_3": 0.75,
                "eq_highs_2": 0.60,
                "eq_lows_2": 0.60,
                "session_high": 0.50,
                "session_low": 0.50,
            },
        ),
        ("feature.smc.zones.lookback", 150),
        ("feature.smc.zones.impulse_atr_mult", 1.5),
        ("feature.smc.zones.base_body_ratio", 0.5),
        ("feature.smc.zones.base_atr_mult", 1.0),
        ("feature.smc.zones.max_base_bars", 5),
        ("feature.smc.zones.zone_height_cap_atr_mult", 2.5),
        ("feature.smc.zones.impulse_overlap_atr_mult", 0.4),
        ("feature.smc.zones.freshness_decay_k", 0.5),
        ("feature.smc.zones.strength_premium_align_mult", 1.20),
        ("feature.smc.zones.strength_fvg_align_mult", 1.15),
        ("feature.smc.zones.age_penalty_floor", 0.70),
        ("feature.smc.zones.age_penalty_window_bars", 200),
        ("feature.smc.zones.age_penalty_max_pct", 0.30),
        ("feature.smc.zones.max_tracked_zones", 5),
        ("feature.smc.bos_choch.lookback", 120),
        ("feature.smc.bos_choch.swing_neighbor", 5),
        ("feature.smc.amd.lookback", 30),
        ("feature.smc.amd.accum_start_utc_hour", 20),
        ("feature.smc.amd.accum_end_utc_hour", 24),
        ("feature.smc.amd.manip_end_utc_hour", 10),
        ("feature.smc.amd.dist_end_utc_hour", 21),
        # --- migration 267: Phase 165 Plan 01 Swing/Fib/Trend/Session Structure
        # (contract only -- consumed by Plans 02-04) ---
        ("feature.swing.pivot_window", 5),
        ("feature.swing.lookback_bars", 120),
        ("feature.trend_structure.atr_strength_divisor", 5.0),
        ("feature.trend_structure.range_lookback_bars", 20),
        ("feature.swing_momentum.confirm_n", 3),
        ("feature.swing_momentum.max_extremes", 6),
        ("feature.swing_momentum.lookback_bars", 60),
        ("feature.swing_momentum.reference_bars", 20),
        ("feature.swing_momentum.speed_factor_min", 0.1),
        ("feature.swing_momentum.speed_factor_max", 3.0),
        ("feature.swing_momentum.energy_divisor", 3.0),
        ("feature.swing_momentum.intensity_ramp_lo", 1.0),
        ("feature.swing_momentum.intensity_ramp_hi", 2.0),
        ("feature.fib.cluster_atr_divisor", 2.0),
        ("feature.fib.cluster_fallback_divisor", 20.0),
        ("feature.session_levels.asia_start_et_hour", 20),
        ("feature.session_levels.asia_end_et_hour", 4),
    )

    async def _prewarm_threshold_config(self) -> None:
        """Prewarm config cache and build FeatureFactoryConfig from feature.* keys."""
        assert self._config_service is not None
        for key, default in self._THRESHOLD_KEYS:
            await self._config_service.get(key, default)

        # Build FeatureFactoryConfig from prewarmed feature.* values (APR contract).
        # All get_sync() calls hit the warm cache — no DB round-trips on compute path.
        cs = self._config_service
        _prewarmed_keys = frozenset(key for key, _default in self._THRESHOLD_KEYS)

        def _check_prewarmed(key: str) -> None:
            # todo 103 (2026-07-27): a key read here but absent from _THRESHOLD_KEYS
            # silently cache-misses and falls through to the hardcoded default
            # forever, regardless of config_state -- exactly how window_fast/mid/slow
            # went inert. Fails loud at startup (this runs once, not on the hot path)
            # instead of leaving APR edits to silently do nothing.
            if key not in _prewarmed_keys:
                raise AssertionError(
                    f"feature.* key {key!r} read while building FeatureFactoryConfig "
                    f"but missing from _THRESHOLD_KEYS -- it will always fall through "
                    f"to its hardcoded default; add it to _THRESHOLD_KEYS"
                )

        def _int(key: str, default: int) -> int:
            _check_prewarmed(key)
            v = cs.get_sync(key, default)
            return int(v) if v is not None else default

        def _float(key: str, default: float) -> float:
            _check_prewarmed(key)
            v = cs.get_sync(key, default)
            return float(v) if v is not None else default

        def _dict(key: str, default: dict) -> dict:
            _check_prewarmed(key)
            return _get_dict_config(cs, key, default)

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
            ret_lag_fast=_int("feature.ret_lag.fast", 5),
            ret_lag_mid=_int("feature.ret_lag.mid", 20),
            ret_lag_slow=_int("feature.ret_lag.slow", 60),
            overnight_gap_window=_int("feature.overnight_gap.window", 20),
            dollar_vol_window=_int("feature.dollar_vol.window", 20),
            vol_range_ratio_window=_int("feature.vol_range_ratio.window", 20),
            vol_trend_fast=_int("feature.vol_trend.fast", 5),
            vol_trend_slow=_int("feature.vol_trend.slow", 20),
            up_vol_ratio_fast=_int("feature.up_vol_ratio.fast", 5),
            up_vol_ratio_slow=_int("feature.up_vol_ratio.slow", 20),
            vol_percentile_window=_int("feature.vol_percentile.window", 20),
            vol_persistence_window=_int("feature.vol_persistence.window", 20),
            vol_std_window=_int("feature.vol_std.window", 20),
            mfi_fast=_int("feature.mfi.fast", 7),
            mfi_slow=_int("feature.mfi.slow", 14),
            obv_window=_int("feature.obv.window", 20),
            dist_window_fast=_int("feature.breakout.dist_window_fast", 20),
            dist_window_slow=_int("feature.breakout.dist_window_slow", 50),
            range_window_fast=_int("feature.breakout.range_window_fast", 20),
            range_window_slow=_int("feature.breakout.range_window_slow", 50),
            stoch_window_fast=_int("feature.breakout.stoch_window_fast", 14),
            stoch_window_slow=_int("feature.breakout.stoch_window_slow", 50),
            percentile_window_fast=_int("feature.breakout.percentile_window_fast", 50),
            percentile_window_slow=_int("feature.breakout.percentile_window_slow", 200),
            efficiency_window_fast=_int("feature.breakout.efficiency_window_fast", 10),
            efficiency_window_slow=_int("feature.breakout.efficiency_window_slow", 50),
            ret_kurtosis_fast=_int("feature.ret_kurtosis.fast", 10),
            ret_kurtosis_slow=_int("feature.ret_kurtosis.slow", 40),
            ret_kurtosis_zscore_window=_int("feature.ret_kurtosis.zscore_window", 20),
            updown_ratio_fast=_int("feature.updown_ratio.fast", 5),
            updown_ratio_slow=_int("feature.updown_ratio.slow", 20),
            streak_window=_int("feature.streak.window", 20),
            realized_var_fast=_int("feature.realized_var.fast", 5),
            realized_var_slow=_int("feature.realized_var.slow", 20),
            vol_of_vol_window=_int("feature.vol_of_vol.window", 20),
            high_low_corr_window=_int("feature.high_low_corr.window", 20),
            variance_ratio_fast=_int("feature.variance_ratio.fast", 5),
            variance_ratio_slow=_int("feature.variance_ratio.slow", 20),
            vol_asymmetry_window=_int("feature.vol_asymmetry.window", 20),
            bb_pct_b_fast=_int("feature.bb_pct_b.fast", 20),
            bb_pct_b_slow=_int("feature.bb_pct_b.slow", 50),
            hv_fast=_int("feature.hv.fast", 10),
            hv_slow=_int("feature.hv.slow", 30),
            hv_ratio_window=_int("feature.hv.ratio_window", 20),
            parkinson_vol_window=_int("feature.parkinson_vol.window", 10),
            parkinson_vol_zscore_window=_int("feature.parkinson_vol.zscore_window", 20),
            garman_klass_vol_window=_int("feature.garman_klass_vol.window", 10),
            garman_klass_vol_zscore_window=_int("feature.garman_klass_vol.zscore_window", 20),
            yang_zhang_vol_window=_int("feature.yang_zhang_vol.window", 20),
            yang_zhang_vol_zscore_window=_int("feature.yang_zhang_vol.zscore_window", 20),
            vol_velocity_window=_int("feature.vol_velocity.window", 20),
            intraday_noise_window=_int("feature.intraday_noise.window", 20),
            price_vol_corr_fast=_int("feature.price_vol_corr.fast", 10),
            price_vol_corr_slow=_int("feature.price_vol_corr.slow", 30),
            momentum_velocity_window=_int("feature.momentum_velocity.window", 14),
            vwap_velocity_window=_int("feature.vwap_velocity.window", 14),
            canary_rng_seed=_int("alpha.ic.canary_rng_seed", 90042),
            session_vp_value_area_pct=_float("feature.session_vp.value_area_pct", 0.70),
            session_vp_n_buckets=_int("feature.session_vp.n_buckets", 50),
            session_vp_hvn_threshold=_float("feature.session_vp.hvn_threshold", 0.80),
            session_vp_lvn_threshold=_float("feature.session_vp.lvn_threshold", 0.20),
            session_vp_rolling_window=_int("feature.session_vp.rolling_window", 480),
            sr_window=_int("feature.sr.window", 10),
            sr_cluster_atr_mult=_float("feature.sr.cluster_atr_mult", 0.5),
            sr_lookback_by_tf=_dict(
                "feature.sr.lookback_by_tf",
                {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60},
            ),
            smc_order_blocks_lookback=_int("feature.smc.order_blocks.lookback", 100),
            smc_order_blocks_impulse_bars=_int("feature.smc.order_blocks.impulse_bars", 3),
            smc_order_blocks_significant_move_pct=_float(
                "feature.smc.order_blocks.significant_move_pct", 0.003
            ),
            smc_order_blocks_opposing_candle_lookback=_int(
                "feature.smc.order_blocks.opposing_candle_lookback", 10
            ),
            smc_order_blocks_strength_fallback=_float(
                "feature.smc.order_blocks.strength_fallback", 0.5
            ),
            smc_fvg_lookback=_int("feature.smc.fvg.lookback", 100),
            smc_liquidity_sweeps_lookback=_int("feature.smc.liquidity_sweeps.lookback", 120),
            smc_liquidity_sweeps_swing_neighbor=_int(
                "feature.smc.liquidity_sweeps.swing_neighbor", 5
            ),
            smc_liquidity_sweeps_reclaim_bars=_int("feature.smc.liquidity_sweeps.reclaim_bars", 3),
            smc_liquidity_sweeps_depth_ramp_max_pct=_float(
                "feature.smc.liquidity_sweeps.depth_ramp_max_pct", 2.0
            ),
            smc_liquidity_sweeps_reclaim_velocity_ramp_max=_float(
                "feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max", 0.5
            ),
            smc_liquidity_pools_lookback=_int("feature.smc.liquidity_pools.lookback", 150),
            smc_liquidity_pools_swing_neighbor=_int(
                "feature.smc.liquidity_pools.swing_neighbor", 5
            ),
            smc_liquidity_pools_equal_level_tolerance_atr_mult=_float(
                "feature.smc.liquidity_pools.equal_level_tolerance_atr_mult", 0.75
            ),
            smc_liquidity_pools_session_bars=_int("feature.smc.liquidity_pools.session_bars", 390),
            smc_liquidity_pools_significance_weights=_dict(
                "feature.smc.liquidity_pools.significance_weights",
                {
                    "eq_highs_3": 0.75,
                    "eq_lows_3": 0.75,
                    "eq_highs_2": 0.60,
                    "eq_lows_2": 0.60,
                    "session_high": 0.50,
                    "session_low": 0.50,
                },
            ),
            smc_zones_lookback=_int("feature.smc.zones.lookback", 150),
            smc_zones_impulse_atr_mult=_float("feature.smc.zones.impulse_atr_mult", 1.5),
            smc_zones_base_body_ratio=_float("feature.smc.zones.base_body_ratio", 0.5),
            smc_zones_base_atr_mult=_float("feature.smc.zones.base_atr_mult", 1.0),
            smc_zones_max_base_bars=_int("feature.smc.zones.max_base_bars", 5),
            smc_zones_zone_height_cap_atr_mult=_float(
                "feature.smc.zones.zone_height_cap_atr_mult", 2.5
            ),
            smc_zones_impulse_overlap_atr_mult=_float(
                "feature.smc.zones.impulse_overlap_atr_mult", 0.4
            ),
            smc_zones_freshness_decay_k=_float("feature.smc.zones.freshness_decay_k", 0.5),
            smc_zones_strength_premium_align_mult=_float(
                "feature.smc.zones.strength_premium_align_mult", 1.20
            ),
            smc_zones_strength_fvg_align_mult=_float(
                "feature.smc.zones.strength_fvg_align_mult", 1.15
            ),
            smc_zones_age_penalty_floor=_float("feature.smc.zones.age_penalty_floor", 0.70),
            smc_zones_age_penalty_window_bars=_int(
                "feature.smc.zones.age_penalty_window_bars", 200
            ),
            smc_zones_age_penalty_max_pct=_float("feature.smc.zones.age_penalty_max_pct", 0.30),
            smc_zones_max_tracked_zones=_int("feature.smc.zones.max_tracked_zones", 5),
            smc_bos_choch_lookback=_int("feature.smc.bos_choch.lookback", 120),
            smc_bos_choch_swing_neighbor=_int("feature.smc.bos_choch.swing_neighbor", 5),
            smc_amd_accum_start_utc_hour=_int("feature.smc.amd.accum_start_utc_hour", 20),
            smc_amd_manip_end_utc_hour=_int("feature.smc.amd.manip_end_utc_hour", 10),
            smc_amd_dist_end_utc_hour=_int("feature.smc.amd.dist_end_utc_hour", 21),
            swing_pivot_window=_int("feature.swing.pivot_window", 5),
            swing_lookback_bars=_int("feature.swing.lookback_bars", 120),
            trend_structure_atr_strength_divisor=_float(
                "feature.trend_structure.atr_strength_divisor", 5.0
            ),
            trend_structure_range_lookback_bars=_int(
                "feature.trend_structure.range_lookback_bars", 20
            ),
            swing_momentum_confirm_n=_int("feature.swing_momentum.confirm_n", 3),
            swing_momentum_max_extremes=_int("feature.swing_momentum.max_extremes", 6),
            swing_momentum_lookback_bars=_int("feature.swing_momentum.lookback_bars", 60),
            swing_momentum_reference_bars=_int("feature.swing_momentum.reference_bars", 20),
            swing_momentum_speed_factor_min=_float("feature.swing_momentum.speed_factor_min", 0.1),
            swing_momentum_speed_factor_max=_float("feature.swing_momentum.speed_factor_max", 3.0),
            swing_momentum_energy_divisor=_float("feature.swing_momentum.energy_divisor", 3.0),
            swing_momentum_intensity_ramp_lo=_float(
                "feature.swing_momentum.intensity_ramp_lo", 1.0
            ),
            swing_momentum_intensity_ramp_hi=_float(
                "feature.swing_momentum.intensity_ramp_hi", 2.0
            ),
            fib_cluster_atr_divisor=_float("feature.fib.cluster_atr_divisor", 2.0),
            session_levels_asia_start_et_hour=_int("feature.session_levels.asia_start_et_hour", 20),
            session_levels_asia_end_et_hour=_int("feature.session_levels.asia_end_et_hour", 4),
        )

        _assert_rsi_mid_period_fits_bar_history(
            self._feature_factory_config.rsi_mid_period, self._bar_history.maxlen
        )

        # feature.cross_asset.role_symbols (migration 279) -- not part of FeatureFactoryConfig
        # (it's pipeline-level routing, not a compute parameter), so it's loaded independently
        # of the _int/_float/_dict helpers above and their _THRESHOLD_KEYS-membership assertion.
        # Order is load-bearing (equity, long_bond, short_bond roles) -- kept as a tuple, not a
        # frozenset, and validated at load time so a misconfigured key fails loud here rather
        # than silently emitting all-zero cross-asset features forever (CLAUDE.md: silent wrong
        # answers are worse than loud crashes).
        await cs.get("feature.cross_asset.role_symbols", list(_CROSS_ASSET_SYMBOLS_DEFAULT))
        _role_symbols = _get_list_config(
            cs, "feature.cross_asset.role_symbols", list(_CROSS_ASSET_SYMBOLS_DEFAULT)
        )
        if len(_role_symbols) != 3:
            raise AssertionError(
                f"feature.cross_asset.role_symbols must have exactly 3 entries "
                f"(equity, long_bond, short_bond roles), got {_role_symbols!r}"
            )
        self._cross_asset_symbols = (_role_symbols[0], _role_symbols[1], _role_symbols[2])

        self.logger.info(
            "feature_vector_pipeline.feature_config_loaded",
            key_count=len(self._THRESHOLD_KEYS),
            regime_cache_refresh_bars=self._feature_factory_config.regime_cache_refresh_bars,
        )

    async def _handle_config_update(self, payload: dict) -> None:
        """Hot-reload a config key: invalidate cache entry then re-fetch from DB.

        WR-03 (163-REVIEW.md): this only refreshes `ConfigService`'s own cache. Every
        `feature.*` key (including Phase 163's 8 new `feature.session_vp.*`/`feature.sr.*`
        dials) is read once into the frozen `self._feature_factory_config` dataclass at
        `_setup()` time via `_prewarm_threshold_config()`, and `compute()`/`compute_batch()`
        always read from that frozen snapshot, never from `ConfigService` directly (by
        design -- purity contract). So this log line fires and looks like success, but a
        `feature.*` edit via the dashboard has zero effect on computed values until the
        service is restarted. Pre-existing gap for every `feature.*` key, not introduced
        by Phase 163 -- just newly inherited by its 8 new keys.
        """
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
            return
        # Recompute ctf_momentum from seeded HTF history immediately (todo 241 follow-up) --
        # without this, every symbol emits the FeatureCache dataclass default (0.0) until its
        # next live "1h"/"1d" bar arrives (up to an hour, or up to a full day), silently
        # diverging from batch even though the underlying computation is now the same formula.
        # Same cold-start class of gap _get_cache()'s own docstring documents fixing for
        # above_wk_vwap/session-VP/overnight-range/session-levels state.
        for symbol in self._symbols:
            for htf_tf in _CTF_LOWER_TFS:
                self._update_ctf_cache_from_htf_bar(symbol, htf_tf, create_if_missing=True)

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
                            await self._cache_mgr.store_cross_asset_payload(tf, payload)
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

        bars_dicts = self._bars_to_dicts(raw_bars)

        # Cross-asset broadcast (todo 221): copy this tf's shared vix_z/flight_quality/
        # yield_slope_z onto this symbol's own cache before compute() reads them -- see
        # _refresh_cross_asset_state() for why refreshes are rate-limited to genuinely-new
        # SPY/TLT/SHY bars.
        cross_state = self._cross_asset_state_for_bar(bar)
        cache.vix_z = cross_state.vix_z
        cache.flight_quality = cross_state.flight_quality
        cache.yield_slope_z = cross_state.yield_slope_z

        # Refresh regime features every N bars (slow path; compute() reads from cache)
        cache.bars_since_regime_refresh += 1
        if cache.bars_since_regime_refresh >= config.regime_cache_refresh_bars:
            cache.refresh_regime(bars_dicts, config)

        # Update CTF cache(s) when a timeframe that serves as another tf's HTF source
        # arrives (todo 241) -- bar.tf in _CTF_LOWER_TFS means bar.tf is itself an HTF
        # (today: "1h" or "1d").
        if bar.tf in _CTF_LOWER_TFS:
            self._update_ctf_cache_from_htf_bar(bar.symbol, bar.tf)

        # Session-VP accumulator (Phase 163 Plan 02): update BEFORE compute()
        # reads FeatureCache's raw session levels to derive the 14 ATR-normalized
        # VP fields. Mirrors compute_batch()'s per-bar update_session_vp() call.
        cache.update_session_vp(bar.ts, bar.high, bar.low, bar.close, float(bar.volume), config)

        # AMD overnight-range accumulator (Phase 164 Plan 04): update BEFORE
        # compute() reads FeatureCache's overnight-range/manipulation state
        # to derive the 4 AMD FeatureVector fields. Mirrors compute_batch()'s
        # per-bar update_overnight_range() call immediately above.
        cache.update_overnight_range(bar.ts, bar.high, bar.low, config)

        # Session-levels accumulator (Phase 165 Plan 04): update BEFORE
        # compute() reads FeatureCache's session/overnight/Asian/weekly-
        # adjacent state (Plan 05 derives the 16 FeatureVector fields).
        # Mirrors compute_batch()'s per-bar update_session_levels() call.
        cache.update_session_levels(bar.ts, bar.open, bar.high, bar.low, bar.close, config)

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

        # Advance per-bar cache state (above_wk_vwap, hmm_duration) after compute(),
        # mirroring compute_batch()'s per-bar cache.advance_bar() call (todo 158).
        cache.advance_bar(bar.ts, bar.high, bar.low, bar.close, float(bar.volume))

        # regime is always None here -- regime_writer.py is the sole writer of
        # feature_vectors.regime, via its own separate, restart-safe
        # `UPDATE ... WHERE regime IS NULL` pass over the fitted per-symbol
        # K=5 HMM (BIC-selected, APR-governed via alpha.hmm.random_state).
        # This path previously derived a heuristic regime label from
        # cache.hmm_regime_prob/hmm_entropy (FeatureCache's separate, fixed-
        # params K=3 forward-filter -- a 2-bucket "ranging"/"trending_up" rule
        # that could never produce "trending_down"). No downstream consumer
        # of topic_feature_vectors reads that value -- feature_vector_writer.py
        # just persists it via FEATURE_VECTOR_INSERT_SQL's DO NOTHING, and
        # every real regime consumer (alpha_frame_writer.py,
        # counterfactual_tracker.py, llm_writer.py) reads the persisted
        # column later expecting regime_writer's authoritative label. Because
        # regime_writer's discovery (`WHERE regime IS NULL`) is symbol-level
        # and restart-safe, a live bar assigned a non-NULL heuristic value
        # here would never be revisited once inserted -- a silent, permanent
        # single-writer-invariant violation on a measurement-critical column
        # (found and fixed 2026-07-30, same investigation as todo 205).
        record = FeatureVectorRecord(
            symbol=bar.symbol,
            tf=bar.tf,
            bar_ts=bar.ts,
            pipeline_version=_PIPELINE_VERSION,
            feature_factory_version=FEATURE_FACTORY_VERSION,
            regime=None,
            regime_label_source="filtered",
            vector=vector,
        )

        # Serialize: dataclasses.asdict() recursively converts FeatureVector to dict.
        # bar_ts datetime must be ISO string for JSON Kafka transport.
        record_dict = dataclasses.asdict(record)
        record_dict["bar_ts"] = format_iso_ts(bar.ts)

        # Fire-and-forget publish -- non-blocking hot path
        # librdkafka batches internally via linger.ms; create_task keeps compute async.
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

    def _update_ctf_cache_from_htf_bar(
        self, symbol: str, htf_tf: str, *, create_if_missing: bool = False
    ) -> None:
        """Recompute ctf_momentum for every LTF cache sourced from (symbol, htf_tf).

        Uses the identical causal Wilder RSI computation as
        backfill_feature_factory.py's _build_ctf_series() (both route through
        feature_cache._rsi_simple) so live-served and corpus-measured ctf_momentum are
        the same statistic (todo 241 -- prior live implementation was a same-bar
        intrabar-return proxy, a different feature entirely from what every IC
        measurement, including Phase 167's live cross_sectional_relative_value tracker,
        was validated against).

        Recomputes over up to 200 buffered HTF bars on every HTF bar arrival (once/hour
        for "1h", once/day for "1d", per symbol) rather than maintaining incremental
        Wilder state -- negligible cost at that cadence, and avoids a second
        hand-rolled implementation of the smoothing recursion.

        `create_if_missing` (todo 241 follow-up, code-review finding #3): False during
        live steady-state (the `_process_bar_compute` call site) -- this method runs
        concurrently with other (symbol, tf) workers via `PerKeyWorkerManager`, and
        `_get_cache(..., exclude_last=False)` assumes every buffered bar is already
        historical. If an LTF cache does not exist yet, its most recent buffered bar
        may be one `_process_bar_inner` has appended but not yet run
        `_process_bar_compute` for (there's a real `await` between those two steps) --
        eagerly creating the cache here would apply that bar's session-VP/overnight-
        range/session-levels contribution now AND a second time when its own worker
        reaches it, double-counting. Skipping (this method silently no-ops for that
        LTF until its own worker creates the cache the normal way) is safe: the next
        HTF arrival re-propagates ctf_momentum into it once it exists.
        True only at cold-start (`_seed_bar_history_from_db`'s caller, before `_run()`
        starts the process loop) -- no concurrent bar processing exists yet at that
        point, so eager creation from purely-historical seeded bars is race-free and
        is what closes the cold-start gap (ctf_momentum stuck at 0.0 for up to an hour
        or a day after every restart) code review found.
        """
        assert self._feature_factory_config is not None, "FeatureFactoryConfig not prewarmed"
        lower_tfs = _CTF_LOWER_TFS.get(htf_tf)
        if not lower_tfs:
            return
        htf_bars = self._bar_history.get(symbol, htf_tf)
        if not htf_bars:
            return
        closes = np.array([b.close for b in htf_bars], dtype=float)
        rsi = _rsi_simple(closes, self._feature_factory_config.rsi_mid_period)
        ctf_momentum = float(np.clip((rsi - 50.0) / 50.0, -1.0, 1.0))
        for ltf in lower_tfs:
            if create_if_missing:
                cache = self._get_cache(symbol, ltf, exclude_last=False)
            else:
                cache = self._feature_caches.get(f"{symbol}:{ltf}")
                if cache is None:
                    continue
            cache.ctf_momentum = ctf_momentum

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
