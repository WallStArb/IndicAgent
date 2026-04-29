"""BaseGroupService — shared dispatcher for agent groups."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import ValidationError

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContextCache
from src.core.ai.output import AgentOutput
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.llm.chain import LLMProviderChain

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class BaseGroupService(BaseAgent, ABC):
    """Shared dispatcher for agent groups (alpha, narrative, risk).

    Subclasses declare 3 abstract properties:
      - agents: list[BaseAIAgent]
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
    has_graduation: bool = False

    @property
    @abstractmethod
    def agents(self) -> list[BaseAIAgent]:
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
    def _bar_topic(self) -> str:
        """Topic for bar data that updates AIContextCache."""
        ...

    def __init__(self, settings: Settings, *args: Any, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, max_idle_seconds=300, settings=settings)
        self.settings = settings
        self._context_cache = AIContextCache()
        self._bar_consumer: KafkaConsumerClient | None = None
        self._trigger_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._pool: Any | None = None  # asyncpg.Pool
        self._llm_chain: LLMProviderChain | None = None

    async def _setup(self) -> None:
        """Wire Kafka consumer/producer + DB pool + cache seeding.

        Subclasses should call super()._setup() then add group-specific wiring.
        """
        # Wire bar consumer (for AIContextCache updates)
        self._bar_consumer = KafkaConsumerClient(
            self._bar_topic(),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.group_id}_bar_consumer",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()

        # Wire trigger consumer (for agent dispatch)
        # Subscribe to all trigger topics
        self._trigger_consumer = KafkaConsumerClient(
            ",".join(self.trigger_topics),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.group_id}_trigger_consumer",
            auto_offset_reset="latest",
        )
        await self._trigger_consumer.start()
        await self._trigger_consumer.skip_lag_if_needed(max_lag=100)

        # Wire producer (for agent output fan-out)
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        # Wire DB pool (for context cache seeding)
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self.settings.database_url,
            min_size=2,
            max_size=5,
        )

        # Wire LLM chain (for LLM-based agents)
        self._llm_chain = LLMProviderChain(
            call_type=self.group_id,
            settings=self.settings,
            cache_ttl=300.0,
        )

        # Seed context cache from DB
        await self._seed_context_cache()

        # D-19: BaseGroupService must call super()._setup() for forward compatibility
        await super()._setup()

    async def _seed_context_cache(self) -> None:
        """Seed AIContextCache with recent intelligence_features rows."""
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (symbol, tf)
                    symbol, tf, ts, bar, i1, i4, i6, i7
                FROM intelligence_features
                WHERE ts > NOW() - INTERVAL '7 days'
                  AND i1 IS NOT NULL AND i4 IS NOT NULL
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
        bar_task = asyncio.create_task(self._bar_loop())
        trigger_task = asyncio.create_task(self._trigger_loop())
        tasks = [bar_task, trigger_task]

        if self.has_graduation:
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
        if self._pool:
            await self._pool.close()
        if self._bar_consumer:
            await self._bar_consumer.stop()
        if self._trigger_consumer:
            await self._trigger_consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def _bar_loop(self) -> None:
        """Update AIContextCache on each IntelligenceEvent."""
        assert self._bar_consumer is not None
        async for _topic, _key, payload in self._bar_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                # Deserialize IntelligenceEvent
                from src.intelligence.schemas import IntelligenceEvent

                event = IntelligenceEvent.model_validate(payload)
                self._context_cache.update(event)
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
                await self._handle_trigger(payload)
            except Exception as exc:
                self.logger.exception(
                    "base_group_service.trigger_error",
                    error=str(exc),
                )

    async def _handle_trigger(self, event: dict) -> None:
        """Build context per agent, gather in parallel, publish results."""
        from src.intelligence.schemas import RankedSignal

        # Extract trigger data (varies by group — alpha gets signals, narrative gets records)
        # Subclasses may override this method to customize trigger parsing
        try:
            signal = RankedSignal(**event) if self.group_id == "alpha" else None
            symbol = signal.symbol if signal else event.get("symbol")
            tf = signal.tf if signal else event.get("tf")
            signal_id = signal.signal_id if signal else None
        except (ValidationError, TypeError):
            self.logger.warning("base_group_service.invalid_trigger", event=event)
            return

        if not symbol or not tf:
            self.logger.warning("base_group_service.missing_symbol_tf", event=event)
            return

        # Build context per agent (parallel SafeAgentWrapper.compute calls)
        from src.core.ai.safe_wrapper import SafeAgentWrapper

        tasks = []
        for agent in self.agents:
            context = self._context_cache.build(
                symbol=symbol,
                tf=tf,
                tiers_needed=agent.tiers_needed,
                signal=signal,
                signal_id=signal_id,
            )
            if context is None:
                self.logger.warning(
                    "base_group_service.no_context",
                    agent_id=agent.agent_id,
                    symbol=symbol,
                    tf=tf,
                )
                continue

            wrapper = SafeAgentWrapper(agent)
            tasks.append(wrapper.compute(context))

        # Gather all agent outputs in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Publish results to output topic
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(
                        "base_group_service.agent_exception",
                        error=str(result),
                    )
                    continue
                if isinstance(result, AgentOutput):
                    await self._publish_result(result)

    async def _publish_result(self, result: AgentOutput) -> None:
        """Publish AgentOutput to output topic."""
        assert self._producer is not None
        payload = result.model_dump(mode="json")
        await self._producer.publish(self.output_topic, payload)

    async def _graduation_loop(self) -> None:
        """Background task: auto-flip shadow_only every 15 min (D-38).

        Evaluates all agents against graduation gates (Spearman correlation).
        Flips shadow_only False when gates pass.
        """
        import asyncio

        while self.running:
            try:
                await asyncio.sleep(900)  # 15 minutes
                # TODO: Implement graduation logic (Phase 75)
                # - Query signal_lineage for agent predictions
                # - Evaluate Spearman correlation gates
                # - Flip agent.shadow_only when gates pass
                # - Publish graduation event to topic_swarm_graduation
            except Exception as exc:
                self.logger.exception(
                    "base_group_service.graduation_error",
                    error=str(exc),
                )
