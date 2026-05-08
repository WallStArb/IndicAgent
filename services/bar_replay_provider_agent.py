"""BarReplayProviderAgent — L1 one-shot.

Phase 81. Reads market_data_ohlcv chronologically and feeds bars into the
pipeline via market.bars (1m) and market.bars.htf (HTF). Self-terminates
when caught up to NOW() - 5 minutes.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import structlog

from src.config.settings import Settings
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import setup_service_logging
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


class BarReplayProviderAgent:
    """One-shot L1 provider that replays market_data_ohlcv into the pipeline.

    Publishes 1m bars to topic_market_bars and HTF bars to topic_market_bars_htf,
    preserving temporal ordering. Self-terminates with exit code 0 when
    last_replayed_ts >= NOW() - 5 minutes.
    """

    agent_id = "bar_replay_provider"

    def __init__(self) -> None:
        self._log = structlog.get_logger(self.agent_id)
        self._settings = Settings()
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._stop = asyncio.Event()
        self._last_replayed_ts: datetime | None = None
        self._rate_bps = DEFAULT_RATE_BPS

    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(self._settings.database_url)
        self._producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._producer.start()
        self._last_replayed_ts = self._load_checkpoint()
        self._log.info(
            "bar_replay_provider.setup_complete",
            resume_from=self._last_replayed_ts.isoformat() if self._last_replayed_ts else None,
            rate_bps=self._rate_bps,
        )

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

    def _load_checkpoint(self) -> datetime | None:
        if not CHECKPOINT_PATH.exists():
            return None
        try:
            data = json.loads(CHECKPOINT_PATH.read_text())
            return datetime.fromisoformat(data["last_replayed_ts"])
        except Exception as exc:
            self._log.warning("checkpoint_load_failed", error=str(exc))
            return None

    def _save_checkpoint(self, ts: datetime) -> None:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(json.dumps({"last_replayed_ts": ts.isoformat()}))

    async def _fetch_batch(self, after_ts: datetime | None) -> list[asyncpg.Record]:
        query = """
            SELECT symbol, timeframe, timestamp, open, high, low, close, volume
            FROM market_data_ohlcv
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
            "timestamp": row["timestamp"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "source": "bar_replay",
        }
        env = self._settings.env_name
        topic = topic_market_bars(env) if tf == "1m" else topic_market_bars_htf(env)
        await self._producer.publish(topic, msg=payload)
        BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL.labels(symbol=row["symbol"], timeframe=tf).inc()

    async def _run(self) -> None:
        sleep_per_bar = 1.0 / max(self._rate_bps, 0.001)
        while not self._stop.is_set():
            rows = await self._fetch_batch(self._last_replayed_ts)
            if not rows:
                self._log.info("bar_replay_drained_zero_rows")
                return
            for row in rows:
                if self._stop.is_set():
                    return
                await self._publish_bar(row)
                self._last_replayed_ts = row["timestamp"]
                BAR_REPLAY_PROVIDER_LAG_SECONDS.set(
                    max(0.0, (datetime.now(UTC) - row["timestamp"]).total_seconds())
                )
                await asyncio.sleep(sleep_per_bar)
            self._save_checkpoint(self._last_replayed_ts)

            # Self-termination: caught up to within 5 minutes of now
            if datetime.now(UTC) - self._last_replayed_ts <= CATCH_UP_THRESHOLD:
                self._log.info(
                    "bar_replay_caught_up",
                    last_replayed_ts=self._last_replayed_ts.isoformat(),
                )
                BAR_REPLAY_PROVIDER_LAG_SECONDS.set(0.0)
                return

    def _install_signals(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)

    async def main(self) -> int:
        setup_service_logging("logs/bar_replay_provider_agent.log")
        self._install_signals()
        await self._setup()
        try:
            await self._run()
        finally:
            if self._last_replayed_ts:
                self._save_checkpoint(self._last_replayed_ts)
            await self._teardown()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(BarReplayProviderAgent().main()))
