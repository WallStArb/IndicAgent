#!/usr/bin/env python3
"""
Cross-Asset Intelligence Service

Subscribes to the intelligence Kafka topic, maintains rolling price/volume windows
for the EQ_INDEX group (ES, NQ, RTY, YM), computes spread z-scores and correlation
break features via compute_eq_index_features(), and publishes results to the
cross_asset Kafka topic.

Always active — CROSS_ASSET_ENABLED feature flag removed after graduation (Phase 47-04).

Service lifecycle follows the signal_generator_service.py canonical pattern:
  - __init__: configure, setup_service_logging, start_metrics_server
  - start(): consumer/producer start, seed from DB, message loop, stop on shutdown
  - stop(): graceful consumer/producer teardown

Version: 1.0.0
Last Updated: 2026-03-18
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import message_key, topic_cross_asset, topic_intelligence
from src.intelligence.cross_asset_features import (
    _EQ_INDEX_BASES,
    _SHORT_WINDOW,
    compute_eq_index_features,
    resolve_eq_index_base,
)
from src.observability.metrics import counter, gauge, start_metrics_server

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Groups: maps group name -> set of base symbols in that group
CROSS_ASSET_GROUPS: dict[str, frozenset[str]] = {
    "EQ_INDEX": _EQ_INDEX_BASES,
}

# Seconds per TF bar — used for staleness detection
_TF_INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}

def _extract_base_symbol(symbol: str) -> str | None:
    """Extract EQ_INDEX base symbol from a full contract symbol.

    Delegates to resolve_eq_index_base — requires len(symbol) > len(base)
    so bare base strings like "ES" are not treated as valid contracts.
    Returns None for non-EQ_INDEX symbols (e.g. CLM6, GCJ6).
    """
    return resolve_eq_index_base(symbol)


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class CrossAssetService:
    """Cross-asset intelligence microservice.

    Subscribes to intelligence topic, computes EQ_INDEX spread features,
    and publishes results to the cross_asset topic.
    """

    def __init__(self) -> None:
        settings = Settings()
        self.running = False
        self.shutdown_requested = False
        self.env_name: str = settings.env_name or ""
        self._window_bars: int = settings.cross_asset_window_bars
        self._metrics_port: int = settings.cross_asset_metrics_port
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._database_url: str = settings.database_url

        # min_needed = window_bars + _SHORT_WINDOW to hold enough history
        _min_needed = self._window_bars + _SHORT_WINDOW

        # Rolling windows keyed by "BASE:tf" (e.g. "ES:1m")
        self._close_windows: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=_min_needed + 1)
        )
        self._vol_windows: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=_min_needed + 1)
        )

        # Staleness tracking: last bar timestamp per "BASE:tf"
        self._last_bar_ts: dict[str, datetime] = {}

        # Dedup: last published timestamp per tf
        self._last_published_ts: dict[str, datetime] = {}

        # Group configuration (extensible for future groups)
        self._groups: dict[str, frozenset[str]] = CROSS_ASSET_GROUPS

        # Consumers and producer (initialized in start())
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._db: DatabaseManager | None = None

        # Metrics
        self._msg_counter = counter(
            "cross_asset_messages_processed",
            "Messages processed by cross_asset_service",
        )
        self._spreads_counter = counter(
            "cross_asset_spreads_published",
            "Spread feature payloads published to cross_asset topic",
        )
        self._quality_gauge = gauge(
            "cross_asset_data_quality",
            "EQ_INDEX data quality score (fraction of fresh symbols)",
        )

        setup_service_logging("logs/cross_asset_service.log")
        start_metrics_server(port=self._metrics_port)
        self.logger = structlog.get_logger("cross_asset_service")

    # -----------------------------------------------------------------------
    # Signal handling
    # -----------------------------------------------------------------------

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Shutdown signal received", signum=signum)
        self.shutdown_requested = True

    # -----------------------------------------------------------------------
    # Public methods used by tests (pure logic, no I/O)
    # -----------------------------------------------------------------------

    def _route_message(self, payload: dict, tf: str) -> None:
        """Extract base symbol from payload, append close/vol to rolling windows.

        Skips non-EQ_INDEX symbols silently.
        """
        raw_symbol = payload.get("symbol", "")
        base = _extract_base_symbol(raw_symbol)
        if base is None:
            return

        bar = payload.get("bar", {})
        close = float(bar.get("c", 0.0))
        volume = float(bar.get("v", 0.0))

        key = f"{base}:{tf}"
        self._close_windows[key].append(close)
        self._vol_windows[key].append(volume)

        # Parse bar timestamp
        ts_raw = payload.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now(UTC)

        self._last_bar_ts[key] = ts

    def _is_duplicate(self, tf: str, ts: datetime) -> bool:
        """Return True if we already published for this (tf, ts) combination."""
        last = self._last_published_ts.get(tf)
        if last is None:
            return False
        return last >= ts

    def _check_group_staleness(
        self, group_name: str, tf: str, now: datetime
    ) -> tuple[bool, float]:
        """Check if any symbol in the group is stale (> 1 TF-interval old).

        Returns (is_stale, data_quality_score).
        data_quality_score = fraction of group symbols with fresh data.
        """
        members = self._groups.get(group_name, frozenset())
        if not members:
            return True, 0.0

        interval_sec = _TF_INTERVAL_SECONDS.get(tf, 60)
        interval = timedelta(seconds=interval_sec)
        fresh_count = 0

        for base in members:
            key = f"{base}:{tf}"
            last_ts = self._last_bar_ts.get(key)
            if last_ts is not None and (now - last_ts) <= interval:
                fresh_count += 1

        total = len(members)
        quality = float(fresh_count) / total
        is_stale = fresh_count < total
        return is_stale, quality

    def _is_group_ready(self, group_name: str, tf: str) -> bool:
        """Return True if all group members have >= window_bars + SHORT_WINDOW data."""
        members = self._groups.get(group_name, frozenset())
        min_needed = self._window_bars + _SHORT_WINDOW
        for base in members:
            key = f"{base}:{tf}"
            if len(self._close_windows[key]) < min_needed:
                return False
        return True

    def _build_close_vol_windows(
        self, group_name: str, tf: str
    ) -> tuple[dict[str, deque], dict[str, deque]]:
        """Build per-base-symbol close/vol dicts for compute_eq_index_features()."""
        members = self._groups.get(group_name, frozenset())
        close_w: dict[str, deque] = {}
        vol_w: dict[str, deque] = {}
        for base in members:
            key = f"{base}:{tf}"
            close_w[base] = self._close_windows[key]
            vol_w[base] = self._vol_windows[key]
        return close_w, vol_w

    # -----------------------------------------------------------------------
    # DB seed (startup)
    # -----------------------------------------------------------------------

    async def _seed_from_db(self) -> None:
        """Seed rolling windows from intelligence_features on startup.

        Queries last (window_bars + SHORT_WINDOW) rows per (symbol, tf)
        for each EQ_INDEX group member. Falls back gracefully on error.
        """
        if self._db is None:
            return

        min_needed = self._window_bars + _SHORT_WINDOW
        tfs = list(_TF_INTERVAL_SECONDS.keys())

        for _group_name, members in self._groups.items():
            for base in members:
                for tf in tfs:
                    try:
                        async with self._db.get_connection() as conn:
                            rows = await conn.fetch(
                                """
                                SELECT
                                    (i1->>'close')::float AS close,
                                    (i1->>'volume')::float AS volume,
                                    computed_at
                                FROM intelligence_features
                                WHERE symbol LIKE $1 || '%'
                                  AND tf = $2
                                ORDER BY computed_at DESC
                                LIMIT $3
                                """,
                                base,
                                tf,
                                min_needed,
                            )
                        if rows:
                            key = f"{base}:{tf}"
                            # Rows are DESC; reverse to chronological order
                            for row in reversed(rows):
                                close_val = row["close"] or 0.0
                                vol_val = row["volume"] or 0.0
                                self._close_windows[key].append(float(close_val))
                                self._vol_windows[key].append(float(vol_val))
                                self._last_bar_ts[key] = row["computed_at"].replace(
                                    tzinfo=UTC
                                )
                            self.logger.info(
                                "Seeded rolling window from DB",
                                base=base,
                                tf=tf,
                                n_bars=len(rows),
                            )
                    except Exception as exc:
                        self.logger.warning(
                            "DB seed failed for symbol/tf — continuing without seed",
                            base=base,
                            tf=tf,
                            error=str(exc),
                        )

    # -----------------------------------------------------------------------
    # Main message processing
    # -----------------------------------------------------------------------

    async def _process_intelligence_message(self, payload: dict) -> None:
        """Process a single IntelligenceEvent message.

        Routes close/vol to rolling windows, then attempts to publish
        cross-asset features if all conditions are met.
        """
        tf = payload.get("tf", "")
        if not tf:
            return

        # Route to windows
        self._route_message(payload, tf)
        self._msg_counter.inc()

        # Try to publish for each group
        now = datetime.now(UTC)
        for group_name, _members in self._groups.items():
            # Skip if insufficient data
            if not self._is_group_ready(group_name, tf):
                continue

            # Parse bar timestamp for dedup
            ts_raw = payload.get("ts", "")
            try:
                bar_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                bar_ts = now

            # Dedup check
            if self._is_duplicate(tf, bar_ts):
                continue

            # Staleness check
            is_stale, quality = self._check_group_staleness(group_name, tf, now)
            self._quality_gauge.set(quality)

            if is_stale:
                self.logger.debug(
                    "Group stale — skipping publish",
                    group=group_name,
                    tf=tf,
                    quality=quality,
                )
                continue

            # Compute features
            close_w, vol_w = self._build_close_vol_windows(group_name, tf)
            result = compute_eq_index_features(
                close_w, vol_w, tf, bar_ts, window_bars=self._window_bars
            )

            if not result.get("ready", False):
                continue

            # Inject quality from staleness check
            result["data_quality_score"] = float(quality)

            # Publish
            if self._producer is not None:
                topic = topic_cross_asset(self.env_name)
                key = message_key(group_name, tf)
                await self._producer.publish(topic, result, key=key)

            self._last_published_ts[tf] = bar_ts
            self._spreads_counter.inc()
            self.logger.info(
                "Published cross-asset features",
                group=group_name,
                tf=tf,
                es_nq_z=result.get("es_nq_spread_z"),
                active_pair=result.get("active_pair"),
            )

    # -----------------------------------------------------------------------
    # Service lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Start the cross-asset intelligence service."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info(
            "Starting CrossAssetService",
            env=self.env_name,
            window_bars=self._window_bars,
        )

        # Initialize DB for seeding
        self._db = DatabaseManager(self._database_url)
        try:
            await self._db.initialize()
        except Exception as exc:
            self.logger.warning("DB init failed — proceeding without seed", error=str(exc))
            self._db = None

        # Seed rolling windows from DB
        await self._seed_from_db()

        # Start Kafka consumer/producer
        intelligence_topic = topic_intelligence(self.env_name)
        self._consumer = KafkaConsumerClient(
            intelligence_topic,
            bootstrap_servers=self._kafka_bootstrap,
            group_id="cross_asset_group",
            auto_offset_reset="latest",
        )
        self._producer = KafkaProducerClient(bootstrap_servers=self._kafka_bootstrap)

        await self._consumer.start()
        await self._producer.start()

        self.running = True
        self.logger.info("CrossAssetService running", topic=intelligence_topic)

        try:
            await self._consume_loop()
        finally:
            await self.stop()

    async def _consume_loop(self) -> None:
        """Main consumer loop — process intelligence messages until shutdown."""
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if self.shutdown_requested:
                break
            try:
                await self._process_intelligence_message(payload)
            except Exception as exc:
                self.logger.error(
                    "Error processing intelligence message",
                    error=str(exc),
                    exc_info=True,
                )

    async def stop(self) -> None:
        """Gracefully stop consumer, producer, and DB pool."""
        self.running = False
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
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
        self.logger.info("CrossAssetService stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(CrossAssetService().start())
