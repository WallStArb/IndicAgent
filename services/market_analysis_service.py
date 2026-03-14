#!/usr/bin/env python3
"""
Market Analysis Service — I3/I4/I5/SMC/I6 plugin execution

Consumes the combined OHLCV+I1 messages published by indicator_service
from indicators:SYMBOL:TF, then runs I3 (structure) → I4 (context) →
I5 (pattern) → SMC (smart money) → I6 (confluence) and publishes
combined intelligence results to intelligence:SYMBOL:TF.

I1 is NOT recomputed here — it arrives pre-computed from indicator_service.
This eliminates the triple I1 computation that existed when each service
maintained its own indicator pipeline.
"""

import asyncio
import json
import signal
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import structlog
from pydantic import ValidationError

from services.indicator_service import parse_indicators_message
from src.config.settings import Settings, get_active_contracts
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.database_manager import DatabaseManager
from src.api.utils import parse_jsonb
from src.core.service_utils import (
    PLUGIN_METRICS_SAMPLE_RATE,
    SEED_LOOKBACK_MULTIPLIER,
    TF_SECONDS,
    min_bars_for_tf,
    setup_service_logging,
    should_skip_plugin,
)
from src.core.stream_keys import message_key, topic_indicators, topic_intelligence
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
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
    BAR_TO_INTELLIGENCE_LATENCY,
    MARKET_ANALYSIS_BARS_PROCESSED_LABELED_TOTAL,
    PLUGIN_SKIPPED_TOTAL,
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)


