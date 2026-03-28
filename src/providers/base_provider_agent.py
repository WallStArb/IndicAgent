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

from src.config.settings import Settings
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
    PROVIDER_RECONNECTS_TOTAL,
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
    - Errors:   provider_reconnects_total{provider, agent}
    - Saturation: provider_connected{provider, agent} (gauge, 0/1)
    - SLA:      provider_gaps_filled_total{provider, agent}
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention — see bar_aggregator_agent.py)
        self._settings = Settings()
        super().__init__(
            name=self._agent_name(),
            metrics_port=self._agent_metrics_port(),
        )

        # Pre-cache labeled metric children — avoids per-bar dict lookup overhead
        pname = self._provider_name_str()
        aname = self._agent_name()
        self._m_bars_raw = PROVIDER_BARS_PRODUCED_TOTAL.labels(provider=pname, agent=aname)
        self._m_reconnects = PROVIDER_RECONNECTS_TOTAL.labels(provider=pname, agent=aname)
        self._g_connected = PROVIDER_CONNECTED.labels(provider=pname, agent=aname)
        self._m_gaps_filled = PROVIDER_GAPS_FILLED_TOTAL.labels(provider=pname, agent=aname)

        self._kafka_producer: KafkaProducerClient | None = None
        self._adapter: DataProviderAdapter | None = None

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
        """Connect Kafka producer and the provider adapter."""
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._adapter = self._create_adapter()
        await self._adapter.connect()
        self._g_connected.set(1)
        self.logger.info(
            f"{self._agent_name()}.setup_complete",
            provider=self._provider_name_str(),
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
        self._g_connected.set(0)
        self.logger.info(
            f"{self._agent_name()}.teardown_complete",
            provider=self._provider_name_str(),
        )

    # ------------------------------------------------------------------
    # Stream loop with exponential-backoff reconnect
    # ------------------------------------------------------------------

    async def _stream_loop(self) -> None:
        """Consume bars from adapter.stream_bars() with auto-reconnect."""
        instruments = self._get_instruments()
        attempt = 0

        while not self._stop_event.is_set():
            try:
                async for bar in self._adapter.stream_bars(instruments):
                    if self._stop_event.is_set():
                        return
                    await self._publish_bar(bar)
                # Generator exited normally — treat as disconnect
                self.logger.warning(
                    f"{self._agent_name()}.stream_ended",
                    provider=self._provider_name_str(),
                )
            except CancelledError:
                return
            except Exception as exc:
                self.logger.error(
                    f"{self._agent_name()}.stream_error",
                    provider=self._provider_name_str(),
                    error=str(exc),
                )

            if self._stop_event.is_set():
                return

            await self._reconnect(attempt)
            attempt += 1

    async def _reconnect(self, attempt: int) -> None:
        """Reconnect with exponential backoff capped at 60 seconds.

        Formula: min(2 ** (attempt + 1), 60)
        Sequence: 2, 4, 8, 16, 32, 60, 60, 60, ...
        """
        delay = min(2 ** (attempt + 1), 60)
        self._m_reconnects.inc()
        self.logger.warning(
            f"{self._agent_name()}.reconnecting",
            provider=self._provider_name_str(),
            attempt=attempt,
            backoff_seconds=delay,
        )
        await asyncio.sleep(delay)

        try:
            connected = await self._adapter.connect()
            if connected:
                self._g_connected.set(1)
                self.logger.info(
                    f"{self._agent_name()}.reconnected",
                    provider=self._provider_name_str(),
                    attempt=attempt,
                )
            else:
                self._g_connected.set(0)
        except Exception as exc:
            self._g_connected.set(0)
            self.logger.error(
                f"{self._agent_name()}.reconnect_failed",
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
        env = self._settings.env_name
        group_id = f"{self._provider_name_str()}_provider_gap_consumer"
        gap_consumer = KafkaConsumerClient(
            topic_gap_requests(env),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
        )
        await gap_consumer.start()
        self.logger.info(
            f"{self._agent_name()}.gap_requests_loop.started",
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
                        f"{self._agent_name()}.gap_requests_loop.received",
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

                    raw_topic = topic_market_bars_raw(env, self._provider_name_str())
                    for bar in bars:
                        await self._kafka_producer.publish(
                            raw_topic,
                            bar.model_dump(),
                            key=message_key(req.symbol, req.tf),
                        )
                        self._m_gaps_filled.inc()

                    self.logger.info(
                        f"{self._agent_name()}.gap_requests_loop.fulfilled",
                        request_id=str(req.request_id),
                        symbol=req.symbol,
                        bars_fetched=len(bars),
                    )

                except CancelledError:
                    raise
                except Exception as exc:
                    self.logger.error(
                        f"{self._agent_name()}.gap_requests_loop.error",
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
        """Publish a BarMessage to the provider's raw topic.

        Publishes to topic_market_bars_raw(env, provider_name) — not to the
        canonical market.bars topic (MergerAgent owns that routing).
        """
        env = self._settings.env_name
        raw_topic = topic_market_bars_raw(env, self._provider_name_str())
        await self._kafka_producer.publish(
            raw_topic,
            bar.model_dump(),
            key=message_key(bar.symbol, bar.tf),
        )
        self._m_bars_raw.inc()
        self._g_connected.set(1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_instruments(self) -> list[Instrument]:
        """Return active instruments from settings."""
        from src.config.settings import get_active_contracts

        return get_active_contracts(self._settings)
