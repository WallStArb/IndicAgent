#!/usr/bin/env python3
"""CTX Writer Agent — persists qualitative context events to ctx_events and ctx_snapshots.

Consumes ctx.snapshot Kafka topic, validates event_type allowlist and payload size,
then batch-writes to both ctx_events (hypertable) and ctx_snapshots (upsert with
valid_to chaining).

WriterAgent role: DB-only, zero compute. No CTX evaluation or enrichment.
Consumer group: ctx_writer_group
"""

from __future__ import annotations

import asyncio
import json
import time

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.service_utils import parse_iso_ts, setup_service_logging
from src.core.stream_keys import topic_ctx_snapshot
from src.observability.metrics import counter
from src.observability.spans import ATTR_BATCH_SIZE, ATTR_FLUSH_MS, observed_span

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "ctx_writer_group"

_ALLOWED_EVENT_TYPES: frozenset[str] = frozenset({"earnings", "macro", "news"})
_MAX_PAYLOAD_BYTES: int = 64 * 1024  # 64 KiB


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_INSERT_CTX_EVENT_SQL = """
INSERT INTO ctx_events (event_ts, symbol, event_type, source, payload)
VALUES ($1, $2, $3, $4, $5)
"""

# Close out the currently-active snapshot for this (symbol, event_type) before
# inserting the new one — sets valid_to to the new row's valid_from.
_CLOSE_PRIOR_SNAPSHOT_SQL = """
UPDATE ctx_snapshots
   SET valid_to = $3
 WHERE symbol IS NOT DISTINCT FROM $1
   AND event_type = $2
   AND valid_to IS NULL
"""

_UPSERT_CTX_SNAPSHOT_SQL = """
INSERT INTO ctx_snapshots (symbol, event_type, valid_from, valid_to, ctx)
VALUES ($1, $2, $3, NULL, $4)
ON CONFLICT (symbol, event_type, valid_from) DO UPDATE
    SET ctx = EXCLUDED.ctx,
        valid_to = NULL
"""