class MarketAnalysisService:
    """Execute I3/I4/I5/SMC/I6 intelligence plugins, consuming I1 from indicators stream."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        self.config = self._load_config(config_file, settings)
        self._setup_logging()

        register_all_plugins()
        for tier_list, tier_name in [
            (TIER_I2, "I2"),
            (TIER_I3, "I3"),
            (TIER_I4, "I4"),
            (TIER_I5, "I5"),
            (TIER_SMC, "SMC"),
            (TIER_I6, "I6"),
        ]:
            registry.validate_tier(tier_list, tier_name)

        # Build plugin reference cache — eliminates per-bar registry lookups
        all_tier_names = TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6
        self._plugin_cache: dict[str, Any] = {n: registry.get_pattern(n) for n in all_tier_names}

        # Per-(plugin, symbol, timeframe) state namespace — prevents cross-symbol state bleed
        self._plugin_states: dict[tuple[str, str, str], dict] = {}
        # Per-key locks for concurrent access protection
        self._plugin_states_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._plugin_call_counts: dict[tuple[str, str], int] = defaultdict(int)

        self.env_name = settings.env_name.strip()

        # Kafka producer/consumer (replaces Redis client)
        self._kafka_producer: KafkaProducerClient = KafkaProducerClient(
            bootstrap_servers=settings.kafka_bootstrap_servers
        )
        self._kafka_consumer: KafkaConsumerClient | None = None

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._prev_i1_features: dict[str, dict[str, Any]] = {}  # key="{symbol}:{tf}"
        self.intelligence_cache: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
        self._df_cache: dict[str, pd.DataFrame | None] = {}
        self._active_symbols: set[str] = set()

        database_url = settings.database_url
        self.db_manager: DatabaseManager | None = (
            DatabaseManager(database_url) if database_url else None
        )

        # Build instrument map for asset-class guard
        self._instrument_map: dict[str, Any] = {inst.symbol: inst for inst in settings.contracts}

        self.bars_processed_total = counter(
            "market_analysis_bars_processed_total",
            "Total indicator messages processed by market analysis service",
        )
        self.calculations_total = counter(
            "market_analysis_calculations_total",
            "Total intelligence calculations performed",
        )
        self.calculation_duration_ms = gauge(
            "market_analysis_calculation_duration_ms",
            "Last calculation duration in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "market_analysis_service_uptime_seconds",
            "Market analysis service uptime in seconds",
        )
        self.active_symbols_count = gauge(
            "market_analysis_active_symbols_count",
            "Number of active symbols being processed",
        )
        self.error_count_total = counter(
            "market_analysis_errors_total",
            "Total errors encountered by market analysis service",
        )

        self.plugin_skipped_total = PLUGIN_SKIPPED_TOTAL
        self.bars_processed_labeled_total = MARKET_ANALYSIS_BARS_PROCESSED_LABELED_TOTAL

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _get_state_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        """Get or create a lock for given state key."""
        return self._plugin_states_locks.setdefault(key, asyncio.Lock())

    def _load_config(self, config_file: str | None, settings: Settings) -> dict[str, Any]:
        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_contracts(settings),
                # 4h and 1d intentionally excluded: day-trading focus. 4h bars close 4×/day,
                # 1d once/day — signal latency too high for intraday entries. Extend in a future
                # phase if swing-trading scope is added.
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
                "min_history_bars": 120,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/market_analysis_service.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _run_analysis_pipeline(
        self, symbol: str, timeframe: str, frames: dict[str, Any]
    ) -> dict[str, Any]:
        """Run I3→I4→I5→SMC→I6 with async-safe per-key state locking.

        Returns tiered dict with keys: i3, i4, i5, smc, i6, flat.
        - i3/i4/i5/smc/i6 — per-tier result dicts for IntelligenceEvent construction
        - flat — merged dict for backward-compat (intelligence_cache, cross-tier feature sharing)
        """
        features: dict[str, Any] = dict(frames.get("features", {}))
        frames["features"] = features

        instrument = self._instrument_map.get(symbol)
        if instrument:
            frames["__instrument__"] = instrument

        async def _run_tier(plugins: list[str], tier: str, results: dict[str, Any]) -> None:
            for pname in plugins:
                t0 = time.time()
                try:
                    p = self._plugin_cache[pname]
                    if should_skip_plugin(p, instrument, self.plugin_skipped_total, pname):
                        continue
                    state_key = (pname, symbol, timeframe)
                    async with self._get_state_lock(state_key):
                        p._state = self._plugin_states.setdefault(state_key, {})
                        out = p.compute_full(frames)
                        self._plugin_states[state_key] = p._state  # capture full reassignments
                    results.update(out)
                except Exception as exc:
                    self.logger.warning(f"{tier} plugin failed", plugin=pname, error=str(exc))
                    record_plugin_execution(
                        pname, symbol, timeframe, time.time() - t0, "error", tier
                    )
                else:
                    self._plugin_call_counts[(pname, tier)] += 1
                    if self._plugin_call_counts[(pname, tier)] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                        record_plugin_execution(
                            pname, symbol, timeframe, time.time() - t0, "success", tier
                        )

        # I2: Composite indicator events (crossovers, extremes) — runs on I1 features
        i2_results: dict[str, Any] = {}
        await _run_tier(TIER_I2, "I2", i2_results)
        features.update(i2_results)

        i3_results: dict[str, Any] = {}
        await _run_tier(TIER_I3, "I3", i3_results)
        features.update(i3_results)

        i4_results: dict[str, Any] = {}
        await _run_tier(TIER_I4, "I4", i4_results)
        features.update(i4_results)

        i5_results: dict[str, Any] = {}
        await _run_tier(TIER_I5, "I5", i5_results)
        features.update(i5_results)

        smc_results: dict[str, Any] = {}
        await _run_tier(TIER_SMC, "SMC", smc_results)
        # Rename SMC's trend_direction to avoid collision with I3's trend_direction in flat dict
        if "trend_direction" in smc_results:
            smc_results["smc_trend_direction"] = smc_results.pop("trend_direction")
        features.update(smc_results)

        i6_results: dict[str, Any] = {}
        await _run_tier(TIER_I6, "I6", i6_results)

        flat = {**i2_results, **i3_results, **i4_results, **i5_results, **smc_results, **i6_results}
        self.intelligence_cache[symbol][timeframe] = flat
        return {
            "i2": i2_results,
            "i3": i3_results,
            "i4": i4_results,
            "i5": i5_results,
            "smc": smc_results,
            "i6": i6_results,
            "flat": flat,
        }

    def _min_bars_for_tf(self, timeframe: str) -> int:
        return min_bars_for_tf(timeframe)

    def _get_df(self, key: str) -> "pd.DataFrame":
        if self._df_cache.get(key) is None:
            self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
        return self._df_cache[key]

    async def _calculate_intelligence(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        i1_features: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the I3→I6 pipeline. Returns tiered dict (i3/i4/i5/smc/i6/flat) or {}."""
        key = f"{symbol}:{timeframe}"
        history = self.bar_history[key]
        min_bars = self._min_bars_for_tf(timeframe)

        if len(history) < min_bars:
            return {}

        frames: dict[str, Any] = {"main": self._get_df(key)}

        # Inject cross-timeframe bar history and cached intelligence
        tf_hierarchy = ["1m", "5m", "15m", "1h"]
        for other_tf in tf_hierarchy:
            if other_tf == timeframe:
                continue
            other_key = f"{symbol}:{other_tf}"
            if other_key in self.bar_history and len(self.bar_history[other_key]) >= 50:
                frames[f"tf_{other_tf}"] = self._get_df(other_key)
            cached = self.intelligence_cache.get(symbol, {}).get(other_tf)
            if cached:
                frames[f"intel_{other_tf}"] = cached

        # I1 features arrive pre-computed from indicator_service
        frames["features"] = dict(i1_features)

        # Inject previous bar's I1 features for I2 crossover detection
        prev_key = f"{symbol}:{timeframe}"
        if prev_key in self._prev_i1_features:
            frames["prev_features"] = self._prev_i1_features[prev_key]
        self._prev_i1_features[prev_key] = dict(i1_features)

        tiered = await self._run_analysis_pipeline(symbol, timeframe, frames)
        self.calculations_total.inc()
        return tiered

    def _get_field(self, fields: dict, key: str) -> str:
        """Get a field value from either str-keyed (Kafka) or bytes-keyed dict."""
        val = fields.get(key) or fields.get(key.encode())
        if val is None:
            return ""
        return val.decode() if isinstance(val, bytes) else str(val)

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict,
        stream_name: str = "",
        message_id: bytes | None = None,
    ) -> bool:
        try:
            bar_ts = datetime.fromisoformat(self._get_field(fields, "timestamp"))
            bar_close_ts_str = self._get_field(fields, "bar_close_ts") or None
            i1_computed_at_str = self._get_field(fields, "i1_computed_at") or None
            bar_data, i1_features = parse_indicators_message(fields)
            bar_data["timestamp"] = bar_ts

            key = f"{symbol}:{timeframe}"
            history = self.bar_history[key]

            # Optimization: Only invalidate cache when deque maxlen overflow occurs.
            # Appending within capacity does not invalidate the cached DataFrame.
            # Overflow happens when deque is already at maxlen before append —
            # the deque then silently removes the oldest bar and adds the new one.
            len_before = len(history)
            history.append(bar_data)
            cache_invalidated = len_before == history.maxlen  # True if overflow occurred

            if cache_invalidated:
                self._df_cache[key] = None

            calc_start = time.time()
            tiered = await self._calculate_intelligence(symbol, timeframe, bar_ts, i1_features)
            calc_ms = (time.time() - calc_start) * 1000

            if tiered:
                await self._publish_intelligence(
                    symbol,
                    timeframe,
                    tiered,
                    bar_ts,
                    bar_data,
                    i1_features,
                    bar_close_ts_str=bar_close_ts_str,
                    i1_computed_at_str=i1_computed_at_str,
                )

            self.bars_processed_total.inc()
            self.bars_processed_labeled_total.labels(symbol=symbol, tf=timeframe).inc()
            self._active_symbols.add(symbol)
            self.calculation_duration_ms.set(calc_ms)

            self.logger.debug(
                "Bar processed",
                symbol=symbol,
                timeframe=timeframe,
                outputs=len(tiered.get("flat", {})) if tiered else 0,
                calc_ms=round(calc_ms, 2),
            )
            return True

        except Exception as e:
            self.logger.error(
                "Error processing bar",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            return False

    async def _publish_intelligence(
        self,
        symbol: str,
        timeframe: str,
        tiered: dict[str, Any],
        timestamp: datetime,
        bar_data: dict[str, Any] | None = None,
        i1_features: dict[str, Any] | None = None,
        bar_close_ts_str: str | None = None,
        i1_computed_at_str: str | None = None,
    ) -> None:
        """Publish a validated IntelligenceEvent to the intelligence: Redis stream.

        Emits a single {"event": "<json>"} field — not flat str(v) k/v pairs.
        Drops the event on ValidationError (malformed plugin output) after logging.
        """
        bar_data = bar_data or {}
        i1_features = i1_features or {}

        bar_close_ts_dt: datetime | None = None
        if bar_close_ts_str:
            try:
                bar_close_ts_dt = datetime.fromisoformat(bar_close_ts_str)
            except (ValueError, TypeError):
                pass

        i1_computed_at_dt: datetime | None = None
        if i1_computed_at_str:
            try:
                i1_computed_at_dt = datetime.fromisoformat(i1_computed_at_str)
            except (ValueError, TypeError):
                pass

        try:
            event = IntelligenceEvent(
                ts=timestamp,
                symbol=symbol,
                tf=timeframe,
                bar=OHLCVBar(
                    o=float(bar_data.get("open", 0.0)),
                    h=float(bar_data.get("high", 0.0)),
                    l=float(bar_data.get("low", 0.0)),
                    c=float(bar_data.get("close", 0.0)),
                    v=int(bar_data.get("volume", 0)),
                ),
                i1=I1Indicators(**{k: v for k, v in i1_features.items() if v is not None}),
                i2=I2Events(**{k: v for k, v in tiered.get("i2", {}).items() if v is not None}),
                i3=I3Structure(**tiered.get("i3", {})),
                i4=I4Context(**tiered.get("i4", {})),
                i5=I5Patterns(**tiered.get("i5", {})),
                smc=SMCContext(**tiered.get("smc", {})),
                i6=I6Confluence(**tiered.get("i6", {})),
                source="live",
                bar_close_ts=bar_close_ts_dt,
                i1_computed_at=i1_computed_at_dt,
                computed_at=datetime.now(UTC),
            )

            # Emit bar-to-intelligence latency for live events with known close time
            if bar_close_ts_dt is not None:
                BAR_TO_INTELLIGENCE_LATENCY.labels(symbol=symbol, tf=timeframe).observe(
                    (event.computed_at - bar_close_ts_dt).total_seconds()
                )
        except ValidationError as e:
            self.logger.error(
                "IntelligenceEvent validation failed — event dropped",
                symbol=symbol,
                tf=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            return  # Do NOT publish malformed events

        await self._kafka_producer.publish(
            topic_intelligence(self.env_name),
            {"event": event.model_dump_json()},
            key=message_key(symbol, timeframe),
        )

    async def _warmup_bar_history(self) -> None:
        """Seed bar_history from intelligence_features and publish last-known intelligence.

        Queries intelligence_features for recent bars per (symbol, tf), populates
        bar_history so the service is immediately ready to process live bars, then
        re-publishes the stored IntelligenceEvent for each so the dashboard shows
        current state without waiting for the next live bar.

        Falls back silently if DB unavailable.
        """
        if not self.db_manager:
            self.logger.warning("DB seed skipped — no db_manager")
            return

        try:
            await self.db_manager.initialize()
        except Exception as e:
            self.logger.warning("DB init failed — skipping seed", error=str(e))
            return

        active_contracts = get_active_contracts()
        timeframes = self.config["service"]["timeframes"]
        seeded_bars = 0
        published_events = 0

        sem = asyncio.Semaphore(8)

        async def _seed_one(symbol: str, tf: str) -> None:
            nonlocal seeded_bars, published_events
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER
                try:
                    rows = await self.db_manager.execute_query(  # type: ignore[union-attr]
                        f"""
                        SELECT ts, bar, i1, i2, i3, i4, i5, smc, i6,
                               bar_close_ts, i1_computed_at, computed_at
                        FROM intelligence_features
                        WHERE symbol = $1 AND tf = $2
                          AND ts > NOW() - INTERVAL '{lookback_secs} seconds'
                        ORDER BY ts DESC
                        LIMIT {min_bars}
                        """,
                        symbol,
                        tf,
                    )
                except Exception as e:
                    self.logger.warning("Seed query failed", symbol=symbol, tf=tf, error=str(e))
                    return

                if not rows:
                    return

                key = f"{symbol}:{tf}"
                # Insert oldest→newest into bar_history
                for row in reversed(rows):
                    bar_json = row["bar"]
                    try:
                        self.bar_history[key].append(
                            {
                                "open": float(bar_json.get("o", 0)),
                                "high": float(bar_json.get("h", 0)),
                                "low": float(bar_json.get("l", 0)),
                                "close": float(bar_json.get("c", 0)),
                                "volume": int(bar_json.get("v", 0)),
                                "timestamp": row["ts"],
                            }
                        )
                        seeded_bars += 1
                    except Exception:
                        pass

                # Re-publish the most recent stored IntelligenceEvent
                latest = rows[0]  # rows are DESC, so first = newest
                try:
                    bar_json = parse_jsonb(latest["bar"], default={})
                    event = IntelligenceEvent(
                        ts=latest["ts"],
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
                        i1=I1Indicators(**{k: v for k, v in parse_jsonb(latest["i1"], default={}).items() if v is not None}),
                        i2=I2Events(**{k: v for k, v in parse_jsonb(latest["i2"], default={}).items() if v is not None}),
                        i3=I3Structure(**{k: v for k, v in parse_jsonb(latest["i3"], default={}).items() if v is not None}),
                        i4=I4Context(**{k: v for k, v in parse_jsonb(latest["i4"], default={}).items() if v is not None}),
                        i5=I5Patterns(**{k: v for k, v in parse_jsonb(latest["i5"], default={}).items() if v is not None}),
                        smc=SMCContext(**{k: v for k, v in parse_jsonb(latest["smc"], default={}).items() if v is not None}),
                        i6=I6Confluence(**{k: v for k, v in parse_jsonb(latest["i6"], default={}).items() if v is not None}),
                        bar_close_ts=latest["bar_close_ts"],
                        i1_computed_at=latest["i1_computed_at"],
                        computed_at=latest["computed_at"],
                    )
                    await self._kafka_producer.publish(
                        topic_intelligence(self.env_name),
                        {"event": event.model_dump_json()},
                        key=message_key(symbol, tf),
                    )
                    published_events += 1
                except Exception as e:
                    self.logger.warning(
                        "Seed publish failed", symbol=symbol, tf=tf, error=str(e)
                    )

        tasks = [_seed_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await asyncio.gather(*tasks)

        self.logger.info(
            "Seeded bar_history and published intelligence",
            seeded_bars=seeded_bars,
            published_events=published_events,
        )

    async def _process_market_data(self) -> None:
        """Consume indicator messages from Kafka and run analysis pipeline."""
        assert self._kafka_consumer is not None
        async for topic, key, payload in self._kafka_consumer.messages():
            if self.shutdown_requested:
                break
            try:
                # Extract symbol and timeframe from message key (e.g., "ES:1m")
                if key:
                    parts = key.split(":", 1)
                    if len(parts) == 2:
                        symbol, timeframe = parts[0], parts[1]
                    else:
                        symbol = parts[0]
                        timeframe = payload.get("timeframe", "")
                else:
                    symbol = payload.get("symbol", "")
                    timeframe = payload.get("timeframe", "")

                if not symbol or not timeframe:
                    continue

                await self._process_single_bar(symbol, timeframe, payload)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now() - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                self.active_symbols_count.set(len(self._active_symbols))
                self.logger.info(
                    "Health check",
                    uptime=uptime,
                    active_symbols=len(self._active_symbols),
                )
                await asyncio.sleep(self.config["service"]["health_check_interval"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def start(self) -> None:
        self.logger.info("Starting Market Analysis Service", config=self.config["service"])
        try:
            start_metrics_server(port=self.config.get("metrics_port", 9114))

            # Start Kafka producer before warmup — warmup publishes seeded intelligence
            await self._kafka_producer.start()
            await self._warmup_bar_history()

            # Start Kafka consumer subscribed to indicators topic
            self._kafka_consumer = KafkaConsumerClient(
                topic_indicators(self.env_name),
                bootstrap_servers=self.config.get(
                    "kafka_bootstrap_servers",
                    Settings().kafka_bootstrap_servers,
                ),
                group_id="market_analysis",
                auto_offset_reset="latest",
            )
            await self._kafka_consumer.start()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Market Analysis Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start market analysis service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Market Analysis Service")
        self.running = False
        self.shutdown_requested = True
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        await self._kafka_producer.stop()
        self.logger.info("Market Analysis Service stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Market Analysis Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    service = MarketAnalysisService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
