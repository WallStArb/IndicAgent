#!/usr/bin/env python3
"""
FeatureComputeAgent — Unified I1-I6 in-process pipeline.

Replaces indicator_service + market_analysis_service + timeframes_builder_service.
Consumes 1m bars from development.market.bars AND HTF bars from
development.market.bars.htf, runs I1→I2→I3→I4→I5→SMC→I6 per bar,
publishes IntelligenceEvent to development.intelligence.

Key design decisions:
- BarHistory replaces raw dict[str, deque] from both legacy services
- BarAccumulator extracted to BarAggregatorComputeAgent (Phase 53.2) — FCA is a pure consumer
- Each bar arriving (1m or HTF) triggers an independent pipeline run (per D-02)
- pipeline_latency_ms published at :9125
- GARCH/HMM plugin state persists across bars (asyncio.to_thread + threading.Lock)
- smc_trend_direction renamed before features merge (I3 trend_direction preserved)
- _prev_i1_features injected before I1, stored after I1 (I2 crossover works bar 2+)
- Roll events migrate BarHistory and adjust price-sensitive I1 plugin state
- gap_preceding=True set when previous bar ts is stale for (symbol, tf)
"""

from __future__ import annotations

import asyncio
import copy
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts
from src.core.bar_history import BarHistory
from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain
from src.core.service_utils import (
    CROSS_ASSET_VALID_TFS,
    PLUGIN_METRICS_SAMPLE_RATE,
    SEED_LOOKBACK_MULTIPLIER,
    TF_SECONDS,
    min_bars_for_tf,
    parse_roll_event,
    setup_service_logging,
    should_skip_plugin,
)
from src.core.stream_keys import (
    message_key,
    topic_cross_asset,
    topic_intelligence,
    topic_intelligence_journal,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_system_events,
)
from src.intelligence.context.vix_context import compute_vix_context
from src.intelligence.cross_asset_features import resolve_eq_index_base
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
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
from src.observability.metrics import (
    PLUGIN_SKIPPED_TOTAL,
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Canonical timeframe ordering for I1-I6 pipeline.
_STANDARD_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

# VIX regime context always uses 1h bars — fixed window regardless of trading TF.
# 20 x 1h = ~20 trading hours: captures session-scale fear elevation.
# Complementary to GARCH (multi-week structural vol regime).
VIX_REGIME_TF: str = "1h"

# I1 plugins that track absolute price levels — adjusted by roll_gap on roll.
PRICE_SENSITIVE_PLUGINS: frozenset[str] = frozenset(
    {"bollinger_bands", "keltner_channel", "donchian_channel"}
)


def _adjust_price_state(state: dict, roll_gap: float) -> dict:
    """Return a deep copy of *state* with all numeric values shifted by *roll_gap*.

    Rules:
    - float/int scalar → add roll_gap
    - list of float/int → add roll_gap to each element
    - nested dict → recurse
    - other types (str, bool, None) → copy unchanged
    """
    result: dict = {}
    for k, v in state.items():
        if isinstance(v, float):
            result[k] = v + roll_gap
        elif isinstance(v, int) and not isinstance(v, bool):
            result[k] = v + roll_gap
        elif isinstance(v, list):
            adjusted: list = []
            for item in v:
                if isinstance(item, float):
                    adjusted.append(item + roll_gap)
                elif isinstance(item, int) and not isinstance(item, bool):
                    adjusted.append(item + roll_gap)
                else:
                    adjusted.append(item)
            result[k] = adjusted
        elif isinstance(v, dict):
            result[k] = _adjust_price_state(v, roll_gap)
        else:
            result[k] = v
    return result


class FeatureComputeAgent:
    """Unified I1-I6 pipeline service — replaces indicator + market_analysis + timeframes_builder.

    Startup sequence:
      1. DB connect → seed BarHistory from intelligence_features (ROW_NUMBER window query)
      2. Re-publish last known IntelligenceEvent per (symbol, tf) for dashboard warmup
      3. Subscribe to system.events for roll events
      4. Begin consuming development.market.bars and development.market.bars.htf

    Per-bar pipeline:
      BarMessage → gap detection → BarHistory.append → pipeline (if warm)
      → I1 → I2 → I3 → I4 → I5 → SMC → I6 → IntelligenceEvent → publish
    """

    def __init__(self) -> None:
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(UTC)

        setup_service_logging("logs/feature_pipeline_service.log")

        self._settings = Settings()
        self._contracts = get_active_contracts(self._settings)
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
        ]:
            registry.validate_tier(tier_list, tier_name)

        # Plugin reference caches — eliminates per-bar registry lookups
        self._plugin_cache: dict[str, Any] = {}
        for n in TIER_I1:
            self._plugin_cache[n] = registry.get_indicator(n)
        for n in TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6:
            self._plugin_cache[n] = registry.get_pattern(n)

        # Build instrument map for asset-class guard
        self._instrument_map: dict[str, Any] = {c.symbol: c for c in self._contracts}

        # Per-(plugin, symbol, timeframe) state namespace — prevents cross-symbol state bleed
        self._plugin_states: dict[tuple[str, str, str], dict] = {}
        # Per-key threading.Lock for asyncio.to_thread CPU-bound plugins
        self._plugin_states_locks: dict[tuple[str, str, str], threading.Lock] = {}
        self._plugin_call_counts: dict[tuple[str, str], int] = defaultdict(int)

        # Previous I1 features per "{symbol}:{tf}" — enables I2 crossover detection on bar 2+
        self._prev_i1_features: dict[str, dict[str, Any]] = {}

        # Concurrency bound per
        self._sem = asyncio.Semaphore(min(32, (os.cpu_count() or 4) * 2))

        # Last published IntelligenceEvent per "{symbol}:{tf}" — for startup re-publish
        self._last_events: dict[str, IntelligenceEvent] = {}

        # Last bar timestamp per "{symbol}:{tf}" — for gap detection
        self._last_bar_ts: dict[str, float] = {}

        # BarHistory — typed deque store (replaces raw dict[str, deque])
        self._bar_history = BarHistory(maxlen=200)

        # Phase 46: Cross-asset cache and VIX symbol resolution
        self._cross_asset_cache: dict[str, dict] = {}  # tf -> cross_asset payload

        # Resolve VIX contract symbol for bar history lookup — D-10
        self._vix_symbol: str | None = None
        for _instr in self._contracts:
            if _instr.symbol in ("VX", "VIX"):
                self._vix_symbol = _instr.symbol
                break

        # Per-symbol tick buffer — flushed at bar close; capped at 10k ticks
        self._tick_buffers: dict[str, list[dict]] = defaultdict(list)
        self._tick_buffer_max: int = 10_000

        # DB-ignorant — no direct database access in compute loop
        self._db = None

        # Kafka clients
        self._producer: KafkaProducerClient = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        self._consumer: KafkaConsumerClient | None = None
        self._tick_consumer: KafkaConsumerClient | None = None

        # Metrics — use metrics.py to prevent duplicate registration
        self._pipeline_latency_histogram = gauge(
            "feature_pipeline_latency_ms",
            "Last per-bar pipeline latency in milliseconds",
        )
        self._bars_processed = counter(
            "feature_pipeline_bars_processed_total",
            "Total bars processed by feature pipeline service",
        )
        self._pipeline_errors = counter(
            "feature_pipeline_errors_total",
            "Total errors in feature pipeline service",
        )
        self._service_uptime = gauge(
            "feature_pipeline_service_uptime_seconds",
            "Feature pipeline service uptime in seconds",
        )
        self.plugin_skipped_total = PLUGIN_SKIPPED_TOTAL

        self.logger = structlog.get_logger(__name__)

    # ---------------------------------------------------------------------------
    # State management helpers
    # ---------------------------------------------------------------------------

    def _get_state_lock(self, key: tuple[str, str, str]) -> threading.Lock:
        """Get or create a threading.Lock for given plugin state key."""
        return self._plugin_states_locks.setdefault(key, threading.Lock())

    # ---------------------------------------------------------------------------
    # Startup — DB seed
    # ---------------------------------------------------------------------------

    async def _seed_bar_history(self) -> None:
        """Seed BarHistory from intelligence_features using a single ROW_NUMBER window query.

        Primary: intelligence_features (preferred — includes I1-I6 context).
        Fallback: market_data_ohlcv for (symbol, tf) pairs with insufficient rows.
        After seeding, re-publishes last known IntelligenceEvent per (symbol, tf).
        """
        if not self._db:
            self.logger.warning("DB seed skipped — no db")
            return

        symbols = self._symbols
        timeframes = self._timeframes

        # Single ROW_NUMBER() window query covering all active symbols
        try:
            rows = await self._db.execute_query(
                """
                WITH ranked AS (
                    SELECT symbol, tf, ts, bar,
                           i1, i2, i3, i4, i5, smc, i6,
                           bar_close_ts, i1_computed_at, computed_at,
                           ROW_NUMBER() OVER (PARTITION BY symbol, tf ORDER BY ts DESC) AS rn
                    FROM intelligence_features
                    WHERE symbol = ANY($1)
                      AND ts > NOW() - INTERVAL '7 days'
                )
                SELECT symbol, tf, ts, bar,
                       i1, i2, i3, i4, i5, smc, i6,
                       bar_close_ts, i1_computed_at, computed_at
                FROM ranked
                WHERE rn <= 200
                ORDER BY symbol, tf, ts ASC
                """,
                symbols,
            )
        except Exception as e:
            self.logger.warning("Seed query failed — falling back to OHLCV only", error=str(e))
            rows = []

        # Group rows by (symbol, tf), build BarMessage list, seed BarHistory
        seeded_bars = 0
        seeded_pairs: set[tuple[str, str]] = set()

        grouped: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            grouped[(row["symbol"], row["tf"])].append(row)

        for (symbol, tf), tf_rows in grouped.items():
            bars: list[BarMessage] = []
            latest_row = None
            for row in tf_rows:  # already ordered ASC by query
                bar_json = row["bar"] or {}
                if isinstance(bar_json, str):
                    import json
                    bar_json = json.loads(bar_json)
                try:
                    raw_ts = row["ts"]
                    bar_ts = (
                        raw_ts
                        if isinstance(raw_ts, datetime)
                        else datetime.fromisoformat(str(raw_ts))
                    )
                    bar = BarMessage(
                        ts=bar_ts,
                        symbol=symbol,
                        tf=tf,
                        open=float(bar_json.get("o", 0)),
                        high=float(bar_json.get("h", 0)),
                        low=float(bar_json.get("l", 0)),
                        close=float(bar_json.get("c", 0)),
                        volume=int(bar_json.get("v", 0)),
                        source="ibkr_seed",
                        session_type=SessionType.RTH,
                        gap_preceding=False,
                    )
                    bars.append(bar)
                    seeded_bars += 1
                    latest_row = row
                except Exception:
                    pass

            if bars:
                self._bar_history.seed(symbol, tf, bars)
                seeded_pairs.add((symbol, tf))

            # Re-publish last known IntelligenceEvent
            if latest_row is not None:
                try:
                    await self._republish_seed_event(symbol, tf, latest_row)
                except Exception as e:
                    self.logger.warning("Seed republish failed", symbol=symbol, tf=tf, error=str(e))

        # Fallback: for pairs below min_bars, seed from market_data_ohlcv
        fallback_bars = 0
        sem = asyncio.Semaphore(8)

        async def _fallback_one(symbol: str, tf: str) -> None:
            nonlocal fallback_bars
            if self._bar_history.is_warm(symbol, tf, min_bars_for_tf(tf)):
                return
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER

                if tf != "1m":
                    tf_minutes = tf_secs // 60
                    lookback_1m = min_bars * tf_minutes * 2
                    try:
                        rows_1m = await self._db.execute_query(  # type: ignore[union-attr]
                            f"""
                            SELECT timestamp, open, high, low, close, volume
                            FROM market_data_ohlcv
                            WHERE symbol = $1 AND timeframe = '1m'
                              AND timestamp > NOW() - INTERVAL '{lookback_1m * 60} seconds'
                            ORDER BY timestamp ASC
                            LIMIT {lookback_1m}
                            """,
                            symbol,
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Fallback HTF seed query failed", symbol=symbol, tf=tf, error=str(e)
                        )
                        return
                    if not rows_1m:
                        return
                    buckets: dict[int, list] = defaultdict(list)
                    for row in rows_1m:
                        ts = row["timestamp"]
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts)
                        period = int(ts.timestamp()) // (tf_minutes * 60) * (tf_minutes * 60)
                        buckets[period].append((ts, row))
                    bars_fb: list[BarMessage] = []
                    for period_ts, bucket in buckets.items():
                        try:
                            bars_fb.append(
                                BarMessage(
                                    ts=datetime.fromtimestamp(period_ts, tz=UTC),
                                    symbol=symbol,
                                    tf=tf,
                                    open=float(bucket[0][1]["open"]),
                                    high=max(float(b[1]["high"]) for b in bucket),
                                    low=min(float(b[1]["low"]) for b in bucket),
                                    close=float(bucket[-1][1]["close"]),
                                    volume=sum(int(b[1]["volume"]) for b in bucket),
                                    source="ibkr_seed",
                                    session_type=SessionType.RTH,
                                    gap_preceding=False,
                                )
                            )
                            fallback_bars += 1
                        except Exception as e:
                            self.logger.warning(
                                "HTF bar construction failed",
                                symbol=symbol,
                                tf=tf,
                                period_ts=period_ts,
                                error=str(e),
                            )
                    if bars_fb:
                        self._bar_history.seed(symbol, tf, bars_fb)
                    return

                try:
                    ohlcv_rows = await self._db.execute_query(  # type: ignore[union-attr]
                        f"""
                        SELECT timestamp, open, high, low, close, volume
                        FROM market_data_ohlcv
                        WHERE symbol = $1 AND timeframe = $2
                          AND timestamp > NOW() - INTERVAL '{lookback_secs} seconds'
                        ORDER BY timestamp DESC
                        LIMIT {min_bars}
                        """,
                        symbol,
                        tf,
                    )
                except Exception as e:
                    self.logger.warning(
                        "Fallback seed query failed", symbol=symbol, tf=tf, error=str(e)
                    )
                    return
                if not ohlcv_rows:
                    return
                bars_fb = []
                for row in reversed(ohlcv_rows):
                    try:
                        ts = row["timestamp"]
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts)
                        bars_fb.append(
                            BarMessage(
                                ts=ts,
                                symbol=symbol,
                                tf=tf,
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                close=float(row["close"]),
                                volume=int(row["volume"]),
                                source="ibkr_seed",
                                session_type=SessionType.RTH,
                                gap_preceding=False,
                            )
                        )
                        fallback_bars += 1
                    except Exception as e:
                        self.logger.warning(
                            "1m bar construction failed",
                            symbol=symbol,
                            tf=tf,
                            error=str(e),
                        )
                if bars_fb:
                    self._bar_history.seed(symbol, tf, bars_fb)

        fallback_tasks = [_fallback_one(sym, tf) for sym in symbols for tf in timeframes]
        await asyncio.gather(*fallback_tasks)

        self.logger.info(
            "BarHistory seeded",
            seeded_bars=seeded_bars,
            fallback_bars=fallback_bars,
            seeded_pairs=len(seeded_pairs),
        )

    async def _republish_seed_event(self, symbol: str, tf: str, row: Any) -> None:
        """Reconstruct and republish the most recent IntelligenceEvent from a seed row."""
        from src.api.utils import parse_jsonb

        bar_json = parse_jsonb(row["bar"], default={})
        try:
            event = IntelligenceEvent(
                ts=row["ts"],
                symbol=symbol,
                tf=tf,
                source="backfill",
                bar=OHLCVBar(
                    o=float(bar_json.get("o", 0)),
                    h=float(bar_json.get("h", 0)),
                    l=float(bar_json.get("l", 0)),
                    c=float(bar_json.get("c", 0)),
                    v=int(bar_json.get("v", 0)),
                ),
                i1=I1Indicators(
                    **{k: v for k, v in parse_jsonb(row["i1"], default={}).items() if v is not None}
                ),
                i2=I2Events(
                    **{k: v for k, v in parse_jsonb(row["i2"], default={}).items() if v is not None}
                ),
                i3=I3Structure(
                    **{k: v for k, v in parse_jsonb(row["i3"], default={}).items() if v is not None}
                ),
                i4=I4Context(
                    **{k: v for k, v in parse_jsonb(row["i4"], default={}).items() if v is not None}
                ),
                i5=I5Patterns(
                    **{k: v for k, v in parse_jsonb(row["i5"], default={}).items() if v is not None}
                ),
                smc=SMCContext(
                    **{
                        k: v
                        for k, v in parse_jsonb(row["smc"], default={}).items()
                        if v is not None
                    }
                ),
                i6=I6Confluence(
                    **{k: v for k, v in parse_jsonb(row["i6"], default={}).items() if v is not None}
                ),
                bar_close_ts=row.get("bar_close_ts"),
                i1_computed_at=row.get("i1_computed_at"),
                computed_at=row.get("computed_at") or datetime.now(UTC),
            )
            await self._producer.publish(
                topic_intelligence(self._settings.env_name),
                {"event": event.model_dump_json()},
                key=message_key(symbol, tf),
            )
        except (ValidationError, Exception) as e:
            self.logger.warning("Seed republish skipped", symbol=symbol, tf=tf, error=str(e))

    # ---------------------------------------------------------------------------
    # Per-bar ingestion + HTF bar publishing
    # ---------------------------------------------------------------------------

    async def _on_bars(self, messages: list[BarMessage]) -> None:
        """Process a batch of incoming 1m bar messages concurrently."""
        async def _bounded(bar: BarMessage) -> None:
            async with self._sem:
                await self._process_bar(bar)

        await asyncio.gather(*[_bounded(b) for b in messages], return_exceptions=True)

    async def _process_bar(self, bar: BarMessage) -> None:
        """Core per-bar processing: gap detection → BarHistory → pipeline (if warm).

        Each bar arriving on either topic_market_bars (1m) or topic_market_bars_htf
        triggers an independent I1-I6 pipeline run (per D-02, D-03).
        BarAccumulator is handled by BarAggregatorComputeAgent — FCA is a pure consumer.
        """
        t0 = time.perf_counter()

        # 1. Gap detection: check if previous bar ts is stale
        key = f"{bar.symbol}:{bar.tf}"
        prev_ts = self._last_bar_ts.get(key)
        if prev_ts is not None:
            tf_seconds = TF_SECONDS.get(bar.tf, 60)
            # tolerance: 1.5x expected interval handles minor delays
            if (bar.ts.timestamp() - prev_ts) > tf_seconds * 1.5:
                bar = bar.model_copy(update={"gap_preceding": True})
        self._last_bar_ts[key] = bar.ts.timestamp()

        # 2. Append to BarHistory
        self._bar_history.append(bar)

        # 3. Run I1-I6 pipeline if warm (each bar independently — per D-02)
        if not self._bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
            return
        try:
            await self._run_pipeline(bar, t0)
        except Exception as e:
            self.logger.error(
                "Pipeline error",
                symbol=bar.symbol,
                tf=bar.tf,
                error=str(e),
            )
            self._pipeline_errors.inc()

    # ---------------------------------------------------------------------------
    # I1-I6 pipeline execution
    # ---------------------------------------------------------------------------

    async def _run_pipeline(self, bar: BarMessage, t0: float) -> None:
        """Run I1→I2→I3→I4→I5→SMC→I6, construct IntelligenceEvent, publish."""
        symbol = bar.symbol
        tf = bar.tf
        key = f"{symbol}:{tf}"

        # Build frames dict with bar history DataFrame and cross-TF data
        main_df = self._bar_history.to_dataframe(symbol, tf)
        frames: dict[str, Any] = {"main": main_df}

        # Inject cross-timeframe bar history and cached intelligence
        tf_hierarchy = _STANDARD_TFS
        for other_tf in tf_hierarchy:
            if other_tf == tf:
                continue
            other_key = f"{symbol}:{other_tf}"
            other_deque = self._bar_history.get(symbol, other_tf)
            if len(other_deque) >= 50:
                frames[f"tf_{other_tf}"] = self._bar_history.to_dataframe(symbol, other_tf)
            cached_evt = self._last_events.get(other_key)
            if cached_evt:
                # Flatten nested tier structure for CrossTimeframeConfluencePlugin
                # which expects top-level keys like trend_direction, swing_pattern, etc.
                intel_dict = cached_evt.model_dump()
                flattened = {}
                for tier_name, tier_data in intel_dict.items():
                    if tier_name in ["i1", "i2", "i3", "i4", "i5", "smc", "i6"] and isinstance(tier_data, dict):
                        flattened.update(tier_data)
                    else:
                        flattened[tier_name] = tier_data
                frames[f"intel_{other_tf}"] = flattened

        instrument = self._instrument_map.get(symbol)
        if instrument:
            frames["__instrument__"] = instrument

        # === I1: Technical indicators ===
        # Inject previous bar's I1 features for I2 crossover detection
        frames["prev_features"] = self._prev_i1_features.get(key, {})

        # Phase 46: Inject cross-asset frames for EQ_INDEX symbols (per D-12, D-13)
        if resolve_eq_index_base(symbol) is not None:
            frames["cross_asset"] = self._cross_asset_cache.get(tf, {"ready": False})
            frames["cross_asset_5m"] = self._cross_asset_cache.get("5m", {"ready": False})

        # Phase 46: Inject VIX context for ALL symbols (per D-04, D-11)
        if self._vix_symbol:
            vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
            frames["vix"] = compute_vix_context(vix_deque)
        else:
            frames["vix"] = {"ready": False}

        i1_result = await self._run_i1(frames, symbol, tf)
        frames["features"] = dict(i1_result)

        # Store I1 features for next bar's prev_features injection
        self._prev_i1_features[key] = dict(i1_result)

        # === I2-I6: Analysis pipeline ===
        tiered = await self._run_analysis_pipeline(symbol, tf, frames)

        if not tiered:
            return

        # Compute pipeline latency
        pipeline_latency_ms = (time.perf_counter() - t0) * 1000
        self._pipeline_latency_histogram.set(pipeline_latency_ms)

        # Construct and publish IntelligenceEvent
        await self._publish_intelligence(bar, i1_result, tiered, pipeline_latency_ms)

        self._bars_processed.inc()
        self.logger.debug(
            "Pipeline complete",
            symbol=symbol,
            tf=tf,
            latency_ms=round(pipeline_latency_ms, 2),
            outputs=len(tiered.get("flat", {})),
        )

    async def _run_i1(
        self, frames: dict[str, Any], symbol: str, tf: str
    ) -> dict[str, Any]:
        """Run all I1 plugins and return merged feature dict."""
        features: dict[str, Any] = {}
        instrument = self._instrument_map.get(symbol)

        for plugin_name in TIER_I1:
            t0 = time.time()
            try:
                p = self._plugin_cache[plugin_name]
                if should_skip_plugin(p, instrument, self.plugin_skipped_total, plugin_name):
                    continue
                state_key = (plugin_name, symbol, tf)
                lock = self._get_state_lock(state_key)

                def _sync_compute_i1(
                    _p=p, _lock=lock, _key=state_key, _frames=frames
                ) -> dict:
                    with _lock:
                        _p._state = self._plugin_states.setdefault(_key, {})
                        _out = _p.compute_full(_frames)
                        # CRITICAL: Write plugin _state back after compute_full().
                        # GARCH/HMM fully reassign _state — omitting this causes stale state.
                        self._plugin_states[_key] = _p._state
                        return _out

                out = await asyncio.to_thread(_sync_compute_i1)
                features.update(out)
            except Exception as exc:
                self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(exc))
                record_plugin_execution(plugin_name, symbol, tf, time.time() - t0, "error", "I1")
            else:
                self._plugin_call_counts[(plugin_name, "I1")] += 1
                if self._plugin_call_counts[(plugin_name, "I1")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    record_plugin_execution(
                        plugin_name, symbol, tf, time.time() - t0, "success", "I1"
                    )
        return features

    async def _run_analysis_pipeline(
        self, symbol: str, tf: str, frames: dict[str, Any]
    ) -> dict[str, Any]:
        """Run I2→I3→I4→I5→SMC→I6 with async-safe per-key state locking.

        Returns tiered dict with keys: i2, i3, i4, i5, smc, i6, flat.
        """
        features: dict[str, Any] = dict(frames.get("features", {}))
        frames["features"] = features

        instrument = self._instrument_map.get(symbol)

        async def _run_tier(plugins: list[str], tier: str, results: dict[str, Any]) -> None:
            for pname in plugins:
                t0 = time.time()
                try:
                    p = self._plugin_cache[pname]
                    if should_skip_plugin(p, instrument, self.plugin_skipped_total, pname):
                        continue
                    state_key = (pname, symbol, tf)
                    lock = self._get_state_lock(state_key)

                    def _sync_compute(
                        _p=p, _lock=lock, _key=state_key, _frames=frames
                    ) -> dict:
                        with _lock:
                            _p._state = self._plugin_states.setdefault(_key, {})
                            _out = _p.compute_full(_frames)
                            # CRITICAL: Write plugin _state back after compute_full().
                            # GARCH/HMM fully reassign _state — omitting this causes stale state.
                            self._plugin_states[_key] = _p._state
                            return _out

                    out = await asyncio.to_thread(_sync_compute)
                    results.update(out)
                except Exception as exc:
                    self.logger.warning(
                        f"{tier} plugin failed", plugin=pname, error=str(exc)
                    )
                    record_plugin_execution(
                        pname, symbol, tf, time.time() - t0, "error", tier
                    )
                else:
                    self._plugin_call_counts[(pname, tier)] += 1
                    if (
                        self._plugin_call_counts[(pname, tier)] % PLUGIN_METRICS_SAMPLE_RATE == 0
                    ):
                        record_plugin_execution(
                            pname, symbol, tf, time.time() - t0, "success", tier
                        )

        # I2: Composite events — on I1 features
        i2_results: dict[str, Any] = {}
        await _run_tier(TIER_I2, "I2", i2_results)
        features.update(i2_results)

        # I3: Market structure
        i3_results: dict[str, Any] = {}
        await _run_tier(TIER_I3, "I3", i3_results)
        features.update(i3_results)

        # I4: Context classification
        i4_results: dict[str, Any] = {}
        await _run_tier(TIER_I4, "I4", i4_results)
        features.update(i4_results)

        # I5: Pattern detection
        i5_results: dict[str, Any] = {}
        await _run_tier(TIER_I5, "I5", i5_results)
        features.update(i5_results)

        # SMC: Smart Money Concepts
        smc_results: dict[str, Any] = {}
        await _run_tier(TIER_SMC, "SMC", smc_results)
        # Rename SMC's trend_direction to avoid collision with I3's trend_direction in flat dict
        if "trend_direction" in smc_results:
            smc_results["smc_trend_direction"] = smc_results.pop("trend_direction")
        features.update(smc_results)

        # I6: Cross-timeframe confluence
        i6_results: dict[str, Any] = {}
        await _run_tier(TIER_I6, "I6", i6_results)

        flat = {
            **i2_results,
            **i3_results,
            **i4_results,
            **i5_results,
            **smc_results,
            **i6_results,
        }
        return {
            "i2": i2_results,
            "i3": i3_results,
            "i4": i4_results,
            "i5": i5_results,
            "smc": smc_results,
            "i6": i6_results,
            "flat": flat,
        }

    # ---------------------------------------------------------------------------
    # IntelligenceEvent publish
    # ---------------------------------------------------------------------------

    async def _publish_intelligence(
        self,
        bar: BarMessage,
        i1_features: dict[str, Any],
        tiered: dict[str, Any],
        pipeline_latency_ms: float,
    ) -> None:
        """Construct and publish IntelligenceEvent to development.intelligence."""
        symbol = bar.symbol
        tf = bar.tf

        try:
            event = IntelligenceEvent(
                ts=bar.ts,
                symbol=symbol,
                tf=tf,
                bar=OHLCVBar(
                    o=bar.open,
                    h=bar.high,
                    l=bar.low,
                    c=bar.close,
                    v=bar.volume,
                ),
                i1=I1Indicators(**{k: v for k, v in i1_features.items() if v is not None}),
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
        except ValidationError as e:
            self.logger.error(
                "IntelligenceEvent validation failed — event dropped",
                symbol=symbol,
                tf=tf,
                error=str(e),
            )
            self._pipeline_errors.inc()
            return

        key = f"{symbol}:{tf}"
        self._last_events[key] = event

        now = datetime.now(UTC)
        msg_key = message_key(symbol, tf)
        event_dict = event.model_dump()

        try:
            feature_journal = IntelligenceJournal(
                ts=now,
                sid=f"feat_{symbol}_{tf}",
                payload=event_dict,
                provenance=ProvenanceChain(
                    origin_ts=now,
                    pipeline_id=f"feat_{symbol}_{tf}",
                    plugin_stack=["feature_pipeline_service"],
                    compute_budget_ms=0.0,
                ),
            )
            await self._producer.publish(
                topic_intelligence_journal(self._settings.env_name),
                feature_journal.model_dump(mode="json"),
                key=msg_key,
            )
        except Exception as e:
            self.logger.warning("Feature journal publish failed", error=str(e))

        await self._producer.publish(
            topic_intelligence(self._settings.env_name),
            {"event": event.model_dump_json()},
            key=msg_key,
        )

    # ---------------------------------------------------------------------------
    # Roll event handling
    # ---------------------------------------------------------------------------

    async def _handle_roll_event(self, event: dict) -> None:
        """Migrate BarHistory and I1 plugin state on futures roll.

        - Migrates bar history deques via BarHistory.migrate_symbol
        - Adjusts price-sensitive plugin state by roll_gap
        - Volume-neutral plugin state copied verbatim
        - Old-symbol state keys deleted after migration
        """
        result = parse_roll_event(event, self.logger)
        if result is None:
            return

        old_symbol, new_symbol = result
        roll_gap: float = float(event.get("roll_gap", 0.0))

        # Migrate BarHistory
        self._bar_history.migrate_symbol(old_symbol, new_symbol)

        # Migrate plugin states — same as indicator_service pattern
        total_migrated = 0
        for tf in _STANDARD_TFS:
            old_plugin_keys = [
                k for k in self._plugin_states
                if k[1] == old_symbol and k[2] == tf
            ]
            if not old_plugin_keys:
                continue

            migrated_count = 0
            for key in old_plugin_keys:
                plugin_name = key[0]
                old_state = self._plugin_states[key]
                new_key = (plugin_name, new_symbol, tf)
                if plugin_name in PRICE_SENSITIVE_PLUGINS:
                    new_state = _adjust_price_state(old_state, roll_gap)
                else:
                    new_state = (
                        copy.deepcopy(old_state) if isinstance(old_state, dict) else old_state
                    )
                self._plugin_states[new_key] = new_state
                del self._plugin_states[key]
                self._plugin_states_locks.pop(key, None)
                migrated_count += 1

            total_migrated += migrated_count
            self.logger.info(
                "roll_plugin_state_migrated",
                old=f"{old_symbol}:{tf}",
                new=f"{new_symbol}:{tf}",
                gap=roll_gap,
                plugins=migrated_count,
            )

        # Migrate prev_i1_features cache
        for tf in _STANDARD_TFS:
            old_key = f"{old_symbol}:{tf}"
            new_key = f"{new_symbol}:{tf}"
            if old_key in self._prev_i1_features:
                self._prev_i1_features[new_key] = self._prev_i1_features.pop(old_key)
            if old_key in self._last_bar_ts:
                self._last_bar_ts[new_key] = self._last_bar_ts.pop(old_key)

        self.logger.info(
            "roll_event_handled",
            old=old_symbol,
            new=new_symbol,
            gap=roll_gap,
            adjusted_plugins=total_migrated,
        )

    # ---------------------------------------------------------------------------
    # Tick buffer
    # ---------------------------------------------------------------------------

    def _process_tick(self, symbol: str, payload: dict) -> None:
        """Buffer incoming ticks per symbol — flushed at bar close. Capped at tick_buffer_max."""
        buf = self._tick_buffers[symbol]
        if len(buf) >= self._tick_buffer_max:
            del buf[: self._tick_buffer_max // 2]
            self.logger.warning("tick_buffer_overflow", symbol=symbol)
        buf.append(payload)

    async def _process_tick_data(self) -> None:
        """Consume ticks from market.ticks topic and buffer per symbol."""
        assert self._tick_consumer is not None
        async for _topic, _key, payload in self._tick_consumer.messages():
            try:
                symbol = (payload.get("symbol") or "").strip()
                if not symbol:
                    continue
                self._process_tick(symbol, payload)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning("tick_process_error", error=str(e))

    # ---------------------------------------------------------------------------
    # Main consumption loop
    # ---------------------------------------------------------------------------

    async def _process_market_data(self) -> None:
        """Consume 1m bars (and optionally system events) from Kafka."""
        assert self._consumer is not None
        env = self._settings.env_name
        _sys_events_topic = topic_system_events(env)
        # Phase 46: Route cross_asset messages to cache
        _cross_asset_topic = topic_cross_asset(env)

        async for topic, key, payload in self._consumer.messages():
            if self.shutdown_requested:
                break
            try:
                # Route system.events to roll handler
                if topic == _sys_events_topic:
                    await self._handle_roll_event(payload)
                    await self._consumer.commit()
                    continue

                # Phase 46: Cache cross-asset snapshot by timeframe
                if topic == _cross_asset_topic:
                    try:
                        tf = payload.get("tf", "")
                        if tf in CROSS_ASSET_VALID_TFS and payload.get("ready"):
                            self._cross_asset_cache[tf] = payload
                        await self._consumer.commit()
                    except Exception as _xa_err:
                        self.logger.warning("cross_asset_parse_failed", error=str(_xa_err))
                    continue

                # Parse BarMessage from Kafka payload
                try:
                    bar = BarMessage.model_validate(payload)
                except Exception:
                    # Fallback: parse from flat dict fields (legacy format)
                    if key:
                        parts = key.split(":", 1)
                        symbol = parts[0] if parts else payload.get("symbol", "")
                        tf = parts[1] if len(parts) == 2 else payload.get("timeframe", "1m")
                    else:
                        symbol = payload.get("symbol", "")
                        tf = payload.get("timeframe", "1m")
                    if not symbol or not tf:
                        continue
                    try:
                        ts_raw = payload.get("timestamp") or payload.get("ts")
                        ts = datetime.fromisoformat(str(ts_raw)) if ts_raw else datetime.now(UTC)
                        bar = BarMessage(
                            ts=ts,
                            symbol=symbol,
                            tf=tf,
                            open=float(payload.get("open", 0)),
                            high=float(payload.get("high", 0)),
                            low=float(payload.get("low", 0)),
                            close=float(payload.get("close", 0)),
                            volume=int(float(payload.get("volume", 0))),
                            source=SOURCE_IBKR_NAMED,
                            session_type=SessionType(payload.get("session_type", "rth")),
                            gap_preceding=bool(payload.get("gap_preceding", False)),
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Bar parse failed", error=str(e), payload=str(payload)[:200]
                        )
                        continue

                await self._process_bar(bar)

                # Explicitly commit after bar is processed
                await self._consumer.commit()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self._pipeline_errors.inc()

    # ---------------------------------------------------------------------------
    # Health monitor
    # ---------------------------------------------------------------------------

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(UTC) - self.start_time).total_seconds())
                self._service_uptime.set(uptime)
                self.logger.info(
                    "Health check",
                    uptime=uptime,
                    symbols=len(self._symbols),
                )
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    # ---------------------------------------------------------------------------
    # Signal handler
    # ---------------------------------------------------------------------------

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    # ---------------------------------------------------------------------------
    # Start / stop
    # ---------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the feature pipeline service."""
        self.logger.info("Starting FeatureComputeAgent", symbols=self._symbols)
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig: self._signal_handler(s, None))

            start_metrics_server(port=9125)

            # 1. DB connect before bar consumption
            if self._db:
                await self._db.initialize()

            # 2. Start Kafka producer before warmup — warmup publishes seeded intelligence
            await self._producer.start()

            # 3. Seed BarHistory from intelligence_features
            await self._seed_bar_history()

            # 4. Build topics list — subscribe to consumer topics only
            # Subscribe to both 1m (market.bars) and HTF (market.bars.htf) topics.
            # HTF bars produced by BarAggregatorComputeAgent — FCA is a pure consumer.
            env = self._settings.env_name
            topics: list[str] = [topic_market_bars(env), topic_market_bars_htf(env)]
            topics.append(topic_system_events(env))
            topics.append(topic_cross_asset(env))

            # 5. Start Kafka consumer subscribed to market.bars + system.events
            self._consumer = KafkaConsumerClient(
                *topics,
                bootstrap_servers=self._settings.kafka_bootstrap_servers,
                group_id="feature_pipeline",
                auto_offset_reset="earliest",
                enable_auto_commit=False,
            )
            await self._consumer.start()

            # 6. Start tick consumer — separate group_id
            self._tick_consumer = KafkaConsumerClient(
                topic_market_ticks(env),
                bootstrap_servers=self._settings.kafka_bootstrap_servers,
                group_id="feature_pipeline_ticks",
                auto_offset_reset="latest",
            )
            await self._tick_consumer.start()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._process_tick_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("FeatureComputeAgent started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start FeatureComputeAgent", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown — drain consumer, flush producer."""
        self.logger.info("Stopping FeatureComputeAgent")
        self.running = False
        self.shutdown_requested = True
        if self._consumer:
            await self._consumer.stop()
        if self._tick_consumer:
            await self._tick_consumer.stop()
        await self._producer.stop()
        self.logger.info("FeatureComputeAgent stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Feature Pipeline Service")
    parser.add_argument("--config", help="Configuration file path")
    _args = parser.parse_args()

    service = FeatureComputeAgent()
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
