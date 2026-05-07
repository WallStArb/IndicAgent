"""SwarmLedgerWriterAgent — writer-owned projection of swarm aggregate adjustments into signal_ledger.

Phase 80, D-07: strict separation of concerns — AlphaSwarmComputeAgent emits aggregate
events on the swarm.alpha topic; this writer owns DB persistence of those adjustments.

Updates signal_ledger columns: adjusted_confidence, swarm_multiplier, swarm_agent_count.
The original signal_ledger.confidence column is NEVER modified.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 -- project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_swarm_alpha
from src.observability.metrics import SWARM_SIGNAL_LEDGER_UPDATE_TOTAL

logger = structlog.get_logger(__name__)

# Exponential backoff schedule for missing signal_ledger rows.
# Swarm events may race the original signal_writer insert.
# 5 attempts max; total max wait ~3.85s per signal.
_RETRY_BACKOFF_S: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0, 2.0)


class SwarmLedgerWriterAgent(BaseAgent):
    """Consumes swarm.alpha events and projects aggregate adjustments into signal_ledger.

    Writer responsibilities (D-07):
    - Subscribe to topic_swarm_alpha(env_name)
    - UPDATE signal_ledger SET adjusted_confidence, swarm_multiplier, swarm_agent_count
    - Bounded retry/backoff when signal_ledger row not yet inserted
    - Emit SWARM_SIGNAL_LEDGER_UPDATE_TOTAL with status=success|retry|miss
    """

    agent_id = "swarm_ledger_writer"

    def __init__(self, **kwargs) -> None:
        setup_service_logging("logs/swarm_ledger_writer_agent.log")
        super().__init__(name="swarm_ledger_writer", **kwargs)
        self._pool: asyncpg.Pool | None = None
        self._consumer: KafkaConsumerClient | None = None

    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(
            self.settings.database_url,
            min_size=2,
            max_size=8,
        )
        self._consumer = KafkaConsumerClient(
            topic_swarm_alpha(self.settings.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="swarm_ledger_writer_consumer",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self.logger.info(
            "swarm_ledger_writer.started",
            topic=topic_swarm_alpha(self.settings.env_name),
        )

    async def _run(self) -> None:
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                await self._handle_event(payload)
            except Exception as exc:
                self.logger.warning("swarm_ledger_writer.handle_failed", error=str(exc))

    async def _teardown(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._pool is not None:
            await self._pool.close()

    async def _handle_event(self, payload: dict) -> None:
        """Validate payload and dispatch to _apply_projection."""
        signal_id = payload.get("signal_id")
        swarm_multiplier = payload.get("swarm_multiplier")
        adjusted_confidence = payload.get("adjusted_confidence")
        swarm_agent_count = payload.get("swarm_agent_count")

        if not signal_id or swarm_multiplier is None or adjusted_confidence is None:
            self.logger.warning(
                "swarm_ledger_writer.invalid_event",
                missing_fields=[
                    k
                    for k, v in {
                        "signal_id": signal_id,
                        "swarm_multiplier": swarm_multiplier,
                        "adjusted_confidence": adjusted_confidence,
                    }.items()
                    if v is None or v == ""
                ],
            )
            return

        await self._apply_projection(
            signal_id=signal_id,
            swarm_multiplier=float(swarm_multiplier),
            adjusted_confidence=float(adjusted_confidence),
            swarm_agent_count=int(swarm_agent_count) if swarm_agent_count is not None else None,
        )

    async def _apply_projection(
        self,
        signal_id: str,
        swarm_multiplier: float,
        adjusted_confidence: float,
        swarm_agent_count: int | None,
    ) -> None:
        """UPDATE signal_ledger with swarm aggregate adjustments.

        Retries with exponential backoff when signal_ledger row not yet inserted
        (race condition between signal_writer and swarm_ledger_writer).
        """
        assert self._pool is not None
        for delay in _RETRY_BACKOFF_S:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE signal_ledger
                       SET adjusted_confidence = $2,
                           swarm_multiplier = $3,
                           swarm_agent_count = $4
                     WHERE signal_id = $1
                    """,
                    signal_id,
                    adjusted_confidence,
                    swarm_multiplier,
                    swarm_agent_count,
                )
            # asyncpg returns "UPDATE N" — parse N to determine row found
            try:
                rowcount = int(result.split()[-1])
            except (ValueError, IndexError):
                rowcount = 0

            if rowcount > 0:
                SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels(status="success").inc()
                return

            SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels(status="retry").inc()
            await asyncio.sleep(delay)

        # Exhausted all retries — row never appeared in signal_ledger
        SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels(status="miss").inc()
        self.logger.warning(
            "swarm_ledger_writer.row_missing",
            signal_id=signal_id,
            attempts=len(_RETRY_BACKOFF_S),
        )


def main() -> None:
    settings = Settings()
    agent = SwarmLedgerWriterAgent(settings=settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
