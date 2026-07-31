"""BaseProvider — abstract base class for all data provider agents.

Every data provider (IBKR, Alpaca, Polygon, etc.) gets lifecycle management,
metrics instrumentation, reconnect with exponential backoff, and gap-fill
handling for free by subclassing BaseProvider.

Adding a new provider = one thin subclass + one systemd unit.

Renaissance Agentic DAG — ProviderAgent hierarchy:
  ProviderAgent: external source → Kafka, no compute, no DB.

Phase 54-03 — Provider Abstraction Layer.
"""

from __future__ import annotations

import abc
import asyncio
import random
from asyncio import CancelledError
from datetime import datetime

import asyncpg

from src.config.settings import Settings, get_active_contracts, get_settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage
from src.core.schemas.market_events import BarGapRequest
from src.core.service_utils import TF_SECONDS
from src.core.stream_keys import message_key, topic_gap_requests, topic_market_bars_raw
from src.observability.metrics import (
    PROVIDER_BARS_PRODUCED_TOTAL,
    PROVIDER_CONNECTED,
    PROVIDER_GAPS_FILLED_TOTAL,
    PROVIDER_RECONNECTS_ATTEMPTED_TOTAL,
    PROVIDER_RECONNECTS_SUCCEEDED_TOTAL,
)
from src.providers.base import DataProviderAdapter


