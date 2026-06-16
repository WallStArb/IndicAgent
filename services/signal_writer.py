#!/usr/bin/env python3
"""Signal Writer Agent — persists I7 signals to signal_events/trade_frames (3-table schema).

Subscribes to intelligence.i7.signals (published by IntelligencePipeline
after each bar's I7 run). Groups signals by signal_id (G0 contract), builds
one signal_events row + N trade_frames rows per group, and inserts atomically
via SignalEventsRepository.

WriterAgent role: DB-only, zero compute. No plugin execution.
Consumer group: signal_writer_group
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import timedelta

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.config_service import ConfigService
from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import parse_iso_ts, tf_to_seconds
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_signal_writer_dlq,
)
from src.intelligence.trading.signal_schema import validate_signal
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    counter,
)
from src.persistence.repository.signal_events_repository import (
    SignalEventsRepository,
)

CONSUMER_GROUP = "signal_writer_group"


class SignalWriter(BaseWriter):
    """WriterAgent: intelligence.i7.signals -> signal_events + trade_frames.

    Consumes I7 signals, groups by signal_id (G0 contract), and inserts
    one signal_events row + N trade_frames rows per group atomically.
    DB-only, zero compute — no plugin execution.
    """

    def __init__(self) -> None:
        super().__init__(
            max_idle_seconds=300,
        )

        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        self._repo: SignalEventsRepository | None = None
        self._invalid_signals: list[dict] = []
        self._config: ConfigService | None = None

        # Metrics — Golden Signals (writer-specific, not provided by base class)
        self._events_consumed = counter(
            "signal_writer_events_consumed_total",
            "Kafka messages consumed",
        )
        self._signals_written = counter(
            "signal_writer_signals_written_total",
            "signal_events rows inserted",
        )
        self._write_errors = counter(
            "signal_writer_write_errors_total",
            "Failed batch inserts",
        )
        self._batch_latency_attrs = {"agent_id": self._agent_label}

    def _topic_name(self) -> str:
        return topic_intelligence_i7_signals(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    def _dlq_topic(self) -> str | None:
        """Route unparseable signal payloads to DLQ."""
        return topic_signal_writer_dlq(self.settings.env_name)

    def _on_message_consumed(self, payload: dict) -> None:
        self._events_consumed.add(1)

    def _parse_payload(self, payload: dict) -> tuple[list, list]:
        """Parse intelligence.i7.signals payload using G0 grouping.

        Groups signals by signal_id. Each group produces one (signal_event, trade_frames)
        tuple representing one signal_events row + N trade_frames rows.

        Returns ([], []) for empty payloads — skip silently.
        Returns ([], [payload]) when all signals are invalid — triggers DLQ.
        """
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")
        signals: list[dict] = payload.get("signals", [])

        # Empty payload — skip silently
        if not signals:
            return [], []

        valid_sigs: list[dict] = []
        invalid_sigs: list[dict] = []
        for sig in signals:
            if validate_signal(sig):
                valid_sigs.append(sig)
            else:
                invalid_sigs.append(sig)

        if invalid_sigs:
            self._invalid_signals.extend(invalid_sigs)
            self.logger.warning(
                "signal_writer.invalid_signals_partitioned",
                count=len(invalid_sigs),
                symbol=symbol,
                tf=tf,
            )

        if not valid_sigs:
            return [], [payload]

        rows = _payload_to_grouped_rows({**payload, "signals": valid_sigs})
        if not rows:
            return [], [payload]
        return rows, []

    async def _flush_batch(self, batch: list) -> None:
        """Write buffered (signal_event, trade_frames) groups to the 3-table schema."""
        invalid = self._invalid_signals[:]
        self._invalid_signals.clear()
        for sig in invalid:
            await self._send_to_dlq(sig, ValueError("validate_signal failed"))

        t0 = time.perf_counter()
        assert self._repo is not None
        for signal_event, trade_frames in batch:
            await self._repo.insert_signal_with_frames(signal_event, trade_frames)
        self._signals_written.add(len(batch))
        PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
        self.logger.info("signal_writer.flushed", count=len(batch))

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = SignalEventsRepository(self._db)

        # Load APR batch/flush/buffer constants (D-12 mandate)
        self._config = ConfigService(self.settings.database_url, pool=self._db.pool)
        self.BATCH_SIZE = int(
            await self._config.get("feature.signal_writer.batch_size", default=100)
        )
        self.FLUSH_INTERVAL_SECS = float(
            await self._config.get("feature.signal_writer.flush_interval_secs", default=5.0)
        )
        self.MAX_BUFFER_SIZE = int(
            await self._config.get("feature.signal_writer.max_buffer_size", default=10000)
        )
        # Sync overflow threshold used by _buffer_rows() overflow guard
        self._overflow_threshold = self.MAX_BUFFER_SIZE

        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info(
            "signal_writer.started",
            topic=self._topic_name(),
            batch_size=self.BATCH_SIZE,
            flush_interval=self.FLUSH_INTERVAL_SECS,
        )

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._db:
            await self._db.close()


def _direction_text(direction_val: int | str) -> str:
    """Convert direction integer (1/-1) or existing text to 'long'/'short'."""
    if isinstance(direction_val, str):
        return direction_val
    return "long" if int(direction_val) == 1 else "short"


def _payload_to_grouped_rows(payload: dict) -> list[tuple[dict, list[dict]]]:
    """Apply G0 grouping: group signals by signal_id, return (signal_event, trade_frames) tuples.

    Each tuple represents one signal_events row and N trade_frames rows (one per entry_type).
    All signals with the same signal_id share detection fields — the first signal in each
    group is used as the canonical source for signal_events detection-layer fields.

    Args:
        payload: Kafka message payload with symbol, tf, bar_ts, computed_at, signals.

    Returns:
        List of (signal_event dict, trade_frames list) tuples, one per unique signal_id.
    """
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    computed_at = parse_iso_ts(payload.get("computed_at"))
    bar_ts = parse_iso_ts(payload.get("bar_ts")) or computed_at

    if not signals:
        return []

    # G0 grouping: group signals by signal_id
    # Multiple signals with the same signal_id = same plugin fire, different entry_types
    groups: dict[str, list[dict]] = defaultdict(list)
    for sig in signals:
        raw_sid = sig.get("signal_id")
        if not raw_sid:
            raise ValueError(
                f"signal_writer: signal missing signal_id — "
                f"setup_plugin={sig.get('setup_plugin')!r} symbol={sig.get('symbol')!r}"
            )
        groups[str(raw_sid)].append(sig)

    rows: list[tuple[dict, list[dict]]] = []
    for signal_id, group_signals in groups.items():
        # Use first signal in group for detection-layer fields (all share same detection)
        detection = group_signals[0]

        # Direction: convert int 1/-1 to text "long"/"short" (signal_events.direction is TEXT)
        direction_text = _direction_text(detection.get("direction", 1))

        # Status: pending unless already regime_suppressed
        status = (
            "regime_suppressed" if detection.get("status") == "regime_suppressed" else "pending"
        )

        # TTL expiry calculation
        ttl = detection.get("ttl_bars")
        expires_at_val = None
        if (
            isinstance(ttl, int)
            and not isinstance(ttl, bool)
            and ttl > 0
            and tf
            and bar_ts is not None
        ):
            try:
                expires_at_val = bar_ts + timedelta(seconds=ttl * tf_to_seconds(tf))
            except (OverflowError, TypeError):
                expires_at_val = None

        # Build signal_events detection row
        signal_event: dict = {
            "signal_id": signal_id,
            "ts": bar_ts,
            "symbol": symbol,
            "tf": tf,
            "setup_plugin": str(detection.get("setup_plugin", "unknown")),
            "direction": direction_text,
            # raw_confidence: prefer pre_quality_confidence (ICC before calibration)
            "raw_confidence": detection.get("pre_quality_confidence")
            or detection.get("confidence")
            or 0.0,
            "calibrated_confidence": detection.get("calibrated_confidence"),
            "cis_score": detection.get("filtered_cis_score"),
            "weights_version": detection.get("weights_version"),
            # ECL extrinsic vectors (Phase 123 fields)
            "factor_scores": detection.get("factor_scores"),
            "context_features": detection.get("context_features"),
            "ctf_score": detection.get("ctf_score"),
            "ctf_confirmed": detection.get("ctf_confirmed"),
            "zone_friction_score": detection.get("zone_friction_score"),
            # Regime + volatility context
            "hmm_regime_at_fire": detection.get("hmm_regime_at_fire"),
            "plugin_regime_type": detection.get("plugin_regime_type"),
            "garch_sigma_at_fire": detection.get("garch_sigma_at_fire"),
            # Classification flags
            "is_shadow": bool(detection.get("is_shadow", False)),
            "is_backfill": bool(detection.get("is_backfill", False)),
            "status": status,
            # signal_schema_version: int constant — no str() (Pitfall 7)
            # SIGNAL_SCHEMA_VERSION injected by repository.insert_signal_with_frames
            # Lifecycle timing
            "ttl_bars": ttl,
            "expires_at": expires_at_val,
            "signal_computed_at": computed_at,
            "feature_ts": bar_ts,
        }

        # Build trade_frames rows — one per signal in group (one per entry_type)
        # concurrent_signal_count and concurrent_plugins left NULL (Pitfall 5 / D-08 / v2.11)
        trade_frames: list[dict] = []
        for sig in group_signals:
            # Stop architecture fields into frame_details JSONB
            frame_details: dict = {}
            for key in (
                "stop_basis",
                "stop_type",
                "structural_stop_distance_atr",
                "adaptive_buffer_mult",
                "stop_structure_age_bars",
            ):
                val = sig.get(key)
                if val is not None:
                    # Normalize key for frame_details (stop_type → stop_type_col in old schema)
                    frame_key = "stop_type_col" if key == "stop_type" else key
                    frame_details[frame_key] = val
            for zone_key in ("entry_zone_low", "entry_zone_high"):
                val = sig.get(zone_key) or sig.get("zone_low" if "low" in zone_key else "zone_high")
                if val is not None:
                    frame_details[zone_key] = val

            # Targets: first element is the primary target_price; list preserved for evaluate_signal
            targets = sig.get("targets") or []
            target_price = targets[0] if targets else None

            trade_frames.append(
                {
                    "entry_type": str(sig.get("entry_type", "at_close")),
                    "direction": direction_text,
                    "entry_price": sig.get("entry_price"),
                    "stop_price": sig.get("stop_loss"),
                    "target_price": target_price,
                    "r_multiple": None,
                    "ttl_bars": ttl,
                    "expires_at": expires_at_val,
                    "was_selected": bool(sig.get("was_selected", False)),
                    "frame_details": frame_details if frame_details else None,
                }
            )

        rows.append((signal_event, trade_frames))
    return rows


if __name__ == "__main__":
    agent = SignalWriter()
    asyncio.run(agent.start())
