"""NarrativeGroupComputeAgent — per-signal market narrative generation service.

Extends BaseGroupService (group_id="narrative"). Subscribes to i7 signals,
dispatches NarrativeComputeAgent for eligible timeframes (5m+), and publishes
narrative AgentOutput to topic_narratives().

TF gate: delegated to NarrativeComputeAgent._NARRATIVE_TFS.
Schema version gate: v0 signals skipped (contaminated zone data).
No graduation loop — narrative text output has no pnl_r correlation axis.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings
from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.base_group_service import BaseGroupService
from src.core.service_utils import is_signal_stale, parse_iso_ts, setup_service_logging
from src.core.stream_keys import (
    topic_intelligence,
    topic_intelligence_i7_signals,
    topic_narratives,
)
from src.intelligence.ai.narrative.narrative_agent import NarrativeComputeAgent
from src.intelligence.schemas import signal_dict_to_ranked
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION

logger = structlog.get_logger(__name__)


class NarrativeGroupComputeAgent(BaseGroupService):
    """Single-agent narrative group service.

    One NarrativeComputeAgent, one consumer group, one output topic.
    Shadow registry enrollment on startup so the agent appears in the registry.
    """

    group_id = "narrative"
    has_graduation = False

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self._narrative_agent: NarrativeComputeAgent | None = None

    @property
    def agents(self) -> list[BaseAIAgent]:
        return [self._narrative_agent] if self._narrative_agent else []

    @property
    def trigger_topics(self) -> list[str]:
        return [topic_intelligence_i7_signals(self.settings.env_name)]

    @property
    def output_topic(self) -> str:
        return topic_narratives(self.settings.env_name)

    def _bar_topics(self) -> list[str]:
        return [topic_intelligence(self.settings.env_name)]

    async def _setup(self) -> None:
        await super()._setup()
        # _llm_chain is wired by super()._setup() — construct agent here.
        self._narrative_agent = NarrativeComputeAgent(llm_chain=self._llm_chain)

        if self._pool is not None:
            await self._shadow_registry_ensure_agents(self.agents)

        self.logger.info(
            "narrative_group.started",
            agent_id=self._narrative_agent.agent_id,
        )

    # Narrative validity: skip signals older than N × TF duration.
    # A 5m signal older than 10m describes a market that no longer exists.
    _STALENESS_MULTIPLIER = 2

    async def _handle_trigger(self, event: dict) -> None:
        signals = event.get("signals", [])
        if signals:
            now = datetime.now(UTC)
            await asyncio.gather(*(self._process_one_signal(s, now) for s in signals))

    async def _process_one_signal(self, raw_signal: dict, now: datetime) -> None:
        if raw_signal.get("signal_schema_version", SIGNAL_SCHEMA_VERSION) == SIGNAL_SCHEMA_VERSION:
            return

        tf = raw_signal.get("tf") or raw_signal.get("timeframe", "")
        if tf not in NarrativeComputeAgent._NARRATIVE_TFS:
            return

        # Quality gate: only winners passed the full 6-stage pipeline
        if not raw_signal.get("was_selected", False):
            return

        # Staleness gate: signal context expires after 2 × TF duration
        ts_raw = raw_signal.get("timestamp")
        if ts_raw is not None:
            signal_ts = parse_iso_ts(ts_raw)
            if signal_ts is not None and is_signal_stale(
                signal_ts, tf, now, self._STALENESS_MULTIPLIER
            ):
                self.logger.debug(
                    "narrative_group.stale_skip",
                    symbol=raw_signal.get("symbol"),
                    tf=tf,
                )
                return

        try:
            signal = signal_dict_to_ranked(raw_signal)
        except Exception as exc:
            self.logger.warning("narrative_group.invalid_signal", exc_info=exc)
            return

        symbol = signal.symbol
        signal_id = signal.signal_id or uuid4()
        signal_dict = signal.model_dump()

        assert self._narrative_agent is not None
        context = self._context_cache.build(
            symbol=symbol,
            tf=signal.tf,
            tiers_needed=self._narrative_agent.tiers_needed,
            signal=signal_dict,
            signal_id=signal_id,
        )
        if context is None:
            self.logger.warning("narrative_group.no_context", symbol=symbol, tf=signal.tf)
            return

        try:
            result = await self._narrative_agent.compute(context)
        except Exception as exc:
            self.logger.error("narrative_group.compute_error", exc_info=exc)
            return

        if result.error:
            self.logger.warning(
                "narrative_group.agent_error",
                error=result.error,
                symbol=symbol,
                tf=signal.tf,
            )
            return

        self.logger.info(
            "narrative_group.generated",
            signal_id=str(signal_id),
            symbol=symbol,
            tf=signal.tf,
            model=result.payload.get("model", ""),
            prompt_version=result.payload.get("prompt_version", ""),
            chars=len(result.payload.get("text", "")),
        )

        assert self._producer is not None
        self._producer.publish(self.output_topic, msg=result.model_dump(mode="json"))


def main() -> None:
    setup_service_logging("logs/narrative_group_compute_agent.log")
    settings = Settings()
    service = NarrativeGroupComputeAgent(settings)
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
