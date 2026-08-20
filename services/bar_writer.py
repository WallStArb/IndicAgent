#!/usr/bin/env python3
"""BarWriter — dedicated OHLCV persistence agent.

Subscribes to market.bars (1m) + market.bars.htf (5m-1d), batch-writes
to market_data_ohlcv with ON CONFLICT DO NOTHING for idempotent writes.

Decouples bar persistence from the feature compute hot path (D-02 through D-07).


Golden Signals (D-06):
- Traffic: events_consumed_total, bars_written_total{tf}
- Latency: persistence_batch_latency_seconds
- Errors: write_errors_total, conflict_skips_total
- Saturation: persistence_consumer_lag

Version: 2.0.0
Last Updated: 2026-04-13
Status: Phase 68 Plan 02 — migrated to BaseWriter
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
from opentelemetry import metrics as _otel_metrics
from pydantic import ValidationError

from src.config.vocabulary_service import VocabularyService
from src.core import vocabulary_access
from src.core.agent.base_writer import BaseWriter
from src.core.bar_normalizer import SOURCE_UNKNOWN
from src.core.database_manager import create_pool as create_db_pool
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

# Module-level OTel instruments — single meter, no prometheus_client
_bw_meter = _otel_metrics.get_meter("indicagent")

_EVENTS_CONSUMED = _bw_meter.create_counter(
    "bar_writer_events_consumed_total",
    description="Bar messages consumed from market.bars and market.bars.htf",
)
_BARS_WRITTEN = _bw_meter.create_counter(
    "bar_writer_bars_written_total",
    description="OHLCV rows successfully written to market_data_ohlcv",
)
_BATCH_LATENCY = _bw_meter.create_histogram(
    "bar_writer_persistence_batch_latency_seconds",
    description="Time to execute an executemany batch INSERT to market_data_ohlcv",
    unit="s",
)
_WRITE_ERRORS = _bw_meter.create_counter(
    "bar_writer_write_errors_total",
    description="Exceptions during batch INSERT — buffer left intact for retry",
)
_CONSUMER_LAG = _bw_meter.create_gauge(
    "bar_writer_persistence_consumer_lag",
    description="Current unwritten buffer depth (proxy for consumer lag)",
)
_CONTRACT_CACHE_SIZE = _bw_meter.create_gauge(
    "bar_writer_contract_cache_size",
    description="Number of entries in the contract->base symbol cache (from contract_metadata)",
)
_CONTRACT_CACHE_RELOADS = _bw_meter.create_counter(
    "bar_writer_contract_cache_reloads_total",
    description="Number of times the contract cache was reloaded (triggered by ContractUpdateEvent or startup)",
)


class BarWriter(BaseWriter):
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
        super().__init__()
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # contract_code -> base_symbol (SoT: contract_metadata)
        self._contract_cache: dict[str, str] = {}

        # Cache OTel attribute dicts — avoids dict rebuild on every bar
        self._events_consumed_attrs = {"agent": self.name}
        self._batch_latency_attrs = {"agent": self.name}
        self._write_errors_attrs = {"agent": self.name}
        self._consumer_lag_attrs = {"agent": self.name}
        # Populated from CVR's `timeframe` namespace in
        # _prewarm_timeframe_vocabulary() (todo 327) -- __init__ stays synchronous,
        # so this is a placeholder until _setup() runs.
        self._bars_written_attrs: dict[str, dict] = {}
        self._vocabulary_service: VocabularyService | None = None  # initialised in _setup()
        self._contract_cache_size_attrs = {"agent": self.name}
        self._contract_cache_reloads_attrs = {"agent": self.name}

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

    def _bar_to_row(self, bar: BarMessage, base: str, source: str) -> tuple:
        """Map a BarMessage to positional params for _INSERT_OHLCV_SQL.

        Positions must match the $N placeholders in _INSERT_OHLCV_SQL exactly.
        """
        return (
            bar.ts,  # $1 timestamp::timestamptz
            bar.symbol,  # $2 symbol::text
            base,  # $3 base::text
            bar.tf,  # $4 timeframe::text
            bar.open,  # $5 open::numeric
            bar.high,  # $6 high::numeric
            bar.low,  # $7 low::numeric
            bar.close,  # $8 close::numeric
            bar.volume,  # $9 volume::bigint
            source,  # $10 source::text
        )

    def _parse_payload(self, payload: dict) -> tuple[list, list]:
        """Parse a bar payload into a buffer row tuple.

        Returns (valid_rows, invalid_rows).
        """
        if not isinstance(payload, dict) or not payload:
            return [], [payload]
        bar = self._parse_bar(payload)
        if bar is None:
            return [], []

        base = self._contract_cache.get(bar.symbol, bar.symbol)
        source = "live_1m" if bar.tf == "1m" else "live_htf"
        return [self._bar_to_row(bar, base, source)], []

    async def _flush_batch(self, batch: list) -> None:
        assert self._db_pool is not None
        t0 = time.monotonic()
        async with self._db_pool.acquire() as conn:
            await conn.executemany(_INSERT_OHLCV_SQL, batch)
        _BATCH_LATENCY.record(time.monotonic() - t0, self._batch_latency_attrs)

        for row in batch:
            tf = row[3]
            if tf in self._bars_written_attrs:
                _BARS_WRITTEN.add(1, self._bars_written_attrs[tf])

        self.logger.debug(
            "bar_writer.flush_complete",
            batch_size=len(batch),
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
        )

    async def _setup(self) -> None:
        """Connect asyncpg pool and Kafka consumer."""
        self._db_pool = await create_db_pool(self.settings.database_url)

        # VocabularyService: shared pool, registers vocabulary_access so
        # _bars_written_attrs reads CVR's `timeframe` namespace instead of a
        # hardcoded tuple (todo 327).
        await self._prewarm_timeframe_vocabulary()

        # AUDIT-LOW-4: Retry contract cache load — transient DB failure at startup
        # must not leave cache empty (would cause days_to_expiry=0 for all symbols).
        _cache_attempts = 3
        _cache_backoff = 5.0
        for _attempt in range(_cache_attempts):
            try:
                await self._load_contract_cache()
                break
            except Exception as error:
                if _attempt == _cache_attempts - 1:
                    self.logger.error(
                        "bar_writer.contract_cache_load_failed",
                        attempts=_cache_attempts,
                        error=str(error),
                    )
                    raise
                self.logger.warning(
                    "bar_writer.contract_cache_retry",
                    attempt=_attempt + 1,
                    backoff_seconds=_cache_backoff,
                    error=str(error),
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
            "bar_writer.setup_complete",
            topics_consumed=self.topics_consumed,
            contracts_cached=len(self._contract_cache),
        )

    async def _prewarm_timeframe_vocabulary(self) -> None:
        """Register a VocabularyService with vocabulary_access and build
        _bars_written_attrs from CVR's `timeframe` namespace instead of a hardcoded
        tuple (todo 327)."""
        self._vocabulary_service = await vocabulary_access.prewarm(
            self.settings.database_url, self._db_pool
        )
        self._bars_written_attrs = {
            tf: {"agent": self.name, "tf": tf} for tf in vocabulary_access.standard_timeframes()
        }

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

            self._record_message_consumed()  # Track liveness for stall detection

            try:
                valid, invalid = self._parse_payload(payload)
                if invalid and not valid:
                    await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
                if valid:
                    self._buffer_rows(valid)
                _EVENTS_CONSUMED.add(1, self._events_consumed_attrs)
            except Exception as error:
                self.logger.warning(
                    "bar_writer.parse_failed",
                    error=str(error),
                    payload_preview=str(payload)[:200],
                )
                continue

            _CONSUMER_LAG.set(len(self._buffer), self._consumer_lag_attrs)
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
        _CONTRACT_CACHE_SIZE.set(cache_size, self._contract_cache_size_attrs)
        _CONTRACT_CACHE_RELOADS.add(1, self._contract_cache_reloads_attrs)

        if cache_size == 0:
            self.logger.warning(
                "bar_writer.contract_cache_empty",
                reason="ContractMetadataWriterAgent may not have seeded yet "
                "— futures fall back to contract code as base symbol",
            )
        else:
            self.logger.info(
                "bar_writer.contract_cache_loaded",
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
                "bar_writer.contract_update_received",
                base_symbol=event.base_symbol,
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                promoted_at=str(event.promoted_at),
            )
            self._contract_cache[event.new_contract] = event.base_symbol
            self._contract_cache.pop(event.old_contract, None)
            _CONTRACT_CACHE_SIZE.set(len(self._contract_cache), self._contract_cache_size_attrs)
            _CONTRACT_CACHE_RELOADS.add(1, self._contract_cache_reloads_attrs)
            self.logger.info(
                "bar_writer.contract_cache_updated",
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                cache_size=len(self._contract_cache),
            )
        except Exception as error:
            self.logger.error(
                "bar_writer.contract_update_handler_failed",
                error=str(error),
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
        except Exception as error:
            self.logger.warning(
                "bar_writer.parse_failed",
                error=str(error),
                payload_preview=str(payload)[:200],
            )
            return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = BarWriter()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
