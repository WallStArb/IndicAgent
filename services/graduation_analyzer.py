#!/usr/bin/env python3
"""GraduationAnalyzer — event-driven Renaissance graduation evaluator.

Consumes topic_lifecycle_transitions, evaluates per-segment graduation when
enough new resolutions accumulate, publishes GraduationResult to
topic_transform_graduation.

Phase 72 Plan 09.
Consumer group: graduation_compute_group
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import pandas as pd

from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import (
    topic_lifecycle_transitions,
    topic_transform_graduation,
    topic_transform_graduation_dlq,
)
from src.intelligence.swarm.graduation import (
    EVAL_RESOLUTION_THRESHOLD,
    EVAL_ROLLING_WINDOW_DAYS,
    evaluate_all,
)
from src.observability.metrics import counter

CONSUMER_GROUP = "graduation_compute_group"

# ---------------------------------------------------------------------------
# SQL queries
# ---------------------------------------------------------------------------

_EVAL_QUERY = """
SELECT stl.multiplier, sl.counterfactual_pnl_r AS pnl_r, stl.ts
FROM signal_transform_log stl
JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
WHERE stl.transform_id = $1
  AND stl.transform_version = $2
  AND stl.segment_key = $3
  AND stl.ts >= NOW() - ($4::int || ' days')::interval
  AND sl.counterfactual_pnl_r IS NOT NULL
ORDER BY stl.ts ASC
"""

_TRANSFORM_LOG_FOR_SIGNAL = """
SELECT transform_id, transform_version, segment_key
FROM signal_transform_log
WHERE signal_id = $1::uuid
"""

_SEED_COUNTERS_QUERY = """
SELECT
    tg.transform_id,
    tg.transform_version,
    tg.segment_key,
    COUNT(DISTINCT stl.signal_id) AS new_exits
