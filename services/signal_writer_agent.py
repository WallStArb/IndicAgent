#!/usr/bin/env python3
"""Signal Writer Agent — persists all I7 signals to signal_ledger hypertable.

Subscribes to intelligence.i7.signals (published by IntelligencePipelineComputeAgent
after each bar's I7 run). Converts signal dicts to LedgerEntry objects and
batch-inserts to signal_ledger via SignalLedgerRepository.

WriterAgent role: DB-only, zero compute. No plugin execution.
Consumer group: signal_writer_group
Metrics port: 9119
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_intelligence_i7_signals
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    gauge,
)
from src.persistence.repository.signal_ledger_repository import (
    LedgerEntry,
    SignalLedgerRepository,
    SignalStatus,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "signal_writer_group"
BATCH_SIZE = 100  # flush after this many LedgerEntry rows
FLUSH_INTERVAL_SECS = 5.0  # or after this many seconds, whichever comes first
MAX_BUFFER_SIZE = 10_000  # drop oldest entries if buffer exceeds this (memory safety)


class SignalWriterAgent(BaseAgent):
    """WriterAgent: intelligence.i7.signals → signal_ledger."""

    def __init__(self) -> None:
        super().__init__(name="signal_writer_agent", metrics_port=9119)
        setup_service_logging("logs/signal_writer_agent.log")

        self._settings = Settings()
        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalLedgerRepository | None = None
        self._buffer: list[LedgerEntry] = []
        self._last_flush: float = 0.0

        # Metrics — Golden Signals
        self._events_consumed = counter(
            "signal_writer_events_consumed_total",
            "Kafka messages consumed",
        )
        self._signals_written = counter(
            "signal_writer_signals_written_total",
            "LedgerEntry rows inserted",
        )
        self._write_errors = counter(
            "signal_writer_write_errors_total",
            "Failed batch inserts",
        )
        self._buffer_dropped = counter(
            "signal_writer_buffer_dropped_total",
            "Entries dropped due to buffer overflow",
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(
            agent_id="signal_writer_agent"
        )
        self._consumer_lag = PERSISTENCE_CONSUMER_LAG.labels(
            agent_id="signal_writer_agent"
        )
        self._buffer_depth = gauge(
            "signal_writer_buffer_depth",
            "Pending LedgerEntry rows awaiting flush",
        )

    async def _setup(self) -> None:
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        topic = topic_intelligence_i7_signals(self._settings.env_name)
        self._consumer = KafkaConsumerClient(
            topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("signal_writer.started", topic=topic)

    async def _run(self) -> None:
        async for _topic, _key, payload in self._consumer.messages():
            if not isinstance(payload, dict):
                continue
            self._events_consumed.inc()

            self._buffer.extend(_payload_to_ledger_entries(payload))

            # Memory safety: drop oldest entries if buffer exceeds MAX_BUFFER_SIZE
            if len(self._buffer) > MAX_BUFFER_SIZE:
                dropped = len(self._buffer) - MAX_BUFFER_SIZE
                self._buffer = self._buffer[-MAX_BUFFER_SIZE:]
                self._buffer_dropped.inc(dropped)
                self.logger.warning("signal_writer.buffer_overflow", dropped=dropped)

            self._buffer_depth.set(len(self._buffer))

            now = time.monotonic()
            if len(self._buffer) >= BATCH_SIZE or (now - self._last_flush) >= FLUSH_INTERVAL_SECS:
                await self._flush()
                self._last_flush = now

    async def _flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer[:]
        t0 = time.perf_counter()
        try:
            await self._repo.insert_signals(batch)
            self._buffer.clear()
            self._buffer_depth.set(0)
            self._signals_written.inc(len(batch))
            self._batch_latency.observe(time.perf_counter() - t0)
            self.logger.info("signal_writer.flushed", count=len(batch))
        except Exception as exc:
            self._write_errors.inc()
            self.logger.error("signal_writer.flush_error", error=str(exc))

    async def _teardown(self) -> None:
        if self._buffer:
            await self._flush()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


def _payload_to_ledger_entries(payload: dict) -> list[LedgerEntry]:
    """Convert an intelligence.i7.signals payload to a list of LedgerEntry objects."""
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    computed_at = _parse_ts(payload.get("computed_at"))
    bar_ts = _parse_ts(payload.get("bar_ts")) or computed_at

    if not signals:
        return []

    entries: list[LedgerEntry] = []
    num_signals = len(signals)
    for sig in signals:
        status = (
            SignalStatus.REGIME_SUPPRESSED
            if sig.get("status") == "regime_suppressed"
            else SignalStatus.PENDING
        )
        entries.append(
            LedgerEntry(
                signal_id=str(sig.get("signal_id") or uuid4()),
                timestamp=bar_ts,
                symbol=symbol,
                timeframe=tf,
                setup_plugin=str(sig.get("setup_plugin", "unknown")),
                signal_type=str(sig.get("signal_type", "unknown")),
                direction=int(sig.get("direction", 0)),
                entry_price=float(sig.get("entry_price", 0.0)),
                stop_loss=float(sig.get("stop_loss", 0.0)),
                targets=[float(t) for t in (sig.get("targets") or [])],
                confidence=float(sig.get("confidence", 0.0)),
                confluence_score=float(sig.get("confluence_score", 0.0)),
                regime_context=str(sig.get("regime_context", "")),
                supporting_factors=list(sig.get("supporting_factors") or []),
                was_selected=bool(sig.get("was_selected", False)),
                num_signals_bar=int(sig.get("num_signals_bar", num_signals)),
                num_agreeing=0,
                num_conflicting=0,
                resolution_method="in_process",
                composite_rank=int(sig.get("composite_rank", 0)),
                status=status,
                feature_ts=bar_ts,
                feature_tf=tf,
                signal_computed_at=computed_at,
                hmm_regime_at_fire=sig.get("hmm_regime_at_fire"),
                regime_type_at_fire=str(sig.get("regime_type", "")) or None,
                is_shadow=bool(sig.get("is_shadow", False)),
                pre_quality_confidence=sig.get("pre_quality_confidence"),
                pre_calibration_confidence=sig.get("pre_calibration_confidence"),
                cis_score=sig.get("filtered_cis_score"),
                raw_cis_score=sig.get("raw_cis_score"),
                filtered_cis_score=sig.get("filtered_cis_score"),
                bucket_scores=sig.get("bucket_scores"),
                weights_version=sig.get("weights_version"),
            )
        )
    return entries


def _parse_ts(value: str | None) -> datetime | None:
    """Parse ISO-8601 timestamp string to timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    agent = SignalWriterAgent()
    asyncio.run(agent.start())
