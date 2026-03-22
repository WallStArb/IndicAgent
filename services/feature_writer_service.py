#!/usr/bin/env python3
"""Feature Writer Service — persists BarIntelligenceRecord to intelligence_features hypertable.

Consumes development.intelligence.record via Kafka consumer group 'feature_writer_group'
and batch-writes complete rows to the intelligence_features TimescaleDB hypertable.

Phase 44.3: Single atomic INSERT per bar from BarIntelligenceRecord.
No more i7/i8 two-phase UPSERT writes — every row is complete at insert time.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import signal
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts, get_active_symbols
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import parse_roll_event, setup_service_logging
from src.core.stream_keys import (
    topic_cross_asset,
    topic_intelligence_record,
    topic_system_events,
)
from src.intelligence.cross_asset_features import _EQ_INDEX_BASES
from src.intelligence.schemas import BarIntelligenceRecord
from src.observability.metrics import counter, gauge, start_metrics_server

# ── Module-level constants ────────────────────────────────────────────────────

BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "feature_writer_group"
CONSUMER_NAME: str = "feature_writer_1"

# ── Module-level SQL ──────────────────────────────────────────────────────────

_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i2, i3, i4, i5, smc, i6, i7,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb,
    $16, $17, $18,
    $19, $20, $21,
    $22, $23, $24,
    $25, $26,
    $27, $28,
    $29, $30, $31
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

_UPSERT_ROLL_BOUNDARY_SQL = """
INSERT INTO intelligence_features (ts, symbol, tf, i7)
VALUES ($1::timestamptz, $2, $3, $4::jsonb)
ON CONFLICT (ts, symbol, tf) DO UPDATE SET i7 = intelligence_features.i7 || EXCLUDED.i7
"""

# Separate constant for cross-asset persistence — same JSONB merge semantics as roll
# boundary, but a distinct name so the two code paths can evolve independently.
_UPSERT_CROSS_ASSET_SQL = """
INSERT INTO intelligence_features (ts, symbol, tf, i7)
VALUES ($1::timestamptz, $2, $3, $4::jsonb)
ON CONFLICT (ts, symbol, tf) DO UPDATE SET i7 = intelligence_features.i7 || EXCLUDED.i7
"""

# Roll detection runs against 1m bars; boundary markers are written to the 1m row.
_ROLL_BOUNDARY_TF = "1m"

logger = structlog.get_logger(__name__)


def _parse_ts(ts_raw: str | bytes) -> datetime:
    """Parse an ISO 8601 timestamp string (or bytes) to a UTC-aware datetime.

    asyncpg requires a datetime object for timestamptz columns — raw strings
    cause a type_mismatch error at execute time.
    """
    if isinstance(ts_raw, bytes):
        ts_raw = ts_raw.decode()
    dt = datetime.fromisoformat(ts_raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ── Module-level pure functions (testable without class instantiation) ─────────


def _build_expiry_map(settings: Settings) -> dict[str, date]:
    """Build symbol → expiry date lookup at service startup. Call once; cache result.

    VX format "YYYYMM" → last calendar day of that month (conservative estimate).
    Non-futures (FX, CRYPTO) → omitted from map; _compute_days_to_expiry returns 0.
    Malformed expiry strings are silently skipped (symbol omitted, returns 0).
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

    Returns 0 for non-futures (symbol not in expiry_map: FX, crypto).
    Returns None if expiry_map is empty (service not yet initialized — signals uncached state).
    Clamps at 0: never returns negative (post-expiry rows get 0, not a negative value).
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
) -> tuple:
    """Build a 31-element tuple of INSERT parameters for _INSERT_FEATURE_SQL.

    Returns positional params matching $1..$31:
      $1  ts                       — datetime
      $2  symbol                   — str
      $3  tf                       — str
      $4  platform                 — str
      $5  source                   — str
      $6  schema_version           — str (from BarIntelligenceRecord)
      $7  bar                      — JSON string (jsonb)
      $8  i1                       — JSON string (jsonb)
      $9  i2                       — JSON string (jsonb)
      $10 i3                       — JSON string (jsonb)
      $11 i4                       — JSON string (jsonb)
      $12 i5                       — JSON string (jsonb)
      $13 smc                      — JSON string (jsonb)
      $14 i6                       — JSON string (jsonb)
      $15 i7                       — JSON string (jsonb) — full ranked_signals array
      $16 bar_close_ts             — datetime | None
      $17 i1_computed_at           — datetime | None
      $18 computed_at              — datetime | None
      $19 winner_plugin            — str | None
      $20 winner_confidence        — float | None
      $21 winner_direction         — str | None (cast from int)
      $22 signals_evaluated        — int
      $23 signals_after_quality    — int
      $24 signals_after_regime     — int
      $25 signals_after_tod        — int
      $26 signals_after_calibration — int
      $27 ledger_written           — bool
      $28 pipeline_latency_ms      — float
      $29 i7_computed_at           — datetime
      $30 session_type             — str
      $31 days_to_expiry           — int | None
    """
    event = record.intelligence
    days = _compute_days_to_expiry(event.symbol, event.ts, expiry_map or {})

    # winner_direction: int in schema, stored as text in DB
    winner_dir = str(record.winner_direction) if record.winner_direction is not None else None

    session_type_val = str(record.session_type)

    return (
        event.ts,  # $1 ts
        event.symbol,  # $2 symbol
        event.tf,  # $3 tf
        event.platform,  # $4 platform
        event.source,  # $5 source
        record.schema_version,  # $6 schema_version
        json.dumps(event.bar.model_dump()),  # $7 bar jsonb
        json.dumps(event.i1.model_dump()),  # $8 i1 jsonb
        json.dumps(event.i2.model_dump(exclude_none=True)),  # $9 i2 jsonb
        json.dumps(event.i3.model_dump(exclude_none=True)),  # $10 i3 jsonb
        json.dumps(event.i4.model_dump(exclude_none=True)),  # $11 i4 jsonb
        json.dumps(event.i5.model_dump(exclude_none=True)),  # $12 i5 jsonb
        json.dumps(event.smc.model_dump(exclude_none=True)),  # $13 smc jsonb
        json.dumps(event.i6.model_dump(exclude_none=True)),  # $14 i6 jsonb
        json.dumps([s.model_dump() for s in record.ranked_signals]),  # $15 i7 jsonb
        event.bar_close_ts,  # $16 bar_close_ts
        event.i1_computed_at,  # $17 i1_computed_at
        event.computed_at,  # $18 computed_at
        record.winner_plugin,  # $19 winner_plugin
        record.winner_confidence,  # $20 winner_confidence
        winner_dir,  # $21 winner_direction
        record.signals_evaluated,  # $22 signals_evaluated
        record.signals_after_quality,  # $23 signals_after_quality
        record.signals_after_regime,  # $24 signals_after_regime
        record.signals_after_tod,  # $25 signals_after_tod
        record.signals_after_calibration,  # $26 signals_after_calibration
        record.ledger_written,  # $27 ledger_written
        record.pipeline_latency_ms,  # $28 pipeline_latency_ms
        record.i7_computed_at,  # $29 i7_computed_at
        session_type_val,  # $30 session_type
        days,  # $31 days_to_expiry
    )


