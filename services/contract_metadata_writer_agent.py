#!/usr/bin/env python3
"""ContractMetadataWriterAgent — contract_metadata seeding and front-month promotion.

Stage 1 (SEED): Bootstraps contract_metadata from settings.py on startup.
Stage 3 (PROMOTE): Consumes RollEvents and atomically promotes the front-month
  contract in contract_metadata, then broadcasts ContractUpdateEvent.

Consumes: market.events.roll
Produces: contract_metadata (DB), market.events.contract_update (Kafka), market.events.roll.dlq

Metrics port: :9124

Golden Signals:
- Traffic: contract_writer_rolls_processed_total, contract_writer_seeds_inserted_total
- Latency: contract_writer_processing_latency_seconds
- Errors: contract_writer_roll_errors_total
- Saturation: (implicit — no buffer; events processed synchronously)

Version: 1.0.0
Last Updated: 2026-04-02
Status: Phase 58.1 Plan 02
"""

from __future__ import annotations

import asyncio
import os
import sys
import time as _time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.models import AssetClass
from src.core.schemas.market_events import ContractUpdateEvent, RollEvent
from src.core.stream_keys import (
    topic_contract_updates,
    topic_roll_dlq,
    topic_roll_events,
)

# ---------------------------------------------------------------------------
# Module-level metrics — prevents duplicate registration across test runs
# ---------------------------------------------------------------------------

_ROLLS_PROCESSED = Counter(
    "contract_writer_rolls_processed_total",
    "Roll events successfully processed",
    ["agent"],
)
_ROLL_ERRORS = Counter(
    "contract_writer_roll_errors_total",
    "Roll event processing failures",
    ["agent"],
)
_SEEDS_INSERTED = Counter(
    "contract_writer_seeds_inserted_total",
    "Contract rows seeded on startup",
    ["agent"],
)
_PROCESSING_LATENCY = Histogram(
    "contract_writer_processing_latency_seconds",
    "Roll event processing latency",
    ["agent"],
)
_LAST_ROLL_TS = Gauge(
    "contract_writer_last_roll_promoted_ts",
    "Unix timestamp of last successful roll promotion (0 = never)",
    ["agent"],
)


