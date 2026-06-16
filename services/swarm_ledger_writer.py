"""SwarmLedgerWriter — writer-owned projection of swarm aggregate adjustments into signal_ai_enrichment.

Phase 80, D-07: strict separation of concerns — AlphaSwarm emits aggregate
events on the swarm.alpha topic; this writer owns DB persistence of those adjustments.

AI-SEP-01 (Phase 70, Plan 02): Writes to signal_ai_enrichment (AI-owned table) instead of
signal_ledger. The quant table signal_ledger is now immutable after the quant writer's INSERT.
Columns adjusted_confidence, swarm_multiplier, swarm_agent_count on signal_ledger are legacy
nullable columns preserved for backwards compatibility — they are no longer populated by this
writer. Downstream readers must LEFT JOIN signal_ai_enrichment instead.

Also populates ml_score / ml_model_id in signal_ai_enrichment when the aggregate swarm event
contains a ml_scorer_v1 agent payload.

Phase 130 (D-06): FK existence check updated from signal_ledger to signal_events. signal_ledger
is dropped in Phase 130; signal_events is the canonical detection table.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 -- project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_swarm_alpha
from src.observability.metrics import SWARM_SIGNAL_LEDGER_UPDATE_TOTAL

logger = structlog.get_logger(__name__)

# Exponential backoff schedule for missing signal_ledger rows.
# Swarm events may race the original signal_writer insert.
# 5 attempts max; total max wait ~3.85s per signal.
_RETRY_BACKOFF_S: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0, 2.0)


class _SignalNotReadyError(Exception):
    """signal_events row not yet visible; triggers retry backoff."""


# AI-SEP-01: UPSERT into AI-owned signal_ai_enrichment table (not signal_ledger UPDATE).
# FK race condition (enrichment arriving before signal_ledger row) is handled by
# the _RETRY_BACKOFF_S loop — same race as before, application-layer FK enforcement.
_UPSERT_ENRICHMENT_SQL = """
INSERT INTO signal_ai_enrichment
    (signal_id, swarm_multiplier, adjusted_confidence, swarm_agent_count, enriched_at)
VALUES ($1::uuid, $2, $3, $4, NOW())
ON CONFLICT (signal_id) DO UPDATE SET
    swarm_multiplier     = EXCLUDED.swarm_multiplier,
    adjusted_confidence  = EXCLUDED.adjusted_confidence,
    swarm_agent_count    = EXCLUDED.swarm_agent_count,
    enriched_at          = NOW()
"""

# Secondary UPSERT for ml_score / ml_model_id when ml_scorer_v1 payload is present
# in the aggregate swarm event. Issued inside the same retry envelope as the base enrichment.
_UPSERT_ML_SCORE_SQL = """
INSERT INTO signal_ai_enrichment (signal_id, ml_score, ml_model_id, enriched_at)
VALUES ($1::uuid, $2, $3::uuid, NOW())
ON CONFLICT (signal_id) DO UPDATE SET
    ml_score    = EXCLUDED.ml_score,
    ml_model_id = EXCLUDED.ml_model_id,
    enriched_at = NOW()
