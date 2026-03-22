#!/usr/bin/env python3
"""
Indicator Service — I1 technical indicator computation

Reads market bars from Redis Streams, runs all 23 I1 plugins via the
plugin registry, and publishes ONE combined OHLCV+indicators message per
bar to indicators:SYMBOL:TF. Downstream services consume this single
message — no coordination across multiple indicator messages needed.

Replaces: indicators_processor_service.py + indicators_enhanced_service.py
"""

import asyncio
import json
import signal
import sys
import time
from collections import OrderedDict, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import structlog

from src.config.settings import Settings, get_active_contracts, get_active_symbols
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.plugin_validator import PluginValidator
from src.core.service_utils import (
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
    topic_indicators,
    topic_market_bars,
    topic_market_bars_htf,
    topic_market_ticks,
    topic_system_events,
)
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I1, register_all_plugins
from src.observability.metrics import (
    BAR_TO_I1_LATENCY,
    INDICATOR_BARS_PROCESSED_LABELED_TOTAL,
    PLUGIN_SKIPPED_TOTAL,
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# I1 plugin names — imported from register_plugins (single source of truth)
I1_PLUGINS = TIER_I1

_OHLCV_FIELDS = frozenset(
    {
        "timestamp",
        "symbol",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "bar_close_ts",
        "i1_computed_at",
    }
)


# I1 plugins that track absolute price levels — must be adjusted by roll_gap on roll.
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

    The original *state* dict is never mutated.
    """
    result: dict = {}
    for k, v in state.items():
        if isinstance(v, float):
            result[k] = v + roll_gap
        elif isinstance(v, int) and not isinstance(v, bool):
            result[k] = v + roll_gap
        elif isinstance(v, list):
            adjusted_list = []
            for item in v:
                if isinstance(item, float):
                    adjusted_list.append(item + roll_gap)
                elif isinstance(item, int) and not isinstance(item, bool):
                    adjusted_list.append(item + roll_gap)
                else:
                    adjusted_list.append(item)
            result[k] = adjusted_list
        elif isinstance(v, dict):
            result[k] = _adjust_price_state(v, roll_gap)
        else:
            result[k] = v
    return result


def build_i1_message(
    bar: dict[str, Any],
    features: dict[str, Any],
    timestamp: datetime,
    symbol: str,
    timeframe: str,
    bar_close_ts: str | None = None,
    source: str = "live",
) -> dict[str, str]:
    """Build a flat string-valued Redis message combining OHLCV and I1 features.

    Only scalar values (str, int, float, bool) are included. Lists and dicts
    are silently dropped — Redis stream fields must be flat strings.

    bar_close_ts is propagated from the incoming market stream message.
    i1_computed_at is added when source=='live' to enable pipeline lag measurement.
    """

    msg: dict[str, str] = {
        "timestamp": timestamp.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "open": str(bar.get("open", "")),
        "high": str(bar.get("high", "")),
        "low": str(bar.get("low", "")),
        "close": str(bar.get("close", "")),
        "volume": str(int(bar.get("volume", 0))),
        "source": source,
    }
    for k, v in features.items():
        if isinstance(v, (str, int, float, bool)):
            msg[k] = str(v)
    if bar_close_ts is not None:
        msg["bar_close_ts"] = bar_close_ts
    if source == "live":
        msg["i1_computed_at"] = datetime.now(UTC).isoformat()
    return msg


def parse_indicators_message(
    fields: dict[bytes, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an indicators stream message into (bar_dict, features_dict).

    bar_dict has float OHLCV values. features_dict has all other numeric
    fields as floats. Used by market_analysis_service to consume this stream.
    """
    bar: dict[str, Any] = {}
    features: dict[str, Any] = {}

    for raw_key, raw_val in fields.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        val = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)

        if key in _OHLCV_FIELDS:
            if key == "open":
                bar["open"] = float(val)
            elif key == "high":
                bar["high"] = float(val)
            elif key == "low":
                bar["low"] = float(val)
            elif key == "close":
                bar["close"] = float(val)
            elif key == "volume":
                bar["volume"] = int(float(val))
        else:
            try:
                features[key] = float(val)
            except (ValueError, TypeError):
                features[key] = val

    return bar, features