class ContractMetadataWriterAgent(BaseAgent):
    """WriterAgent for contract_metadata seeding and front-month promotion.

    Lifecycle:
    1. _setup(): Create DB pool, seed missing contracts, start Kafka consumer/producer.
    2. _run(): Consume market.events.roll; atomically promote front-month per event.
    3. _teardown(): Drain Kafka, close DB pool.

    DRY_RUN mode (env DRY_RUN=true): Logs and publishes ContractUpdateEvent but
    skips all DB writes. Useful for dry-run validation before going live.
    """

    def __init__(self) -> None:
        self._dry_run: bool = os.environ.get("DRY_RUN", "false").lower() == "true"
        super().__init__(name="contract_metadata_writer_agent", metrics_port=9124)
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # Cache labeled metric children — avoids dict lookup on every event
        self._rolls_processed = _ROLLS_PROCESSED.labels(agent=self.name)
        self._roll_errors = _ROLL_ERRORS.labels(agent=self.name)
        self._seeds_inserted = _SEEDS_INSERTED.labels(agent=self.name)
        self._processing_latency = _PROCESSING_LATENCY.labels(agent=self.name)
        self._last_roll_ts = _LAST_ROLL_TS.labels(agent=self.name)

        if self._dry_run:
            self.logger.warning("contract_metadata_writer.DRY_RUN_ENABLED — DB writes suppressed")

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_roll_events(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_contract_updates(self.env_name),
            topic_roll_dlq(self.env_name),
        ]

    async def _setup(self) -> None:
        """Connect DB pool, seed missing contracts, start Kafka consumer/producer."""
        # Hard-fail on DB unavailability per CONTEXT.md D-spec
        self._db_pool = await asyncpg.create_pool(
            self.settings.database_url, min_size=1, max_size=3
        )
        await self._seed_missing_contracts()

        self._kafka_consumer = KafkaConsumerClient(
            topic_roll_events(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="contract_metadata_writer_consumer",
            auto_offset_reset="earliest",  # must not miss roll events
        )
        await self._kafka_consumer.start()

        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self.logger.info(
            "contract_metadata_writer.setup_complete",
            topics_consumed=self.topics_consumed,
            dry_run=self._dry_run,
        )


    async def _teardown(self) -> None:
        """Stop Kafka consumer/producer and close DB pool."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _seed_missing_contracts(self) -> None:
        """Seed contract_metadata rows for futures instruments missing from DB.

        Runs once in _setup(). Idempotent via ON CONFLICT (symbol) DO NOTHING.
        Only futures instruments are seeded — non-futures instruments are not
        tracked in contract_metadata.

        Uses a single multi-row INSERT instead of N sequential round-trips.
        """
        instruments = get_active_contracts(self.settings)
        futures = [i for i in instruments if i.asset_class == AssetClass.FUTURES]
        if not futures:
            return
        async with self._db_pool.acquire() as conn:
            # Build multi-row VALUES clause: ($1,$2,$3), ($4,$5,$6), ...
            params: list = []
            value_clauses: list[str] = []
            for idx, instrument in enumerate(futures):
                base_idx = idx * 4
                value_clauses.append(
                    f"(${base_idx + 1}, ${base_idx + 2}, ${base_idx + 3}, ${base_idx + 4}, true)"
                )
                params.extend(
                    [
                        instrument.symbol,
                        instrument.base,
                        AssetClass.FUTURES,
                        instrument.exchange,
                    ]
                )

            result = await conn.fetch(
                f"""INSERT INTO contract_metadata
                        (symbol, base_symbol, asset_class, exchange, is_front_month)
                    VALUES {', '.join(value_clauses)}
                    ON CONFLICT (symbol) DO NOTHING
                    RETURNING symbol, base_symbol""",
                *params,
            )
            for row in result:
                self._seeds_inserted.inc()
                self.logger.info(
                    "contract_metadata_writer.seeded",
                    symbol=row["symbol"],
                    base=row["base_symbol"],
                )

    async def _publish_to_dlq(self, payload: dict, key: str = "unknown") -> None:
        """Route an unprocessable payload to the roll DLQ topic."""
        await self._kafka_producer.publish(
            topic_roll_dlq(self.env_name),
            payload,
            key=key,
        )

    def _extract_dlq_key(self, payload: dict) -> str:
        """Extract a routing key from a raw payload dict (pre-validation)."""
        if isinstance(payload, dict):
            return payload.get("symbol", "unknown")
        return "unknown"

    async def _handle_roll_event(self, payload: dict) -> None:
        """Process a single RollEvent: validate, promote front-month, broadcast update.

        Error paths:
        - Validation failure (malformed payload) → DLQ, return
        - Empty old_contract or new_contract → DLQ, return
        - Unknown old_contract (no DB row) → DLQ, return
        - DRY_RUN=true → log + publish with dry_run flag, skip DB write

        Happy path:
        1. Fetch old_contract row to copy exchange field.
        2. Atomic transaction: set old=false, upsert new=true.
        3. Publish ContractUpdateEvent.
        4. Update gauge + emit IBKR_RESTART_REQUIRED warning.
        """
        try:
            event = RollEvent.model_validate(payload)
        except ValidationError as exc:
            self._roll_errors.inc()
            self.logger.error(
                "contract_metadata_writer.invalid_roll_event",
                error=str(exc),
            )
            await self._publish_to_dlq(payload, key=self._extract_dlq_key(payload))
            return

        if not event.old_contract or not event.new_contract:
            self._roll_errors.inc()
            self.logger.error(
                "contract_metadata_writer.empty_contract",
                old=event.old_contract,
                new=event.new_contract,
            )
            await self._publish_to_dlq(payload, key=event.symbol)
            return

        with self._processing_latency.time():
            async with self._db_pool.acquire() as conn:
                # Step 2: DRY_RUN — log and publish but skip DB write
                if self._dry_run:
                    # Fetch without lock — dry-run never modifies
                    old_row = await conn.fetchrow(
                        "SELECT base_symbol, exchange FROM contract_metadata WHERE symbol = $1",
                        event.old_contract,
                    )
                    if old_row is None:
                        self._roll_errors.inc()
                        self.logger.error(
                            "contract_metadata_writer.unknown_old_contract",
                            old_contract=event.old_contract,
                            base=event.symbol,
                        )
                        await self._publish_to_dlq(payload, key=event.symbol)
                        return
                    exchange = old_row["exchange"]
                    self.logger.warning(
                        "contract_metadata_writer.DRY_RUN_promotion_skipped",
                        base=event.symbol,
                        old=event.old_contract,
                        new=event.new_contract,
                        exchange=exchange,
                    )
                    update_event = ContractUpdateEvent(
                        base_symbol=event.symbol,
                        old_contract=event.old_contract,
                        new_contract=event.new_contract,
                        promoted_at=datetime.now(UTC),
                    )
                    await self._kafka_producer.publish(
                        topic_contract_updates(self.env_name),
                        {**update_event.model_dump(mode="json"), "dry_run": True},
                        key=f"dry_run:{event.symbol}",
                    )
                    return

                # Step 3: Atomic promotion in transaction
                async with conn.transaction():
                    # Lock old row first — prevents concurrent roll from racing
                    old_row = await conn.fetchrow(
                        "SELECT base_symbol, exchange FROM contract_metadata WHERE symbol = $1 FOR UPDATE",
                        event.old_contract,
                    )
                    if old_row is None:
                        self._roll_errors.inc()
                        self.logger.error(
                            "contract_metadata_writer.unknown_old_contract",
                            old_contract=event.old_contract,
                            base=event.symbol,
                        )
                        await self._publish_to_dlq(payload, key=event.symbol)
                        return
                    exchange = old_row["exchange"]
                    await conn.execute(
                        """UPDATE contract_metadata
                           SET is_front_month = false, updated_at = NOW()
                           WHERE symbol = $1""",
                        event.old_contract,
                    )
                    await conn.execute(
                        """INSERT INTO contract_metadata
                               (symbol, base_symbol, asset_class, exchange, is_front_month,
                                roll_from, roll_detected_at, confirmation_count, updated_at)
                           VALUES ($1, $2, $3, $4, true, $5, $6, $7, NOW())
                           ON CONFLICT (symbol) DO UPDATE SET
                               is_front_month = true,
                               roll_from = EXCLUDED.roll_from,
                               roll_detected_at = EXCLUDED.roll_detected_at,
                               confirmation_count = EXCLUDED.confirmation_count,
                               updated_at = NOW()""",
                        event.new_contract,
                        event.symbol,  # base_symbol from RollEvent
                        AssetClass.FUTURES,
                        exchange,  # copied from old_contract row
                        event.old_contract,
                        event.detection_ts,
                        event.confirmation_count,
                    )

            # Step 4: Publish ContractUpdateEvent
            update_event = ContractUpdateEvent(
                base_symbol=event.symbol,
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                promoted_at=datetime.now(UTC),
            )
            await self._kafka_producer.publish(
                topic_contract_updates(self.env_name),
                update_event.model_dump(mode="json"),
                key=event.symbol,
            )

            # Step 5: Update gauge + emit operator alert
            self._last_roll_ts.set(_time.time())
            self._rolls_processed.inc()
            self.logger.info(
                "contract_metadata_writer.roll_promoted",
                base=event.symbol,
                old=event.old_contract,
                new=event.new_contract,
            )
            self.logger.warning(
                "contract_metadata_writer.IBKR_RESTART_REQUIRED",
                base=event.symbol,
                old_contract=event.old_contract,
                new_contract=event.new_contract,
                action=f"sudo systemctl restart indicagent-ibkr-provider on {self.settings.ibkr_host}",
            )

    async def _run(self) -> None:
        """Main loop: consume roll events, handle each one."""
        # lag_task created by BaseAgent.start() at line 155
        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break
            try:
                await self._handle_roll_event(payload)
            except Exception as exc:
                self._roll_errors.inc()
                self.logger.error(
                    "contract_metadata_writer.unhandled_error",
                    error=str(exc),
                    payload=payload,
                )
                await self._publish_to_dlq(payload, key=self._extract_dlq_key(payload))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = ContractMetadataWriterAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