# ── Service class ─────────────────────────────────────────────────────────────


class FeatureWriterService:
    """Async Kafka consumer service: intelligence.record topic → buffer → batch INSERT to
    intelligence_features.

    Phase 44.3: Consumes development.intelligence.record only. Performs a single atomic
    INSERT per bar with all columns from BarIntelligenceRecord. No i7/i8 two-phase writes.
    """

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        self._kafka_consumer: KafkaConsumerClient | None = None
        self.db_manager: DatabaseManager | None = None

        self._buffer: list[tuple] = []
        self._last_flush: float = time.monotonic()

        try:
            _s = Settings()
            self._env_name: str = _s.env_name or ""
            self._kafka_bootstrap: str = getattr(_s, "kafka_bootstrap_servers", "localhost:19092")
        except Exception as e:
            self.logger.warning("Settings() failed — defaulting env/kafka to ''", error=str(e))
            self._env_name = ""
            self._kafka_bootstrap = "localhost:19092"

        # Prometheus metrics
        self.events_consumed_total = counter(
            "feature_writer_events_consumed_total",
            "Total BarIntelligenceRecords consumed from intelligence.record topic",
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
        self._parse_errors_total = counter(
            "feature_writer_parse_errors_total",
            "Total BarIntelligenceRecord parse failures",
        )

        self._total_events = 0
        self._total_batches = 0
        self._error_count = 0
        self._expiry_map: dict[str, date] = {}

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        metrics_port = self.config.get("service", {}).get("metrics_port", 9116)
        start_metrics_server(port=metrics_port)

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
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _connect_database(self) -> None:
        dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
        try:
            self.db_manager = DatabaseManager(dsn)
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

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

        # Build topics list
        topics = [
            topic_intelligence_record(self._env_name),
            topic_system_events(self._env_name),
            topic_cross_asset(self._env_name),
        ]

        # Single consumer subscribed to intelligence.record, system.events, and cross_asset
        self._kafka_consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self._kafka_bootstrap,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "Kafka consumer started",
            topics=topics,
            group=CONSUMER_GROUP,
        )

    def _parse_intelligence_record(self, raw: bytes | str) -> BarIntelligenceRecord | None:
        """Parse BarIntelligenceRecord from Kafka message bytes/str.

        Returns None on any failure — caller skips the message.
        """
        try:
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as e:
            self.logger.warning("parse_record_failed", error=str(e))
            self._parse_errors_total.inc()
            return None

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        payload: dict,
    ) -> bool:
        """Parse one Kafka message payload (BarIntelligenceRecord), buffer insert params."""
        try:
            # Extract raw JSON from payload dict (Kafka message value)
            # intelligence.record messages arrive as raw JSON (str or bytes)
            raw = payload if not isinstance(payload, dict) else json.dumps(payload).encode()
            if isinstance(raw, str):
                raw = raw.encode()

            record = self._parse_intelligence_record(raw)
            if record is None:
                self.logger.warning(
                    "Malformed BarIntelligenceRecord — skipped",
                    symbol=symbol,
                    tf=timeframe,
                )
                self.error_count_total.inc()
                return True

            params = _record_to_insert_params(record, self._expiry_map)
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
        - force=True (explicit flush, e.g. on shutdown)
        - time since last flush >= FLUSH_INTERVAL_SECS (time-based flush)
        - len(buffer) >= BATCH_SIZE (size-based safety net)
        """
        should_flush = force or (time.monotonic() - self._last_flush >= FLUSH_INTERVAL_SECS) or len(self._buffer) >= BATCH_SIZE

        if not self._buffer:
            return

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

        try:
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, params)
            # Explicitly commit offsets after successful DB persistence
            if getattr(self, "_kafka_consumer", None):
                await self._kafka_consumer.commit()
            
            # Remove all items from buffer after successful batch
            self._buffer.clear()
            self._last_flush = time.monotonic()
            self.batch_writes_total.inc()
            self._total_batches += 1
            self.events_buffered_gauge.set(0)
            self.logger.debug("Flushed intelligence_features batch", rows=len(params))
        except Exception as e:
            self.logger.error("Batch write failed", error=str(e), rows=len(params))
            # params remain in self._buffer for retry on next flush cycle
            self.error_count_total.inc()
            self._error_count += 1
            self.events_buffered_gauge.set(len(self._buffer))

    async def _handle_roll_event(self, event: dict) -> None:
        """Write roll boundary marker to intelligence_features on futures roll.

        Writes {"roll_boundary": "ESM6->ESU6"} into the i7 JSONB column at the
        roll detection timestamp. Uses ON CONFLICT ... DO UPDATE to merge into any
        existing i7 data for that (ts, symbol, tf) row.

        INTEL-04: Also writes roll_premium_pct to the intelligence_features column
        when the event payload includes it. roll_premium_pct is 0.0 at detection time
        (price comparison unavailable) — Phase 49 ML training treats this as
        "roll detected, gap unknown" vs NULL for "no roll context".
        """
        result = parse_roll_event(event, self.logger)
        if result is None:
            return
        old_symbol, new_symbol = result
        detected_at_raw: str = event.get("detected_at") or datetime.now(tz=UTC).isoformat()
        detected_at = _parse_ts(detected_at_raw)

        # INTEL-04: Extract roll_premium_pct from event payload (default None for backward compat)
        roll_premium_pct_raw = event.get("roll_premium_pct")
        roll_premium_pct: float | None = None
        if roll_premium_pct_raw is not None:
            try:
                roll_premium_pct = float(roll_premium_pct_raw)
            except (TypeError, ValueError):
                pass

        if not self.db_manager:
            self.logger.warning(
                "roll_boundary_skipped_no_db",
                old=old_symbol,
                new=new_symbol,
            )
            return

        marker = json.dumps({"roll_boundary": f"{old_symbol}->{new_symbol}"})
        try:
            await self.db_manager.execute_batch(
                _UPSERT_ROLL_BOUNDARY_SQL,
                [(detected_at, new_symbol, _ROLL_BOUNDARY_TF, marker)],
            )

            # INTEL-04: Persist roll_premium_pct to intelligence_features column
            if roll_premium_pct is not None:
                await self.db_manager.execute_query(
                    """
                    UPDATE intelligence_features
                       SET roll_premium_pct = $1
                     WHERE symbol = $2
                       AND ts = $3
                       AND tf = $4
                    """,
                    roll_premium_pct,
                    new_symbol,
                    detected_at,
                    _ROLL_BOUNDARY_TF,
                )

            # Explicitly commit after roll boundary write
            if self._kafka_consumer:
                await self._kafka_consumer.commit()

            self.logger.info(
                "roll_boundary_written",
                old=old_symbol,
                new=new_symbol,
                detected_at=detected_at,
                roll_premium_pct=roll_premium_pct,
            )
        except Exception as e:
            self.logger.error("roll_boundary_write_failed", error=str(e))
            self.error_count_total.inc()

    async def _process_cross_asset_message(self, payload: dict) -> None:
        """Persist cross-asset spread features to intelligence_features.

        Cross-asset features are group-level snapshots (not symbol-specific).
        They are persisted by merging into the i7 JSONB column for the most
        recent intelligence_features row matching this tf + group timestamp.
        Uses ON CONFLICT ... DO UPDATE to merge into any existing i7 data.
        """
        if not self.db_manager:
            return
        try:
            tf = payload.get("tf", "")
            ts_raw = payload.get("ts", "")
            if not tf or not ts_raw or not payload.get("ready"):
                return
            ts_dt = _parse_ts(ts_raw)
            cross_asset_data = json.dumps(
                {
                    "cross_asset": {
                        "es_nq_spread_z": payload.get("es_nq_spread_z"),
                        "es_rty_spread_z": payload.get("es_rty_spread_z"),
                        "eq_corr_break": payload.get("eq_corr_break"),
                        "eq_vol_imbalance": payload.get("eq_vol_imbalance"),
                        "active_pair": payload.get("active_pair"),
                        "pairs_confirming": payload.get("pairs_confirming"),
                        "data_quality_score": payload.get("data_quality_score"),
                        "low_vol_flag": payload.get("low_vol_flag"),
                    }
                }
            )
            # Persist cross-asset snapshot for each EQ_INDEX group member symbol
            params = [(ts_dt, sym, tf, cross_asset_data) for sym in _EQ_INDEX_BASES]
            await self.db_manager.execute_batch(_UPSERT_CROSS_ASSET_SQL, params)

            # Explicitly commit after cross-asset write
            if self._kafka_consumer:
                await self._kafka_consumer.commit()

            self.logger.debug(
                "cross_asset_persisted",

                tf=tf,
                ts=ts_raw,
                symbols=sorted(_EQ_INDEX_BASES),
            )
        except Exception as e:
            self.logger.warning("cross_asset_persist_failed", error=str(e))
            self.error_count_total.inc()

    async def _process_loop(self) -> None:
        """Kafka consumer loop — reads intelligence.record topic and routes by topic."""
        if not self._kafka_consumer:
            return

        intelligence_record_topic = topic_intelligence_record(self._env_name)
        sys_events_topic = topic_system_events(self._env_name)
        cross_asset_topic = topic_cross_asset(self._env_name)

        async for kafka_topic, key, payload in self._kafka_consumer.messages():
            if self.shutdown_requested:
                break
            try:
                # Route system.events to roll handler (no symbol/tf key required)
                if kafka_topic == sys_events_topic:
                    await self._handle_roll_event(payload)
                    continue

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

                if kafka_topic == intelligence_record_topic:
                    await self._process_single_message(symbol, timeframe, payload)
                    await self._maybe_flush(force=False)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
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

    async def _shutdown(self) -> None:
        """Graceful shutdown: flush buffer, close connections."""
        self.logger.info("Shutting down Feature Writer Service")
        self.shutdown_requested = True
        self.running = False

        # Flush remaining buffered records before closing
        await self._maybe_flush(force=True)
        self._buffer.clear()

        if self._kafka_consumer:
            await self._kafka_consumer.stop()
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
            await self._connect_database()
            await self._setup_kafka_clients()
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
