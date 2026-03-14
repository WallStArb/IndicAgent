#!/usr/bin/env python3
"""
Timeframe Builder Service — Kafka-native higher-TF bar aggregation (Phase 30)

Consumes 1m bars from dev.market.bars, builds 5m/15m/1h/4h/1d aggregations,
and publishes completed higher-TF bars back to dev.market.bars with the
correct SYMBOL:TF message key.

Replaces: legacy Redis xreadgroup/xadd pattern.
Reuses:   _update_accumulator, _floor_to_period, _parse_ts from timeframe_builder.py.

Version: 2.0.0
Last Updated: 2026-03-14
Status: Current ✅
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings, get_active_contracts
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_DURATIONS
from src.core.stream_keys import message_key, topic_market_bars
from src.core.timeframe_builder import (
    _TARGET_TIMEFRAMES,
    _floor_to_period,
    _parse_ts,
    _update_accumulator,
)

logger = structlog.get_logger(__name__)


class TimeframeBuilderService:
    """Kafka consumer+producer for higher-timeframe bar aggregation."""

    def __init__(self) -> None:
        settings = Settings()
        self._env_name = settings.env_name.strip()
        self._bootstrap = settings.kafka_bootstrap_servers
        self._symbols: list[str] = get_active_contracts(settings)

        self.running = False
        self.shutdown_requested = False

        # Per-symbol accumulators: {symbol: {tf: accumulator_dict | None}}
        self._accumulators: dict[str, dict[str, dict[str, Any] | None]] = {
            sym: {tf: None for tf in _TARGET_TIMEFRAMES} for sym in self._symbols
        }
        # Dedup: last emitted period_ts per (symbol, tf)
        self._last_emitted: dict[str, dict[str, int]] = {}

        # Metrics counters
        self._bars_1m_processed: int = 0
        self._bars_built: dict[str, int] = {tf: 0 for tf in _TARGET_TIMEFRAMES}

        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _process_bar(self, symbol: str, payload: dict[str, Any]) -> None:
        """Process a single 1m bar and emit completed higher-TF bars."""
        try:
            ts_raw = payload.get("timestamp", "0")
            ts_seconds = _parse_ts(str(ts_raw))
            open_ = float(payload.get("open", 0))
            high = float(payload.get("high", 0))
            low = float(payload.get("low", 0))
            close = float(payload.get("close", 0))
            volume = int(float(payload.get("volume", 0)))
        except (ValueError, TypeError) as e:
            self.logger.warning("Bad bar fields", symbol=symbol, error=str(e))
            return

        self._bars_1m_processed += 1

        if symbol not in self._accumulators:
            self._accumulators[symbol] = {tf: None for tf in _TARGET_TIMEFRAMES}

        for tf, tf_minutes in _TARGET_TIMEFRAMES.items():
            if volume == 0 and close == 0.0:
                continue

            new_period_ts = _floor_to_period(ts_seconds, tf_minutes)
            acc = self._accumulators[symbol][tf]

            if acc is not None and acc["period_ts"] != new_period_ts:
                await self._emit_bar(symbol, tf, acc)
                acc = None

            bar_data: dict[str, Any] = {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "period_ts": new_period_ts,
            }
            self._accumulators[symbol][tf] = _update_accumulator(acc, bar_data, new_period_ts)

    async def _emit_bar(self, symbol: str, timeframe: str, acc: dict[str, Any]) -> None:
        """Publish a completed aggregated bar to dev.market.bars."""
        period_ts = acc["period_ts"]

        last = self._last_emitted.get(symbol, {}).get(timeframe)
        if last is not None and period_ts <= last:
            self.logger.debug(
                "Skipping duplicate bar",
                symbol=symbol,
                timeframe=timeframe,
                period_ts=period_ts,
            )
            return

        assert self._producer is not None
        period_ts_dt = datetime.fromtimestamp(period_ts, tz=UTC)
        tf_secs = TF_DURATIONS.get(timeframe, 0)
        close_ts = (period_ts_dt + timedelta(seconds=tf_secs)).isoformat()

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": period_ts_dt.isoformat(),
            "open": str(acc["open"]),
            "high": str(acc["high"]),
            "low": str(acc["low"]),
            "close": str(acc["close"]),
            "volume": str(acc["volume"]),
            "source": "timeframe_builder",
            "bar_close_ts": close_ts,
        }

        try:
            await self._producer.publish(
                topic_market_bars(self._env_name),
                payload,
                key=message_key(symbol, timeframe),
            )
            self._bars_built[timeframe] = self._bars_built.get(timeframe, 0) + 1
            self._last_emitted.setdefault(symbol, {})[timeframe] = period_ts
            self.logger.debug(
                "Emitted aggregated bar",
                symbol=symbol,
                timeframe=timeframe,
                period_ts=period_ts,
            )
        except Exception as e:
            self.logger.error(
                "Failed to emit bar",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )

    async def _consume_loop(self) -> None:
        """Main consume loop: read 1m bars from Kafka and aggregate."""
        assert self._consumer is not None
        async for topic, key, payload in self._consumer.messages():
            if self.shutdown_requested:
                break

            # Only process 1m bars
            tf = payload.get("timeframe", "")
            if tf != "1m":
                continue

            symbol = payload.get("symbol", "")
            if not symbol:
                if key:
                    # Fallback: extract symbol from key (e.g., "ES:1m" → "ES")
                    symbol = key.split(":")[0]
            if not symbol:
                continue

            await self._process_bar(symbol, payload)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                self.logger.info(
                    "Health check",
                    bars_1m_processed=self._bars_1m_processed,
                    bars_built=self._bars_built,
                )
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Timeframe Builder Service (Kafka)")
        try:
            self._producer = KafkaProducerClient(bootstrap_servers=self._bootstrap)
            await self._producer.start()

            self._consumer = KafkaConsumerClient(
                topic_market_bars(self._env_name),
                bootstrap_servers=self._bootstrap,
                group_id="timeframe_builder",
                auto_offset_reset="latest",
            )
            await self._consumer.start()

            self.running = True
            self.logger.info("Timeframe Builder Service started")

            tasks = [
                asyncio.create_task(self._consume_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error("Failed to start timeframe builder service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Timeframe Builder Service")
        self.running = False
        self.shutdown_requested = True
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        self.logger.info("Timeframe Builder Service stopped")


async def main() -> None:
    service = TimeframeBuilderService()
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