class IndicatorService:
    """Compute I1 technical indicators and publish one combined message per bar."""

    _WARMUP_READ_MULTIPLIER: int = 5  # read 5× target to survive duplicate timestamps

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()
        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()
        registry.validate_tier(I1_PLUGINS, "I1")

        # I1 plugin reference cache and per-symbol state isolation
        self._i1_plugin_cache: dict[str, Any] = {n: registry.get_indicator(n) for n in I1_PLUGINS}
        self._i1_plugin_states: dict[tuple[str, str, str], dict] = {}
        # Per-key locks for concurrent access protection
        self._i1_plugin_states_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._i1_call_counts: dict[tuple[str, str], int] = defaultdict(int)

        settings = Settings()
        self.env_name = settings.env_name.strip()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        # Kafka producer/consumer (replaces Redis client)
        self._kafka_producer: KafkaProducerClient = KafkaProducerClient(
            bootstrap_servers=settings.kafka_bootstrap_servers
        )
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._tick_consumer: KafkaConsumerClient | None = None

        # Per-symbol tick buffer — flushed into frames at bar close; capped at 10k ticks
        _TICK_BUFFER_MAX = 10_000
        self._tick_buffer_max: int = _TICK_BUFFER_MAX
        self._tick_buffers: dict[str, list[dict]] = defaultdict(list)

        # DatabaseManager for DB warmup at startup (Phase 26 pattern)
        self.db_manager: DatabaseManager | None = DatabaseManager(settings.database_url)

        # Build instrument map for asset-class guard
        self._instrument_map: dict[str, Any] = {
            inst.symbol: inst for inst in get_active_contracts(settings)
        }

        self.bar_history: dict[str, OrderedDict] = defaultdict(OrderedDict)
        self._bar_history_max = 200
        self._df_cache: dict[str, pd.DataFrame | None] = {}

        self.bars_processed_total = counter(
            "indicator_bars_processed_total",
            "Total market bars processed by indicator service",
        )
        self.service_uptime_seconds = gauge(
            "indicator_service_uptime_seconds",
            "Indicator service uptime in seconds",
        )
        self.error_count_total = counter(
            "indicator_errors_total",
            "Total errors in indicator service",
        )

        self.plugin_skipped_total = PLUGIN_SKIPPED_TOTAL
        self.bars_processed_labeled_total = INDICATOR_BARS_PROCESSED_LABELED_TOTAL

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_symbols(),
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "min_history_bars": 120,
                "processing_interval": 0.1,
            },
            "metrics_port": 9109,
            "logging": {
                "level": "INFO",
                "file": "logs/indicator_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    def _min_bars_for_tf(self, timeframe: str) -> int:
        return min_bars_for_tf(timeframe)

    def _get_state_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        """Get or create a lock for given state key."""
        return self._i1_plugin_states_locks.setdefault(key, asyncio.Lock())

    def _get_df(self, key: str) -> "pd.DataFrame":
        if self._df_cache.get(key) is None:
            self._df_cache[key] = pd.DataFrame(list(self.bar_history[key].values()))
        return self._df_cache[key]

    async def _run_i1_plugins(
        self, frames: dict[str, Any], symbol: str, timeframe: str
    ) -> dict[str, Any]:
        """Run all I1 plugins and return merged feature dict."""
        instrument = self._instrument_map.get(symbol)
        if instrument:
            frames["__instrument__"] = instrument
        features: dict[str, Any] = {}
        for plugin_name in I1_PLUGINS:
            t0 = time.time()
            try:
                p = self._i1_plugin_cache[plugin_name]
                if should_skip_plugin(p, instrument, self.plugin_skipped_total, plugin_name):
                    continue
                state_key = (plugin_name, symbol, timeframe)
                async with self._get_state_lock(state_key):
                    p._state = self._i1_plugin_states.setdefault(state_key, {})
                    result = p.compute_full(frames)
                    # CRITICAL: Write plugin _state back after compute_full().
                    # GARCH/HMM fully reassign _state — failing to write back causes stale state.
                    self._i1_plugin_states[state_key] = p._state
                features.update(result)
            except Exception as e:
                self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(e))
                record_plugin_execution(
                    plugin_name, symbol, timeframe, time.time() - t0, "error", "I1"
                )
            else:
                self._i1_call_counts[(plugin_name, "I1")] += 1
                if self._i1_call_counts[(plugin_name, "I1")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    record_plugin_execution(
                        plugin_name, symbol, timeframe, time.time() - t0, "success", "I1"
                    )
        return features

    def _get_field(self, fields: dict, key: str) -> str:
        """Get a field value from either str-keyed (Kafka) or bytes-keyed (legacy test) dict."""
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
            bar_source = self._get_field(fields, "source")
            bar_close_ts_str = self._get_field(fields, "bar_close_ts") or None
            bar_data = {
                "timestamp": bar_ts,
                "open": float(self._get_field(fields, "open")),
                "high": float(self._get_field(fields, "high")),
                "low": float(self._get_field(fields, "low")),
                "close": float(self._get_field(fields, "close")),
                "volume": int(float(self._get_field(fields, "volume"))),
            }

            key = f"{symbol}:{timeframe}"

            if bar_source == "tick_derived":
                # Tick data drives display only; real IBKR bars drive the pipeline
                return True

            # authoritative bar: update history (dedup by timestamp, O(1))
            # Optimization: Only invalidate DataFrame cache when buffer capacity is
            # exceeded. Appending to OrderedDict does not invalidate the cached
            # DataFrame — the new bar will be included on the next cache rebuild.
            history = self.bar_history[key]
            history[bar_ts.isoformat()] = bar_data

            # Only invalidate cache when oldest bar is evicted (capacity exceeded).
            # Bars arrive one at a time so at most one entry is ever evicted per call.
            if len(history) > self._bar_history_max:
                history.popitem(last=False)
                self._df_cache[key] = None

            min_bars = self._min_bars_for_tf(timeframe)
            if len(self.bar_history[key]) < min_bars:
                return True

            tick_buf = self._tick_buffers.pop(symbol, [])
            frames = {"main": self._get_df(key), "tick_buffer": tick_buf}

            features = await self._run_i1_plugins(frames, symbol, timeframe)

            msg = build_i1_message(
                bar_data,
                features,
                bar_ts,
                symbol,
                timeframe,
                bar_close_ts=bar_close_ts_str,
                source="live",
            )

            # Emit bar-to-I1 latency for live events with known close time
            if bar_close_ts_str:
                try:
                    bct_dt = datetime.fromisoformat(bar_close_ts_str)
                    BAR_TO_I1_LATENCY.labels(symbol=symbol, tf=timeframe).observe(
                        (datetime.now(UTC) - bct_dt).total_seconds()
                    )
                except (ValueError, TypeError):
                    pass
            await self._kafka_producer.publish(
                topic_indicators(self.env_name),
                msg,
                key=message_key(symbol, timeframe),
            )

            self.bars_processed_total.inc()

            self.logger.debug(
                "I1 published",
                symbol=symbol,
                timeframe=timeframe,
                features=len(features),
            )
            return True

        except Exception as e:
            self.logger.error(
                "Error processing bar", symbol=symbol, timeframe=timeframe, error=str(e)
            )
            self.error_count_total.inc()
            return False

    def _process_tick(self, symbol: str, payload: dict) -> None:
        """Buffer incoming ticks per symbol — flushed at bar close. Capped at tick_buffer_max."""
        buf = self._tick_buffers[symbol]
        if len(buf) >= self._tick_buffer_max:
            # Drop oldest half to keep recent ticks; log once per overflow
            del buf[: self._tick_buffer_max // 2]
            dropped = self._tick_buffer_max // 2
            self.logger.warning("tick_buffer_overflow", symbol=symbol, dropped=dropped)
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

    async def _seed_bar_history_from_db(self) -> None:
        """Seed bar_history from market_data_ohlcv at startup (Phase 26 pattern).

        Reads last min_bars_for_tf(tf) * 2 bars per (symbol, tf) from DB.
        Falls back silently if DB unavailable — live warmup continues naturally.
        """
        if not self.db_manager:
            self.logger.warning("DB seed skipped — no db_manager", reason="no db_manager")
            return

        timeframes = self.config["service"]["timeframes"]
        symbols = self.config["service"]["symbols"]
        seeded_count = 0

        sem = asyncio.Semaphore(8)

        async def _fetch_one(symbol: str, tf: str) -> tuple[str, str, list]:
            async with sem:
                min_bars = self._min_bars_for_tf(tf) * 2
                # Lookback = 48× the data needed, expressed in seconds (~2 days
                # for 1m). This handles symbols with data gaps (e.g. crypto
                # during IBKR maintenance) while still letting TimescaleDB
                # exclude most chunks at planning time via the timestamp index.
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER
                query = f"""
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_data_ohlcv
                    WHERE symbol = $1 AND timeframe = $2
                      AND timestamp > NOW() - INTERVAL '{lookback_secs} seconds'
                    ORDER BY timestamp DESC
                    LIMIT {min_bars}
                """
                try:
                    result = await self.db_manager.execute_query(query, symbol, tf)
                    return symbol, tf, result or []
                except Exception:
                    return symbol, tf, []

        try:
            tasks = [_fetch_one(sym, tf) for sym in symbols for tf in timeframes]
            results = await asyncio.gather(*tasks)

            for symbol, tf, rows in results:
                if not rows:
                    continue
                key = f"{symbol}:{tf}"
                for row in reversed(rows):  # DB returns DESC; insert oldest→newest
                    try:
                        bar_ts = row["timestamp"]
                        if isinstance(bar_ts, str):
                            bar_ts = datetime.fromisoformat(bar_ts)
                        bar_data = {
                            "timestamp": bar_ts,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": int(row["volume"]),
                        }
                        history = self.bar_history[key]
                        history[bar_ts.isoformat()] = bar_data
                        while len(history) > self._bar_history_max:
                            history.popitem(last=False)
                        seeded_count += 1
                    except Exception:
                        pass

            self.logger.info("Seeded bar_history from DB", seeded_count=seeded_count)

        except Exception as e:
            self.logger.warning("DB seed failed — falling back to live warmup", error=str(e))

    async def _publish_seeded_state(self) -> None:
        """Compute and publish I1 indicators for the most recent seeded bar per (symbol, tf).

        Runs immediately after seed + Kafka producer start so the dashboard
        shows current state without waiting for the next live bar.
        Skips any (symbol, tf) that doesn't have enough bars for computation.
        """
        timeframes = self.config["service"]["timeframes"]
        symbols = self.config["service"]["symbols"]
        published = 0
        for symbol in symbols:
            for tf in timeframes:
                key = f"{symbol}:{tf}"
                history = self.bar_history.get(key)
                if not history or len(history) < self._min_bars_for_tf(tf):
                    continue
                try:
                    # Most recent bar is the last entry in the OrderedDict
                    bar_data = next(reversed(history.values()))
                    bar_ts = bar_data["timestamp"]
                    frames = {"main": self._get_df(key), "tick_buffer": []}
                    features = await self._run_i1_plugins(frames, symbol, tf)
                    msg = build_i1_message(bar_data, features, bar_ts, symbol, tf, source="seed")
                    await self._kafka_producer.publish(
                        topic_indicators(self.env_name),
                        msg,
                        key=message_key(symbol, tf),
                    )
                    published += 1
                except Exception as e:
                    self.logger.warning(
                        "Seed publish failed", symbol=symbol, tf=tf, error=str(e)
                    )
        self.logger.info("Published seeded I1 state", published=published)

    async def _process_market_data(self) -> None:
        """Consume market bars (and optionally system events) from Kafka."""
        assert self._kafka_consumer is not None
        _sys_events_topic = topic_system_events(self.env_name)
        async for topic, key, payload in self._kafka_consumer.messages():
            if self.shutdown_requested:
                break
            try:
                # Route system.events to roll handler
                if topic == _sys_events_topic:
                    await self._handle_roll_event(payload)
                    continue

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
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def _handle_roll_event(self, event: dict) -> None:
        """Migrate I1 plugin state from old_symbol to new_symbol on futures roll.

        Price-sensitive plugins (bollinger, keltner, donchian) have all numeric
        price levels adjusted by roll_gap. Volume-neutral plugins are copied verbatim.
        Old-symbol state keys are deleted after migration.

        This method is a no-op when event_type != 'roll'.
        """
        result = parse_roll_event(event, self.logger)
        if result is None:
            return
        old_symbol, new_symbol = result
        roll_gap: float = float(event.get("roll_gap", 0.0))

        for tf in ["1m", "5m", "15m", "1h"]:
            # _i1_plugin_states keys: (plugin_name, symbol, timeframe)
            old_plugin_keys = [
                k for k in self._i1_plugin_states
                if k[1] == old_symbol and k[2] == tf
            ]
            if not old_plugin_keys:
                continue

            migrated_count = 0
            keys_to_delete = []
            for key in old_plugin_keys:
                plugin_name = key[0]
                old_state = self._i1_plugin_states[key]
                new_key = (plugin_name, new_symbol, tf)
                if plugin_name in PRICE_SENSITIVE_PLUGINS:
                    new_state = _adjust_price_state(old_state, roll_gap)
                else:
                    new_state = old_state.copy() if isinstance(old_state, dict) else old_state
                self._i1_plugin_states[new_key] = new_state
                keys_to_delete.append(key)
                migrated_count += 1

            for key in keys_to_delete:
                del self._i1_plugin_states[key]
                self._i1_plugin_states_locks.pop(key, None)

            self.logger.info(
                "roll_plugin_state_migrated",
                old=f"{old_symbol}:{tf}",
                new=f"{new_symbol}:{tf}",
                gap=roll_gap,
                plugins=migrated_count,
            )

    async def start(self) -> None:
        self.logger.info("Starting Indicator Service", config=self.config["service"])
        try:
            start_metrics_server(port=self.config.get("metrics_port", 9109))

            # Seed bar history from DB before starting consumer (Phase 26 pattern)
            if self.db_manager:
                await self.db_manager.initialize()
            await self._seed_bar_history_from_db()

            # Start Kafka producer
            await self._kafka_producer.start()

            # Publish last-known I1 state from seeded history so dashboard is
            # populated immediately without waiting for the first live bar.
            await self._publish_seeded_state()

            # Build topics list
            _settings = Settings()
            topics: list[str] = [
                topic_market_bars(self.env_name),
                topic_market_bars_htf(self.env_name),
                topic_system_events(self.env_name),
            ]

            # Start Kafka consumer subscribed to market.bars and system.events topics
            self._kafka_consumer = KafkaConsumerClient(
                *topics,
                bootstrap_servers=self.config.get(
                    "kafka_bootstrap_servers",
                    _settings.kafka_bootstrap_servers,
                ),
                group_id="indicator_service",
                auto_offset_reset="latest",
            )
            await self._kafka_consumer.start()

            # Start tick consumer — separate group_id to avoid offset conflicts
            self._tick_consumer = KafkaConsumerClient(
                topic_market_ticks(self.env_name),
                bootstrap_servers=self.config.get(
                    "kafka_bootstrap_servers",
                    _settings.kafka_bootstrap_servers,
                ),
                group_id="indicator_service_ticks",
                auto_offset_reset="latest",
            )
            await self._tick_consumer.start()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._process_tick_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Indicator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start indicator service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Indicator Service")
        self.running = False
        self.shutdown_requested = True
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._tick_consumer:
            await self._tick_consumer.stop()
        await self._kafka_producer.stop()
        self.logger.info("Indicator Service stopped")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Indicator Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = IndicatorService(args.config)
    # Run plugin validation before starting service
    validator = PluginValidator()
    try:
        validator.validate_all()
        print("✅ Plugin validation passed")
    except RuntimeError as e:
        print(f"❌ Plugin validation failed: {e}")
        sys.exit(1)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
