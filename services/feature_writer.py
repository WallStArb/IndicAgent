#!/usr/bin/env python3
"""Feature Writer Agent — persists FeatureVectorRecord to feature_vectors hypertable.

Consumes topic_feature_vectors via Kafka consumer group 'feature_vector_writer_group'
and batch-writes complete rows to the feature_vectors TimescaleDB hypertable.

Phase 137 P4: Retargeted to feature_vectors (v3.0).
All BaseWriter infrastructure (batching, flush loop, DLQ, OTel) unchanged.

Version: 4.0.0
Last Updated: 2026-06-20
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings, get_active_symbols
from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import (
    topic_feature_vectors,
    topic_feature_vectors_dlq,
)
from src.intelligence.schemas import FeatureVector, FeatureVectorRecord
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    point_gauge,
)
from src.observability.spans import ATTR_BATCH_SIZE, ATTR_FLUSH_MS, observed_span

# OTel meter for feature writer-specific gauges
_otel_metrics = __import__("opentelemetry").metrics
_fw_meter = _otel_metrics.get_meter("indicagent")

# ── Module-level constants ────────────────────────────────────────────────────

# Spot-check set of columns that must exist in feature_vectors before startup.
_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "tf",
        "bar_ts",
        "pipeline_version",
        "momentum_z_5",
        "momentum_z_20",
        "hurst",
        "atr_z",
    }
)

BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "feature_vector_writer_group"
CONSUMER_NAME: str = "feature_writer_1"

# ── Module-level SQL ──────────────────────────────────────────────────────────

# table_schema filter is mandatory: omitting it returns same-named tables from
# other schemas (e.g. timescaledb_internal), producing false "column exists" verdicts.
_VERIFY_SCHEMA_SQL = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'feature_vectors' AND table_schema = 'public'"
)

_INSERT_FEATURE_VECTOR_SQL = """
INSERT INTO feature_vectors (
    symbol, tf, bar_ts, pipeline_version, regime, regime_label_source,
    momentum_z_5, momentum_z_20, range_position, bar_close_pos,
    gap_z, informed_flow, volume_z, ofi_z, ofi_div, cvd_slope_z, cmf,
    rel_volume, vwap_dev_sigma, atr_z, vol_ratio,
    poc_dist_atr, va_position, sr_support_dist, sr_resist_dist,
    hmm_regime_prob, hmm_entropy, hmm_duration, hurst, shannon, garch_ratio,
    hma_slope_z, adx, aroon_fast, aroon_slow,
    rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow,
    vix_z, flight_quality, yield_slope_z,
    in_ny_session, in_london_kz, in_overlap, power_hour, opening_range,
    above_wk_vwap, dow_sin, dow_cos, month_position,
    ctf_momentum, ctf_vwap_align, ctf_regime_align,
    amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17,
    $18, $19, $20, $21,
    $22, $23, $24, $25,
    $26, $27, $28, $29, $30, $31,
    $32, $33, $34, $35,
    $36, $37, $38, $39, $40, $41,
    $42, $43, $44,
    $45, $46, $47, $48, $49,
    $50, $51, $52, $53,
    $54, $55, $56,
    $57, $58, $59, $60
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ─────────


def _record_to_insert_params(record: FeatureVectorRecord) -> tuple:
    """Build a 60-element tuple of INSERT parameters for _INSERT_FEATURE_VECTOR_SQL.

    Column order matches the INSERT statement exactly:
    $1-$6: structural (symbol, tf, bar_ts, pipeline_version, regime, regime_label_source)
    $7-$60: 54 feature floats in FeatureVector field order
    """
    v: FeatureVector = record.vector
    return (
        record.symbol,  # $1  symbol
        record.tf,  # $2  tf
        record.bar_ts,  # $3  bar_ts
        record.pipeline_version,  # $4  pipeline_version
        record.regime,  # $5  regime
        record.regime_label_source,  # $6 regime_label_source
        # Momentum (5)
        v.momentum_z_5,  # $7
        v.momentum_z_20,  # $8
        v.range_position,  # $9
        v.bar_close_pos,  # $10
        # Volume / order flow (8)
        v.gap_z,  # $11
        v.informed_flow,  # $12
        v.volume_z,  # $13
        v.ofi_z,  # $14
        v.ofi_div,  # $15
        v.cvd_slope_z,  # $16
        v.cmf,  # $17
        # Volatility (2)
        v.rel_volume,  # $18
        v.vwap_dev_sigma,  # $19
        v.atr_z,  # $20
        v.vol_ratio,  # $21
        # Session-level (4)
        v.poc_dist_atr,  # $22
        v.va_position,  # $23
        v.sr_support_dist,  # $24
        v.sr_resist_dist,  # $25
        # Regime-level (11)
        v.hmm_regime_prob,  # $26
        v.hmm_entropy,  # $27
        v.hmm_duration,  # $28
        v.hurst,  # $29
        v.shannon,  # $30
        v.garch_ratio,  # $31
        v.hma_slope_z,  # $32
        v.adx,  # $33
        v.aroon_fast,  # $34
        v.aroon_slow,  # $35
        # Oscillators (6)
        v.rsi_fast,  # $36
        v.rsi_mid,  # $37
        v.rsi_slow,  # $38
        v.cci_fast,  # $39
        v.cci_mid,  # $40
        v.cci_slow,  # $41
        # Cross-asset (3)
        v.vix_z,  # $42
        v.flight_quality,  # $43
        v.yield_slope_z,  # $44
        # Calendar (9)
        v.in_ny_session,  # $45
        v.in_london_kz,  # $46
        v.in_overlap,  # $47
        v.power_hour,  # $48
        v.opening_range,  # $49
        v.above_wk_vwap,  # $50
        v.dow_sin,  # $51
        v.dow_cos,  # $52
        v.month_position,  # $53
        # Cross-timeframe (3)
        v.ctf_momentum,  # $54
        v.ctf_vwap_align,  # $55
        v.ctf_regime_align,  # $56
        # Statistical / liquidity (4)
        v.amihud_illiq_z,  # $57
        v.high_52w_dist,  # $58
        v.ret_skew_z,  # $59
        v.ret_acf1_z,  # $60
    )


# ── Service class ─────────────────────────────────────────────────────────────


class FeatureWriter(BaseWriter):
    """Async Kafka consumer agent: topic_feature_vectors -> buffer -> batch INSERT.

    Consumes FeatureVectorRecord messages and batch-writes 60-column rows
    to the feature_vectors TimescaleDB hypertable. Single atomic INSERT per bar.
    """

    BATCH_SIZE = BATCH_SIZE
    FLUSH_INTERVAL_SECS = FLUSH_INTERVAL_SECS

    def __init__(self, config_file: str | None = None):
        self.start_time = datetime.now(tz=UTC)

        config = self._load_config(config_file)
        super().__init__(
            max_idle_seconds=300,
        )
        self.config = config
        self._setup_logging()

        self._kafka_consumer: KafkaConsumerClient | None = None
        self.db_manager: DatabaseManager | None = None

        self._kafka_bootstrap: str = self.settings.kafka_bootstrap_servers

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
            "Feature writer service uptime in seconds",
        )
        self.error_count_total = counter(
            "feature_writer_errors_total",
            "Total errors encountered by feature writer",
        )
        self._parse_errors_total = counter(
            "feature_writer_parse_errors_total",
            "Total FeatureVectorRecord parse failures",
        )
        self._db_connected = _fw_meter.create_gauge(
            "feature_writer_db_connected",
            description="DB connection state (1=connected, 0=disconnected)",
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
            # FeatureVectorRecord contains a nested FeatureVector dataclass.
            # The payload is a dict with 'vector' as a nested dict.
            vector_data = payload.get("vector")
            if not isinstance(vector_data, dict):
                self._parse_errors_total.add(1)
                return [], [payload]

            vector = FeatureVector(**vector_data)
            record = FeatureVectorRecord(
                symbol=payload["symbol"],
                tf=payload["tf"],
                bar_ts=payload["bar_ts"],
                pipeline_version=payload["pipeline_version"],
                regime=payload.get("regime"),
                regime_label_source=payload["regime_label_source"],
                vector=vector,
            )
        except (TypeError, KeyError, ValueError):
            self._parse_errors_total.add(1)
            return [], [payload]

        params = _record_to_insert_params(record)
        return [params], []

    async def _flush_batch(self, batch: list) -> None:
        if not self.db_manager:
            self.logger.warning(
                "No database connection — cannot flush",
                count=len(batch),
            )
            raise RuntimeError("No database connection")

        async with observed_span("writer.flush", tracer=self.tracer) as span:
            _fw_t0 = __import__("time").perf_counter()
            await self.db_manager.execute_batch(_INSERT_FEATURE_VECTOR_SQL, batch)
            PERSISTENCE_BATCH_LATENCY.record(
                __import__("time").perf_counter() - _fw_t0, self._batch_latency_attrs
            )

            self.batch_writes_total.add(1)
            self._total_batches += 1
            self.events_buffered_gauge.set(0)
            # Single authoritative lag update after flush (not duplicated before + after)
            PERSISTENCE_CONSUMER_LAG.set(0, {"agent_id": self._agent_label})
            self.logger.debug("Flushed feature_vectors batch", rows=len(batch))

            span.set_attribute(ATTR_BATCH_SIZE, len(batch))
            flush_ms = (__import__("time").perf_counter() - _fw_t0) * 1000
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
                f" {sorted(missing)}. Run migration 155"
                f" (production/migrations/155_feature_vectors.sql)."
            )

    async def _setup(self) -> None:
        """Connect DB and start Kafka consumer."""
        await self._connect_database()
        await self._verify_schema()
        await self._setup_kafka_clients()

    async def _run(self) -> None:
        """Main feature writing loop."""
        self.logger.info("Feature Writer Agent started")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._process_loop())
            tg.create_task(self._periodic_flush_loop())
            tg.create_task(self._health_monitor_loop())

    async def _teardown(self) -> None:
        """Flush buffer, close Kafka consumer and DB pool."""
        await self._shutdown()

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception as error:
            logger.warning("Settings() failed in _load_config — using defaults", error=str(error))
            _settings = None

        default_config: dict[str, Any] = {
            "database": {"dsn": "postgresql://postgres:postgres@localhost:5432/indicagent"},
            "service": {
                "symbols": get_active_symbols(_settings),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.01,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/feature_writer.log",
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

    async def _connect_database(self) -> None:
        dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
        try:
            mgr = DatabaseManager(dsn)
            await mgr.initialize()
            self.db_manager = mgr
            self._db_connected.set(1)
            self.logger.info("Connected to database")
        except Exception as error:
            self._db_connected.set(0)
            self.logger.error("feature_writer.db_connect_failed", error=str(error))
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
            "Kafka consumer started",
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
                    await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
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
                self.logger.error("Error in processing loop", error=str(error))
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
                await asyncio.sleep(FLUSH_INTERVAL_SECS)
                await self.maybe_flush()
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.error("Error in periodic flush loop", error=str(error))

    async def _health_monitor_loop(self) -> None:
        while self.running:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                PERSISTENCE_CONSUMER_LAG.set(len(self._buffer), {"agent_id": self._agent_label})
                interval = self.config["service"].get("health_check_interval", 30)
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
            except Exception as error:
                self.logger.error("Error in health monitor", error=str(error))
                await asyncio.sleep(5)

    async def _shutdown(self) -> None:
        """Graceful shutdown: flush buffer, close connections."""
        self.logger.info("Shutting down Feature Writer Agent")

        # Flush remaining buffered records before closing
        if self._buffer:
            await self._do_flush()
        self._buffer.clear()

        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self.db_manager:
            await self.db_manager.close()

        self.logger.info(
            "Feature Writer Agent stopped",
            total_events=getattr(self, "_total_events", 0),
            total_batches=getattr(self, "_total_batches", 0),
        )


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Feature Writer Agent")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    svc = FeatureWriter(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
