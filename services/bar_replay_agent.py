#!/usr/bin/env python3
"""BarReplayAgent — signal gap self-healer.

Consumes SignalReplayRequest events from topic_signal_replay_requests.
Fetches historical bars from market_data_ohlcv (no IBKR dependency).
Republishes to market.bars (1m) or market.bars.htf (HTF) in chronological order
so IntelligencePipelineAgent can recompute missing signals naturally.

Bounded concurrency: asyncio.Semaphore(5) — up to 5 concurrent replays.
Dedup guard: _replay_in_progress set prevents duplicate replays for same (symbol, tf, date).

Trust boundary T-63.6-02-A: parameterized SQL ($1/$2/$3/$4) — no string interpolation.
Trust boundary T-63.6-02-B: Semaphore(5) caps concurrent DB queries.
source="replay" on every BarMessage for provenance — T-63.6-02-E.

Metrics port: :9135
Golden Signals:
- Traffic: bar_replay_requests_total
- Traffic: bar_replay_bars_published_total{symbol, tf}
- Errors: bar_replay_errors_total
- Latency: bar_replay_duration_seconds

Version: 1.0.0
Phase: 63.6
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from prometheus_client import Counter, Histogram

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.bar_normalizer import SOURCE_REPLAY
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.schemas.market_events import SignalReplayRequest
from src.core.stream_keys import (
    topic_market_bars,
    topic_market_bars_htf,
    topic_signal_replay_requests,
)
from src.observability.otel import init_tracing

# ---------------------------------------------------------------------------
# Module-level metrics (prevents duplicate registration on re-import)
# ---------------------------------------------------------------------------

_BAR_REPLAY_REQUESTS = Counter(
    "bar_replay_requests_total",
    "Total SignalReplayRequest events consumed",
    ["agent"],
)
_BAR_REPLAY_BARS_PUBLISHED = Counter(
    "bar_replay_bars_published_total",
    "Total bars republished by BarReplayAgent",
    ["agent", "symbol", "tf"],
)
_BAR_REPLAY_ERRORS = Counter(
    "bar_replay_errors_total",
    "Errors during replay (DB fetch or publish failure)",
    ["agent"],
)
_BAR_REPLAY_DURATION = Histogram(
    "bar_replay_duration_seconds",
    "Wall-clock time for a single replay task (fetch + publish)",
    ["agent", "symbol", "tf"],
)

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_FETCH_BARS_SQL = """
SELECT symbol, timeframe, timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = $2
  AND timestamp >= $3 AND timestamp < $4
