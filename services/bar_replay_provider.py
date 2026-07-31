"""BarReplayProvider — L1 one-shot.

Phase 81. Reads market_data_ohlcv_tradeable chronologically and feeds bars into
the pipeline via market.bars (1m) and market.bars.htf (HTF). Self-terminates
when caught up to NOW() - 5 minutes.

Reads the tradeable view, not the raw table (todo 124): this replays bars into
the live real-time topics as if they were arriving from the market now — a
raw-table read would replay synthetic-fill/flat-carry-forward placeholder bars
into the pipeline as if real trading activity occurred.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg

from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import (
    TF_SECONDS,  # noqa: F401 — confirms Plan 02 dependency satisfied
    topic_market_bars,
    topic_market_bars_htf,
)
from src.observability.metrics import (
    BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL,
    BAR_REPLAY_PROVIDER_LAG_SECONDS,
)

CHECKPOINT_PATH = Path("cache/bar_replay_checkpoint.json")
CATCH_UP_THRESHOLD = timedelta(minutes=5)
BATCH_SIZE = 1000
DEFAULT_RATE_BPS = float(os.environ.get("BAR_REPLAY_BARS_PER_SEC", "10"))


class BarReplayProvider(BaseDaemon):
    """One-shot L1 provider that replays market_data_ohlcv_tradeable into the pipeline.

    Publishes 1m bars to topic_market_bars and HTF bars to topic_market_bars_htf,
    preserving temporal ordering. Self-terminates with exit code 0 when
    last_replayed_ts >= NOW() - 5 minutes.
    """

    agent_id = "bar_replay_provider"

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=300)
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._last_replayed_ts: datetime | None = None
        self._rate_bps = DEFAULT_RATE_BPS

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="bar_replay_provider",
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._producer.start()
        self._last_replayed_ts = self._load_checkpoint()
        self.logger.info(
            "bar_replay_provider.setup_complete",
            resume_from=self._last_replayed_ts.isoformat() if self._last_replayed_ts else None,
            rate_bps=self._rate_bps,
        )

    def _load_checkpoint(self) -> datetime | None:
        if not CHECKPOINT_PATH.exists():
            return None
        try:
            data = json.loads(CHECKPOINT_PATH.read_text())
            return datetime.fromisoformat(data["last_replayed_ts"])
        except Exception as error:
            self.logger.warning("checkpoint_load_failed", error=str(error))
            return None

    def _save_checkpoint(self, ts: datetime) -> None:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(json.dumps({"last_replayed_ts": ts.isoformat()}))

    async def _fetch_batch(self, after_ts: datetime | None) -> list[asyncpg.Record]:
        query = """
            SELECT symbol, timeframe, timestamp, open, high, low, close, volume
            FROM market_data_ohlcv_tradeable
            WHERE ($1::timestamptz IS NULL OR timestamp > $1)
            ORDER BY timestamp ASC,
              CASE timeframe
                WHEN '1m' THEN 1 WHEN '5m' THEN 5 WHEN '15m' THEN 15
                WHEN '1h' THEN 60 WHEN '4h' THEN 240 WHEN '1d' THEN 1440
                ELSE 9999
              END ASC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, after_ts, BATCH_SIZE)

    async def _publish_bar(self, row: asyncpg.Record) -> None:
        tf = row["timeframe"]
        payload = {
            "symbol": row["symbol"],
            "timeframe": tf,
            "timestamp": format_iso_ts(row["timestamp"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "source": "bar_replay",
        }
        env = self.settings.env_name
        topic = topic_market_bars(env) if tf == "1m" else topic_market_bars_htf(env)
        await self._producer.publish(topic, msg=payload)
        BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL.add(1, {"symbol": row["symbol"], "timeframe": tf})

    async def _run(self) -> None:
        sleep_per_bar = 1.0 / max(self._rate_bps, 0.001)
        while self.running:
            rows = await self._fetch_batch(self._last_replayed_ts)
            if not rows:
                self.logger.info("bar_replay_drained_zero_rows")
                return
            for row in rows:
                if self._stop_event.is_set():
                    return
                await self._publish_bar(row)
                self._last_replayed_ts = row["timestamp"]
                BAR_REPLAY_PROVIDER_LAG_SECONDS.add(
                    max(0.0, (datetime.now(UTC) - row["timestamp"]).total_seconds())
                )
                await asyncio.sleep(sleep_per_bar)
            self._save_checkpoint(self._last_replayed_ts)

            # Self-termination: caught up to within 5 minutes of now
            if datetime.now(UTC) - self._last_replayed_ts <= CATCH_UP_THRESHOLD:
                self.logger.info(
                    "bar_replay_caught_up",
                    last_replayed_ts=self._last_replayed_ts.isoformat(),
                )
                BAR_REPLAY_PROVIDER_LAG_SECONDS.add(0.0)
                return

    async def _teardown(self) -> None:
        # Save checkpoint on shutdown for one-shot batch service
        if self._last_replayed_ts:
            self._save_checkpoint(self._last_replayed_ts)
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

    async def main(self) -> int:
        await self.start()
        # Self-terminate with exit code 0 on completion (one-shot batch service)
        sys.exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(BarReplayProvider().main()))
