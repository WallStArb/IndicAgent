#!/usr/bin/env python3
"""Feature Vector Writer Agent — persists FeatureVectorRecord to feature_vectors hypertable.

Consumes topic_feature_vectors via Kafka consumer group 'feature_vector_writer_group'
and batch-writes complete rows to the feature_vectors TimescaleDB hypertable.

All BaseWriter infrastructure (batching, flush loop, DLQ, OTel) unchanged.

Version: 4.1.0
Last Updated: 2026-06-22
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any  # noqa: F401

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings, get_active_symbols  # noqa: F401
from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import (
    topic_feature_vectors,
    topic_feature_vectors_dlq,
)
from src.intelligence.features.feature_vector_persistence import (
    FEATURE_VECTOR_INSERT_SQL,
    VALID_REGIME_LABEL_SOURCES,
    feature_vector_to_insert_params,
)
from src.intelligence.schemas import FeatureVector, FeatureVectorRecord
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    point_gauge,
)
from src.observability.spans import ATTR_BATCH_SIZE, ATTR_FLUSH_MS, observed_span

# ── Module-level constants ────────────────────────────────────────────────────

# Spot-check set of columns that must exist in feature_vectors before startup.
# Includes migration 159 columns so the service refuses to start against a stale schema.
_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "tf",
        "bar_ts",
        "pipeline_version",
        "feature_factory_version",
        "momentum_z_fast",
        "momentum_z_mid",
        "hurst",
        "atr_z",
        "feature_vector_id",
        "bar_close_ts",
        "momentum_z_slow",
    }
)

CONSUMER_GROUP: str = "feature_vector_writer_group"

HEALTH_CHECK_INTERVAL_SECS: int = 30

# ── Module-level SQL ──────────────────────────────────────────────────────────

# table_schema filter is mandatory: omitting it returns same-named tables from
# other schemas (e.g. timescaledb_internal), producing false "column exists" verdicts.
_VERIFY_SCHEMA_SQL = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'feature_vectors' AND table_schema = 'public'"
)

# Canonical SQL imported from shared persistence module.
# Do not inline SQL here — feature_vector_persistence.py is the single source of truth.
_INSERT_FEATURE_VECTOR_SQL = FEATURE_VECTOR_INSERT_SQL

logger = structlog.get_logger(__name__)


# ── Module-level pure functions ───────────────────────────────────────────────


def _record_to_insert_params(record: FeatureVectorRecord) -> tuple:
    """Unpack a FeatureVectorRecord and delegate to the canonical serializer.

    Validates regime_label_source against the schema constraint before INSERT.
    """
    return feature_vector_to_insert_params(
        symbol=record.symbol,
        tf=record.tf,
        bar_ts=record.bar_ts,
        pipeline_version=record.pipeline_version,
        feature_factory_version=record.feature_factory_version,
        regime=record.regime,
        regime_label_source=record.regime_label_source,
        vector=record.vector,
    )


# ── Service class ─────────────────────────────────────────────────────────────


class FeatureVectorWriter(BaseWriter):
    """Async Kafka consumer agent: topic_feature_vectors -> buffer -> batch INSERT.

    Consumes FeatureVectorRecord messages and batch-writes 61-column rows
    to the feature_vectors TimescaleDB hypertable. Single atomic INSERT per bar.
    """

    def __init__(self) -> None:
        self.start_time = datetime.now(tz=UTC)

        super().__init__(
            max_idle_seconds=300,
        )
        setup_service_logging("logs/feature_vector_writer.log")

        self._kafka_consumer: KafkaConsumerClient | None = None
        self.db_manager: DatabaseManager | None = None

        self._kafka_bootstrap: str = self.settings.kafka_bootstrap_servers

        # APR-backed batch parameters (read at _setup() with fallback defaults)
        self.BATCH_SIZE: int = 50
        self.FLUSH_INTERVAL_SECS: float = 5.0

        # OTel metrics (writer-specific)
        self.events_consumed_total = counter(
            "feature_writer_events_consumed_total",
            "Total FeatureVectorRecords consumed from topic_feature_vectors",
        )
        self.batch_writes_total = counter(
            "feature_writer_batch_writes_total",
            "Total batch writes to feature_vectors",
        )
        self.events_buffered_gauge = point_gauge(
            "feature_writer_buffer_size",
            "Current number of events in write buffer",
        )
        self.service_uptime_seconds = point_gauge(
            "feature_writer_service_uptime_seconds",
            "Feature vector writer service uptime in seconds",
        )
        self.error_count_total = counter(
            "feature_writer_errors_total",
            "Total errors encountered by feature vector writer",
        )
        self._parse_errors_total = counter(
            "feature_writer_parse_errors_total",
            "Total FeatureVectorRecord parse failures",
        )
        self._rows_parsed_by_symbol_tf = counter(
            "feature_writer_rows_parsed_by_symbol_tf_total",
            "Rows successfully parsed per symbol and timeframe",
        )
        self._db_connected = point_gauge(
            "feature_writer_db_connected",
            "DB connection state (1=connected, 0=disconnected)",
        )
        self._batch_latency_attrs = {"agent_id": self._agent_label}

        self._total_events = 0
        self._total_batches = 0
        self._error_count = 0

    def _topic_name(self) -> str:
        return topic_feature_vectors(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_feature_vectors(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return []  # DB writer — no Kafka output

    @property
    def lag_threshold_messages(self) -> int:
        return 500  # persistence agent — tighter lag threshold

    def _dlq_topic(self) -> str | None:
        """Route unparseable FeatureVectorRecord payloads to DLQ."""
        return topic_feature_vectors_dlq(self.env_name)

    def _parse_payload(self, payload: dict) -> tuple[list, list]:
        """Parse a FeatureVectorRecord payload dict into insert param tuples.

        Returns ([params_tuple], []) on success.
        Returns ([], [payload]) on parse failure — increments _parse_errors_total.
        Returns None only for structurally impossible payloads (triggers DLQ via BaseWriter).
        """
        if not isinstance(payload, dict):
            return [], [payload]

        try:
            vector_data = payload.get("vector")
            if not isinstance(vector_data, dict):
                self._parse_errors_total.add(1)
                return [], [payload]

            regime_label_source = payload.get("regime_label_source", "")
            if regime_label_source not in VALID_REGIME_LABEL_SOURCES:
                self.logger.error(
                    "feature_vector_writer.invalid_regime_label_source",
                    regime_label_source=regime_label_source,
                    valid=sorted(VALID_REGIME_LABEL_SOURCES),
                )
                self._parse_errors_total.add(1)
                return [], [payload]

            vector = FeatureVector(**vector_data)
            record = FeatureVectorRecord(
                symbol=payload["symbol"],
                tf=payload["tf"],
                bar_ts=payload["bar_ts"],
                pipeline_version=payload["pipeline_version"],
                feature_factory_version=payload.get("feature_factory_version", "1.0.0"),
                regime=payload.get("regime"),
                regime_label_source=regime_label_source,
                vector=vector,
            )
        except (TypeError, KeyError, ValueError):
            self._parse_errors_total.add(1)
            return [], [payload]

        self._rows_parsed_by_symbol_tf.add(1, {"symbol": record.symbol, "tf": record.tf})
        params = _record_to_insert_params(record)
        return [params], []

    async def _flush_batch(self, batch: list) -> None:
        if not self.db_manager:
            self.logger.warning(
                "feature_vector_writer.flush_no_db",
                count=len(batch),
            )
            raise RuntimeError("No database connection")

        async with observed_span("writer.flush", tracer=self.tracer) as span:
            _fw_t0 = time.perf_counter()
            await self.db_manager.execute_batch(_INSERT_FEATURE_VECTOR_SQL, batch)
            PERSISTENCE_BATCH_LATENCY.record(
                time.perf_counter() - _fw_t0, self._batch_latency_attrs
            )

            self.batch_writes_total.add(1)
            self._total_batches += 1
            self.events_buffered_gauge.set(0)
            # Single authoritative lag update after flush (not duplicated before + after)
            PERSISTENCE_CONSUMER_LAG.set(0, {"agent_id": self._agent_label})
            self.logger.debug("feature_vector_writer.batch_flushed", rows=len(batch))

            span.set_attribute(ATTR_BATCH_SIZE, len(batch))
            flush_ms = (time.perf_counter() - _fw_t0) * 1000
            span.set_attribute(ATTR_FLUSH_MS, flush_ms)

    async def _verify_schema(self) -> None:
        """Pre-flight: confirm feature_vectors spot-check columns exist.

        Raises RuntimeError immediately (before Kafka start) if any column is absent,
        converting a silent multi-hour data-loss failure into a loud startup crash.
        """
        rows = await self.db_manager.fetch(_VERIFY_SCHEMA_SQL)
        existing = {row["column_name"] for row in rows}
        missing = _REQUIRED_COLUMNS - existing
        if missing:
            raise RuntimeError(
                f"feature_vectors schema mismatch - missing columns:"
                f" {sorted(missing)}. Run migration 155/158"
                f" (production/migrations/)."
            )

    async def _setup(self) -> None:
        """Connect DB, load APR config, and start Kafka consumer."""
        await self._connect_database()
        await self._verify_schema()
        self._load_apr_config()
        await self._setup_kafka_clients()

    def _load_apr_config(self) -> None:
        """Load batch parameters from APR with fallback defaults."""
        try:
            from src.config.config_service import ConfigService

            cfg = ConfigService(database_url=self.settings.database_url)
            self.BATCH_SIZE = int(cfg.get_sync("threshold.feature_writer.batch_size", 50))
            self.FLUSH_INTERVAL_SECS = float(
                cfg.get_sync("threshold.feature_writer.flush_interval_secs", 5.0)
            )
        except Exception as error:
            self.logger.warning(
                "feature_vector_writer.apr_load_failed",
                error=str(error),
                batch_size=self.BATCH_SIZE,
                flush_interval=self.FLUSH_INTERVAL_SECS,
            )

    async def _run(self) -> None:
        """Main feature writing loop."""
        self.logger.info("feature_vector_writer.started")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._process_loop())
            tg.create_task(self._periodic_flush_loop())
            tg.create_task(self._health_monitor_loop())

    async def _teardown(self) -> None:
        """Flush buffer, close Kafka consumer and DB pool."""
        await self._shutdown()

    async def _connect_database(self) -> None:
        dsn = self.settings.database_url
        try:
            mgr = DatabaseManager(dsn)
            await mgr.initialize()
            self.db_manager = mgr
            self._db_connected.set(1)
            self.logger.info("feature_vector_writer.db_connected")
        except Exception as error:
            self._db_connected.set(0)
            self.logger.error("feature_vector_writer.db_connect_failed", error=str(error))
            raise

    async def _setup_kafka_clients(self) -> None:
        """Create Kafka consumer for topic_feature_vectors."""
        topics = [topic_feature_vectors(self.env_name)]

        self._kafka_consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self._kafka_bootstrap,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._kafka_consumer.start()
        # Wire up BaseWriter._consumer so _do_flush() can commit offsets
        self._consumer = self._kafka_consumer
        self.logger.info(
            "feature_vector_writer.kafka_consumer_started",
            topics=topics,
            group=CONSUMER_GROUP,
        )

    async def _process_loop(self) -> None:
        """Kafka consumer loop — reads topic_feature_vectors and buffers for flush."""
        if not self._kafka_consumer:
            return

        async for _kafka_topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                valid, invalid = self._parse_payload(payload)
                if invalid:
                    await self._maybe_route_to_dlq(
                        payload, ValueError("FeatureVectorRecord parse failed")
                    )
                    self.error_count_total.add(1)
                if valid:
                    self._buffer_rows(valid)
                    self.events_consumed_total.add(1)
                    self._total_events += 1
                self.events_buffered_gauge.set(len(self._buffer))
                await self.maybe_flush()

            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.error("feature_vector_writer.process_loop_error", error=str(error))
                self.error_count_total.add(1)
                self._error_count += 1

    async def _periodic_flush_loop(self) -> None:
        """Flush buffered events every FLUSH_INTERVAL_SECS regardless of message rate.

        Without this, the time-based flush in maybe_flush only triggers when a new
        message arrives. If topic_feature_vectors goes quiet, buffered events
        never reach the database until the next message arrives.
        """
        while self.running:
            try:
                await asyncio.sleep(self.FLUSH_INTERVAL_SECS)
                await self.maybe_flush()
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.error("feature_vector_writer.flush_loop_error", error=str(error))

    async def _health_monitor_loop(self) -> None:
        while self.running:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                PERSISTENCE_CONSUMER_LAG.set(len(self._buffer), {"agent_id": self._agent_label})
                self.logger.info(
                    "feature_vector_writer.health_check",
                    uptime=uptime,
                    events_consumed=self._total_events,
                    batches_written=self._total_batches,
                    buffer_size=len(self._buffer),
                    errors=self._error_count,
                )
                await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECS)
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.error("feature_vector_writer.health_monitor_error", error=str(error))
                await asyncio.sleep(5)

    async def _shutdown(self) -> None:
        """Graceful shutdown: flush buffer, close connections."""
        self.logger.info("feature_vector_writer.shutdown_started")

        # Flush remaining buffered records before closing
        if self._buffer:
            await self._do_flush()
        self._buffer.clear()

        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self.db_manager:
            await self.db_manager.close()

        self.logger.info(
            "feature_vector_writer.stopped",
            total_events=self._total_events,
            total_batches=self._total_batches,
        )


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    svc = FeatureVectorWriter()
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