ORDER BY timestamp ASC
"""


class BarReplayAgent(BaseAgent):
    """AuditorAgent companion: replays historical bars for signal gap self-healing.

    Consumes SignalReplayRequest from topic_signal_replay_requests.
    Fetches bars from market_data_ohlcv — zero IBKR dependency.
    Republishes each bar as BarMessage(source='replay') to:
      - market.bars if tf == '1m'
      - market.bars.htf for all other timeframes

    IntelligencePipelineAgent processes replay bars identically to live bars,
    so missing signals are recomputed without any hot-path changes.

    Bounded concurrency: asyncio.Semaphore(5).
    Dedup guard: _replay_in_progress set, keyed on (symbol, tf, session_date).
    SIGTERM: drains all in-flight replay tasks before exit.

    Metrics port: :9135
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="bar_replay_agent", metrics_port=9135)

        self._kafka_producer: KafkaProducerClient | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # Dedup: prevent duplicate replays for same (symbol, tf, date)
        self._replay_in_progress: set[str] = set()

        # Cache labeled metric children
        self._bar_replay_requests_total = _BAR_REPLAY_REQUESTS.labels(agent=self.name)
        self._bar_replay_errors = _BAR_REPLAY_ERRORS.labels(agent=self.name)
        # Dynamic symbol/tf labels — call .labels() at use time
        self._bar_replay_bars_published = _BAR_REPLAY_BARS_PUBLISHED
        self._bar_replay_duration = _BAR_REPLAY_DURATION

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_signal_replay_requests(self._env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_market_bars(self._env_name),
            topic_market_bars_htf(self._env_name),
        ]

    async def _setup(self) -> None:
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=5
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self._consumer = KafkaConsumerClient(
            topic_signal_replay_requests(self._env_name),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="bar_replay_agent_consumer",
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self.logger.info(
            "bar_replay_agent.setup_complete",
            topics_consumed=self.topics_consumed,
            topics_produced=self.topics_produced,
        )

    async def _teardown(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Consume SignalReplayRequest events; dispatch concurrent replay tasks.

        Uses asyncio.Semaphore(5) to cap concurrent DB fetches.
        On SIGTERM: drains all in-flight tasks before returning.
        """
        sem = asyncio.Semaphore(5)
        tasks: set[asyncio.Task] = set()

        assert self._consumer is not None

        async for _topic, _key, payload in self._consumer.messages():
            if not self.running:
                break

            try:
                req = SignalReplayRequest.model_validate(payload)
            except Exception as exc:
                self.logger.error(
                    "bar_replay_agent.invalid_payload",
                    error=str(exc),
                )
                self._bar_replay_errors.inc()
                continue

            self._bar_replay_requests_total.inc()

            task = asyncio.create_task(self._replay(req, sem))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        # Drain in-flight tasks on SIGTERM
        if tasks:
            self.logger.info(
                "bar_replay_agent.draining_tasks",
                in_flight=len(tasks),
            )
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Replay logic
    # ------------------------------------------------------------------

    async def _replay(self, req: SignalReplayRequest, sem: asyncio.Semaphore) -> None:
        """Acquire semaphore slot and run the replay."""
        async with sem:
            await self._do_replay(req)

    async def _do_replay(self, req: SignalReplayRequest) -> None:
        """Fetch bars from DB and republish to the correct topic.

        Trust boundary T-63.6-02-A: all WHERE clause values passed as $N parameters.
        Trust boundary T-63.6-02-B: caller holds Semaphore(5) slot.
        Trust boundary T-63.6-02-C: replay bars have historical timestamps; the
        monotonic guard in IntelligencePipelineAgent prevents _last_bar_ts regression.
        """
        dedup_key = f"{req.symbol}:{req.tf}:{req.session_start.date()}"

        # Dedup check — skip if already in progress or completed this session
        if dedup_key in self._replay_in_progress:
            self.logger.info(
                "bar_replay_agent.dedup_skip",
                symbol=req.symbol,
                tf=req.tf,
                session_date=str(req.session_start.date()),
            )
            return

        self._replay_in_progress.add(dedup_key)

        # Route topic: 1m → market.bars, HTF → market.bars.htf
        topic = (
            topic_market_bars(self._env_name)
            if req.tf == "1m"
            else topic_market_bars_htf(self._env_name)
        )

        with self._bar_replay_duration.labels(
            agent=self.name, symbol=req.symbol, tf=req.tf
        ).time():
            try:
                assert self._db_pool is not None
                assert self._kafka_producer is not None

                async with self._db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        _FETCH_BARS_SQL,
                        req.symbol,
                        req.tf,
                        req.session_start,
                        req.session_end,
                    )

                if not rows:
                    self.logger.warning(
                        "bar_replay_agent.no_bars_found",
                        symbol=req.symbol,
                        tf=req.tf,
                        session_start=req.session_start.isoformat(),
                        session_end=req.session_end.isoformat(),
                    )
                    return

                bar_count = 0
                for row in rows:
                    bar = BarMessage(
                        symbol=row["symbol"],
                        tf=row["timeframe"],
                        ts=row["timestamp"],
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                        source=SOURCE_REPLAY,
                        session_type=SessionType.RTH,  # replay bars: session not re-derived
                        gap_preceding=False,
                    )
                    await self._kafka_producer.publish(
                        topic,
                        bar.model_dump(mode="json"),
                        key=f"{bar.symbol}:{bar.tf}",
                    )
                    bar_count += 1

                self._bar_replay_bars_published.labels(
                    agent=self.name, symbol=req.symbol, tf=req.tf
                ).inc(bar_count)

                self.logger.info(
                    "bar_replay_agent.replay_complete",
                    symbol=req.symbol,
                    tf=req.tf,
                    bars_published=bar_count,
                    topic=topic,
                    session_start=req.session_start.isoformat(),
                    session_end=req.session_end.isoformat(),
                )

            except Exception as exc:
                self._bar_replay_errors.inc()
                self.logger.error(
                    "bar_replay_agent.replay_error",
                    symbol=req.symbol,
                    tf=req.tf,
                    error=str(exc),
                )


if __name__ == "__main__":
    init_tracing("bar_replay_agent")
    asyncio.run(BarReplayAgent().start())
