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

Version: 2.0.0
Last Updated: 2026-04-13
Status: Phase 68 Plan 02 — migrated to BaseWriterAgent
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

from src.core.agent.base_writer import BaseWriterAgent
from src.core.bar_normalizer import SOURCE_UNKNOWN
from src.core.kafka_utils import KafkaConsumerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.schemas.market_events import ContractUpdateEvent
from src.core.stream_keys import (
    topic_bar_writer_dlq,
    topic_contract_updates,
    topic_market_bars,
    topic_market_bars_htf,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSERT_OHLCV_SQL: str = """
INSERT INTO market_data_ohlcv (
    timestamp, symbol, base, timeframe, open, high, low, close, volume, source
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
_CONTRACT_CACHE_SIZE = Gauge(
    "bar_writer_contract_cache_size",
    "Number of entries in the contract->base symbol cache (from contract_metadata)",
    ["agent"],
)
_CONTRACT_CACHE_RELOADS = Counter(
    "bar_writer_contract_cache_reloads_total",
    "Number of times the contract cache was reloaded (triggered by ContractUpdateEvent or startup)",
    ["agent"],
)


class BarWriterAgent(BaseWriterAgent):
    """Dedicated OHLCV persistence agent.

    Consumes 1m bars from topic_market_bars and HTF bars from
    topic_market_bars_htf. Batch-writes to market_data_ohlcv using
    ON CONFLICT DO NOTHING for idempotent, replay-safe inserts.

    WriterAgent — DB-access allowed (persistence responsibility).
    Cold-start: auto.offset.reset=latest (D-14).
    """

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 5.0

    def __init__(self) -> None:
        super().__init__(name="bar_writer_agent", metrics_port=9121)
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # contract_code -> base_symbol (SoT: contract_metadata)
        self._contract_cache: dict[str, str] = {}

        # Cache labeled children — avoids dict lookup on every bar
        self._events_consumed_lbl = _EVENTS_CONSUMED.labels(agent=self.name)
        self._persistence_batch_latency_lbl = _BATCH_LATENCY.labels(agent=self.name)
        self._write_errors_lbl = _WRITE_ERRORS.labels(agent=self.name)
        # _conflict_skips_lbl intentionally omitted — ON CONFLICT DO NOTHING rows are
        # not countable from asyncpg executemany return value; metric removed rather
        # than reporting misleading 0s. See AUDIT-M7.
        self._persistence_consumer_lag_lbl = _CONSUMER_LAG.labels(agent=self.name)
        self._bars_written_lbl: dict[str, object] = {
            tf: _BARS_WRITTEN.labels(agent=self.name, tf=tf) for tf in _BAR_TFS
        }
        self._contract_cache_size_lbl = _CONTRACT_CACHE_SIZE.labels(agent=self.name)
        self._contract_cache_reloads_lbl = _CONTRACT_CACHE_RELOADS.labels(agent=self.name)

    def _topic_name(self) -> str:
        return topic_market_bars(self.env_name)

    def _dlq_topic(self) -> str | None:
        return topic_bar_writer_dlq(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return "bar_writer_consumer"

    @property
    def topics_consumed(self) -> list[str]:
        return [
            topic_market_bars(self.env_name),
            topic_market_bars_htf(self.env_name),
            topic_contract_updates(self.env_name),
        ]

    @property
    def topics_produced(self) -> list[str]:
        return []

    def _parse_payload(self, payload: dict) -> list | None:
        """Parse a bar payload into a buffer row tuple.

        Returns list with one 10-tuple, empty list if parse fails (not DLQ),
        or None for non-bar payloads (contract updates handled separately).
        """
        bar = self._parse_bar(payload)
        if bar is None:
            return None

        base = self._contract_cache.get(bar.symbol, bar.symbol)
        source = "live_1m" if bar.tf == "1m" else "live_htf"
        row = (
            bar.ts,
            bar.symbol,
            base,
            bar.tf,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            source,
        )
        return [row]

    async def _flush_batch(self, batch: list) -> None:
        assert self._db_pool is not None
        t0 = time.monotonic()
        async with self._db_pool.acquire() as conn:
            with self._persistence_batch_latency_lbl.time():
                await conn.executemany(_INSERT_OHLCV_SQL, batch)

        for row in batch:
            tf = row[3]
            if tf in self._bars_written_lbl:
                self._bars_written_lbl[tf].inc()

        self.logger.debug(
            "bar_writer_agent.flush_complete",
            batch_size=len(batch),
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
        )

    async def _setup(self) -> None:
        """Connect asyncpg pool and Kafka consumer."""
        self._db_pool = await asyncpg.create_pool(self.settings.database_url)
        # AUDIT-LOW-4: Retry contract cache load — transient DB failure at startup
        # must not leave cache empty (would cause days_to_expiry=0 for all symbols).
        _cache_attempts = 3
        _cache_backoff = 5.0
        for _attempt in range(_cache_attempts):
            try:
                await self._load_contract_cache()
                break
            except Exception as exc:
                if _attempt == _cache_attempts - 1:
                    self.logger.error(
                        "bar_writer_agent.contract_cache_load_failed",
                        attempts=_cache_attempts,
                        error=str(exc),
                    )
                    raise
                self.logger.warning(
                    "bar_writer_agent.contract_cache_retry",
                    attempt=_attempt + 1,
                    backoff_seconds=_cache_backoff,
                    error=str(exc),
                )
                await asyncio.sleep(_cache_backoff)

        self._kafka_consumer = self._create_consumer(
            topics=[
                topic_market_bars(self.env_name),
                topic_market_bars_htf(self.env_name),
                topic_contract_updates(self.env_name),
            ]
        )
        await self._kafka_consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info(
            "bar_writer_agent.setup_complete",
            topics_consumed=self.topics_consumed,
            contracts_cached=len(self._contract_cache),
        )

    async def _run(self) -> None:
        """Main loop: consume bars, buffer, flush on batch size or interval."""
        _contract_updates_topic = topic_contract_updates(self.env_name)

        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break

            # Route contract update events to cache invalidation — do not buffer as bars
            if _topic == _contract_updates_topic:
                await self._handle_contract_update(payload)
                continue

            try:
                rows = self._parse_payload(payload)
                if rows is not None:
                    self._buffer_rows(rows)
                else:
                    await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
                self._events_consumed_lbl.inc()
            except Exception as exc:
                self.logger.warning(
                    "bar_writer_agent.parse_failed",
                    error=str(exc),
                    payload_preview=str(payload)[:200],
                )
                continue

            self._persistence_consumer_lag_lbl.set(len(self._buffer))
            await self.maybe_flush()

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _load_contract_cache(self) -> None:
        """Load contract_metadata into memory for O(1) contract->base lookups.

        Renaissance SoT: contract_metadata is the authoritative registry for
        contract->base mappings, maintained by ContractMetadataWriterAgent.

        Non-futures (ETFs, FX, crypto) are not in contract_metadata — fallback
        to bar.symbol is correct for those (they have no roll lifecycle).

        Cache size: ~33 rows (11 base symbols x 3 expiries each) — trivial footprint.
        Reloaded on ContractUpdateEvent (quarterly rolls) and at startup.
        """
        query = "SELECT symbol, base_symbol FROM contract_metadata;"
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(query)

        self._contract_cache = {row["symbol"]: row["base_symbol"] for row in rows}
        cache_size = len(self._contract_cache)
        self._contract_cache_size_lbl.set(cache_size)
        self._contract_cache_reloads_lbl.inc()

        if cache_size == 0:
            self.logger.warning(
                "bar_writer_agent.contract_cache_empty",
                reason="ContractMetadataWriterAgent may not have seeded yet "
                "— futures fall back to contract code as base symbol",
            )
        else:
            self.logger.info(
                "bar_writer_agent.contract_cache_loaded",
                count=cache_size,
            )

    async def _handle_contract_update(self, payload: dict) -> None:
        """Handle ContractUpdateEvent — invalidate and reload contract->base cache.

        Called when ContractMetadataWriterAgent promotes a new front-month contract.
        Reloads _contract_cache so subsequent bars use the new contract code's base symbol.

        Failure mode: log and continue — stale cache resolves correctly for the outgoing
        contract and will be fixed on next restart if reload fails.
        """
        try:
            event = ContractUpdateEvent.model_validate(payload)
            self.logger.info(
                "bar_writer_agent.contract_update_received",
                base_symbol=event.base_symbol,
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                promoted_at=str(event.promoted_at),
            )
            self._contract_cache[event.new_contract] = event.base_symbol
            self._contract_cache.pop(event.old_contract, None)
            self._contract_cache_size_lbl.set(len(self._contract_cache))
            self._contract_cache_reloads_lbl.inc()
            self.logger.info(
                "bar_writer_agent.contract_cache_updated",
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                cache_size=len(self._contract_cache),
            )
        except Exception as exc:
            self.logger.error(
                "bar_writer_agent.contract_update_handler_failed",
                error=str(exc),
            )
            # Do not crash — existing cache remains valid for outgoing contract

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
            if not ts_raw:
                return None  # route to DLQ — never fabricate a timestamp
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            return BarMessage(
                ts=ts,
                symbol=symbol,
                tf=tf,
                open=float(payload.get("open", 0)),
                high=float(payload.get("high", 0)),
                low=float(payload.get("low", 0)),
                close=float(payload.get("close", 0)),
                volume=int(float(payload.get("volume", 0))),
                source=payload.get("source", SOURCE_UNKNOWN),
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
    asyncio.run(main())
