"""BaseProviderAgent — abstract base class for all data provider agents.

Every data provider (IBKR, Alpaca, Polygon, etc.) gets lifecycle management,
metrics instrumentation, reconnect with exponential backoff, and gap-fill
handling for free by subclassing BaseProviderAgent.

Adding a new provider = one thin subclass + one systemd unit.

Renaissance Agentic DAG — ProviderAgent taxonomy:
  ProviderAgent: external source → Kafka, no compute, no DB.

Phase 54-03 — Provider Abstraction Layer.
"""

from __future__ import annotations

import abc
import asyncio
from asyncio import CancelledError

from src.config.settings import Settings, get_active_contracts, get_settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.models import Instrument
from src.core.schemas.bar_message import BarMessage
from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import message_key, topic_gap_requests, topic_market_bars_raw
from src.observability.metrics import (
    PROVIDER_BARS_PRODUCED_TOTAL,
    PROVIDER_CONNECTED,
    PROVIDER_GAPS_FILLED_TOTAL,
    PROVIDER_RECONNECTS_ATTEMPTED_TOTAL,
    PROVIDER_RECONNECTS_SUCCEEDED_TOTAL,
)
from src.providers.base import DataProviderAdapter


class BaseProviderAgent(BaseAgent):
    """Abstract base for all data provider agents.

    Handles lifecycle, metrics, exponential-backoff reconnect, and gap-fill
    routing generically. Subclasses must implement four abstract methods:

    - _agent_name()        → str, e.g. "ibkr_provider_agent"
    - _agent_metrics_port() → int, e.g. 9129
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
        # Pass settings to BaseAgent to avoid duplicate creation
        # BaseAgent will use get_settings() singleton if settings is None
        _settings = settings or get_settings()
        super().__init__(
            name=self._agent_name(),
            metrics_port=self._agent_metrics_port(),
            settings=_settings,
        )

        # Pre-cache labeled metric children — avoids per-bar dict lookup overhead
        pname = self._provider_name_str()
        self._m_bars_raw = PROVIDER_BARS_PRODUCED_TOTAL.labels(provider=pname, agent=self.name)
        self._m_reconnects_attempted = PROVIDER_RECONNECTS_ATTEMPTED_TOTAL.labels(
            provider=pname, agent=self.name
        )
        self._m_reconnects_succeeded = PROVIDER_RECONNECTS_SUCCEEDED_TOTAL.labels(
            provider=pname, agent=self.name
        )
        self._g_connected = PROVIDER_CONNECTED.labels(provider=pname, agent=self.name)
        self._m_gaps_filled = PROVIDER_GAPS_FILLED_TOTAL.labels(provider=pname, agent=self.name)

        # Cache raw topic — constant for agent lifetime
        self._raw_topic = topic_market_bars_raw(self.settings.env_name or "", pname)

        self._kafka_producer: KafkaProducerClient | None = None
        self._adapter: DataProviderAdapter | None = None
        self._instruments: list[Instrument] = []
        # Semaphore created at runtime (not class level) to stay within the event loop.
        self._qualify_sem: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement all four
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _agent_name(self) -> str:
        """Return the agent name, e.g. 'ibkr_provider_agent'."""

    @abc.abstractmethod
    def _agent_metrics_port(self) -> int:
        """Return the Prometheus metrics port, e.g. 9129."""

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
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._adapter = self._create_adapter()
        await self._adapter.connect()
        self._g_connected.set(1)

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
        health_task = asyncio.create_task(self._health_check_loop())

        await self._stop_event.wait()

        for task in (stream_task, gap_task, health_task):
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
        self._g_connected.set(0)
        self.logger.info(
            "provider_agent.teardown_complete",
            agent=self.name,
            provider=self._provider_name_str(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _qualify_instrument(self, instrument: Instrument) -> bool:
        """Qualify a single instrument via the adapter, rate-limited to 5 concurrent."""
        async with self._qualify_sem:
            try:
                await self._adapter.qualify_instrument(instrument)
                return True
            except Exception as exc:
                self.logger.warning(
                    "provider_agent.qualify_failed",
                    agent=self.name,
                    symbol=instrument.symbol,
                    error=str(exc),
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
                    await self._publish_bar(bar)
                # Generator exited normally — treat as disconnect
                self.logger.warning(
                    "provider_agent.stream_ended",
                    agent=self.name,
                    provider=self._provider_name_str(),
                )
            except CancelledError:
                return
            except Exception as exc:
                self.logger.error(
                    "provider_agent.stream_error",
                    agent=self.name,
                    provider=self._provider_name_str(),
                    error=str(exc),
                )

            if self._stop_event.is_set():
                return

            await self._reconnect(attempt)
            attempt += 1

    async def _reconnect(self, attempt: int) -> None:
        """Reconnect with exponential backoff capped at 10 seconds.

        Formula: min(2 ** (attempt + 1), 10)
        Sequence: 2, 4, 8, 10, 10, 10, ...
        """
        delay = min(2 ** (attempt + 1), 10)
        self._m_reconnects_attempted.inc()
        self.logger.warning(
            "provider_agent.reconnecting",
            agent=self.name,
            provider=self._provider_name_str(),
            attempt=attempt,
            backoff_seconds=delay,
        )
        await asyncio.sleep(delay)

        try:
            connected = await self._adapter.connect()
            if connected:
                self._g_connected.set(1)
                self._m_reconnects_succeeded.inc()
                self.logger.info(
                    "provider_agent.reconnected",
                    agent=self.name,
                    provider=self._provider_name_str(),
                    attempt=attempt,
                )
            else:
                self._g_connected.set(0)
        except Exception as exc:
            self._g_connected.set(0)
            self.logger.error(
                "provider_agent.reconnect_failed",
                agent=self.name,
                provider=self._provider_name_str(),
                attempt=attempt,
                error=str(exc),
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

                    bars = await self._adapter.fetch_historical(
                        symbol=req.symbol,
                        tf=req.tf,
                        start=req.start_ts,
                        end=req.end_ts,
                    )

                    for bar in bars:
                        await self._kafka_producer.publish(
                            self._raw_topic,
                            bar.model_dump(mode="json"),
                            key=message_key(req.symbol, req.tf),
                        )
                        self._m_gaps_filled.inc()

                    self.logger.info(
                        "provider_agent.gap_requests_loop.fulfilled",
                        agent=self.name,
                        request_id=str(req.request_id),
                        symbol=req.symbol,
                        bars_fetched=len(bars),
                    )

                except CancelledError:
                    raise
                except Exception as exc:
                    self.logger.error(
                        "provider_agent.gap_requests_loop.error",
                        agent=self.name,
                        error=str(exc),
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
        await self._kafka_producer.publish(
            self._raw_topic,
            bar.model_dump(mode="json"),
            key=message_key(bar.symbol, bar.tf),
        )
        self._m_bars_raw.inc()
        self._record_message_consumed()

    async def _health_check_loop(self) -> None:
        """Active health check — ping adapter every 30s to detect dead connections.

        Prevents the 10-hour idle connection failure we saw where the provider
        sat disconnected without attempting reconnection. Triggers reconnect if ping fails.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(30)  # Check every 30 seconds
            if self._stop_event.is_set():
                break

            # Skip check if adapter doesn't support ping (not IBKR)
            if not hasattr(self._adapter, "ping"):
                continue

            try:
                is_healthy = await self._adapter.ping()
                if not is_healthy:
                    self.logger.warning(
                        "provider_agent.health_check_failed",
                        agent=self.name,
                        provider=self._provider_name_str(),
                    )
                    # Trigger reconnect by breaking stream loop
                    if hasattr(self._adapter, "disconnect"):
                        await self._adapter.disconnect()
            except Exception as exc:
                self.logger.error(
                    "provider_agent.health_check_exception",
                    agent=self.name,
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_instruments(self) -> list[Instrument]:
        """Return active instruments from settings."""
        return get_active_contracts(self.settings)