class ContextWriter(BaseWriter):
    """WriterAgent: ctx.snapshot -> ctx_events + ctx_snapshots batch writes."""

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 10.0

    def __init__(self) -> None:
        super().__init__(
            name="ctx_writer_agent",
            max_idle_seconds=300,
        )

        self._db: DatabaseManager | None = None

        # Two separate buffers: one for event rows, one for snapshot upserts.
        self._event_buffer: list[tuple] = []
        self._snapshot_buffer: list[tuple] = []

        # Metrics — Golden Signals
        self._events_consumed = counter(
            "ctx_writer_events_consumed_total",
            "Kafka messages consumed by ContextWriter",
        )
        self._events_written = counter(
            "ctx_writer_events_written_total",
            "ctx_events rows written",
        )
        self._snapshots_written = counter(
            "ctx_writer_snapshots_written_total",
            "ctx_snapshots rows upserted",
        )
        self._validation_errors = counter(
            "ctx_writer_validation_errors_total",
            "Messages rejected by validation (event_type, payload size, missing keys)",
        )

    def _topic_name(self) -> str:
        return topic_ctx_snapshot(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    # -----------------------------------------------------------------------
    # Validation and parse
    # -----------------------------------------------------------------------

    def _parse_payload(self, payload: dict) -> dict | None:
        """Validate incoming CTX message.

        Returns the validated payload dict on success,
        or None to route to DLQ on validation failure.

        Threat model (from plan threat_model):
        - event_type must be in allowlist
        - payload JSON must not exceed _MAX_PAYLOAD_BYTES
        - event_ts, event_type, source, payload are required keys
        """
        # Required key check
        required_keys = {"event_ts", "event_type", "source", "payload"}
        missing = required_keys - payload.keys()
        if missing:
            self.logger.warning(
                "ctx_writer.rejected_missing_keys",
                missing=sorted(missing),
            )
            self._validation_errors.add(1)
            return None

        event_type = payload.get("event_type", "")
        if event_type not in _ALLOWED_EVENT_TYPES:
            self.logger.warning(
                "ctx_writer.rejected_disallowed_event_type",
                event_type=event_type,
                allowed=sorted(_ALLOWED_EVENT_TYPES),
            )
            self._validation_errors.add(1)
            return None

        inner_payload = payload.get("payload")
        if not isinstance(inner_payload, dict):
            self.logger.warning(
                "ctx_writer.rejected_payload_not_dict",
                event_type=event_type,
            )
            self._validation_errors.add(1)
            return None

        payload_bytes = len(json.dumps(inner_payload))
        if payload_bytes > _MAX_PAYLOAD_BYTES:
            self.logger.warning(
                "ctx_writer.rejected_payload_too_large",
                event_type=event_type,
                payload_bytes=payload_bytes,
                max_bytes=_MAX_PAYLOAD_BYTES,
            )
            self._validation_errors.add(1)
            return None

        return payload

    def _on_message_consumed(self, payload: dict) -> None:
        self._events_consumed.add(1)

    # -----------------------------------------------------------------------
    # Buffer routing — override _run() to split to two internal buffers
    # -----------------------------------------------------------------------

    async def _run(self) -> None:
        """Consume loop: route validated messages to event + snapshot buffers."""
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            if not isinstance(payload, dict):
                continue
            self._record_message_consumed()
            self._on_message_consumed(payload)

            msg = self._parse_payload(payload)
            if msg is None:
                self._parse_failures_total.add(1)
                await self._maybe_route_to_dlq(payload, Exception("Validation failed"))
                continue
            await self._process_message(msg)
            await self.maybe_flush()

    def _to_event_row(
        self,
        event_ts,
        symbol,
        event_type: str,
        source: str,
        inner_payload: dict,
    ) -> tuple:
        """Map CTX event fields to positional params for _INSERT_CTX_EVENT_SQL.

        Positions must match the $N placeholders in _INSERT_CTX_EVENT_SQL exactly.
        """
        return (
            event_ts,  # $1 event_ts::timestamptz
            symbol,  # $2 symbol::text (may be None for global events)
            event_type,  # $3 event_type::text
            source,  # $4 source::text
            inner_payload,  # $5 payload::jsonb
        )

    def _to_snapshot_row(
        self,
        symbol,
        event_type: str,
        valid_from,
        ctx_data: dict,
    ) -> tuple:
        """Map CTX snapshot fields to positional params for _UPSERT_CTX_SNAPSHOT_SQL.

        Positions must match the $N placeholders in _UPSERT_CTX_SNAPSHOT_SQL exactly.
        Note: valid_to is a NULL literal in the SQL, not a parameter.
        """
        return (
            symbol,  # $1 symbol::text (may be None for global snapshots)
            event_type,  # $2 event_type::text
            valid_from,  # $3 valid_from::timestamptz
            ctx_data,  # $4 ctx::jsonb
        )

    async def _process_message(self, msg: dict) -> None:
        """Buffer a validated CTX message into the event and (optionally) snapshot buffers.

        ctx_events row: always buffered.
        ctx_snapshots row: buffered only when msg contains valid_from + ctx keys.
        """
        event_ts_raw = msg.get("event_ts")
        symbol = msg.get("symbol")  # may be None (global event)
        event_type: str = msg["event_type"]
        source: str = msg["source"]
        inner_payload: dict = msg["payload"]

        # Parse event_ts to datetime for asyncpg
        try:
            event_ts = parse_iso_ts(event_ts_raw) if isinstance(event_ts_raw, str) else event_ts_raw
        except Exception:
            self.logger.warning(
                "ctx_writer.rejected_invalid_event_ts",
                event_ts=event_ts_raw,
                event_type=event_type,
            )
            self._validation_errors.add(1)
            return

        self._event_buffer.append(
            self._to_event_row(
                event_ts=event_ts,
                symbol=symbol,
                event_type=event_type,
                source=source,
                inner_payload=inner_payload,
            )
        )

        # Buffer ctx_snapshots UPSERT if message includes snapshot fields
        valid_from_raw = msg.get("valid_from")
        ctx_data = msg.get("ctx")
        if valid_from_raw is not None and ctx_data is not None:
            if not isinstance(ctx_data, dict):
                self.logger.warning(
                    "ctx_writer.snapshot_ctx_not_dict",
                    event_type=event_type,
                )
            else:
                try:
                    valid_from = (
                        parse_iso_ts(valid_from_raw)
                        if isinstance(valid_from_raw, str)
                        else valid_from_raw
                    )
                except Exception:
                    self.logger.warning(
                        "ctx_writer.rejected_invalid_valid_from",
                        valid_from=valid_from_raw,
                        event_type=event_type,
                    )
                    return
                self._snapshot_buffer.append(
                    self._to_snapshot_row(
                        symbol=symbol,
                        event_type=event_type,
                        valid_from=valid_from,
                        ctx_data=ctx_data,
                    )
                )

    def _should_flush(self) -> bool:
        """Check if either buffer warrants a flush."""
        if not self._event_buffer and not self._snapshot_buffer:
            return False
        now = time.monotonic()
        total = len(self._event_buffer) + len(self._snapshot_buffer)
        return total >= self.BATCH_SIZE or (now - self._last_flush) >= self.FLUSH_INTERVAL_SECS

    async def maybe_flush(self) -> None:
        if self._should_flush():
            await self._do_flush()
            self._last_flush = time.monotonic()

    async def _do_flush(self) -> None:
        """Flush both buffers in a single transaction."""
        if not self._event_buffer and not self._snapshot_buffer:
            return
        event_batch = self._event_buffer[:]
        snapshot_batch = self._snapshot_buffer[:]
        try:
            await self._flush(event_batch, snapshot_batch)
            self._event_buffer.clear()
            self._snapshot_buffer.clear()
            self._buffer_depth_gauge.set(0)
            if self._consumer and hasattr(self._consumer, "commit"):
                await self._consumer.commit()
        except Exception:
            self._flush_errors_total.add(1)
            self.logger.exception(
                "ctx_writer.flush_failed",
                events=len(event_batch),
                snapshots=len(snapshot_batch),
            )

    async def _flush(self, event_batch: list[tuple], snapshot_batch: list[tuple]) -> None:
        """Write both ctx_events rows and ctx_snapshot upserts in a single transaction.

        For each snapshot row: close the prior open snapshot (valid_to = new valid_from),
        then upsert the new snapshot row.
        """
        assert self._db is not None

        async with observed_span("writer.flush", tracer=self.tracer) as span:
            flush_start = time.monotonic()

            async with self._db.pool.acquire() as conn:
                async with conn.transaction():
                    # Write ctx_events
                    if event_batch:
                        await conn.executemany(_INSERT_CTX_EVENT_SQL, event_batch)
                        self._events_written.add(len(event_batch))
                        span.set_attribute(ATTR_BATCH_SIZE, len(event_batch))

                    # Upsert ctx_snapshots — batch close then batch insert (2 roundtrips, not N×2)
                    if snapshot_batch:
                        close_params = [(s, e, vf) for s, e, vf, _ in snapshot_batch]
                        upsert_params = list(snapshot_batch)
                        await conn.executemany(_CLOSE_PRIOR_SNAPSHOT_SQL, close_params)
                        await conn.executemany(_UPSERT_CTX_SNAPSHOT_SQL, upsert_params)
                        self._snapshots_written.add(len(snapshot_batch))
                        span.set_attribute("snapshot_batch_size", len(snapshot_batch))

            flush_ms = (time.monotonic() - flush_start) * 1000
            span.set_attribute(ATTR_FLUSH_MS, flush_ms)

            self.logger.info(
                "ctx_writer.flushed",
                events=len(event_batch),
                snapshots=len(snapshot_batch),
            )

    # BaseWriter requires _flush_batch — delegate to _flush with current buffers.
    async def _flush_batch(self, batch: list) -> None:
        """Required abstract method — actual flush is via _do_flush()/_flush()."""
        # This path is used by BaseWriter._do_flush when called from
        # the default _run() loop. In ContextWriter we override _run() and
        # _do_flush() directly, so this method is a no-op safety fallback.
        pass

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("ctx_writer.started", topic=self._topic_name())

    async def _teardown(self) -> None:
        await super()._teardown()  # drains self._buffer (generic) and stops lifecycle
        if self._event_buffer or self._snapshot_buffer:
            try:
                await self._flush(self._event_buffer[:], self._snapshot_buffer[:])
                self._event_buffer.clear()
                self._snapshot_buffer.clear()
            except Exception:
                self.logger.exception("ctx_writer.teardown_flush_failed")
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    setup_service_logging("logs/ctx_writer_agent.log")
    agent = ContextWriter()
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