class BaseProvider(BaseDaemon):
    """Abstract base for all data provider agents.

    Handles lifecycle, metrics, exponential-backoff reconnect, and gap-fill
    routing generically. Subclasses must implement four abstract methods:

    - _agent_name()        → str, e.g. "ibkr_provider_agent"
    - _provider_name_str() → str, e.g. "ibkr" (used in topic keys + metric labels)
    - _create_adapter()    → DataProviderAdapter implementation

    Publishing goes to topic_market_bars_raw(env, provider_name) — never to
    the canonical market.bars topic (that is MergerAgent's job).

    Golden Signals (D-16):
    - Traffic:  provider_bars_produced_total{provider, agent}
    - Errors:   provider_reconnects_attempted_total{provider, agent}
                provider_reconnects_succeeded_total{provider, agent}
    - Saturation: provider_connected{provider, agent} (gauge, 0/1)
    - SLA:      provider_gaps_filled_total{provider, agent}
    """

    def __init__(self, settings: Settings | None = None) -> None:
        # Pass settings to BaseDaemon to avoid duplicate creation
        # BaseDaemon will use get_settings() singleton if settings is None
        _settings = settings or get_settings()
        super().__init__(
            name=self._agent_name(),
            settings=_settings,
        )

        # Pre-cache OTel attribute dicts — avoids per-bar dict rebuild overhead
        pname = self._provider_name_str()
        self._provider_attrs = {"provider": pname, "agent": self.name}

        # Cache raw topic — constant for agent lifetime
        self._raw_topic = topic_market_bars_raw(self.settings.env_name or "", pname)

        self._kafka_producer: KafkaProducerClient | None = None
        self._adapter: DataProviderAdapter | None = None
        self._instruments: list[Instrument] = []
        # Semaphore created at runtime (not class level) to stay within the event loop.
        self._qualify_sem: asyncio.Semaphore | None = None
        # Gap-fetch pacing: 1 in-flight fetch at a time + 0.2s spacing between fetches
        # → ≤5 req/s sustained, well under IBKR's historical-data pacing thresholds.
        self._gap_fetch_sem = asyncio.Semaphore(1)
        self._db_pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement all four
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _agent_name(self) -> str:
        """Return the agent name, e.g. 'ibkr_provider_agent'."""

    @abc.abstractmethod
    def _provider_name_str(self) -> str:
        """Return the lower-case provider identifier, e.g. 'ibkr'.

        Used in:
        - Kafka topic keys: topic_market_bars_raw(env, provider_name)
        - Prometheus labels: provider=provider_name
        - Consumer group IDs: f"{provider_name}_provider_gap_consumer"
        """

    @abc.abstractmethod
    def _create_adapter(self) -> DataProviderAdapter:
        """Instantiate and return the provider-specific DataProviderAdapter."""

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        """Connect Kafka producer and the provider adapter, then qualify all instruments."""
        self._db_pool = await create_db_pool(self.settings.database_url)

        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._adapter = self._create_adapter()
        await self._adapter.connect()
        PROVIDER_CONNECTED.add(1, self._provider_attrs)

        self._instruments = self._get_instruments()
        self._qualify_sem = asyncio.Semaphore(5)
        total = len(self._instruments)

        # Qualify all instruments concurrently; cap at 5 parallel requests to
        # avoid overwhelming the provider connection on startup.
        results = await asyncio.gather(
            *[self._qualify_instrument(i) for i in self._instruments],
            return_exceptions=True,
        )
        # Keep only instruments that qualified successfully. Unqualified instruments
        # cannot be used for streaming (adapter lacks conId/localSymbol after failure).
        # False and exception objects both represent failures.
        self._instruments = [
            inst for inst, ok in zip(self._instruments, results, strict=True) if ok is True
        ]
        qualified_count = len(self._instruments)

        if qualified_count == 0:
            self.logger.error(
                "provider_agent.no_qualified_instruments",
                agent=self.name,
                total=total,
            )
            raise RuntimeError(f"{self.name}: no instruments qualified — cannot stream data")
        if qualified_count < total:
            self.logger.warning(
                "provider_agent.partial_qualification",
                agent=self.name,
                qualified=qualified_count,
                total=total,
            )
        self.logger.info(
            "provider_agent.setup_complete",
            agent=self.name,
            provider=self._provider_name_str(),
            qualified=qualified_count,
            total=total,
        )

    async def _run(self) -> None:
        """Launch stream + gap-fill loops, wait for stop event."""
        stream_task = asyncio.create_task(self._stream_loop())
        gap_task = asyncio.create_task(self._gap_requests_loop())

        await self._stop_event.wait()

        for task in (stream_task, gap_task):
            task.cancel()
            try:
                await task
            except CancelledError:
                pass

    async def _teardown(self) -> None:
        """Drain Kafka producer and disconnect the provider adapter."""
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._adapter is not None:
            await self._adapter.disconnect()
        if self._db_pool is not None:
            await self._db_pool.close()
        PROVIDER_CONNECTED.add(0, self._provider_attrs)
        self.logger.info(
            "provider_agent.teardown_complete",
            agent=self.name,
            provider=self._provider_name_str(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _gap_already_filled(
        self,
        symbol: str,
        tf: str,
        start_ts: datetime,
        end_ts: datetime,
        expected_bars: int,
    ) -> bool:
        """Return True if market_data_ohlcv_tradeable already has >= expected_bars for
        this window.

        Prevents redundant IBKR historical fetches on restart or duplicate gap requests.
        Reads the tradeable view, not the raw table (todo 124): expected_bars is a pure
        calendar-time count (window_seconds // tf_seconds), and this gate decides
        whether to skip a real IBKR fetch -- counting synthetic-fill placeholder rows
        would let a window that's entirely flat-filled (e.g. during an outage) be
        judged "already filled," silently masking a genuine data gap with fake bars
        instead of backfilling it for real.
        """
        if self._db_pool is None or expected_bars <= 0:
            return False
        async with self._db_pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM market_data_ohlcv_tradeable
                WHERE symbol = $1 AND timeframe = $2
                  AND timestamp >= $3 AND timestamp < $4
                """,
                symbol,
                tf,
                start_ts,
                end_ts,
            )
        return (count or 0) >= expected_bars

    async def _qualify_instrument(self, instrument: Instrument) -> bool:
        """Qualify a single instrument via the adapter, rate-limited to 5 concurrent."""
        async with self._qualify_sem:
            with self.tracer.start_as_current_span(
                "provider.qualify_instrument",
                attributes={
                    "symbol": instrument.symbol,
                    "provider": self._provider_name_str(),
                },
            ) as span:
                try:
                    await self._adapter.qualify_instrument(instrument)
                    span.set_attribute("success", True)
                    return True
                except Exception as error:
                    span.set_attribute("success", False)
                    self.logger.warning(
                        "provider_agent.qualify_failed",
                        agent=self.name,
                        symbol=instrument.symbol,
                        error=str(error),
                    )
                    return False

    # ------------------------------------------------------------------
    # Stream loop with exponential-backoff reconnect
    # ------------------------------------------------------------------

    async def _stream_loop(self) -> None:
        """Consume bars from adapter.stream_bars() with auto-reconnect."""
        attempt = 0

        while not self._stop_event.is_set():
            try:
                async for bar in self._adapter.stream_bars(self._instruments):
                    if self._stop_event.is_set():
                        return
                    attempt = 0
                    await self._publish_bar(bar)
                # Generator exited normally — treat as disconnect
                self.logger.warning(
                    "provider_agent.stream_ended",
                    agent=self.name,
                    provider=self._provider_name_str(),
                )
            except CancelledError:
                return
            except Exception as error:
                self.logger.error(
                    "provider_agent.stream_error",
                    agent=self.name,
                    provider=self._provider_name_str(),
                    error=str(error),
                )

            if self._stop_event.is_set():
                return

            await self._reconnect(attempt)
            attempt += 1

    async def _reconnect(self, attempt: int) -> None:
        """Reconnect with jittered exponential backoff (base ≤30s, delay ≤45s).

        base = min(2 ** (attempt + 1), 30); delay = base * uniform(0.5, 1.5)
        Jitter avoids thundering-herd reconnect after a broker-wide blip.
        """
        with self.tracer.start_as_current_span(
            "provider.reconnect",
            attributes={
                "provider": self._provider_name_str(),
                "attempt": attempt,
            },
        ) as span:
            base = min(2 ** (attempt + 1), 30)
            delay = base * random.uniform(0.5, 1.5)
            PROVIDER_RECONNECTS_ATTEMPTED_TOTAL.add(1, self._provider_attrs)
            self.logger.warning(
                "provider_agent.reconnecting",
                agent=self.name,
                provider=self._provider_name_str(),
                attempt=attempt,
                backoff_seconds=delay,
            )
            await asyncio.sleep(delay)

            try:
                await self._adapter.disconnect()
                connected = await self._adapter.connect()
                if connected:
                    PROVIDER_CONNECTED.add(1, self._provider_attrs)
                    PROVIDER_RECONNECTS_SUCCEEDED_TOTAL.add(1, self._provider_attrs)
                    span.set_attribute("success", True)
                    self.logger.info(
                        "provider_agent.reconnected",
                        agent=self.name,
                        provider=self._provider_name_str(),
                        attempt=attempt,
                    )
                else:
                    PROVIDER_CONNECTED.add(0, self._provider_attrs)
                    span.set_attribute("success", False)
            except Exception as error:
                PROVIDER_CONNECTED.add(0, self._provider_attrs)
                span.set_attribute("success", False)
                self.logger.error(
                    "provider_agent.reconnect_failed",
                    agent=self.name,
                    provider=self._provider_name_str(),
                    attempt=attempt,
                    error=str(error),
                )

    # ------------------------------------------------------------------
    # Gap-fill loop
    # ------------------------------------------------------------------

    async def _gap_requests_loop(self) -> None:
        """Consume BarGapRequest events and re-fetch bars from the adapter.

        Pure Kafka consumer — no dependency on adapter connection state.
        Submitted once; IBKR disconnects do NOT cancel it. The per-message
        try/except handles fetch failures gracefully.

        Gap-fill bars are published to topic_market_bars_raw(env, provider)
        so MergerAgent routes them into the canonical stream.
        """
        env = self.settings.env_name or ""
        group_id = f"{self._provider_name_str()}_provider_gap_consumer"
        gap_consumer = KafkaConsumerClient(
            topic_gap_requests(env),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
        )
        await gap_consumer.start()
        self.logger.info(
            "provider_agent.gap_requests_loop.started",
            agent=self.name,
            topic=topic_gap_requests(env),
            group_id=group_id,
        )

        try:
            async for _topic, _key, payload in gap_consumer.messages():
                if self._stop_event.is_set():
                    break
                try:
                    req = BarGapRequest.model_validate(payload)
                    self.logger.info(
                        "provider_agent.gap_requests_loop.received",
                        agent=self.name,
                        request_id=str(req.request_id),
                        symbol=req.symbol,
                        tf=req.tf,
                        start_ts=req.start_ts.isoformat(),
                        end_ts=req.end_ts.isoformat(),
                    )

                    window_seconds = int((req.end_ts - req.start_ts).total_seconds())
                    tf_seconds = TF_SECONDS.get(req.tf, 60)
                    expected_bars = max(1, window_seconds // tf_seconds)

                    already_filled = await self._gap_already_filled(
                        req.symbol, req.tf, req.start_ts, req.end_ts, expected_bars
                    )
                    if already_filled:
                        self.logger.info(
                            "provider_agent.gap_request_skipped_already_filled",
                            agent=self.name,
                            request_id=str(req.request_id),
                            symbol=req.symbol,
                            expected_bars=expected_bars,
                        )
                        continue

                    if not self._adapter.is_connected():
                        await self._adapter.connect()

                    # IBKR historical-data pacing guard: 5 req/s sustained.
                    # Prevents Error 162 when multiple gap requests stack up.
                    async with self._gap_fetch_sem:
                        bars = await self._adapter.fetch_historical(
                            symbol=req.symbol,
                            tf=req.tf,
                            start=req.start_ts,
                            end=req.end_ts,
                        )
                        await asyncio.sleep(0.2)

                    for bar in bars:
                        await self._kafka_producer.publish(
                            self._raw_topic,
                            bar.model_dump(mode="json"),
                            key=message_key(req.symbol, req.tf),
                        )
                        PROVIDER_GAPS_FILLED_TOTAL.add(1, self._provider_attrs)

                    self.logger.info(
                        "provider_agent.gap_requests_loop.fulfilled",
                        agent=self.name,
                        request_id=str(req.request_id),
                        symbol=req.symbol,
                        bars_fetched=len(bars),
                    )

                except CancelledError:
                    raise
                except Exception as error:
                    self.logger.error(
                        "provider_agent.gap_requests_loop.error",
                        agent=self.name,
                        error=str(error),
                        payload_preview=str(payload)[:200],
                    )
                    # Continue consuming — don't crash the loop on a single failure

        finally:
            await gap_consumer.stop()

    # ------------------------------------------------------------------
    # Bar publishing
    # ------------------------------------------------------------------

    async def _publish_bar(self, bar: BarMessage) -> None:
        """Publish a BarMessage to the provider's raw topic."""
        with self.tracer.start_as_current_span(
            "provider.publish_bar",
            attributes={"symbol": bar.symbol, "tf": bar.tf},
        ):
            await self._kafka_producer.publish(
                self._raw_topic,
                bar.model_dump(mode="json"),
                key=message_key(bar.symbol, bar.tf),
            )
            PROVIDER_BARS_PRODUCED_TOTAL.add(1, self._provider_attrs)
            self._record_message_consumed()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_instruments(self) -> list[Instrument]:
        """Return active instruments from settings."""
        return get_active_contracts(self.settings)
