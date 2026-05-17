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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "signal_writer_group"


class SignalWriterAgent(BaseWriterAgent):
    """WriterAgent: intelligence.i7.signals -> signal_ledger."""

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
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")
        signals: list[dict] = payload.get("signals", [])

        # Empty payload — base class will DLQ the whole message via _maybe_route_to_dlq
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
        # Return [] (not None) when all signals are invalid — prevents the base writer
        # from double-DLQ-ing the whole payload via _maybe_route_to_dlq.
        # The per-signal DLQ records in self._invalid_signals are drained in _flush_batch.
        return rows if rows else []

    async def _flush_batch(self, batch: list) -> None:
        for sig in self._invalid_signals:
            await self._send_to_dlq(sig, ValueError("validate_signal failed"))
        self._invalid_signals.clear()

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
    """Convert an intelligence.i7.signals payload to a list of LedgerEntry objects."""
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    computed_at = parse_iso_ts(payload.get("computed_at"))
    bar_ts = parse_iso_ts(payload.get("bar_ts")) or computed_at

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
                num_agreeing=int(sig.get("num_agreeing", 0)),
                num_conflicting=int(sig.get("num_conflicting", 0)),
                resolution_method=str(sig.get("resolution_method", "in_process")),
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
                entry_zone_low=sig.get("zone_low"),
                entry_zone_high=sig.get("zone_high"),
                signal_schema_version=sig.get("signal_schema_version", SIGNAL_SCHEMA_VERSION),
                entry_type=sig.get("entry_type"),
                co_fire_count=sig.get("co_fire_count", 1),
                co_fire_partners=sig.get("co_fire_partners", []),
                market_price_at_signal=sig.get("market_price_at_signal"),
                market_entry_price=sig.get("market_entry_price"),
                features_snapshot=sig.get("features_snapshot") or None,
                is_backfill=bool(sig.get("is_backfill", False)),
                ttl_bars=sig.get("ttl_bars"),
            )
        )
    return entries


if __name__ == "__main__":
    agent = SignalWriterAgent()
    asyncio.run(agent.start())
