"""NarrativeOrchestrator — single-signal narrative generation.

Accepts BarIntelligenceRecord, builds appropriate prompt tier, calls LLM.
Pure orchestration — no Kafka, no DB. Use LLMProviderChain from src.core.llm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.intelligence.narrative.parsers import parse_bar_intelligence_record
from src.intelligence.narrative.prompts import build_deep_prompt, build_short_prompt

if TYPE_CHECKING:
    from src.intelligence.schemas import BarIntelligenceRecord

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a professional equity futures market analyst. "
    "Be direct and precise. No fluff. Use trader terminology. "
    "Never hedge with 'may', 'might', 'could' — state what the data shows."
)


class NarrativeOrchestrator:
    """Generate a per-signal narrative using the provided LLM chain."""

    def __init__(self, chain: object, max_tokens: int = 200, timeout: float = 30.0) -> None:
        self._chain = chain
        self._max_tokens = max_tokens
        self._timeout = timeout

    async def generate(
        self,
        record: BarIntelligenceRecord,
        deep: bool = False,
        call_type: str = "narrative",
    ) -> str | None:
        """Return narrative string or None if record has no actionable signal."""
        parsed = parse_bar_intelligence_record(record)
        if parsed is None:
            return None

        prompt = build_deep_prompt(record) if deep else build_short_prompt(record)

        result = await self._chain.generate(
            prompt=prompt,
            system=_SYSTEM_PROMPT,
            max_tokens=self._max_tokens,
            timeout=self._timeout,
        )

        if result is None:
            logger.warning(
                "narrative.llm_failed",
                symbol=parsed["symbol"],
                tf=parsed["timeframe"],
            )
        return result
