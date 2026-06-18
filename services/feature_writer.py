#!/usr/bin/env python3
"""Feature Writer Agent — persists BarIntelligenceRecord to intelligence_features hypertable.

Consumes development.intelligence.record via Kafka consumer group 'feature_writer_group'
and batch-writes complete rows to the intelligence_features TimescaleDB hypertable.

Phase 44.3: Single atomic INSERT per bar from BarIntelligenceRecord.
No more i7/i8 two-phase UPSERT writes — every row is complete at insert time.

Version: 3.0.0
Last Updated: 2026-04-13
Status: Phase 68 Plan 02 — migrated to BaseWriter
"""

from __future__ import annotations

import asyncio
import calendar
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts, get_active_symbols
from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import (
    normalize_session_type,
    setup_service_logging,
)
from src.core.stream_keys import (
    topic_cross_asset,
    topic_feature_writer_dlq,
    topic_intelligence_journal,
)
from src.intelligence.schemas import CTF_DEDICATED_COLUMNS, BarIntelligenceRecord
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

_REQUIRED_COLUMNS: frozenset[str] = CTF_DEDICATED_COLUMNS

BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "feature_writer_group"
CONSUMER_NAME: str = "feature_writer_1"

# ── Module-level SQL ──────────────────────────────────────────────────────────

# table_schema filter is mandatory: omitting it returns same-named tables from
# other schemas (e.g. timescaledb_internal), producing false "column exists" verdicts.
_VERIFY_SCHEMA_SQL = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'intelligence_features' AND table_schema = 'public'"
)

_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, technical_indicators, market_context, pattern_detections, regime_features,
    confluence_scores, smc, cross_timeframe_context, composite_events, trading_signals,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry,
    feature_schema_version,
    ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement,
    ctx
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb,
    $17, $18, $19,
    $20, $21, $22,
    $23, $24, $25,
    $26, $27,
    $28, $29,
    $30, $31, $32,
    $33,
    $34, $35, $36, $37,
    (
        SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
        FROM ctx_snapshots
        WHERE (symbol = $2 OR symbol IS NULL)
          AND valid_from <= $1
          AND (valid_to IS NULL OR valid_to > $1)
    )
)
ON CONFLICT (ts, symbol, tf)
DO UPDATE SET
    ctf_score = EXCLUDED.ctf_score,
    ctf_trend_alignment = EXCLUDED.ctf_trend_alignment,
    ctf_structure_alignment = EXCLUDED.ctf_structure_alignment,
    ctf_regime_agreement = EXCLUDED.ctf_regime_agreement
