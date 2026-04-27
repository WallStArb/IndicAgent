#!/usr/bin/env python3
"""Macro Factors Service.

Computes macro factors (yield curve, flight-to-quality, USD strength)
from cross-asset bar data and publishes to macro_signals topic.

Service lifecycle follows BaseAgent canonical pattern (Phase 071):
  - __init__: configure settings, logging, metrics
  - _setup(): Kafka, DB, tracing
  - _run(): main loop — consume, compute, publish
  - _teardown(): graceful shutdown

Version: 1.0.0
Last Updated: 2026-04-26
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import message_key, topic_macro_signals, topic_market_bars
from src.intelligence.macro.constants import MACRO_RATE_FUTURES
from src.intelligence.macro.flight_to_quality import compute_flight_to_quality
from src.intelligence.macro.yield_curve import compute_yield_curve_slope
from src.observability.metrics import AGENT_CRASH_TOTAL, counter


logger = structlog.get_logger(__name__)


class MacroComputeAgent(BaseAgent):
    """Macro factors microservice — extends BaseAgent.

    Subscribes to market_bars topic, computes macro factors from
    cross-asset instruments (rate futures, FX pairs, ETFs),
    publishes results to macro_signals topic.

    Migrated to BaseAgent for Renaissance-style observability (Phase 071).
    Inherits crash metrics, stall detection, and alert publishing.
    """

    agent_id: str = "macro_compute_agent"

    def __init__(self) -> None:
        settings = Settings()
        self._settings = settings
        self._window_bars: int = settings.macro_window_bars
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._database_url: str = settings.database_url

        # Rolling windows keyed by symbol
        min_needed = self._window_bars + 1
        self._bar_windows: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=min_needed)
        )

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

        # Initialize BaseAgent with metrics port
        super().__init__(
            name="MacroComputeAgent",
            metrics_port=settings.macro_metrics_port,
            max_idle_seconds=300,  # 5 minutes stall detection
        )

    # -----------------------------------------------------------------------
    # BaseAgent lifecycle hooks
    # -----------------------------------------------------------------------

    async def _setup(self) -> None:
        """Initialize Kafka, DB, metrics."""
        # Initialize database connection pool
        self._db_manager = DatabaseManager(self._database_url)
        await self._db_manager.initialize()

        # Initialize Kafka consumer for market_bars
        self._consumer = KafkaConsumerClient(
            bootstrap_servers=self._kafka_bootstrap,
            topic=topic_market_bars(self._settings.env_name),
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
            async for msg in self._consumer.messages():
                # Parse bar message
                bar = self._parse_bar(msg.value)

                if bar is None:
                    continue

                # Update rolling window
                symbol = bar["symbol"]
                self._bar_windows[symbol].append(bar)
                self._bars_processed.inc()
                self._last_message_ts = asyncio.get_event_loop().time()

                # Only compute yield curve when BOTH ZT and ZB have full windows
                # Triggering on any single rate future produced zero-default writes
                if (
                    symbol in MACRO_RATE_FUTURES
                    and all(
                        len(self._bar_windows.get(s, [])) >= self._window_bars
                        for s in ["ZT", "ZB"]
                    )
                ):

                    # Compute yield curve slope
                    macro_result = compute_yield_curve_slope(
                        dict(self._bar_windows),
                        lookback=self._window_bars,
                    )

                    # Publish to macro_signals topic
                    await self._publish_macro_signal(macro_result, bar)

                    # Persist to macro_features table
                    await self._persist_to_db(macro_result, bar)

                    logger.debug(
                        "macro.computed",
                        symbol=symbol,
                        yield_curve_slope=macro_result["yield_curve_slope"],
                    )

                # Also compute flight-to-quality (if TLT+SPY data available)
                # FIXED: Only compute on SPY/TLT bars, not every incoming bar
                if bar["symbol"] in ["SPY", "TLT"]:
                    if all(symbol in self._bar_windows for symbol in ["SPY", "TLT"]):
                        # Check we have enough data for both symbols
                        if all(len(self._bar_windows[s]) >= self._window_bars for s in ["SPY", "TLT"]):
                            ftq_result = compute_flight_to_quality(
                                dict(self._bar_windows),
                                lookback=self._window_bars,
                            )

                            # FIXED: Publish under canonical "FTQ" symbol, not incoming bar symbol
                            ftq_bar = {
                                **bar,
                                "symbol": "FTQ",  # Canonical symbol for FTQ signals
                            }
                            await self._publish_macro_signal(ftq_result, ftq_bar)

                            # FTQ shares macro_features table with yield curve
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
            AGENT_CRASH_TOTAL.labels(agent_id=self.agent_id).inc()
            raise

    # -----------------------------------------------------------------------
    # Helper methods
    # -----------------------------------------------------------------------

    def _parse_bar(self, msg_value: bytes) -> dict | None:
        """Parse Kafka bar message.

        Expected format: JSON with ts, symbol, tf, open, high, low, close, volume
        """
        try:
            bar = json.loads(msg_value)
            # Validate required fields
            if not all(k in bar for k in ["ts", "symbol", "tf", "close"]):
                logger.warning("macro.invalid_bar", missing_fields="required")
                return None
            return bar
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("macro.parse_error", error=str(e))
            return None

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
            key=key,
            value=payload,
        )
        self._macro_published.inc()

    async def _persist_to_db(self, macro_result: dict, bar: dict) -> None:
        """Persist macro result to TimescaleDB.

        Handles both yield curve and flight-to-quality results based on
        which fields are present in macro_result dict.
        """
        if not self._db_manager:
            logger.warning("macro.db_not_ready")
            return

        # Parse timestamp to datetime object for asyncpg
        if isinstance(bar["ts"], str):
            ts = datetime.fromisoformat(bar["ts"].replace("Z", "+00:00"))
        else:
            ts = bar["ts"]

        # Ensure timezone-aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        try:
            async with self._db_manager.pool.acquire() as conn:
                # Detect result type by fields present
                if "yield_curve_slope" in macro_result:
                    # FIXED: Use upsert to update only yield curve columns on conflict
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
                    # FIXED: Use upsert to update only FTQ columns on conflict
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
    agent = MacroComputeAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
