"""BarHistorySeeder — startup warmup for intelligence compute agents.

Seeds bar_history from intelligence_features (and falls back to market_data_ohlcv),
then re-publishes the most recent stored IntelligenceEvent per (symbol, tf) so the
dashboard shows current state without waiting for the next live bar.

Owns its own DB connection lifecycle: open → seed → close. The calling compute agent
remains DB-ignorant after seed() returns.
"""

import asyncio
from datetime import datetime
from typing import Any

import structlog

from src.api.utils import parse_jsonb
from src.config.settings import Settings, get_active_symbols
from src.core.bar_history import BarHistory
from src.core.bar_normalizer import SOURCE_IBKR_SEED
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
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


class BarHistorySeeder:
    """Seeds bar_history from DB at compute-agent startup.

    Usage::

        seeder = BarHistorySeeder(settings, config, kafka_producer)
        await seeder.seed(bar_history)
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

    async def seed(self, bar_history: BarHistory) -> None:
        """Seed bar_history from DB, then close the DB connection.

        Falls back silently if DB is unavailable.
        """
        if not self._db_url:
            self.logger.warning("DB seed skipped — no database_url configured")
            return

        db = DatabaseManager(self._db_url)
        try:
            await db.initialize()
        except Exception as e:
            self.logger.warning("DB init failed — skipping seed", error=str(e))
            return

        try:
            await self._run_seed(db, bar_history)
        finally:
            await db.close()

    async def _run_seed(self, db: DatabaseManager, bar_history: BarHistory) -> None:
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
                try:
                    rows = await db.execute_query(
                        f"""
                        SELECT ts, bar, i1, i2, i3, i4, i5, smc, i6,
                               bar_close_ts, i1_computed_at, computed_at
                        FROM intelligence_features
                        WHERE symbol = $1 AND tf = $2
                          AND ts > NOW() - INTERVAL '{lookback_secs} seconds'
                        ORDER BY ts DESC
                        LIMIT {min_bars}
                        """,
                        symbol,
                        tf,
                    )
                except Exception as e:
                    self.logger.warning("Seed query failed", symbol=symbol, tf=tf, error=str(e))
                    return

                if not rows:
                    return

                bar_messages: list[BarMessage] = []
                for row in reversed(rows):
                    bar_json = row["bar"]
                    try:
                        bar_messages.append(
                            BarMessage(
                                ts=row["ts"],
                                symbol=symbol,
                                tf=tf,
                                open=float(bar_json.get("o", 0)),
                                high=float(bar_json.get("h", 0)),
                                low=float(bar_json.get("l", 0)),
                                close=float(bar_json.get("c", 0)),
                                volume=int(bar_json.get("v", 0)),
                                source=SOURCE_IBKR_SEED,
                                session_type=SessionType.RTH,
                            )
                        )
                        seeded_bars += 1
                    except Exception as e:
                        self.logger.debug(
                            "Primary bar parse failed — skipping row",
                            symbol=symbol,
                            tf=tf,
                            error=str(e),
                        )
                if bar_messages:
                    bar_history.seed(symbol, tf, bar_messages)

                latest = rows[0]
                try:
                    def _tier(key: str) -> dict:
                        return {
                            k: v
                            for k, v in parse_jsonb(latest[key], default={}).items()
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
                except Exception as e:
                    self.logger.warning("Seed publish failed", symbol=symbol, tf=tf, error=str(e))

        tasks = [_seed_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await asyncio.gather(*tasks)

        # Fallback: seed bar_history from market_data_ohlcv for combos still below threshold
        fallback_seeded = 0

        async def _fallback_one(symbol: str, tf: str) -> None:
            nonlocal fallback_seeded
            if len(bar_history.get(symbol, tf)) >= min_bars_for_tf(tf):
                return
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER
                try:
                    rows = await db.execute_query(
                        f"""
                        SELECT timestamp, open, high, low, close, volume
                        FROM market_data_ohlcv
                        WHERE symbol = $1 AND timeframe = $2
                          AND timestamp > NOW() - INTERVAL '{lookback_secs} seconds'
                        ORDER BY timestamp DESC
                        LIMIT {min_bars}
                        """,
                        symbol,
                        tf,
                    )
                except Exception as e:
                    self.logger.warning(
                        "Fallback seed query failed", symbol=symbol, tf=tf, error=str(e)
                    )
                    return
                if not rows:
                    return
                bar_messages: list[BarMessage] = []
                for row in reversed(rows):
                    try:
                        bar_ts = row["timestamp"]
                        if isinstance(bar_ts, str):
                            bar_ts = datetime.fromisoformat(bar_ts)
                        bar_messages.append(
                            BarMessage(
                                ts=bar_ts,
                                symbol=symbol,
                                tf=tf,
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                close=float(row["close"]),
                                volume=int(row["volume"]),
                                source=SOURCE_IBKR_SEED,
                                session_type=SessionType.RTH,
                            )
                        )
                        fallback_seeded += 1
                    except Exception as e:
                        self.logger.debug(
                            "Fallback bar parse failed — skipping row",
                            symbol=symbol,
                            tf=tf,
                            error=str(e),
                        )
                if bar_messages:
                    bar_history.seed(symbol, tf, bar_messages)

        fallback_tasks = [_fallback_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await asyncio.gather(*fallback_tasks)

        self.logger.info(
            "Seeded bar_history and published intelligence",
            seeded_bars=seeded_bars,
            fallback_bars=fallback_seeded,
            published_events=published_events,
        )
