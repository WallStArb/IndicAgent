#!/usr/bin/env python3
"""BarWriterAgent — dedicated OHLCV persistence agent.

Subscribes to market.bars (1m) + market.bars.htf (5m-1d), batch-writes
to market_data_ohlcv with ON CONFLICT DO NOTHING for idempotent writes.

Decouples bar persistence from the feature compute hot path (D-02 through D-07).

Metrics port: :9121

Golden Signals (D-06):
- Traffic: events_consumed_total, bars_written_total{tf}
- Latency: persistence_batch_latency_seconds
- Errors: write_errors_total, conflict_skips_total
- Saturation: persistence_consumer_lag

Version: 1.0.0
Last Updated: 2026-03-28
Status: Phase 053.1 Plan 01
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.stream_keys import topic_market_bars, topic_market_bars_htf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BATCH_SIZE: int = 50
_FLUSH_INTERVAL: float = 5.0

_INSERT_OHLCV_SQL: str = """
INSERT INTO market_data_ohlcv (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""

# All TF labels we pre-cache labeled Counter children for
_BAR_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

# Module-level metric objects — prevents duplicate registration if the agent class
# is imported more than once in the same process (e.g., unit tests without isolation)
_EVENTS_CONSUMED = Counter(
    "bar_writer_events_consumed_total",
    "Bar messages consumed from market.bars and market.bars.htf",
    ["agent"],
)
_BARS_WRITTEN = Counter(
    "bar_writer_bars_written_total",
    "OHLCV rows successfully written to market_data_ohlcv",
    ["agent", "tf"],
)
_BATCH_LATENCY = Histogram(
    "bar_writer_persistence_batch_latency_seconds",
    "Time to execute an executemany batch INSERT to market_data_ohlcv",
    ["agent"],
)
_WRITE_ERRORS = Counter(
    "bar_writer_write_errors_total",
    "Exceptions during batch INSERT — buffer left intact for retry",
    ["agent"],
)
_CONFLICT_SKIPS = Counter(
    "bar_writer_conflict_skips_total",
    "Bars skipped due to ON CONFLICT DO NOTHING (duplicate detection)",
    ["agent"],
)
_CONSUMER_LAG = Gauge(
    "bar_writer_persistence_consumer_lag",
    "Current unwritten buffer depth (proxy for consumer lag)",
    ["agent"],
)


class BarWriterAgent(BaseAgent):
    """Dedicated OHLCV persistence agent.

    Consumes 1m bars from topic_market_bars and HTF bars from
    topic_market_bars_htf. Batch-writes to market_data_ohlcv using
    ON CONFLICT DO NOTHING for idempotent, replay-safe inserts.

    WriterAgent — DB-access allowed (persistence responsibility).
    Cold-start: auto.offset.reset=latest (D-14).
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="bar_writer_agent", metrics_port=9121)

        self._kafka_consumer: KafkaConsumerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        self._buffer: list[tuple] = []
        self._last_flush: float = 0.0

        # Cache labeled children — avoids dict lookup on every bar
        self._events_consumed_lbl = _EVENTS_CONSUMED.labels(agent=self.name)
        self._persistence_batch_latency_lbl = _BATCH_LATENCY.labels(agent=self.name)
        self._write_errors_lbl = _WRITE_ERRORS.labels(agent=self.name)
        self._conflict_skips_lbl = _CONFLICT_SKIPS.labels(agent=self.name)
        self._persistence_consumer_lag_lbl = _CONSUMER_LAG.labels(agent=self.name)
        self._bars_written_lbl: dict[str, object] = {
            tf: _BARS_WRITTEN.labels(agent=self.name, tf=tf) for tf in _BAR_TFS
        }

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self._env_name), topic_market_bars_htf(self._env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return []

    async def _setup(self) -> None:
        """Connect asyncpg pool and Kafka consumer."""
        self._db_pool = await asyncpg.create_pool(self._settings.database_url)

        self._kafka_consumer = KafkaConsumerClient(
            topic_market_bars(self._env_name),
            topic_market_bars_htf(self._env_name),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="bar_writer_consumer",
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "bar_writer_agent.setup_complete",
            topics_consumed=self.topics_consumed,
        )

    async def _teardown(self) -> None:
        """Flush remaining buffer, stop consumer, close DB pool."""
        if self._buffer:
            await self._flush_buffer()
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Main loop: consume bars, buffer, flush on batch size or interval."""
        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break

            try:
                self._buffer_bar(payload)
                self._events_consumed_lbl.inc()
            except Exception as exc:
                self.logger.warning(
                    "bar_writer_agent.parse_failed",
                    error=str(exc),
                    payload_preview=str(payload)[:200],
                )
                continue

            # Flush if batch full or interval elapsed
            should_flush = len(self._buffer) >= _BATCH_SIZE or (
                self._buffer and time.monotonic() - self._last_flush > _FLUSH_INTERVAL
            )
            if should_flush:
                await self._flush_buffer()

            # Update consumer lag gauge (buffer depth as proxy)
            self._persistence_consumer_lag_lbl.set(len(self._buffer))

    def _buffer_bar(self, payload: dict) -> None:
        """Parse payload and append a 9-tuple to the write buffer.

        Tuple layout: (ts, symbol, tf, open, high, low, close, volume, source)
        source: "live_1m" for 1m bars, "live_htf" for all HTF bars (D-04).
        """
        bar = self._parse_bar(payload)
        if bar is None:
            return

        source = "live_1m" if bar.tf == "1m" else "live_htf"
        self._buffer.append((
            bar.ts,      # $1 timestamp — Python datetime (asyncpg requirement)
            bar.symbol,  # $2 symbol
            bar.tf,      # $3 timeframe
            bar.open,    # $4 open
            bar.high,    # $5 high
            bar.low,     # $6 low
            bar.close,   # $7 close
            bar.volume,  # $8 volume
            source,      # $9 source
        ))

    async def _flush_buffer(self) -> None:
        """Batch-write _buffer to market_data_ohlcv.

        Uses executemany for efficiency. ON CONFLICT DO NOTHING makes writes
        idempotent — safe on replay or duplicate delivery.

        On success: clears buffer, updates last_flush timestamp.
        On error: logs, increments error counter, leaves buffer intact for retry.
        """
        if not self._buffer:
            return

        batch = self._buffer[:]
        t0 = time.monotonic()
        try:
            async with self._db_pool.acquire() as conn:
                with self._persistence_batch_latency_lbl.time():
                    await conn.executemany(_INSERT_OHLCV_SQL, batch)

            # Increment per-tf write counters
            for row in batch:
                tf = row[2]
                if tf in self._bars_written_lbl:
                    self._bars_written_lbl[tf].inc()

            self._buffer.clear()
            self._last_flush = time.monotonic()
            self.logger.debug(
                "bar_writer_agent.flush_complete",
                batch_size=len(batch),
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )
        except Exception as exc:
            self._write_errors_lbl.inc()
            self.logger.error(
                "bar_writer_agent.flush_failed",
                error=str(exc),
                buffer_size=len(batch),
            )
            # Leave buffer intact for retry on next flush cycle

    def _parse_bar(self, payload: dict) -> BarMessage | None:
        """Parse a bar payload dict into a typed BarMessage.

        Tries model_validate first (canonical BarMessage dict).
        Falls back to manual field extraction for legacy DataProviderAgent format.

        Returns None when the payload cannot be parsed.
        """
        try:
            return BarMessage.model_validate(payload)
        except ValidationError:
            pass

        # Legacy / flat dict format from DataProviderAgent
        try:
            symbol = payload.get("symbol", "")
            tf = payload.get("tf") or payload.get("timeframe", "1m")
            if not symbol or not tf:
                return None

            ts_raw = payload.get("ts") or payload.get("timestamp")
            if ts_raw:
                ts = datetime.fromisoformat(str(ts_raw))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            else:
                ts = datetime.now(UTC)

            return BarMessage(
                ts=ts,
                symbol=symbol,
                tf=tf,
                open=float(payload.get("open", 0)),
                high=float(payload.get("high", 0)),
                low=float(payload.get("low", 0)),
                close=float(payload.get("close", 0)),
                volume=int(float(payload.get("volume", 0))),
                source=payload.get("source", "ibkr_named"),
                session_type=SessionType(payload.get("session_type", "rth")),
                gap_preceding=bool(payload.get("gap_preceding", False)),
                is_flat_bar=bool(payload.get("is_flat_bar", False)),
            )
        except Exception as exc:
            self.logger.warning(
                "bar_writer_agent.parse_failed",
                error=str(exc),
                payload_preview=str(payload)[:200],
            )
            return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = BarWriterAgent()
    await agent.start()


if __name__ == "__main__":
    from src.core.service_utils import setup_service_logging
    from src.observability.otel import init_tracing

    setup_service_logging("logs/bar_writer_agent.log")
    init_tracing("bar_writer_agent")
    asyncio.run(main())
