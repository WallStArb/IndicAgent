"""WarmupProvider — startup bar-history seeding for intelligence compute agents.

Seeds bar_history from intelligence_features (with market_data_ohlcv fallback),
then re-publishes the most recent stored IntelligenceEvent per (symbol, tf) so the
dashboard shows current state without waiting for the next live bar.

Owns its own DB connection lifecycle: open → seed → close. The calling compute agent
remains DB-ignorant after seed() returns.

Retry/backoff: if the DB is unreachable at startup the provider will retry with
exponential backoff before giving up gracefully (non-fatal — agent starts cold).
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Any

import structlog

from src.api.utils import parse_jsonb
from src.config.settings import Settings, get_active_symbols
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import SEED_LOOKBACK_MULTIPLIER, TF_SECONDS, min_bars_for_tf
from src.core.stream_keys import message_key, topic_intelligence
from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)
from src.persistence.repository.feature_snapshot_repository import FeatureSnapshotRepository

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; doubled each attempt


class WarmupProvider:
    """Seeds bar_history and re-publishes latest intelligence at compute-agent startup.

    Usage::

        provider = WarmupProvider(settings, config, kafka_producer)
        await provider.seed(bar_history)
        # DB connection closed; compute agent runs DB-free from here.
    """

    def __init__(
        self,
        settings: Settings,
        config: dict[str, Any],
        kafka_producer: KafkaProducerClient,
    ) -> None:
        self._db_url = settings.database_url
        self._env_name = settings.env_name.strip()
        self._config = config
        self._kafka_producer = kafka_producer
        self.logger = structlog.get_logger(__name__)

    async def seed(self, bar_history: dict[str, deque]) -> None:
        """Seed bar_history from DB, then close the DB connection.

        Retries DB initialisation up to _MAX_RETRIES times with exponential backoff.
        Falls back silently if DB is unavailable after all retries — the agent starts
        cold and warms up naturally from live data.
        """
        if not self._db_url:
            self.logger.warning("warmup_skipped", reason="no database_url configured")
            return

        db = await self._connect_with_backoff()
        if db is None:
            return

        try:
            repo = FeatureSnapshotRepository(db)
            await self._run_seed(repo, bar_history)
        finally:
            await db.close()

    async def _connect_with_backoff(self) -> DatabaseManager | None:
        """Attempt DB connection with exponential backoff. Returns None on failure."""
        delay = _RETRY_BASE_DELAY
        for attempt in range(1, _MAX_RETRIES + 1):
            db = DatabaseManager(self._db_url)
            try:
                await db.initialize()
                return db
            except Exception as exc:
                self.logger.warning(
                    "warmup_db_connect_failed",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    retry_in=delay if attempt < _MAX_RETRIES else None,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= 2
        self.logger.warning("warmup_db_unavailable", reason="all retries exhausted — starting cold")
        return None

    async def _run_seed(
        self,
        repo: FeatureSnapshotRepository,
        bar_history: dict[str, deque],
    ) -> None:
        active_contracts = get_active_symbols()
        timeframes = self._config["service"]["timeframes"]
        seeded_bars = 0
        published_events = 0
        sem = asyncio.Semaphore(8)

        async def _seed_one(symbol: str, tf: str) -> None:
            nonlocal seeded_bars, published_events
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER

                rows = await repo.get_recent_features(symbol, tf, min_bars, lookback_secs)
                if not rows:
                    return

                key = f"{symbol}:{tf}"
                for row in reversed(rows):
                    bar_json = row["bar"]
                    try:
                        bar_history[key].append(
                            {
                                "open": float(bar_json.get("o", 0)),
                                "high": float(bar_json.get("h", 0)),
                                "low": float(bar_json.get("l", 0)),
                                "close": float(bar_json.get("c", 0)),
                                "volume": int(bar_json.get("v", 0)),
                                "timestamp": row["ts"],
                            }
                        )
                        seeded_bars += 1
                    except Exception:
                        pass

                latest = rows[0]
                try:
                    def _tier(tier_key: str) -> dict:
                        return {
                            k: v
                            for k, v in parse_jsonb(latest[tier_key], default={}).items()
                            if v is not None
                        }

                    bar_json = parse_jsonb(latest["bar"], default={})
                    event = IntelligenceEvent(
                        ts=latest["ts"],
                        symbol=symbol,
                        tf=tf,
                        source="backfill",
                        bar=OHLCVBar(
                            o=float(bar_json.get("o", 0)),
                            h=float(bar_json.get("h", 0)),
                            l=float(bar_json.get("l", 0)),
                            c=float(bar_json.get("c", 0)),
                            v=int(bar_json.get("v", 0)),
                        ),
                        i1=I1Indicators(**_tier("i1")),
                        i2=I2Events(**_tier("i2")),
                        i3=I3Structure(**_tier("i3")),
                        i4=I4Context(**_tier("i4")),
                        i5=I5Patterns(**_tier("i5")),
                        smc=SMCContext(**_tier("smc")),
                        i6=I6Confluence(**_tier("i6")),
                        bar_close_ts=latest["bar_close_ts"],
                        i1_computed_at=latest["i1_computed_at"],
                        computed_at=latest["computed_at"],
                    )
                    await self._kafka_producer.publish(
                        topic_intelligence(self._env_name),
                        {"event": event.model_dump_json()},
                        key=message_key(symbol, tf),
                    )
                    published_events += 1
                except Exception as exc:
                    self.logger.warning(
                        "warmup_publish_failed", symbol=symbol, tf=tf, error=str(exc)
                    )

        tasks = [_seed_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await asyncio.gather(*tasks)

        # Fallback: seed bar_history from market_data_ohlcv for combos still below threshold
        fallback_seeded = 0

        async def _fallback_one(symbol: str, tf: str) -> None:
            nonlocal fallback_seeded
            key = f"{symbol}:{tf}"
            if len(bar_history[key]) >= min_bars_for_tf(tf):
                return
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER

                rows = await repo.get_ohlcv_fallback(symbol, tf, min_bars, lookback_secs)
                for row in reversed(rows):
                    try:
                        bar_ts = row["timestamp"]
                        if isinstance(bar_ts, str):
                            bar_ts = datetime.fromisoformat(bar_ts)
                        bar_history[key].append(
                            {
                                "open": float(row["open"]),
                                "high": float(row["high"]),
                                "low": float(row["low"]),
                                "close": float(row["close"]),
                                "volume": int(row["volume"]),
                                "timestamp": bar_ts,
                            }
                        )
                        fallback_seeded += 1
                    except Exception as exc:
                        self.logger.debug(
                            "warmup_fallback_bar_parse_failed",
                            symbol=symbol,
                            tf=tf,
                            error=str(exc),
                        )

        fallback_tasks = [_fallback_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await asyncio.gather(*fallback_tasks)

        self.logger.info(
            "warmup_complete",
            seeded_bars=seeded_bars,
            fallback_bars=fallback_seeded,
            published_events=published_events,
        )
