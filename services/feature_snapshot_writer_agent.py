#!/usr/bin/env python3
"""FeatureSnapshotWriterAgent — shadow persistence for parity validation.

Consumes BarIntelligenceRecord from intelligence.journal under consumer group
'feature_snapshot_writer_group' (separate from 'feature_writer_group') and writes
to feature_snapshots_shadow. ParityAuditorAgent (Phase 52.5) will compare both
tables to certify that FeatureRepository produces identical results to
FeatureWriterAgent before primary-write cutover.

Architecture:
    intelligence.journal topic
      ├── feature_writer_group         -> intelligence_features       (existing primary)
      └── feature_snapshot_writer_group -> feature_snapshots_shadow   (this agent)

Design invariant: this agent is intentionally thin — no business logic.
All param-building is delegated to _record_to_insert_params() from feature_writer_agent.

Renaissance principle: Shadow before cutover. Earn the right through proof.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pydantic import ValidationError

from services.feature_writer_agent import _build_expiry_map, _record_to_insert_params
from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import topic_intelligence_journal, topic_system_events
from src.intelligence.schemas import BarIntelligenceRecord
from src.observability.metrics import counter
from src.persistence.repository.feature_repository import FeatureRepository

# ── Module-level constants ────────────────────────────────────────────────────

CONSUMER_GROUP: str = "feature_snapshot_writer_group"
SHADOW_TABLE: str = "feature_snapshots_shadow"
METRICS_PORT: int = 9132


class FeatureSnapshotWriterAgent(BaseWriterAgent):
    """Shadow writer: intelligence.journal -> feature_snapshots_shadow.

    Inherits BaseWriterAgent for buffer/flush/commit/DLQ pattern.
    Keeps custom _run() because payloads are raw bytes (not dicts) and
    the agent filters topics (skipping system.events).
    """

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 5.0

    def __init__(self) -> None:
        super().__init__(
            name="FeatureSnapshotWriterAgent",
            metrics_port=METRICS_PORT,
        )

        self._expiry_map: dict = {}
        self._db: DatabaseManager | None = None
        self._repo: FeatureRepository | None = None

        self._events_consumed = counter(
            "feature_snapshot_writer_events_consumed_total",
            "BarIntelligenceRecords consumed by FeatureSnapshotWriterAgent",
        )
        self._shadow_writes = counter(
            "feature_snapshot_writer_shadow_writes_total",
            "Rows written to feature_snapshots_shadow",
        )
        self._parse_errors = counter(
            "feature_snapshot_writer_parse_errors_total",
            "BarIntelligenceRecord parse failures",
        )
        self._write_errors = counter(
            "feature_snapshot_writer_write_errors_total",
            "Shadow write failures",
        )

    def _topic_name(self) -> str:
        return topic_intelligence_journal(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    def _parse_payload(self, payload: dict) -> list | None:
        """Not used — _run() parses raw bytes directly."""
        return None

    async def _flush_batch(self, batch: list) -> None:
        """Write batch to shadow table. Clears buffer on error (shadow — no retry)."""
        assert self._repo is not None
        await self._repo.insert_batch(batch)
        self._shadow_writes.inc(len(batch))

    async def _do_flush(self) -> None:
        """Override: shadow table clears buffer on error instead of retrying."""
        if not self._buffer:
            return
        batch = self._buffer[:]
        try:
            await self._flush_batch(batch)
            self._buffer.clear()
            self._buffer_depth_gauge.set(0)
            if self._consumer and hasattr(self._consumer, "commit"):
                await self._consumer.commit()
        except Exception:
            self._flush_errors_total.inc()
            self.logger.exception("shadow_write_failed", rows=len(batch))
            self._buffer.clear()  # shadow table — drop on failure, don't retry

    def _parse_record(self, raw: bytes | str) -> BarIntelligenceRecord | None:
        try:
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
            self._parse_errors.inc()
            return None

    async def _setup(self) -> None:
        # Build expiry map (same as FeatureWriterAgent)
        try:
            self._expiry_map = _build_expiry_map(self.settings)
            self.logger.info("expiry_map_built", contracts=len(self._expiry_map))
        except Exception as exc:
            self.logger.warning("expiry_map_failed", error=str(exc))

        # DB connection -> shadow repository
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = FeatureRepository(self._db, table_name=SHADOW_TABLE)

        # Kafka consumer — distinct group so offsets are tracked independently
        self._create_consumer(
            topics=[
                topic_intelligence_journal(self.settings.env_name),
                topic_system_events(self.settings.env_name),
            ]
        )
        await self._consumer.start()
        await self._consumer.skip_lag_if_needed(max_lag=1000)
        self.logger.info(
            "snapshot_writer_consumer_started",
            topic=self._topic_name(),
            group=CONSUMER_GROUP,
        )

    async def _run(self) -> None:
        """Custom loop: raw bytes payloads, topic filtering."""
        assert self._consumer is not None
        _journal_topic = topic_intelligence_journal(self.settings.env_name)

        async for topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                if topic != _journal_topic:
                    continue  # skip system.events on this consumer

                raw = payload if isinstance(payload, (bytes, str)) else str(payload)
                record = self._parse_record(raw)
                if record is None:
                    continue

                params = _record_to_insert_params(record, self._expiry_map)
                self._buffer_rows([params])
                self._events_consumed.inc()

                await self.maybe_flush()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("consume_loop_error", error=str(exc))

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = FeatureSnapshotWriterAgent()
    asyncio.run(agent.start())
