#!/usr/bin/env python3
"""IntelligencePipelineComputeAgent — Unified I1-I7 in-process pipeline.

Merges FeatureComputeAgent (I1-I6) and SignalGeneratorAgent (I7) into a single
agent that runs the full intelligence pipeline without Kafka between I6 and I7.

Key design decisions:
- I6 output feeds directly into I7 in-process (no Kafka round-trip)
- Async output buffer (asyncio.Queue maxsize=500) — hot path never blocks
- State checkpointing via StateSerializer to compacted Kafka topic
- Attribution capture: pre_quality_confidence + pre_calibration_confidence
- Shadow mode via INTELLIGENCE_PIPELINE_SHADOW env var
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import threading
import time
import zoneinfo
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import msgpack as _msgpack

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.bar_history import BarHistory
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage
from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain
from src.core.service_utils import (
    TF_SECONDS,
    min_bars_for_tf,
    setup_service_logging,
    should_skip_plugin,
)
from src.core.state_serializer import StateSerializer
from src.core.stream_keys import (
    message_key,
    topic_cross_asset,
    topic_intelligence,
    topic_intelligence_i7_signals,
    topic_intelligence_journal,
    topic_intelligence_pipeline_state,
    topic_intelligence_shadow,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_signals_aggregated,
    topic_system_events,
)
from src.intelligence.context.vix_context import compute_vix_context
from src.intelligence.cross_asset_features import resolve_eq_index_base
from src.intelligence.pipeline import (
    apply_calibration,
    apply_quality_gate,
    apply_regime_gate,
    apply_tod_adjustment,
    rank_signals,
    select_winner,
)
from src.intelligence.plugins import registry

# Re-import I1-I6 tiers from register_plugins (shared source of truth)
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
    register_all_plugins,
)
from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)
from src.intelligence.trading.cis_scorer import CISScorer
from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES
from src.observability.metrics import (
    counter,
    gauge,
)

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

# Regime authority TF mapping
_REGIME_AUTHORITY_TF: dict[str, str] = {
    "1m": "5m",
    "5m": "15m",
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
    "1d": "1d",
}

# Phase 35: Eastern Time zone for hour extraction
_ET = zoneinfo.ZoneInfo("America/New_York")

# CIS Kalman defaults
_CIS_KALMAN_DEFAULTS: dict[str, dict[str, float]] = {
    "1m": {"Q": 0.01, "R": 0.08},
    "5m": {"Q": 0.01, "R": 0.06},
    "15m": {"Q": 0.01, "R": 0.04},
    "1h": {"Q": 0.01, "R": 0.02},
}


def _load_cis_kalman_params() -> dict[str, dict[str, float]]:
    """Load per-TF CIS Kalman Q/R from config/kalman_parameters.json."""
    config_path = Path(__file__).parent.parent / "config" / "kalman_parameters.json"
    try:
        data = json.loads(config_path.read_text())
        params = data.get("cis_kalman", _CIS_KALMAN_DEFAULTS)
        return {tf: dict(v) for tf, v in params.items()}
    except Exception:
        return dict(_CIS_KALMAN_DEFAULTS)


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
    f["regime_type"] = f.get("hmm_regime", "ranging")
    return f


logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pattern reliability weight cache
# ---------------------------------------------------------------------------
_pattern_reliability_cache: dict[str, float] | None = None
_pattern_reliability_cache_ts: datetime | None = None
_pattern_reliability_cache_ttl_sec: int = 900


async def _load_pattern_reliability_weights(db_manager: DatabaseManager) -> dict[str, float]:
    """Load pattern confidence weights from pattern_reliability table."""
    global _pattern_reliability_cache, _pattern_reliability_cache_ts

    if db_manager is None:
        return _pattern_reliability_cache if _pattern_reliability_cache is not None else {}

    now = datetime.now(UTC)
    if (
        _pattern_reliability_cache is not None
        and _pattern_reliability_cache_ts is not None
        and (now - _pattern_reliability_cache_ts).total_seconds()
        < _pattern_reliability_cache_ttl_sec
    ):
        return _pattern_reliability_cache

    try:
        rows = await db_manager.execute_query("""
            SELECT pattern_name, base_confidence
            FROM pattern_reliability
            WHERE is_bootstrap = true OR sample_size >= 30
        """)
        weights = {r["pattern_name"]: float(r["base_confidence"]) for r in rows}
        _pattern_reliability_cache = weights
        _pattern_reliability_cache_ts = now
        logger.info(f"Pattern reliability weights loaded from DB: {len(weights)} patterns")
        return weights
    except Exception as exc:
        logger.warning(f"Pattern reliability load failed, using fallback: {exc}")
        return {}


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

_AGENT_VERSION = "v1"


def _restore_tuple_key(k: Any) -> Any:
    """Convert stringified tuple keys back to tuples for state restoration."""
    if isinstance(k, str):
        try:
            parsed = ast.literal_eval(k)
            if isinstance(parsed, tuple):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return k


_STATE_TOPIC_PARTITIONS = 1
_STATE_TOPIC_REPLICATION = 1
_STATE_TOPIC_RETENTION_MS = 604800000  # 7 days


_OUTPUT_QUEUE_MAXSIZE = 500


class IntelligencePipelineComputeAgent(BaseAgent):
    """Unified I1-I7 in-process pipeline agent.

    Replaces FeatureComputeAgent (I1-I6) and SignalGeneratorAgent (I7) with
    a single agent that runs the full pipeline per bar.

    Pipeline flow (per bar):
        BarMessage → gap_detection → BarHistory.append
        → I1 → I2 → I3 → I4 → I5 → SMC → I6
        → IntelligenceEvent enqueued to output buffer
        → I7 plugins → attribution capture → quality_gate → regime_gate
        → tod_adjust → calibration → rank → select_winner
        → SignalResult + StateSnapshot enqueued to output buffer
    """

    def __init__(self) -> None:
        super().__init__(
            name="intelligence_pipeline_agent",
            metrics_port=9125,
        )

        setup_service_logging("logs/intelligence_pipeline_agent.log")

        self._settings = Settings()
        self._contracts = get_active_contracts(self._settings)
        self._symbols = [c.symbol for c in self._contracts]
        self._timeframes = list(_STANDARD_TFS)

        # Plugin registry
        register_all_plugins()
        for tier_list, tier_name in [
            (TIER_I1, "I1"), (TIER_I2, "I2"), (TIER_I3, "I3"),
            (TIER_I4, "I4"), (TIER_I5, "I5"), (TIER_SMC, "SMC"),
            (TIER_I6, "I6"), (TIER_I7, "I7"),
        ]:
            registry.validate_tier(tier_list, tier_name)

        # Plugin caches
        self._plugin_cache: dict[str, Any] = {}
        for n in TIER_I1:
            self._plugin_cache[n] = registry.get_indicator(n)
        for n in (
            TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5
            + TIER_SMC + TIER_I6 + TIER_I7
        ):
            self._plugin_cache[n] = registry.get_pattern(n)

        self._instrument_map: dict[str, Any] = {c.symbol: c for c in self._contracts}

        # --- State dicts (all five checkpointed fields) ---
        self._plugin_states: dict = {}  # (plugin_name, symbol, tf) -> dict
        self._plugin_states_locks: dict = {}  # (plugin_name, symbol, tf) -> Lock
        self._kalman_state: dict = {}  # (symbol, tf) -> {x, P, Q, R}
        self._tod_priors: dict = {}  # (regime_type, tf, hour_et) -> float
        self._bar_history = BarHistory(maxlen=200)
        self._last_bar_offset: dict = {}  # (symbol, tf) -> int (Kafka offset)

        # --- Transient state (NOT checkpointed) ---
        self._signal_gate: dict = {}  # (symbol, tf) -> gate dict
        self._setup_cooldown: dict = {}  # (symbol, tf, plugin, direction) -> datetime
        self._setup_last_fire: dict = {}  # (symbol, tf, plugin, direction) -> {bars_since}
        self._regime_cache: dict = defaultdict(dict)
        self._cross_asset_cache: dict = {}
        self._htf_intel_cache: dict = {}
        self._live_quotes: dict = {}
        self._df_cache: dict = {}
        self._prev_i1_features: dict = {}
        self._last_bar_ts: dict = {}
        self._last_events: dict = {}
        self._pattern_reliability: dict = {}

        # CIS / aggregator state
        self._cis_scorer = CISScorer()
        self._cis_weights_cache: dict = {}
        self._calibration_curves: dict = {}
        self._perf_weights: dict = {}
        self._drift_penalties: dict = {}

        # I7 config
        self._regime_prob_min: float = 0.30
        self._regime_dur_min: float = 0.30

        # Output buffer
        self._output_queue: asyncio.Queue = asyncio.Queue(
            maxsize=_OUTPUT_QUEUE_MAXSIZE
        )

        # Shadow mode
        self._shadow_mode: bool = (
            os.environ.get("INTELLIGENCE_PIPELINE_SHADOW", "0") == "1"
        )

        # Consumer group
        self._consumer_group = "intelligence_pipeline_group"

        # --- Prometheus metrics ---
        self._output_buffer_depth = gauge(
            "intelligence_pipeline_output_buffer_depth",
            "Current depth of async output queue",
        )
        self._output_buffer_drops = counter(
            "intelligence_pipeline_output_buffer_drops_total",
            "Output buffer drops due to queue full",
        )
        self._output_publish_failures = counter(
            "intelligence_pipeline_output_publish_failures_total",
            "Output buffer publish failures",
        )
        self._state_checkpoint_fallback_total = counter(
            "intelligence_pipeline_state_checkpoint_fallback_total",
            "State checkpoint fallback to BarHistorySeeder",
        )
        self._state_checkpoint_failures_total = counter(
            "intelligence_pipeline_state_checkpoint_failures_total",
            "State checkpoint encode/decode failures",
        )
        self._state_offset_reset_total = counter(
            "intelligence_pipeline_state_offset_reset_total",
            "Consumer offset resets after checkpoint restore",
        )
        self._bars_processed = counter(
            "intelligence_pipeline_bars_processed_total",
            "Bars processed through I1-I7 pipeline",
        )
        self._signals_generated = counter(
            "intelligence_pipeline_signals_generated_total",
            "Raw signals generated by I7 plugins",
        )
        self._signals_selected = counter(
            "intelligence_pipeline_signals_selected_total",
            "Winner signals selected by aggregator",
        )
        self._pipeline_errors = counter(
            "intelligence_pipeline_pipeline_errors_total",
            "Pipeline processing errors",
        )
        self._pipeline_latency = gauge(
            "intelligence_pipeline_pipeline_latency_ms",
            "Per-bar pipeline latency in milliseconds",
        )
        self._plugin_call_counts: dict = defaultdict(int)
        self._plugin_skipped_total = counter(
            "intelligence_pipeline_plugin_skipped_total",
            "Plugin executions skipped due to asset class mismatch",
        )

        self._vix_symbol: str | None = None
        for c in self._contracts:
            if c.symbol == "VX":
                self._vix_symbol = "VX"
                break

    # ------------------------------------------------------------------
    # State lock management
    # ------------------------------------------------------------------

    def _get_state_lock(self, key: tuple) -> threading.Lock:
        """Get or create a threading.Lock for a (plugin, symbol, tf) state key."""
        if key not in self._plugin_states_locks:
            self._plugin_states_locks[key] = threading.Lock()
        return self._plugin_states_locks[key]

    # ------------------------------------------------------------------
    # _setup: DB connect, state restore, Kafka setup, cache loading
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        # 1. Connect DB
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()

        # 2. Setup Kafka clients (must come before checkpoint restore + seed)
        # (moved to here so kafka_producer is available for BarHistorySeeder)
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        topics = [
            topic_market_bars(self._settings.env_name),
            topic_market_bars_htf(self._settings.env_name),
            topic_system_events(self._settings.env_name),
            topic_cross_asset(self._settings.env_name),
            topic_market_ticks(self._settings.env_name),
        ]
        self._kafka_consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=self._consumer_group,
        )
        await self._kafka_consumer.start()
        self.logger.info("kafka.subscribed", topics=topics)

        # 3. Restore state from checkpoint topic
        restored = await self._restore_state_checkpoint()

        # 4. Fallback to BarHistorySeeder if checkpoint miss
        if not restored:
            self._state_checkpoint_fallback_total.inc()
            self.logger.info("state.checkpoint_miss — seeding via BarHistorySeeder")
            await self._seed_bar_history_from_db()

        # 5. Load DB caches (I7 setup, same as SignalGeneratorAgent)
        await self._load_perf_weights()
        await self._refresh_drift_penalties()
        await self._load_cis_weights()
        await self._load_calibration_curves()
        await self._load_tod_multipliers()
        self._pattern_reliability = await _load_pattern_reliability_weights(self._db)

        # Create compacted state topic if needed
        await self._ensure_state_topic()

        self.logger.info(
            "agent.setup_complete",
            shadow=self._shadow_mode,
            symbols=self._symbols,
            timeframes=self._timeframes,
        )

    async def _ensure_state_topic(self) -> None:
        """Create the compacted state checkpoint topic if it doesn't exist."""
        state_topic = topic_intelligence_pipeline_state(self._settings.env_name)
        try:
            import subprocess
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker", "exec", "redpanda", "rpk", "topic", "create", state_topic,
                    "--partitions", str(_STATE_TOPIC_PARTITIONS),
                    "--replicas", str(_STATE_TOPIC_REPLICATION),
                    "--topic-config", "cleanup.policy=compact",
                    "--topic-config", f"retention.ms={_STATE_TOPIC_RETENTION_MS}",
                ],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0 and b"already exists" not in result.stderr:
                self.logger.warning("state_topic.create_failed", stderr=result.stderr.decode())
        except Exception:
            self.logger.debug("state_topic.create_skipped", reason="rpk unavailable")

    async def _seed_bar_history_from_db(self) -> None:
        """Seed BarHistory from intelligence_features (fallback)."""
        try:
            from src.core.bar_history_seeder import BarHistorySeeder

            config = {"service": {"timeframes": list(self._timeframes)}}
            seeder = BarHistorySeeder(self._settings, config, self._kafka_producer)
            await seeder.seed(self._bar_history)
        except Exception as exc:
            self.logger.warning("bar_history.seed_failed", error=str(exc))

    # ------------------------------------------------------------------
    # State checkpoint restore
    # ------------------------------------------------------------------

    async def _restore_state_checkpoint(self) -> bool:
        """Consume compacted state topic and restore all five state fields."""
        state_topic = topic_intelligence_pipeline_state(self._settings.env_name)
        consumer = None
        try:
            consumer = KafkaConsumerClient(
                state_topic,
                bootstrap_servers=self._settings.kafka_bootstrap_servers,
                group_id=f"{self._consumer_group}_state_restore",
                auto_offset_reset="earliest",
            )
            await consumer.start()

            result: list[bool] = [False]

            async def _drain() -> None:
                async for _topic, key_str, payload in consumer.messages():  # type: ignore[union-attr]
                    if not key_str or not key_str.startswith(f"{_AGENT_VERSION}:"):
                        self._state_checkpoint_fallback_total.inc()
                        continue
                    try:
                        if isinstance(payload, dict):
                            raw = _msgpack.packb(payload, use_bin_type=True)
                            state = StateSerializer.decode(raw)
                        else:
                            state = StateSerializer.decode(payload)
                    except Exception:
                        self._state_checkpoint_failures_total.inc()
                        continue

                    parts = key_str.split(":")
                    if len(parts) != 3:
                        continue
                    _, symbol, tf = parts  # noqa: F841

                    if "_plugin_states" in state:
                        for k, v in state["_plugin_states"].items():
                            self._plugin_states[_restore_tuple_key(k)] = v
                    if "_kalman_state" in state:
                        for k, v in state["_kalman_state"].items():
                            self._kalman_state[_restore_tuple_key(k)] = v
                    if "_tod_priors" in state:
                        for k, v in state["_tod_priors"].items():
                            self._tod_priors[_restore_tuple_key(k)] = v
                    if "_bar_history" in state:
                        for k, v in state["_bar_history"].items():
                            self._bar_history._data[k] = v
                    if "_last_bar_offset" in state:
                        for k, v in state["_last_bar_offset"].items():
                            self._last_bar_offset[_restore_tuple_key(k)] = v
                    result[0] = True

            try:
                await asyncio.wait_for(_drain(), timeout=5.0)
            except asyncio.TimeoutError:
                pass  # normal — drained all available messages

            restored_any = result[0]
            if restored_any and self._last_bar_offset:
                self._state_offset_reset_total.inc()
                self.logger.info("state.restored", offsets=self._last_bar_offset)

            return restored_any

        except Exception as exc:
            self.logger.warning("state.restore_failed", error=str(exc))
            self._state_checkpoint_failures_total.inc()
            return False
        finally:
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # _run: main event loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Main loop: consume bars, run I1-I7, drain output."""
        tasks = [
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._drain_output()),
            asyncio.create_task(self._health_monitor_loop()),
            # Refresh loops
            asyncio.create_task(
                self._run_refresh_loop(self._load_perf_weights, 3600)
            ),
            asyncio.create_task(
                self._run_refresh_loop(self._refresh_drift_penalties, 14400)
            ),
            asyncio.create_task(
                self._run_refresh_loop(self._load_cis_weights, 1800)
            ),
            asyncio.create_task(
                self._run_refresh_loop(self._load_calibration_curves, 1800)
            ),
            asyncio.create_task(
                self._run_refresh_loop(self._load_tod_multipliers, 14400)
            ),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _teardown(self) -> None:
        """Drain output queue, close connections."""
        self._stop_event.set()
        # Wait for output queue to drain (10s timeout)
        try:
            await asyncio.wait_for(self._output_queue.join(), timeout=10.0)
        except TimeoutError:
            self.logger.warning("teardown.output_drain_timeout")
        if hasattr(self, "_kafka_consumer"):
            await self._kafka_consumer.stop()
        if hasattr(self, "_kafka_producer"):
            await self._kafka_producer.stop()
        if hasattr(self, "_db"):
            await self._db.close()
        self.logger.info("agent.teardown_complete")

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        """Consume all topics and route: bar → I1-I7 pipeline; non-bar → caches."""
        _cross_asset_topic = topic_cross_asset(self._settings.env_name)
        _ticks_topic = topic_market_ticks(self._settings.env_name)
        _system_topic = topic_system_events(self._settings.env_name)
        while self.running:
            try:
                async for _topic, _key, payload in self._kafka_consumer.messages():
                    if not isinstance(payload, dict):
                        continue
                    try:
                        if _topic == _cross_asset_topic:
                            tf = payload.get("tf", "1m")
                            self._cross_asset_cache[tf] = payload
                        elif _topic == _ticks_topic:
                            symbol = payload.get("symbol", "")
                            self._live_quotes[symbol] = payload
                        elif _topic == _system_topic:
                            await self._handle_system_event(payload)
                        else:
                            bar = self._parse_bar(payload)
                            if bar is None:
                                continue
                            await self._process_bar(bar)
                    except Exception as exc:
                        self.logger.error(
                            "bar.process_error",
                            error=str(exc),
                        )
                        self._pipeline_errors.inc()
            except Exception as exc:
                self.logger.warning("process_loop.consumer_error", error=str(exc))
                await asyncio.sleep(1)

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
            self._pipeline_errors.inc()
            return

        if intel_event is None:
            return

        # 5. Enqueue IntelligenceEvent to output buffer
        msg_key = message_key(bar.symbol, bar.tf)
        output_topic = (
            topic_intelligence_shadow(self._settings.env_name)
            if self._shadow_mode
            else topic_intelligence(self._settings.env_name)
        )
        self._enqueue(output_topic, msg_key, {"event": intel_event.model_dump_json()})

        # Also publish intelligence journal
        self._enqueue_intel_journal(bar, intel_event, msg_key)

        # 6. Run I7 pipeline (in-process, no Kafka)
        try:
            await self._run_i7(bar, intel_event, tiered)
        except Exception as exc:
            self.logger.error("pipeline.i7_error", symbol=bar.symbol, tf=bar.tf, error=str(exc))
            self._pipeline_errors.inc()

        # 7. State checkpoint (best-effort — non-serializable state is skipped)
        try:
            await self._checkpoint_state(bar)
        except Exception:
            self._state_checkpoint_failures_total.inc()

        self._bars_processed.inc()

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
        frames: dict[str, Any] = {"main": main_df}

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
                    if (
                        tier_name in ("i1", "i2", "i3", "i4", "i5", "smc", "i6")
                        and isinstance(tier_data, dict)
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

        # Cross-asset
        if resolve_eq_index_base(symbol) is not None:
            frames["cross_asset"] = self._cross_asset_cache.get(tf, {"ready": False})
            frames["cross_asset_5m"] = self._cross_asset_cache.get("5m", {"ready": False})

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

        # I1
        i1_result = await self._run_i1(frames, symbol, tf)
        frames["features"] = dict(i1_result)
        self._prev_i1_features[key] = dict(i1_result)

        self._last_events[key + "_i1"] = i1_result

        # I2-I6
        tiered = await self._run_analysis_pipeline(symbol, tf, frames)
        if not tiered:
            return None, None

        pipeline_latency_ms = (time.perf_counter() - t0) * 1000

        self._pipeline_latency.set(pipeline_latency_ms)

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
            )
        except ValidationError as exc:
            self.logger.error(
                "IntelligenceEvent validation failed",
                symbol=symbol, tf=tf, error=str(exc),
            )
            self._pipeline_errors.inc()
            return None, None

        self._last_events[key] = event
        return event, tiered

    # ------------------------------------------------------------------
    # Output buffer
    # ------------------------------------------------------------------

    def _enqueue(self, topic: str, key: str, value: Any) -> None:
        """Non-blocking enqueue to output buffer. Drops on QueueFull."""
        try:
            self._output_queue.put_nowait((topic, key, value))
        except asyncio.QueueFull:
            self._output_buffer_drops.inc()

    async def _drain_output(self) -> None:
        """Background task: drain output queue and publish to Kafka."""
        while self.running or not self._output_queue.empty():
            try:
                topic, key, value = await asyncio.wait_for(
                    self._output_queue.get(), timeout=1.0
                )
                self._output_buffer_depth.set(self._output_queue.qsize())
                await self._kafka_producer.publish(topic, msg=value, key=key)
                self._output_queue.task_done()
            except TimeoutError:
                continue
            except Exception:
                self._output_publish_failures.inc()
                self.logger.exception("output.publish_failed")
                self._output_queue.task_done()

    # ------------------------------------------------------------------
    # I1 plugin execution
    # ------------------------------------------------------------------

    async def _run_i1(self, frames: dict, symbol: str, tf: str) -> dict:
        """Run all I1 plugins and return merged result dict."""
        result: dict[str, Any] = {}
        for plugin_name in TIER_I1:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is None:
                continue
            if should_skip_plugin(plugin, self._instrument_map.get(symbol), self._plugin_skipped_total, plugin_name):
                continue
            state_key = (plugin_name, symbol, tf)
            lock = self._get_state_lock(state_key)
            try:
                out = await asyncio.to_thread(plugin.compute_full, frames)
                if isinstance(out, dict):
                    with lock:
                        if "_state" in out:
                            self._plugin_states[state_key] = out.pop("_state")
                        result.update(out)
            except Exception as exc:
                self._pipeline_errors.inc()
                self.logger.warning(
                    "plugin.error", plugin=plugin_name, error=str(exc)
                )
        return result

    # ------------------------------------------------------------------
    # I2-I6 analysis pipeline
    # ------------------------------------------------------------------

    async def _run_analysis_pipeline(
        self, symbol: str, tf: str, frames: dict
    ) -> dict | None:
        """Run I2 → I3 → I4 → I5 → SMC → I6 and return tiered dict."""
        tiered: dict[str, dict] = {}
        tier_map = [
            ("i2", TIER_I2),
            ("i3", TIER_I3),
            ("i4", TIER_I4),
            ("i5", TIER_I5),
            ("smc", TIER_SMC),
            ("i6", TIER_I6),
        ]
        for tier_key, tier_list in tier_map:
            tier_result: dict[str, Any] = {}
            for plugin_name in tier_list:
                plugin = self._plugin_cache.get(plugin_name)
                if plugin is None:
                    continue
                if should_skip_plugin(plugin, self._instrument_map.get(symbol), self._plugin_skipped_total, plugin_name):
                    continue
                state_key = (plugin_name, symbol, tf)
                lock = self._get_state_lock(state_key)
                try:
                    out = await asyncio.to_thread(plugin.compute_full, frames)
                    if isinstance(out, dict):
                        with lock:
                            if "_state" in out:
                                self._plugin_states[state_key] = out.pop("_state")
                            # SMC plugin outputs trend_direction; rename to smc_trend_direction
                            # to avoid collision with I3Structure.trend_direction
                            if tier_key == "smc" and "trend_direction" in out:
                                out["smc_trend_direction"] = out.pop("trend_direction")
                            tier_result.update(out)
                except Exception as exc:
                    self._pipeline_errors.inc()
                    self.logger.warning(
                        "plugin.error", plugin=plugin_name, tier=tier_key, error=str(exc)
                    )
            tiered[tier_key] = tier_result
            frames[tier_key] = tier_result

        return tiered

    # ------------------------------------------------------------------
    # I7 signal generation pipeline
    # ------------------------------------------------------------------

    async def _run_i7(
        self, bar: BarMessage, event: IntelligenceEvent, tiered: dict
    ) -> None:
        """Run I7 plugins → quality gate → regime gate → calibration → rank → select."""
        symbol, tf = bar.symbol, bar.tf
        features = _build_features_from_event(event)

        # Run all I7 plugins
        raw_signals: list[dict] = []
        for plugin_name in I7_PLUGINS:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is None:
                continue
            if should_skip_plugin(plugin, self._instrument_map.get(symbol), self._plugin_skipped_total, plugin_name):
                continue
            state_key = (plugin_name, symbol, tf)
            lock = self._get_state_lock(state_key)
            try:
                out = await asyncio.to_thread(plugin.compute_full, {"main": None, **features})
                if isinstance(out, dict) and out.get("signal"):
                    sig = out["signal"]
                    sig["setup_plugin"] = plugin_name
                    sig["symbol"] = symbol
                    sig["tf"] = tf
                    # Alpha decay
                    fire_key = (symbol, tf, plugin_name, sig.get("direction", 0))
                    _apply_alpha_decay(sig, tf, self._setup_last_fire.get(fire_key))
                    raw_signals.append(sig)
                    self._signals_generated.inc()
                if isinstance(out, dict) and "_state" in out:
                    with lock:
                        self._plugin_states[state_key] = out["_state"]
            except Exception as exc:
                self._pipeline_errors.inc()
                self.logger.warning(
                    "i7.plugin.error", plugin=plugin_name, error=str(exc)
                )

        if not raw_signals:
            return

        # Attribution capture: BEFORE quality gate
        for sig in raw_signals:
            sig["pre_quality_confidence"] = sig.get("confidence", 0.0)

        # Pipeline stages
        quality_gated = apply_quality_gate(raw_signals, features)
        regime_gated = apply_regime_gate(
            quality_gated,
            self._regime_cache,
            tf,
            _REGIME_AUTHORITY_TF,
            features,
        )
        tod_adjusted = apply_tod_adjustment(regime_gated, self._tod_priors, tf, features)

        # Attribution capture: BEFORE calibration
        for sig in tod_adjusted:
            sig["pre_calibration_confidence"] = sig.get("confidence", 0.0)

        calibrated = apply_calibration(tod_adjusted, self._calibration_curves, tf)
        ranked = rank_signals(calibrated, self._perf_weights)

        # Annotate each ranked signal with ledger metadata before publishing
        num_signals = len(ranked)
        for rank_idx, sig in enumerate(ranked, start=1):
            sig["composite_rank"] = rank_idx
            sig["num_signals_bar"] = num_signals
            sig["was_selected"] = False  # filled in after winner selection below
            sig["status"] = (
                "pending" if sig.get("regime_eligible", True) else "regime_suppressed"
            )
            # Regime context from features (populated by _build_features_from_event)
            sig["regime_type"] = features.get("regime_type")
            sig["hmm_regime_at_fire"] = features.get("hmm_regime")
            # is_shadow: check plugin class attribute via _plugin_cache
            plugin_inst = self._plugin_cache.get(sig.get("setup_plugin", ""))
            sig["is_shadow"] = bool(
                plugin_inst is not None and getattr(plugin_inst, "IS_SHADOW", False)
            )

        # Select winner from regime-eligible signals only
        winner = select_winner([s for s in ranked if s.get("regime_eligible", True)])
        winner_plugin = winner.get("setup_plugin") if winner else None

        # Mark the winner
        if winner_plugin is not None:
            for sig in ranked:
                if (
                    sig.get("setup_plugin") == winner_plugin
                    and sig.get("regime_eligible", True)
                ):
                    sig["was_selected"] = True
                    break

        # Publish ALL ranked signals (including regime_suppressed) for SignalWriterAgent → signal_ledger
        self._enqueue(
            topic_intelligence_i7_signals(self._settings.env_name),
            message_key(symbol, tf),
            {
                "symbol": symbol,
                "tf": tf,
                "bar_ts": bar.ts.isoformat(),
                "computed_at": datetime.now(UTC).isoformat(),
                "signals": ranked,
            },
        )

        # Publish winner to signals.aggregated for signal_tracker_agent
        if winner:
            self._signals_selected.inc()
            self._enqueue(
                topic_signals_aggregated(self._settings.env_name),
                message_key(symbol, tf),
                winner,
            )

    # ------------------------------------------------------------------
    # State checkpointing
    # ------------------------------------------------------------------

    async def _checkpoint_state(self, bar: BarMessage) -> None:
        """Encode current state and enqueue to compacted state topic."""
        state = {
            "_plugin_states": self._plugin_states,
            "_kalman_state": self._kalman_state,
            "_tod_priors": self._tod_priors,
            "_bar_history": self._bar_history._data,
            "_last_bar_offset": self._last_bar_offset,
        }
        encoded = StateSerializer.encode(state)
        checkpoint_key = f"{_AGENT_VERSION}:{bar.symbol}:{bar.tf}"
        self._enqueue(
            topic_intelligence_pipeline_state(self._settings.env_name),
            checkpoint_key,
            encoded,
        )

    # ------------------------------------------------------------------
    # Intelligence journal
    # ------------------------------------------------------------------

    def _enqueue_intel_journal(
        self, bar: BarMessage, event: IntelligenceEvent, msg_key: str
    ) -> None:
        """Enqueue IntelligenceJournal record to output buffer."""
        now = datetime.now(UTC)
        symbol = bar.symbol
        tf = bar.tf
        journal = IntelligenceJournal(
            ts=now,
            sid=f"intel_{symbol}_{tf}",
            payload=event.model_dump(mode="json"),
            provenance=ProvenanceChain(
                origin_ts=now,
                pipeline_id=f"intel_{symbol}_{tf}",
                plugin_stack=["intelligence_pipeline_agent"],
                compute_budget_ms=0.0,
            ),
        )
        self._enqueue(
            topic_intelligence_journal(self._settings.env_name),
            msg_key,
            journal.model_dump(mode="json"),
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

    # ------------------------------------------------------------------
    # DB cache refresh loops
    # ------------------------------------------------------------------

    async def _run_refresh_loop(self, load_fn, interval_sec: int) -> None:
        """Periodically refresh a DB cache."""
        while self.running:
            try:
                await asyncio.sleep(interval_sec)
                await load_fn()
            except Exception as exc:
                self.logger.warning("refresh_loop.error", error=str(exc))

    async def _load_perf_weights(self) -> None:
        """Load perf_weights from setup_performance table."""
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query("""
                SELECT setup_plugin, direction, win_rate, avg_pnl_r, sample_size
                FROM setup_performance
                WHERE sample_size >= 30
            """)
            weights: dict = {}
            for r in rows:
                key = (r["setup_plugin"], r["direction"])
                weights[key] = r.get("win_rate", 0.5)
            self._perf_weights = weights
        except Exception as exc:
            self.logger.warning("perf_weights.load_failed", error=str(exc))

    async def _refresh_drift_penalties(self) -> None:
        """Refresh drift penalties from DRIFT_PENALTIES config."""
        self._drift_penalties = dict(DRIFT_PENALTIES)

    async def _load_cis_weights(self) -> None:
        """Load CIS bucket weights from cis_weights table."""
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query(
                "SELECT version, weights FROM cis_weights ORDER BY version DESC LIMIT 1"
            )
            if rows:
                self._cis_weights_cache = rows[0].get("weights", {})
        except Exception as exc:
            self.logger.warning("cis_weights.load_failed", error=str(exc))

    async def _load_calibration_curves(self) -> None:
        """Load calibration curves from calibration_curves table."""
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query(
                "SELECT setup_plugin, curve_data FROM calibration_curves"
            )
            curves: dict = {}
            for r in rows:
                curves[r["setup_plugin"]] = r.get("curve_data", {})
            self._calibration_curves = curves
        except Exception as exc:
            self.logger.warning("calibration_curves.load_failed", error=str(exc))

    async def _load_tod_multipliers(self) -> None:
        """Load TOD multipliers from tod_multipliers table."""
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query(
                "SELECT regime_type, tf, hour_et, multiplier FROM tod_multipliers"
            )
            priors: dict = {}
            for r in rows:
                key = (r["regime_type"], r["tf"], r["hour_et"])
                priors[key] = float(r["multiplier"])
            self._tod_priors = {**self._tod_priors, **priors}
        except Exception as exc:
            self.logger.warning("tod_multipliers.load_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = IntelligencePipelineComputeAgent()
    asyncio.run(agent.start())
