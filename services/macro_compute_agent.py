#!/usr/bin/env python3
"""Macro Factors Service.

Computes macro factors (yield curve, flight-to-quality, USD strength)
from cross-asset bar data and publishes to macro_signals topic.

Service lifecycle follows BaseDaemon canonical pattern:
  - __init__: configure settings, logging, metrics
  - _setup(): Kafka, DB, tracing
  - _run(): main loop — consume, compute, publish
  - _teardown(): graceful shutdown
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import AGENT_CRASH_TOTAL, BaseDaemon
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import message_key, topic_macro_signals, topic_market_bars
from src.intelligence.macro.constants import (
    MACRO_ACTIVE_SYMBOLS,
    MACRO_FTQ_INSTRUMENTS,
    MACRO_RATE_FUTURES,
    MACRO_YC_ANCHOR_PAIR,
)
from src.intelligence.macro.flight_to_quality import compute_flight_to_quality
from src.intelligence.macro.yield_curve import compute_yield_curve_slope
from src.observability.metrics import counter

logger = structlog.get_logger(__name__)


class MacroAnalyzer(BaseDaemon):
    """Macro factors microservice — extends BaseDaemon.

    Subscribes to market_bars topic, computes macro factors from
    cross-asset instruments (rate futures, FX pairs, ETFs),
    publishes results to macro_signals topic.

    Migrated to BaseDaemon for Renaissance-style observability (Phase 071).
    Inherits crash metrics, stall detection, and alert publishing.
    """

    agent_id: str = "macro_compute_agent"

    def __init__(self) -> None:
        import os

        _log_file = os.environ.get("LOG_FILE")
        if _log_file:
            from src.core.service_utils import setup_service_logging

            setup_service_logging(_log_file)

        settings = Settings()
        self._settings = settings
        self._window_bars: int = settings.macro_window_bars
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._database_url: str = settings.database_url

        # Rolling windows keyed by symbol
        min_needed = self._window_bars + 1
        self._bar_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=min_needed))

        # Kafka clients (initialized in _setup)
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._db_manager: DatabaseManager | None = None

        # Metrics — no per-symbol labels (counter registered without labelnames)
        self._bars_processed = counter(
            "macro_bars_processed",
            "Bars processed by macro_compute_agent",
        )
        self._macro_published = counter(
            "macro_signals_published",
            "Macro signal payloads published to macro_signals topic",
        )

        super().__init__(
            name="MacroComputeAgent",
            max_idle_seconds=300,  # 5 minutes stall detection
            settings=settings,
        )

    # -----------------------------------------------------------------------
    # BaseDaemon lifecycle hooks
    # -----------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialize Kafka, DB, metrics."""
        # Initialize database connection pool
        self._db_manager = DatabaseManager(self._database_url)
        await self._db_manager.initialize()

        # Initialize Kafka consumer for market_bars
        self._consumer = KafkaConsumerClient(
            topic_market_bars(self._settings.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="macro_consumer",
            auto_offset_reset="latest",
        )
        await self._consumer.start()

        # Initialize Kafka producer for macro_signals
        self._producer = KafkaProducerClient(
            bootstrap_servers=self._kafka_bootstrap,
        )
        await self._producer.start()

        logger.info(
            "macro_compute_agent.setup",
            window_bars=self._window_bars,
            rate_futures=list(MACRO_RATE_FUTURES),
        )

    async def _teardown(self) -> None:
        """Graceful shutdown."""
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        if self._db_manager:
            await self._db_manager.close()
        logger.info("macro_compute_agent.teardown")

    async def _run(self) -> None:
        """Main loop — consume bars, compute macro, publish signals."""
        logger.info("macro_compute_agent.started")

        if not self._consumer:
            raise RuntimeError("Consumer not initialized in _setup")

        try:
            async for _topic, _key, bar in self._consumer.messages():
                symbol = bar.get("symbol")
                if symbol not in MACRO_ACTIVE_SYMBOLS:
                    continue

                self._bar_windows[symbol].append(bar)
                self._bars_processed.add(1)
                self._record_message_consumed()

                # Yield curve — only when both anchor instruments have full windows
                # Triggering on any single rate future produced zero-default writes
                if symbol in MACRO_RATE_FUTURES and all(
                    len(self._bar_windows.get(s, [])) >= self._window_bars
                    for s in MACRO_YC_ANCHOR_PAIR
                ):
                    macro_result = compute_yield_curve_slope(
                        self._bar_windows,
                        lookback=self._window_bars,
                    )
                    await self._publish_macro_signal(macro_result, bar)
                    await self._persist_to_db(macro_result, bar)
                    logger.debug(
                        "macro.computed",
                        symbol=symbol,
                        yield_curve_slope=macro_result["yield_curve_slope"],
                    )

                # FTQ — only on SPY/TLT bars once both have full windows
                if symbol in MACRO_FTQ_INSTRUMENTS and all(
                    len(self._bar_windows.get(s, [])) >= self._window_bars
                    for s in MACRO_FTQ_INSTRUMENTS
                ):
                    ftq_result = compute_flight_to_quality(
                        self._bar_windows,
                        lookback=self._window_bars,
                    )
                    ftq_bar = {**bar, "symbol": "FTQ"}
                    await self._publish_macro_signal(ftq_result, ftq_bar)
                    await self._persist_to_db(ftq_result, ftq_bar)
                    logger.debug(
                        "macro.ftq_computed",
                        ftq_score=ftq_result["ftq_score"],
                        ftq_regime=ftq_result["ftq_regime"],
                    )

        except asyncio.CancelledError:
            logger.info("macro_compute_agent.shutdown")
            raise
        except Exception as e:
            logger.exception("macro_compute_agent.error", error=str(e))
            AGENT_CRASH_TOTAL.add(1, {"agent": self.agent_id})
            raise

    # -----------------------------------------------------------------------
    # Helper methods
    # -----------------------------------------------------------------------

    async def _publish_macro_signal(self, macro_result: dict, bar: dict) -> None:
        """Publish macro signal to Kafka."""
        if not self._producer:
            logger.warning("macro.producer_not_ready")
            return

        payload = {
            "ts": bar["ts"],
            "symbol": bar["symbol"],
            "timeframe": bar["tf"],
            **macro_result,  # yield_curve_slope, yield_curve_regime
        }

        key = message_key(bar["symbol"], bar["tf"])
        await self._producer.publish(
            topic=topic_macro_signals(self._settings.env_name),
            msg=payload,
            key=key,
        )
        self._macro_published.add(1)

    async def _persist_to_db(self, macro_result: dict, bar: dict) -> None:
        """Persist macro result to TimescaleDB.

        Handles both yield curve and flight-to-quality results based on
        which fields are present in macro_result dict.
        """
        if not self._db_manager:
            logger.warning("macro.db_not_ready")
            return

        if isinstance(bar["ts"], str):
            ts = datetime.fromisoformat(bar["ts"])
        else:
            ts = bar["ts"]

        # Ensure timezone-aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        try:
            async with self._db_manager.pool.acquire() as conn:
                # Detect result type by fields present
                if "yield_curve_slope" in macro_result:
                    await conn.execute(
                        """
                        INSERT INTO macro_features
                        (ts, symbol, timeframe, yield_curve_slope, yield_curve_regime)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (ts, symbol, timeframe)
                        DO UPDATE SET
                            yield_curve_slope = EXCLUDED.yield_curve_slope,
                            yield_curve_regime = EXCLUDED.yield_curve_regime
                        """,
                        ts,
                        bar["symbol"],
                        bar["tf"],
                        macro_result["yield_curve_slope"],
                        macro_result["yield_curve_regime"],
                    )
                elif "ftq_score" in macro_result:
                    await conn.execute(
                        """
                        INSERT INTO macro_features
                        (ts, symbol, timeframe, ftq_score, ftq_regime)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (ts, symbol, timeframe)
                        DO UPDATE SET
                            ftq_score = EXCLUDED.ftq_score,
                            ftq_regime = EXCLUDED.ftq_regime
                        """,
                        ts,
                        bar["symbol"],
                        bar["tf"],
                        macro_result["ftq_score"],
                        macro_result["ftq_regime"],
                    )
        except asyncpg.PostgresError as e:
            logger.error("macro.db_error", error=str(e))


def main() -> None:
    """Entry point for systemd service."""
    agent = MacroAnalyzer()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