"""


class SwarmLedgerWriter(BaseDaemon):
    """Consumes swarm.alpha events and UPSERTs aggregate adjustments into signal_ai_enrichment.

    Writer responsibilities (D-07, AI-SEP-01):
    - Subscribe to topic_swarm_alpha(env_name)
    - UPSERT signal_ai_enrichment (swarm_multiplier, adjusted_confidence, swarm_agent_count)
    - UPSERT ml_score / ml_model_id into signal_ai_enrichment when ml_scorer_v1 payload present
    - Bounded retry/backoff when signal_ledger row not yet visible (application-layer FK)
    - Emit SWARM_SIGNAL_LEDGER_UPDATE_TOTAL with status=success|retry|miss
    """

    agent_id = "swarm_ledger_writer"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool: asyncpg.Pool | None = None
        self._consumer: KafkaConsumerClient | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="swarm_ledger_writer",
            min_size=2,
            max_size=8,
        )
        self._consumer = KafkaConsumerClient(
            topic_swarm_alpha(self.settings.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="swarm_ledger_writer_consumer",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
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
                terminal = await self._handle_event(payload)
            except Exception as error:
                # transient (e.g. DB) failure: do NOT commit, allow re-delivery
                self.logger.warning("swarm_ledger_writer.handle_failed", error=str(error))
                continue
            if terminal:
                # success OR terminal-invalid: commit so we do not replay forever
                await self._consumer.commit()

    async def _teardown(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._pool is not None:
            await self._pool.close()

    async def _handle_event(self, payload: dict) -> bool:
        """Validate payload and dispatch to _apply_projection.

        Extracts aggregate swarm fields (swarm_multiplier, adjusted_confidence,
        swarm_agent_count) and optionally ml_score / ml_model_id from the
        ml_scorer_v1 agent payload, if present in the aggregate event.

        Returns True when the message reached a terminal state (successful write
        or terminal-invalid payload). Returns True for invalid payloads because
        a malformed payload will never become valid on re-delivery. Transient DB
        errors propagate as exceptions so the caller can skip the commit.
        """
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
            return True

        # Extract ml_scorer_v1 payload from aggregate agent_outputs list if present.
        # The AlphaSwarm aggregate event carries individual agent payloads
        # under "agent_outputs": [{"agent_id": ..., "payload": {...}}, ...].
        ml_score: float | None = None
        ml_model_id: str | None = None
        agent_outputs = payload.get("agent_outputs") or []
        for agent_out in agent_outputs:
            if isinstance(agent_out, dict) and agent_out.get("agent_id") == "ml_scorer_v1":
                agent_payload = agent_out.get("payload") or {}
                raw_ml_score = agent_payload.get("ml_score")
                if raw_ml_score is not None:
                    ml_score = float(raw_ml_score)
                    raw_model_id = agent_payload.get("model_id")
                    ml_model_id = str(raw_model_id) if raw_model_id else None
                break

        await self._apply_projection(
            signal_id=signal_id,
            swarm_multiplier=float(swarm_multiplier),
            adjusted_confidence=float(adjusted_confidence),
            swarm_agent_count=int(swarm_agent_count) if swarm_agent_count is not None else None,
            ml_score=ml_score,
            ml_model_id=ml_model_id,
        )
        return True

    async def _apply_projection(
        self,
        signal_id: str,
        swarm_multiplier: float,
        adjusted_confidence: float,
        swarm_agent_count: int | None,
        ml_score: float | None = None,
        ml_model_id: str | None = None,
    ) -> None:
        """UPSERT swarm aggregate adjustments into signal_ai_enrichment (AI-SEP-01).

        Retries with exponential backoff — application-layer FK: signal_ai_enrichment
        references signal_events(signal_id) logically; the enrichment INSERT must wait
        for the signal_events row to be visible (race condition between signal_writer
        and swarm_ledger_writer). The retry loop handles this identically to before.

        If ml_score is provided (ml_scorer_v1 agent payload present in aggregate event),
        a second UPSERT populates ml_score / ml_model_id in the same row via
        _UPSERT_ML_SCORE_SQL inside the same connection acquisition.
        """
        assert self._pool is not None
        for delay in _RETRY_BACKOFF_S:
            try:
                async with self._pool.acquire() as conn:
                    # Application-layer FK check: signal_ai_enrichment has no declarative FK
                    # on signal_id (TimescaleDB limitation), so ForeignKeyViolationError will
                    # never fire. Enforce the logical constraint explicitly instead.
                    # Phase 130 D-06: check signal_events (not signal_ledger, which is dropped).
                    exists = await conn.fetchval(
                        "SELECT 1 FROM signal_events WHERE signal_id = $1::uuid LIMIT 1",
                        str(signal_id),
                    )
                    if not exists:
                        raise _SignalNotReadyError()

                    # Base enrichment UPSERT: swarm aggregate fields.
                    # Parameters: ($1 signal_id::uuid, $2 swarm_multiplier,
                    #              $3 adjusted_confidence, $4 swarm_agent_count)
                    await conn.execute(
                        _UPSERT_ENRICHMENT_SQL,
                        str(signal_id),
                        swarm_multiplier,
                        adjusted_confidence,
                        swarm_agent_count,
                    )

                    # Optional ml_score branch: issued in same connection.
                    if ml_score is not None:
                        await conn.execute(
                            _UPSERT_ML_SCORE_SQL,
                            str(signal_id),
                            ml_score,
                            str(ml_model_id) if ml_model_id else None,
                        )

                SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.add(1, {"status": "success"})
                self.logger.debug(
                    "swarm_ledger_writer.enrichment_written",
                    signal_id=signal_id,
                    has_ml_score=(ml_score is not None),
                )
                return

            except _SignalNotReadyError:
                SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.add(1, {"status": "retry"})
                await asyncio.sleep(delay)

            except asyncpg.exceptions.InvalidTextRepresentationError:
                # Malformed UUID — no retry
                self.logger.warning(
                    "swarm_ledger_writer.invalid_uuid",
                    signal_id=signal_id,
                )
                SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.add(1, {"status": "miss"})
                return

        # Exhausted all retries — signal_ledger row never became visible
        SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.add(1, {"status": "miss"})
        self.logger.warning(
            "swarm_ledger_writer.row_missing",
            signal_id=signal_id,
            attempts=len(_RETRY_BACKOFF_S),
        )


def main() -> None:
    settings = Settings()
    agent = SwarmLedgerWriter(settings=settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