WHERE intelligence_features.ctf_score IS NULL
"""

# Pure UPDATE — no-op if the main bar row doesn't exist yet.
# Prevents roll boundary and cross-asset writes from creating sparse rows
# with NULL mandatory columns before the main BarIntelligenceRecord arrives.
_UPDATE_MARKET_CTX_SQL = """
UPDATE intelligence_features
SET market_context = COALESCE(market_context, '{}'::jsonb) || $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
"""

logger = structlog.get_logger(__name__)


# ── Module-level pure functions (testable without class instantiation) ─────────


def _build_expiry_map(settings: Settings) -> dict[str, date]:
    """Build symbol -> expiry date lookup at service startup.

    VX format "YYYYMM" -> last calendar day of that month.
    Non-futures (FX, CRYPTO) -> omitted from map; _compute_days_to_expiry returns 0.
    Malformed expiry strings are silently skipped.

    Returns:
        Mapping of symbol to expiry date for futures contracts.
    """
    from src.core.models import AssetClass

    result: dict[str, date] = {}
    for inst in get_active_contracts(settings):
        if inst.asset_class in (AssetClass.FX, AssetClass.CRYPTO) or not inst.expiry:
            continue
        expiry_str = inst.expiry
        try:
            if len(expiry_str) == 8:  # YYYYMMDD — standard futures
                result[inst.symbol] = date.fromisoformat(expiry_str)
            elif len(expiry_str) == 6:  # YYYYMM — VX style
                year, month = int(expiry_str[:4]), int(expiry_str[4:])
                last_day = calendar.monthrange(year, month)[1]
                result[inst.symbol] = date(year, month, last_day)
        except ValueError:
            pass  # malformed — leave out; _compute_days_to_expiry returns 0
    return result


def _compute_days_to_expiry(
    symbol: str,
    bar_ts: datetime,
    expiry_map: dict[str, date],
) -> int | None:
    """Return calendar days to expiry for a symbol at bar_ts.

    Args:
        symbol: Contract symbol
        bar_ts: Bar timestamp
        expiry_map: Symbol to expiry date mapping

    Returns:
        Days to expiry (0 for non-futures, None if map empty).
    """
    if not expiry_map:
        return None
    expiry_date = expiry_map.get(symbol)
    if expiry_date is None:
        return 0  # non-futures (FX, crypto) or unknown symbol
    return max(0, (expiry_date - bar_ts.date()).days)


def _record_to_insert_params(
    record: BarIntelligenceRecord,
    expiry_map: dict[str, date] | None = None,
    cross_asset_snapshot: dict | None = None,
) -> tuple:
    """Build a 37-element tuple of INSERT parameters for _INSERT_FEATURE_SQL."""
    event = record.intelligence
    days = _compute_days_to_expiry(event.symbol, event.ts, expiry_map or {})
    winner_dir = str(record.winner_direction) if record.winner_direction is not None else None
    session_type_val = normalize_session_type(record.session_type)

    i2_data = event.i2.model_dump(exclude_none=True)
    market_ctx = cross_asset_snapshot or {}

    # Extract CTF sub-scores from I6Confluence using explicit None semantics:
    # None = cold-start (I6 not computed), 0.0 = genuine neutral alignment.
    # Never use `or 0.0` fallback — that collapses the meaningful None/0.0 distinction.
    i6_dict = event.i6.model_dump(exclude_none=True)
    ctf_score = i6_dict.get("ctf_score")
    ctf_trend_alignment = i6_dict.get("ctf_trend_alignment")
    ctf_structure_alignment = i6_dict.get("ctf_structure_alignment")
    ctf_regime_agreement = i6_dict.get("ctf_regime_agreement")

    return (
        event.ts,  # $1 ts
        event.symbol,  # $2 symbol
        event.tf,  # $3 tf
        event.platform,  # $4 platform
        event.source,  # $5 source
        record.schema_version,  # $6 schema_version
        event.bar.model_dump(),  # $7 bar
        event.i1.model_dump(),  # $8 i1
        market_ctx,  # $9 market_context (cross_asset only)
        event.i5.model_dump(
            exclude_none=True
        ),  # $10 i5 (I5Patterns: dt_db_confidence, hs_confidence, tri_confidence)
        event.i3.model_dump(
            exclude_none=True
        ),  # $11 i3 (I3Structure: swing_high, nearest_resistance, trend structure, session levels)
        event.i4.model_dump(
            exclude_none=True
        ),  # $12 i4 (I4Context: GARCH, Kalman, AVWAP, VP, SessionContext)
        event.smc.model_dump(exclude_none=True),  # $13 smc
        event.i6.model_dump(  # $14 cross_timeframe_context
            exclude_none=True,
            exclude=CTF_DEDICATED_COLUMNS,
        ),
        i2_data,  # $15 i2
        [s.model_dump() for s in record.ranked_signals],  # $16 trading_signals
        event.bar_close_ts,  # $17 bar_close_ts
        event.i1_computed_at,  # $18 i1_computed_at
        event.computed_at,  # $19 computed_at
        record.winner_plugin,  # $20 winner_plugin
        record.winner_confidence,  # $21 winner_confidence
        winner_dir,  # $22 winner_direction
        record.signals_evaluated,  # $23 signals_evaluated
        record.signals_after_quality,  # $24 signals_after_quality
        record.signals_after_regime,  # $25 signals_after_regime
        record.signals_after_tod,  # $26 signals_after_tod
        record.signals_after_calibration,  # $27 signals_after_calibration
        record.ledger_written,  # $28 ledger_written
        record.pipeline_latency_ms,  # $29 pipeline_latency_ms
        record.i7_computed_at,  # $30 i7_computed_at
        session_type_val,  # $31 session_type
        days,  # $32 days_to_expiry
        event.feature_schema_version,  # $33 feature_schema_version (contamination boundary)
        ctf_score,  # $34 ctf_score (top-level; None = cold-start, 0.0 = genuine neutral)
        ctf_trend_alignment,  # $35 ctf_trend_alignment
        ctf_structure_alignment,  # $36 ctf_structure_alignment
        ctf_regime_agreement,  # $37 ctf_regime_agreement
    )


# ── Service class ─────────────────────────────────────────────────────────────


class FeatureWriter(BaseWriter):
    """Async Kafka consumer agent: intelligence.record topic -> buffer -> batch INSERT.

    Phase 44.3: Consumes intelligence.record only. Performs a single atomic INSERT
    per bar with all columns from BarIntelligenceRecord. No i7/i8 two-phase writes.
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

        # Prometheus metrics (writer-specific)
        self.events_consumed_total = counter(
            "feature_writer_events_consumed_total",
            "Total BarIntelligenceRecords consumed from intelligence.record topic",
        )
        self.batch_writes_total = counter(
            "feature_writer_batch_writes_total",
            "Total batch writes to intelligence_features",
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
            "Total BarIntelligenceRecord parse failures",
        )
        self._db_connected = _fw_meter.create_gauge(
            "feature_writer_db_connected",
            description="DB connection state (1=connected, 0=disconnected)",
        )
        self._batch_latency_attrs = {"agent_id": self._agent_label}

        self._total_events = 0
        self._total_batches = 0
        self._error_count = 0
        self._expiry_map: dict[str, date] = {}
        self._cross_asset_cache: dict[str, dict] = {}

    def _topic_name(self) -> str:
        return topic_intelligence_journal(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_intelligence_journal(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return []  # DB writer — no Kafka output

    @property
    def lag_threshold_messages(self) -> int:
        return 500  # persistence agent — tighter lag threshold

    def _dlq_topic(self) -> str | None:
        """Route unparseable intelligence payloads to DLQ."""
        return topic_feature_writer_dlq(self.env_name)

    def _parse_payload(self, payload: dict) -> tuple[list, list]:
        """Parse a BarIntelligenceRecord payload into insert param tuples."""
        try:
            if isinstance(payload, dict):
                record = BarIntelligenceRecord.model_validate(payload)
            elif isinstance(payload, str):
                record = BarIntelligenceRecord.model_validate_json(payload.encode())
            elif isinstance(payload, bytes):
                record = BarIntelligenceRecord.model_validate_json(payload)
            else:
                return [], [payload]
        except (ValidationError, ValueError):
            self._parse_errors_total.add(1)
            return [], [payload]

        if record is None:
            return [], [payload]

        cross_asset = getattr(self, "_cross_asset_cache", {}).get(record.intelligence.tf, {})
        params = _record_to_insert_params(record, self._expiry_map, cross_asset)
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
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, batch)
            PERSISTENCE_BATCH_LATENCY.record(
                __import__("time").perf_counter() - _fw_t0, self._batch_latency_attrs
            )

            self.batch_writes_total.add(1)
            self._total_batches += 1
            self.events_buffered_gauge.set(0)
            # Single authoritative lag update after flush (not duplicated before + after)
            PERSISTENCE_CONSUMER_LAG.set(0, {"agent_id": self._agent_label})
            self.logger.debug("Flushed intelligence_features batch", rows=len(batch))

            span.set_attribute(ATTR_BATCH_SIZE, len(batch))
            flush_ms = (__import__("time").perf_counter() - _fw_t0) * 1000
            span.set_attribute(ATTR_FLUSH_MS, flush_ms)

    async def _verify_schema(self) -> None:
        """Pre-flight: confirm Phase-130 CTF columns exist in intelligence_features.

        Raises RuntimeError immediately (before Kafka start) if any column is absent,
        converting a silent multi-hour data-loss failure into a loud startup crash.
        """
        rows = await self.db_manager.fetch(_VERIFY_SCHEMA_SQL)
        existing = {row["column_name"] for row in rows}
        missing = _REQUIRED_COLUMNS - existing
        if missing:
            raise RuntimeError(
                f"intelligence_features schema mismatch - missing columns:"
                f" {sorted(missing)}. Run migration 130"
                f" (production/migrations/130_promote_ctf_columns.sql)."
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
        except Exception as e:
            logger.warning("Settings() failed in _load_config — using defaults", error=str(e))
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
        except Exception as e:
            self._db_connected.set(0)
            self.logger.error("feature_writer.db_connect_failed", error=str(e))
            raise

    async def _setup_kafka_clients(self) -> None:
        """Build expiry map and create Kafka consumer for intelligence.record topic."""
        # Build expiry map at startup (cached for lifetime of service)
        try:
            _s = Settings()
            self._expiry_map = _build_expiry_map(_s)
            self.logger.info("Expiry map built", contracts=len(self._expiry_map))
        except Exception as e:
            self.logger.warning("Failed to build expiry map", error=str(e))
            self._expiry_map = {}

        if not self._expiry_map:
            self.logger.warning(
                "expiry_map_empty",
                reason="No futures contracts in settings or _build_expiry_map failed — "
                "days_to_expiry=0 for all symbols until service restarts",
            )

        # Build topics list
        topics = [
            topic_intelligence_journal(self.env_name),
            topic_cross_asset(self.env_name),
        ]

        # Single consumer subscribed to intelligence.journal and cross_asset
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
        """Kafka consumer loop — reads intelligence.journal topic and routes by topic."""
        if not self._kafka_consumer:
            return

        intelligence_journal_topic = topic_intelligence_journal(self.env_name)
        cross_asset_topic = topic_cross_asset(self.env_name)

        async for kafka_topic, key, payload in self._kafka_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                # Route cross_asset topic — group-level, no symbol/tf key
                if kafka_topic == cross_asset_topic:
                    await self._process_cross_asset_message(payload)
                    continue

                # Extract symbol and timeframe from key (format "SYMBOL:TF")
                key_str = key if isinstance(key, str) else (key.decode() if key else "")
                parts = key_str.split(":")
                if len(parts) != 2:
                    self.logger.warning("Skipping message with malformed key", key=key_str)
                    continue
                symbol, timeframe = parts

                # SAFETY: Skip raw intelligence events — these have tier keys like "i1", "i2", etc.
                # Plan 05 serialization fix: intel events are now flat dicts (model_dump mode="json"),
                # not {"event": "<json_string>"}. Check for tier key presence instead.
                if isinstance(payload, dict) and "i1" in payload:
                    continue

                if kafka_topic == intelligence_journal_topic:
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
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.add(1)
                self._error_count += 1

    async def _periodic_flush_loop(self) -> None:
        """Flush buffered events every FLUSH_INTERVAL_SECS regardless of message rate.

        Without this, the time-based flush in maybe_flush only triggers when a new
        message arrives. If the intelligence.record topic goes quiet, buffered events
        never reach the database until the next message arrives.
        """
        while self.running:
            try:
                await asyncio.sleep(FLUSH_INTERVAL_SECS)
                await self.maybe_flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in periodic flush loop", error=str(e))

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
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def _process_cross_asset_message(self, payload: dict) -> None:
        try:
            tf = payload.get("tf", "")
            if not tf or not payload.get("ready"):
                return
            self._cross_asset_cache[tf] = {
                "cross_asset": {
                    "es_nq_spread_z": payload.get("es_nq_spread_z"),
                    "es_rty_spread_z": payload.get("es_rty_spread_z"),
                    "eq_corr_break": payload.get("eq_corr_break"),
                    "eq_vol_imbalance": payload.get("eq_vol_imbalance"),
                    "active_pair": payload.get("active_pair"),
                    "pairs_confirming": payload.get("pairs_confirming"),
                    "data_quality_score": payload.get("data_quality_score"),
                    "low_vol_flag": payload.get("low_vol_flag"),
                    "corr_z": payload.get("corr_z"),
                }
            }
        except Exception as e:
            self.logger.warning("cross_asset_cache_update_failed", error=str(e))
            self.error_count_total.add(1)

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
