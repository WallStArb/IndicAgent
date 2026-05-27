#!/usr/bin/env python3
"""Signal Writer Agent — persists all I7 signals to signal_ledger hypertable.

Subscribes to intelligence.i7.signals (published by IntelligencePipelineComputeAgent
after each bar's I7 run). Converts signal dicts to LedgerEntry objects and
batch-inserts to signal_ledger via SignalLedgerRepository.

WriterAgent role: DB-only, zero compute. No plugin execution.
Consumer group: signal_writer_group
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import parse_iso_ts
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_signal_writer_dlq,
)
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION, validate_signal
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    counter,
)
from src.persistence.repository.signal_ledger_repository import (
    LedgerEntry,
    SignalLedgerRepository,
    SignalStatus,
)

CONSUMER_GROUP = "signal_writer_group"


class SignalWriterAgent(BaseWriterAgent):
    """WriterAgent: intelligence.i7.signals -> signal_ledger.

    Consumes I7 signals and batch-inserts them to signal_ledger hypertable.
    DB-only, zero compute — no plugin execution.
    """

    BATCH_SIZE = 100
    FLUSH_INTERVAL_SECS = 5.0
    MAX_BUFFER_SIZE = 10_000

    def __init__(self) -> None:
        super().__init__(
            name="signal_writer_agent",
            max_idle_seconds=300,
        )

        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalLedgerRepository | None = None
        self._invalid_signals: list[dict] = []

        # Metrics — Golden Signals (writer-specific, not provided by base class)
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
        self._batch_latency_attrs = {"agent_id": "signal_writer_agent"}

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

    def _parse_payload(self, payload: dict) -> list | None:
        """Parse intelligence.i7.signals payload into LedgerEntry objects.

        Returns None for truly empty payloads (triggers DLQ via base class).
        Returns [] when all signals are invalid (prevents double-DLQ).
        """
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")
        signals: list[dict] = payload.get("signals", [])

        # Empty payload — base class will DLQ the whole message
        if not signals:
            return None

        valid: list[dict] = []
        invalid: list[dict] = []
        for sig in signals:
            if validate_signal(sig):
                valid.append(sig)
            else:
                invalid.append(sig)

        if invalid:
            self._invalid_signals.extend(invalid)
            self.logger.warning(
                "signal_writer.invalid_signals_partitioned",
                count=len(invalid),
                symbol=symbol,
                tf=tf,
            )

        rows = _payload_to_ledger_entries({**payload, "signals": valid})
        # Return [] when all signals invalid — prevents double-DLQ
        return rows if rows else []

    async def _flush_batch(self, batch: list) -> None:
        invalid = self._invalid_signals[:]
        self._invalid_signals.clear()
        for sig in invalid:
            await self._send_to_dlq(sig, ValueError("validate_signal failed"))

        t0 = time.perf_counter()
        assert self._repo is not None
        await self._repo.insert_signals(batch)
        self._signals_written.add(len(batch))
        PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
        self.logger.info("signal_writer.flushed", count=len(batch))

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("signal_writer.started", topic=self._topic_name())

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


def _payload_to_ledger_entries(payload: dict) -> list[LedgerEntry]:
    """Convert an intelligence.i7.signals payload to a list of LedgerEntry objects.

    Args:
        payload: Kafka message payload with symbol, tf, bar_ts, computed_at, signals

    Returns:
        List of LedgerEntry objects ready for database insertion.
    """
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    computed_at = parse_iso_ts(payload.get("computed_at"))
    bar_ts = parse_iso_ts(payload.get("bar_ts")) or computed_at

    if not signals:
        return []

    entries: list[LedgerEntry] = []
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
                was_selected=bool(sig.get("was_selected", False)),
                status=status,
                feature_ts=bar_ts,
                feature_tf=tf,
                signal_computed_at=computed_at,
                hmm_regime_at_fire=sig.get("hmm_regime_at_fire"),
                garch_sigma_at_fire=sig.get("garch_sigma_at_fire"),
                is_shadow=bool(sig.get("is_shadow", False)),
                signal_schema_version=sig.get("signal_schema_version", SIGNAL_SCHEMA_VERSION),
                is_backfill=bool(sig.get("is_backfill", False)),
                ttl_bars=sig.get("ttl_bars"),
                entry_price=sig.get("entry_price"),
                stop_loss=sig.get("stop_loss"),
                targets=sig.get("targets") or None,
                entry_zone_low=sig.get("zone_low"),
                entry_zone_high=sig.get("zone_high"),
                # cis_score column stores the filtered (regime-adjusted) score that drives ranking,
                # not raw_cis_score. Both are stamped by signal_processor.
                cis_score=sig.get("filtered_cis_score"),
                bucket_scores=sig.get("bucket_scores"),
                weights_version=sig.get("weights_version"),
            )
        )
    return entries


if __name__ == "__main__":
    agent = SignalWriterAgent()
    asyncio.run(agent.start())
