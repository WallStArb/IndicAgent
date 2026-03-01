#!/usr/bin/env python3
"""Feature Writer Service — persists IntelligenceEvent to intelligence_features hypertable.

Consumes intelligence:SYMBOL:TF streams via consumer group feature_writer:persist
and batch-writes rows to the intelligence_features TimescaleDB hypertable.

This service is additive: it does NOT modify market_analysis_service.py.
Every IntelligenceEvent published is durably persisted here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import intelligence as sk_intelligence
from src.intelligence.schemas import IntelligenceEvent
from src.observability.metrics import counter, gauge, start_metrics_server

# ── Module-level constants ────────────────────────────────────────────────────

BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "feature_writer:persist"
CONSUMER_NAME: str = "feature_writer_1"

# ── Module-level SQL ──────────────────────────────────────────────────────────

_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ─────────

def _parse_intelligence_event(fields: dict[bytes, bytes]) -> IntelligenceEvent | None:
    """Parse intelligence stream message into typed IntelligenceEvent.

    Identical pattern to signal_generator_service.py: reads b'event' key,
    calls IntelligenceEvent.model_validate_json(), returns None on any failure.
    """
    raw = fields.get(b"event", b"")
    if not raw:
        return None
    try:
        return IntelligenceEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("Failed to parse IntelligenceEvent", error=str(e))
        return None


def _event_to_insert_params(event: IntelligenceEvent) -> tuple:
    """Build a 13-element tuple of INSERT parameters for _INSERT_FEATURE_SQL.

    Returns positional params matching $1..$13:
      $1  ts             — datetime
      $2  symbol         — str
      $3  tf             — str
      $4  platform       — str
      $5  source         — str
      $6  schema_version — str
      $7  bar            — JSON string (jsonb)
      $8  i1             — JSON string (jsonb)
      $9  i3             — JSON string (jsonb)
      $10 i4             — JSON string (jsonb)
      $11 i5             — JSON string (jsonb)
      $12 smc            — JSON string (jsonb)
      $13 i6             — JSON string (jsonb)

    JSONB columns MUST be json.dumps() strings — asyncpg does not auto-serialize dicts.
    - bar uses model.model_dump() (no exclude_none — bar always has full data)
    - i1 uses model.model_dump() (no exclude_none — I1 has extra='allow', many dynamic fields)
    - i3..i6 use model.model_dump(exclude_none=True) (strict models, exclude None for compactness)
    """
    return (
        event.ts,
        event.symbol,
        event.tf,
        event.platform,
        event.source,
        event.schema_version,
        json.dumps(event.bar.model_dump()),
        json.dumps(event.i1.model_dump()),
        json.dumps(event.i3.model_dump(exclude_none=True)),
        json.dumps(event.i4.model_dump(exclude_none=True)),
        json.dumps(event.i5.model_dump(exclude_none=True)),
        json.dumps(event.smc.model_dump(exclude_none=True)),
        json.dumps(event.i6.model_dump(exclude_none=True)),
    )


# ── Service class ─────────────────────────────────────────────────────────────

class FeatureWriterService:
    """Async consumer group service: xreadgroup → buffer → batch INSERT to intelligence_features."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None

        self._buffer: list[tuple] = []
        self._last_flush: float = time.monotonic()

        try:
            _s = Settings()
            self._env_prefix: str = f"{_s.env_name}:" if _s.env_name else ""
        except Exception:
            self._env_prefix = ""

        # Prometheus metrics
        self.events_consumed_total = counter(
            "feature_writer_events_consumed_total",
            "Total IntelligenceEvents consumed from intelligence: streams",
        )
        self.batch_writes_total = counter(
            "feature_writer_batch_writes_total",
            "Total batch writes to intelligence_features",
        )
        self.events_buffered_gauge = gauge(
            "feature_writer_buffer_size",
            "Current number of events in write buffer",
        )
        self.service_uptime_seconds = gauge(
            "feature_writer_service_uptime_seconds",
            "Feature writer service uptime in seconds",
        )
        self.error_count_total = counter(
            "feature_writer_errors_total",
            "Total errors encountered by feature writer",
        )

        self._total_events = 0
        self._total_batches = 0
        self._error_count = 0
        self._stream_map: dict[str, tuple[str, str]] = {}

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        metrics_port = self.config.get("service", {}).get("metrics_port", 9116)
        start_metrics_server(port=metrics_port)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "dsn": "postgresql://postgres:postgres@localhost:5432/indicagent"
            },
            "service": {
                "symbols": get_active_contracts(_settings),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.01,
                "metrics_port": 9116,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/feature_writer_service.log",
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
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"],
            maxBytes=10 * 1024 * 1024,
            backupCount=self.config["logging"].get("backup_count", 5),
        )
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"].get("db", 0),
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _connect_database(self) -> None:
        dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
        try:
            self.db_manager = DatabaseManager(dsn)
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        """Create consumer group for each intelligence:SYMBOL:TF stream."""
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = sk_intelligence(self._env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, CONSUMER_GROUP, "$", mkstream=True
                    )
                    self.logger.debug(
                        "Created consumer group",
                        group=CONSUMER_GROUP,
                        stream=stream_name,
                    )
                except Exception:
                    # Group already exists — reset position to skip stale backlog
                    await self.redis_client.xgroup_setid(
                        stream_name, CONSUMER_GROUP, "$"
                    )
                self._stream_map[stream_name] = (sym, tf)

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> bool:
        """Parse one stream message, buffer insert params, and signal ack."""
        try:
            event = _parse_intelligence_event(fields)
            if event is None:
                # Malformed or missing event — ack-and-skip (do not crash)
                return True

            params = _event_to_insert_params(event)
            self._buffer.append(params)
            self.events_consumed_total.inc()
            self._total_events += 1
            self.events_buffered_gauge.set(len(self._buffer))

            # Flush if buffer full
            if len(self._buffer) >= BATCH_SIZE:
                await self._maybe_flush(force=True)

            return True

        except Exception as e:
            self.logger.error(
                "Error processing message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
            return False

    async def _maybe_flush(self, force: bool = False) -> None:
        """Write buffered events to intelligence_features if conditions are met.

        Flushes when:
        - force=True (explicit flush, e.g. on BATCH_SIZE reached or shutdown)
        - time since last flush >= FLUSH_INTERVAL_SECS (time-based flush)

        Does NOT flush if buffer is empty or db_manager is unavailable.
        """
        if not self._buffer:
            return

        should_flush = force or (time.monotonic() - self._last_flush >= FLUSH_INTERVAL_SECS)
        if not should_flush:
            return

        if not self.db_manager:
            # No DB — clear buffer to avoid unbounded growth, log warning
            self.logger.warning(
                "No database connection — dropping buffered events",
                count=len(self._buffer),
            )
            self._buffer.clear()
            self._last_flush = time.monotonic()
            return

        params = list(self._buffer)
        self._last_flush = time.monotonic()

        try:
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, params)
            self._buffer.clear()
            if hasattr(self, "batch_writes_total"):
                self.batch_writes_total.inc()
            if hasattr(self, "_total_batches"):
                self._total_batches += 1
            if hasattr(self, "events_buffered_gauge"):
                self.events_buffered_gauge.set(0)
            self.logger.debug("Flushed intelligence_features batch", rows=len(params))
        except Exception as e:
            self.logger.error("Batch write failed", error=str(e), rows=len(params))
            # params remain in self._buffer for retry on next flush cycle
            if hasattr(self, "error_count_total"):
                self.error_count_total.inc()
            if hasattr(self, "_error_count"):
                self._error_count += 1

    async def _process_loop(self) -> None:
        """Main consumer group loop — reads all streams and processes messages."""
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    CONSUMER_GROUP, CONSUMER_NAME,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    sym, tf = self._stream_map[stream_name]
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_single_message(
                            sym, tf, fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(stream_name, CONSUMER_GROUP, *to_ack)

                await self._maybe_flush(force=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"].get("health_check_interval", 30)
                if uptime % interval == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        events_consumed=self._total_events,
                        batches_written=self._total_batches,
                        buffer_size=len(self._buffer),
                        errors=self._error_count,
                    )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def _shutdown(self) -> None:
        """Graceful shutdown: flush buffer, close connections."""
        self.logger.info("Shutting down Feature Writer Service")
        self.shutdown_requested = True
        self.running = False

        # Flush remaining buffered events before closing
        await self._maybe_flush(force=True)

        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()

        self.logger.info(
            "Feature Writer Service stopped",
            total_events=getattr(self, "_total_events", 0),
            total_batches=getattr(self, "_total_batches", 0),
        )

    async def start(self) -> None:
        self.logger.info("Starting Feature Writer Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Feature Writer Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start feature writer", error=str(e))
            raise
        finally:
            await self._shutdown()


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Feature Writer Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    svc = FeatureWriterService(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
