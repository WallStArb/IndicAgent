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
import hashlib
import uuid
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
        "feature_vector_id",
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

_INSERT_FEATURE_VECTOR_SQL = """
INSERT INTO feature_vectors (
    feature_vector_id,
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
    $1,
    $2, $3, $4, $5, $6, $7,
    $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24, $25, $26,
    $27, $28, $29, $30, $31, $32,
    $33, $34, $35, $36,
    $37, $38, $39, $40, $41, $42,
    $43, $44, $45,
    $46, $47, $48, $49, $50,
    $51, $52, $53, $54,
    $55, $56, $57,
    $58, $59, $60, $61
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ─────────


def _make_feature_vector_id(
    symbol: str, tf: str, bar_ts: datetime, pipeline_version: str
) -> uuid.UUID:
    """Compute the content-key UUID for a feature_vectors row.

    SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] cast to UUID.
    Idempotent across replays — same inputs always produce the same UUID.
    """
    bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
    raw = hashlib.sha256(f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}".encode()).hexdigest()[:32]
    return uuid.UUID(raw)


def _record_to_insert_params(record: FeatureVectorRecord) -> tuple:
    """Build a 61-element tuple of INSERT parameters for _INSERT_FEATURE_VECTOR_SQL.

    Column order matches the INSERT statement exactly:
    $1:     feature_vector_id (content-key UUID)
    $2-$7:  structural (symbol, tf, bar_ts, pipeline_version, regime, regime_label_source)
    $8-$61: 54 feature floats in FeatureVector field order
    """
    feature_vector_id = _make_feature_vector_id(
        record.symbol, record.tf, record.bar_ts, record.pipeline_version
    )
    v: FeatureVector = record.vector
    return (
        feature_vector_id,  # $1  feature_vector_id
        record.symbol,  # $2  symbol
        record.tf,  # $3  tf
        record.bar_ts,  # $4  bar_ts
        record.pipeline_version,  # $5  pipeline_version
        record.regime,  # $6  regime
        record.regime_label_source,  # $7  regime_label_source
        # Momentum (4)
        v.momentum_z_5,  # $8
        v.momentum_z_20,  # $9
        v.range_position,  # $10
        v.bar_close_pos,  # $11
        # Volume / order flow (7)
        v.gap_z,  # $12
        v.informed_flow,  # $13
        v.volume_z,  # $14
        v.ofi_z,  # $15
        v.ofi_div,  # $16
        v.cvd_slope_z,  # $17
        v.cmf,  # $18
        # Volatility / volume profile (4)
        v.rel_volume,  # $19
        v.vwap_dev_sigma,  # $20
        v.atr_z,  # $21
        v.vol_ratio,  # $22
        # Session-level (4)
        v.poc_dist_atr,  # $23
        v.va_position,  # $24
        v.sr_support_dist,  # $25
        v.sr_resist_dist,  # $26
        # Regime-level (11)
        v.hmm_regime_prob,  # $27
        v.hmm_entropy,  # $28
        v.hmm_duration,  # $29
        v.hurst,  # $30
        v.shannon,  # $31
        v.garch_ratio,  # $32
        v.hma_slope_z,  # $33
        v.adx,  # $34
        v.aroon_fast,  # $35
        v.aroon_slow,  # $36
        # Oscillators (6)
        v.rsi_fast,  # $37
        v.rsi_mid,  # $38
        v.rsi_slow,  # $39
        v.cci_fast,  # $40
        v.cci_mid,  # $41
        v.cci_slow,  # $42
        # Cross-asset (3)
        v.vix_z,  # $43
        v.flight_quality,  # $44
        v.yield_slope_z,  # $45
        # Calendar (9)
        v.in_ny_session,  # $46
        v.in_london_kz,  # $47
        v.in_overlap,  # $48
        v.power_hour,  # $49
        v.opening_range,  # $50
        v.above_wk_vwap,  # $51
        v.dow_sin,  # $52
        v.dow_cos,  # $53
        v.month_position,  # $54
        # Cross-timeframe (3)
        v.ctf_momentum,  # $55
        v.ctf_vwap_align,  # $56
        v.ctf_regime_align,  # $57
        # Statistical / liquidity (4)
        v.amihud_illiq_z,  # $58
        v.high_52w_dist,  # $59
        v.ret_skew_z,  # $60
        v.ret_acf1_z,  # $61
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
                "feature_vector_writer.flush_no_db",
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
            self.logger.debug("feature_vector_writer.batch_flushed", rows=len(batch))

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
