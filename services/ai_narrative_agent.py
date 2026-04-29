"""ai_narrative_agent.py -- NarrativeGroupComputeAgent extending BaseGroupService.

Per B+ architecture: narrative group service, extends BaseGroupService.
group_id="narrative", has_graduation=False
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings
from src.core.ai.base_group_service import BaseGroupService
from src.core.ai.output import AgentOutput
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_intelligence_journal, topic_narratives
from src.intelligence.ai.narrative.narrative_agent import NarrativeComputeAgent

logger = structlog.get_logger(__name__)


class NarrativeGroupComputeAgent(BaseGroupService):
    """Narrative group service extending BaseGroupService.

    Subscribes to intelligence journal topic, generates LLM narrative per signal,
    publishes to narratives topic.

    Per D-33: has_graduation=False (narrative group has no graduation).
    """

    group_id = "narrative"
    has_graduation = False

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self.settings = settings

        # Single narrative agent
        self._agents = [NarrativeComputeAgent(llm_chain=self._llm_chain)]

    @property
    def agents(self) -> list:
        """List of agents managed by this group service."""
        return self._agents

    @property
    def trigger_topics(self) -> list[str]:
        """Kafka topics that trigger agent dispatch."""
        return [topic_intelligence_journal(self.settings.env_name)]

    @property
    def output_topic(self) -> str:
        """Kafka topic for agent output fan-out."""
        return topic_narratives(self.settings.env_name)

    def _bar_topics(self) -> list[str]:
        """No bar consumer needed — narrative triggers from intelligence journal only."""
        return []

    async def _setup(self) -> None:
        """Wire infrastructure beyond BaseGroupService defaults."""
        # Don't call super()._setup() since we don't need bar consumer
        # Just wire trigger consumer and producer

        # Wire trigger consumer (for agent dispatch)
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

        # Seed context cache from DB
        await self._seed_context_cache()

        agent_ids = [a.agent_id for a in self._agents]
        self.logger.info("narrative_group.started", agents=agent_ids)

    async def _run(self) -> None:
        """Run main loop: trigger_loop only (no bar_loop for narrative)."""
        # Narrative doesn't need bar_loop or graduation_loop
        trigger_task = asyncio.create_task(self._trigger_loop())
        try:
            await trigger_task
        except Exception:
            trigger_task.cancel()
            raise

    # Drop bars older than this — prevents wasting LLM tokens on replay/stale data.
    _STALENESS_LIMIT = timedelta(minutes=10)

    async def _handle_trigger(self, event: dict) -> None:
        """Process a single BarIntelligenceRecord payload.

        Wraps the payload in a lightweight adapter so NarrativeComputeAgent can
        access AIContext fields.

        Includes staleness gate (D-35) — skip stale bars to avoid wasting LLM tokens.
        """
        # Adapt dict payload to object with attribute access
        adapted = _RecordAdapter(event) if isinstance(event, dict) else event

        # Freshness gate — skip stale bars (replay, backfill, lag) to avoid
        # wasting LLM tokens on data that is no longer actionable.
        bar_ts_raw = adapted.intelligence.ts
        if bar_ts_raw:
            try:
                bar_ts = (
                    bar_ts_raw
                    if isinstance(bar_ts_raw, datetime)
                    else datetime.fromisoformat(str(bar_ts_raw))
                )
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=UTC)
                age = datetime.now(UTC) - bar_ts
                if age > self._STALENESS_LIMIT:
                    self.logger.info(
                        "narrative_group.skipped_stale_bar",
                        symbol=adapted.intelligence.symbol,
                        tf=adapted.intelligence.tf,
                        bar_age_s=round(age.total_seconds()),
                    )
                    return
            except (ValueError, TypeError):
                pass  # Unparseable ts — let it through rather than block

        # Extract signal_id
        signal_id = getattr(adapted, "record_id", None)

        # Build AIContext for NarrativeComputeAgent
        symbol = adapted.intelligence.symbol
        tf = adapted.intelligence.tf

        context = self._context_cache.build(
            symbol=symbol,
            tf=tf,
            tiers_needed=self._agents[0].tiers_needed,
            signal=event,
            signal_id=signal_id,
        )

        if context is None:
            self.logger.warning(
                "narrative_group.no_context",
                symbol=symbol,
                tf=tf,
            )
            return

        # Run narrative agent
        from src.core.ai.safe_wrapper import SafeAgentWrapper

        wrapper = SafeAgentWrapper(self._agents[0])
        result = await wrapper.compute(context)

        if isinstance(result, Exception):
            self.logger.error(
                "narrative_group.agent_exception",
                error=str(result),
            )
            return

        if isinstance(result, AgentOutput):
            # Check if narrative was generated (not TF-gated)
            narrative_text = result.payload.get("text", "")
            if not narrative_text or result.error:
                # TF gate or neutral result - skip publishing
                return

            # Publish narrative to output topic
            await self._publish_result(result)


class _IntelAdapter:
    """Lightweight adapter for the intelligence sub-dict."""

    __slots__ = ("symbol", "tf", "ts")

    def __init__(self, d: dict) -> None:
        self.symbol = d.get("symbol", "")
        self.tf = d.get("tf", "")
        self.ts = d.get("ts", "")


class _RecordAdapter:
    """Lightweight adapter for raw dict BarIntelligenceRecord payloads."""

    __slots__ = (
        "intelligence",
        "winner_direction",
        "winner_confidence",
        "winner_plugin",
        "record_id",
    )

    def __init__(self, d: dict) -> None:
        intel_raw = d.get("intelligence", {})
        self.intelligence = _IntelAdapter(intel_raw if isinstance(intel_raw, dict) else {})
        self.winner_direction = d.get("winner_direction")
        self.winner_confidence = d.get("winner_confidence")
        self.winner_plugin = d.get("winner_plugin")
        self.record_id = d.get("record_id")


def main() -> None:
    settings = Settings()
    service = NarrativeGroupComputeAgent(settings)
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
