"""BaseSwarmCoordinator — shared dispatcher for agent groups."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry.trace import StatusCode

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.ai.base_agent import BaseAIWorker
from src.core.ai.lineage import LineageRecorder
from src.core.ai.output import AgentOutput
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.context import SignalContextCache
from src.intelligence.schemas import IntelligenceEvent
from src.observability.spans import ATTR_GROUP_ID, ATTR_SYMBOL, ATTR_TF

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class BaseSwarmCoordinator(BaseDaemon, ABC):
    """Shared dispatcher for agent groups (alpha, narrative, risk).

    Subclasses declare 3 abstract properties:
      - agents: list[BaseAIWorker]
      - trigger_topics: list[str]  (Kafka topics that trigger dispatch)
      - output_topic: str          (Kafka topic for agent output fan-out)

    Everything else (Kafka plumbing, DB pool, context cache, graduation)
    is inherited. Adding a new group = ~25 lines.

    Lifecycle:
    - _setup(): Wire Kafka consumer/producer + DB pool + cache seeding
    - _run(): Start bar_loop, trigger_loop, and optional graduation_loop
    - _teardown(): Flush recorder, close pool, stop consumers/producer
    """

    group_id: str = ""
    llm_cache_ttl: float = 0.0  # 0 = no caching; override in subclasses that benefit from it

    @property
    @abstractmethod
    def agents(self) -> list[BaseAIWorker]:
        """List of agents managed by this group service."""
        ...

    @property
    @abstractmethod
    def trigger_topics(self) -> list[str]:
        """Kafka topics that trigger agent dispatch."""
        ...

    @property
    @abstractmethod
    def output_topic(self) -> str:
        """Kafka topic for agent output fan-out."""
        ...

    # Abstract methods for subclass Kafka wiring
    @abstractmethod
    def _bar_topics(self) -> list[str]:
        """Topics for bar data that update SignalContextCache. Return [] to skip bar consumer."""
        ...

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, max_idle_seconds=0, settings=settings)
        self.settings = settings
        self._context_cache = SignalContextCache()
        self._bar_consumer: KafkaConsumerClient | None = None
        self._trigger_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._pool: Any | None = None  # asyncpg.Pool
        self._llm_chain: LLMProviderChain | None = None
        self._lineage: LineageRecorder | None = None

    async def _setup(self) -> None:
        """Wire Kafka consumer/producer + DB pool + cache seeding.

        Subclasses should call super()._setup() then add group-specific wiring.
        """
        # Wire bar consumer (for SignalContextCache updates)
        bar_topics = self._bar_topics()
        if bar_topics:
            self._bar_consumer = KafkaConsumerClient(
                *bar_topics,
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                group_id=f"{self.group_id}_bar_consumer",
                auto_offset_reset="latest",
            )
            await self._bar_consumer.start()
            await self._bar_consumer.skip_lag_if_needed(max_lag=500)

        # Wire trigger consumer (for agent dispatch)
        # Subscribe to all trigger topics
        self._trigger_consumer = KafkaConsumerClient(
            *self.trigger_topics,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.group_id}_trigger_consumer",
            auto_offset_reset="latest",
        )
        await self._trigger_consumer.start()
        # Drop stale trigger backlog on startup — replaying queued signals from a
        # prior run against a cold context cache produces low-quality enrichments.
        await self._trigger_consumer.skip_lag_if_needed(max_lag=500)

        # Wire producer (for agent output fan-out)
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        # Wire DB pool (for context cache seeding)
        from src.core.database_manager import create_pool as create_db_pool

        self._pool = await create_db_pool(
            self.settings.database_url,
            min_size=2,
            max_size=5,
        )

        # Wire LLM chain (for LLM-based agents) — producer enables auto-audit to topic_llm_calls
        self._llm_chain = LLMProviderChain(
            call_type=self.group_id,
            settings=self.settings,
            cache_ttl=self.llm_cache_ttl,
            producer=self._producer,
        )

        # Seed context cache from DB
        await self._seed_context_cache()

        # Wire LineageRecorder lifecycle — subclass can pre-set _lineage to skip
        if self._lineage is None:
            self._lineage = LineageRecorder(
                producer=self._producer,
                env_name=self.env_name,
            )
            await self._lineage.start()
        for agent in self.agents:
            agent._lineage = self._lineage

        # D-19: BaseSwarmCoordinator must call super()._setup() for forward compatibility
        await super()._setup()

    async def _shadow_registry_ensure_agents(self, agents: list[BaseAIWorker]) -> None:
        """Idempotent enrollment of agents in shadow_registry as component_type='swarm_agent'.

        ON CONFLICT DO NOTHING preserves any manually-tuned gate params.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            for agent in agents:
                await conn.execute(
                    "INSERT INTO shadow_registry (component_name, component_type, is_shadow) "
                    "VALUES ($1, 'swarm_agent', TRUE) ON CONFLICT (component_name) DO NOTHING",
                    agent.agent_id,
                )
        self.logger.info(
            "base_group_service.shadow_enrolled",
            group_id=self.group_id,
            agents=[a.agent_id for a in agents],
        )

    async def _seed_context_cache(self) -> None:
        """Seed SignalContextCache with recent intelligence_features rows."""
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (symbol, tf)
                    symbol, tf, ts, bar, technical_indicators, market_context, pattern_detections,
                    regime_features, confluence_scores, cross_timeframe_context, trading_signals, smc
                FROM intelligence_features
                WHERE ts > NOW() - INTERVAL '7 days'
                  AND technical_indicators IS NOT NULL AND regime_features IS NOT NULL
                ORDER BY symbol, tf, ts DESC
            """)
        for row in rows:
            self._context_cache.seed_from_db_row(dict(row))
        logger.info(
            "base_group_service.cache_seeded",
            group_id=self.group_id,
            entries=len(rows),
        )

    async def _run(self) -> None:
        """Run main loops: bar_loop, trigger_loop, and optional graduation_loop."""
        trigger_task = asyncio.create_task(self._trigger_loop())
        tasks = [trigger_task]

        if self._bar_consumer is not None:
            tasks.append(asyncio.create_task(self._bar_loop()))

        if hasattr(type(self), "_graduation_loop"):
            graduation_task = asyncio.create_task(self._graduation_loop())
            tasks.append(graduation_task)

        try:
            await asyncio.gather(*tasks)
        except Exception:
            for t in tasks:
                t.cancel()
            raise

    async def _teardown(self) -> None:
        """Flush recorder, close pool, stop consumers/producer."""
        if getattr(self, "_lineage", None) is not None:
            await self._lineage.stop()
        if self._pool:
            await self._pool.close()
        if self._bar_consumer:
            await self._bar_consumer.stop()
        if self._trigger_consumer:
            await self._trigger_consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def _bar_loop(self) -> None:
        """Update SignalContextCache on each IntelligenceEvent."""
        assert self._bar_consumer is not None
        async for _topic, _key, payload in self._bar_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                # Pipeline publishes {"event": "<json_string>"}
                raw = payload.get("event", payload)
                if isinstance(raw, str):
                    import json

                    raw = json.loads(raw)
                event = IntelligenceEvent.model_validate(raw)
                with self.tracer.start_as_current_span(
                    "group.bar_cache_update",
                    attributes={
                        ATTR_GROUP_ID: self.group_id,
                        ATTR_SYMBOL: event.symbol,
                        ATTR_TF: event.tf,
                    },
                ) as span:
                    try:
                        self._context_cache.update(event)
                    except Exception as exc:
                        span.set_status(StatusCode.ERROR, str(exc))
                        span.record_exception(exc)
                        raise
            except Exception as exc:
                self.logger.warning(
                    "base_group_service.bar_cache_error",
                    error=str(exc),
                )

    async def _trigger_loop(self) -> None:
        """Dispatch agents on trigger events."""
        assert self._trigger_consumer is not None
        async for _topic, _key, payload in self._trigger_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                with self.tracer.start_as_current_span(
                    "group.handle_trigger",
                    attributes={ATTR_GROUP_ID: self.group_id},
                ) as span:
                    try:
                        await self._handle_trigger(payload)
                    except Exception as exc:
                        span.set_status(StatusCode.ERROR, str(exc))
                        span.record_exception(exc)
                        raise
            except Exception as exc:
                self.logger.exception(
                    "base_group_service.trigger_error",
                    error=str(exc),
                )

    @abstractmethod
    async def _handle_trigger(self, event: dict) -> None:
        """Process a trigger event. Subclasses own all parsing and dispatch logic."""
        ...

    async def _publish_result(self, result: AgentOutput) -> None:
        """Publish AgentOutput to output topic."""
        assert self._producer is not None
        payload = result.model_dump(mode="json")
        await self._producer.publish(self.output_topic, payload)