FROM transform_graduation tg
LEFT JOIN LATERAL (
    SELECT stl.signal_id
    FROM signal_transform_log stl
    JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
    WHERE stl.transform_id = tg.transform_id
      AND stl.transform_version = tg.transform_version
      AND stl.segment_key = tg.segment_key
      AND sl.exit_at >= tg.evaluated_at
      AND sl.counterfactual_pnl_r IS NOT NULL
) stl ON TRUE
GROUP BY tg.transform_id, tg.transform_version, tg.segment_key
"""


class GraduationAnalyzer(BaseDaemon):
    """Event-driven transform graduation evaluator.

    Consumes lifecycle.transitions EXIT events, increments per-segment counters,
    triggers evaluation when EVAL_RESOLUTION_THRESHOLD is reached, and publishes
    GraduationResult payloads to topic_transform_graduation.

    Invariants:
      - DB-read-at-evaluation only (not DB-ignorant — must JOIN signal_ledger)
      - Counters are ephemeral; recovered from transform_graduation on restart
      - Never crashes the consume loop on evaluation errors; routes to DLQ instead
    """

    def __init__(self) -> None:
        super().__init__()

        # Kafka clients (initialized in _setup)
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None

        # Per-segment resolution counters: (transform_id, transform_version, segment_key) -> count
        self._counters: dict[tuple[str, str, str], int] = defaultdict(int)

        # Metrics
        self._exits_consumed = counter(
            "graduation_compute_exits_consumed_total",
            "Lifecycle EXIT transitions processed",
        )
        self._evaluations_total = counter(
            "graduation_compute_evaluations_total",
            "Per-segment graduation evaluations performed",
        )
        self._evaluation_errors = counter(
            "graduation_compute_evaluation_errors_total",
            "Failed graduation evaluations",
        )

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_lifecycle_transitions(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_transform_graduation(self.env_name)]

    def _dlq_topic(self) -> str | None:
        return topic_transform_graduation_dlq(self.env_name)

    async def _setup(self) -> None:
        """Open DB pool, start Kafka clients, seed counters from transform_graduation."""
        self._pool = await create_db_pool(
            self.settings.database_url,
            min_size=2,
            max_size=5,
        )

        self._consumer = KafkaConsumerClient(
            topic_lifecycle_transitions(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        await self._consumer.skip_lag_if_needed(max_lag=10_000)

        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        await self._seed_counters()
        self.logger.info(
            "graduation_compute.started",
            segments_seeded=len(self._counters),
        )

    async def _seed_counters(self) -> None:
        """Re-count new resolutions since last evaluated_at per segment.

        For each known (transform_id, version, segment_key) in transform_graduation,
        count signals resolved since the last evaluated_at. This recovers the
        counter state after a restart so we don't miss a threshold crossing.

        Segments with no row in transform_graduation start at counter=0 and fire
        their first evaluation after EVAL_RESOLUTION_THRESHOLD new resolutions.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SEED_COUNTERS_QUERY)

        for row in rows:
            key = (row["transform_id"], row["transform_version"], row["segment_key"])
            self._counters[key] = int(row["new_exits"] or 0)

        self.logger.info(
            "graduation_compute.counters_seeded",
            segments=len(self._counters),
        )

    async def _run(self) -> None:
        """Main consume loop — process lifecycle transitions until stop event."""
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                await self._handle_transition(payload)
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.warning(
                    "graduation_compute.handle_error",
                    error=str(error),
                )

    async def _handle_transition(self, payload: dict) -> None:
        """Process a single lifecycle transition payload.

        Only EXIT transitions trigger counter increments. All other types are
        silently ignored so non-EXIT traffic (ACTIVATION, MAE_MFE_UPDATE, etc.)
        passes through with zero overhead.
        """
        if not isinstance(payload, dict):
            return
        if payload.get("transition_type") != "EXIT":
            return

        signal_id = payload.get("signal_id")
        if not signal_id:
            return

        self._exits_consumed.add(1)

        # Fetch all transform rows for this resolved signal
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_TRANSFORM_LOG_FOR_SIGNAL, str(signal_id))

        for row in rows:
            key = (row["transform_id"], row["transform_version"], row["segment_key"])
            self._counters[key] += 1

            if self._counters[key] >= EVAL_RESOLUTION_THRESHOLD:
                success = await self._evaluate_segment(*key)
                if success:
                    self._counters[key] = 0

    async def _evaluate_segment(
        self,
        transform_id: str,
        transform_version: str,
        segment_key: str,
    ) -> bool:
        """Run Renaissance graduation evaluation for one (transform, version, segment).

        Fetches rolling 90d data, calls evaluate_all(), publishes result to Kafka.
        Returns True on success (counter should reset), False on any failure.
        On failure: logs, increments error counter, routes error payload to DLQ.
        """
        assert self._pool is not None
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    _EVAL_QUERY,
                    transform_id,
                    transform_version,
                    segment_key,
                    EVAL_ROLLING_WINDOW_DAYS,
                )

            if not rows:
                self.logger.info(
                    "graduation_compute.eval_skipped_no_data",
                    transform_id=transform_id,
                    segment_key=segment_key,
                )
                return True

            df = pd.DataFrame([dict(r) for r in rows])
            result = evaluate_all(
                df,
                transform_id=transform_id,
                transform_version=transform_version,
                segment_key=segment_key,
            )

            assert self._producer is not None
            await self._producer.publish(
                topic_transform_graduation(self.env_name),
                result,
                key=f"{transform_id}:{segment_key}",
            )
            self._evaluations_total.add(1)
            self.logger.info(
                "graduation_compute.evaluated",
                transform_id=transform_id,
                segment_key=segment_key,
                n=result["n"],
                is_graduated=result["is_graduated"],
            )
            return True

        except Exception as error:
            self._evaluation_errors.add(1)
            self.logger.exception(
                "graduation_compute.eval_error",
                transform_id=transform_id,
                segment_key=segment_key,
                error=str(error),
            )
            # Route to DLQ so the error is traceable without crashing the loop
            dlq_payload = {
                "transform_id": transform_id,
                "transform_version": transform_version,
                "segment_key": segment_key,
                "error": str(error),
                "ts": datetime.now(UTC).isoformat(),
            }
            await self._send_to_dlq(dlq_payload, error)
            return False

    async def _teardown(self) -> None:
        """Close Kafka clients and DB pool."""
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            except Exception:
                pass
        if self._producer is not None:
            try:
                await self._producer.stop()
            except Exception:
                pass
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception:
                pass


async def main() -> None:
    agent = GraduationAnalyzer()
    try:
        await agent.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
