"""BarHistorySeeder — startup warmup for intelligence compute agents.

Seeds bar_history from intelligence_features (and falls back to
market_data_ohlcv_tradeable),
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

# Batch size for concurrent tasks (prevents event loop overwhelm)
_SEED_BATCH_SIZE = 8
# Backoff delays (seconds) between DB init retry attempts on startup
_SEED_INIT_DELAYS = (2, 4, 8)


async def _gather_in_batches(tasks: list, batch_size: int = _SEED_BATCH_SIZE) -> None:
    """Execute async tasks in batches to avoid overwhelming the event loop."""
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i : i + batch_size]
        await asyncio.gather(*batch)


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

        Retries DB init up to len(_SEED_INIT_DELAYS) times with exponential backoff.
        Raises on all-retries-exhausted — a cold pipeline is a real failure.
        """
        if not self._db_url:
            self.logger.warning("DB seed skipped — no database_url configured")
            return

        db = DatabaseManager(self._db_url)
        for attempt, backoff in enumerate((0, *_SEED_INIT_DELAYS)):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                await db.initialize()
                break
            except Exception as e:
                if attempt >= len(_SEED_INIT_DELAYS):
                    self.logger.error(
                        "db_pool_init_failed",
                        attempts=len(_SEED_INIT_DELAYS),
                        error=str(e),
                    )
                    raise
                self.logger.warning(
                    "DB init failed — retrying",
                    attempt=attempt + 1,
                    retry_in_sec=_SEED_INIT_DELAYS[attempt],
                    error=str(e),
                )

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
                        SELECT ts, bar, technical_indicators, composite_events, market_context,
                               pattern_detections, regime_features, confluence_scores, smc,
                               cross_timeframe_context, bar_close_ts, i1_computed_at, computed_at
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
                        i1=I1Indicators(**_tier("technical_indicators")),
                        i2=I2Events(**_tier("composite_events")),
                        i3=I3Structure(**_tier("regime_features")),
                        i4=I4Context(**_tier("confluence_scores")),
                        i5=I5Patterns(**_tier("pattern_detections")),
                        smc=SMCContext(**_tier("smc")),
                        i6=I6Confluence(**_tier("cross_timeframe_context")),
                        bar_close_ts=latest["bar_close_ts"],
                        i1_computed_at=latest["i1_computed_at"],
                        computed_at=latest["computed_at"],
                    )
                    # Plan 05 serialization fix: publish flat dict, not {"event": "<json_string>"}
                    await self._kafka_producer.publish(
                        topic_intelligence(self._env_name),
                        event.model_dump(mode="json"),
                        key=message_key(symbol, tf),
                    )
                    published_events += 1
                except Exception as e:
                    self.logger.warning("Seed publish failed", symbol=symbol, tf=tf, error=str(e))

        all_tasks = [_seed_one(sym, tf) for sym in active_contracts for tf in timeframes]
        await _gather_in_batches(all_tasks)

        # Fallback: seed bar_history from market_data_ohlcv_tradeable for combos still
        # below threshold. Tradeable view, not the raw table (todo 124): bar_history
        # feeds the live compute path's rolling-window indicators directly -- a
        # synthetic-fill placeholder bar seeded here would corrupt momentum/volatility
        # state at startup, not just leave a harmless gap.
        fallback_seeded = 0

        async def _fallback_one(symbol: str, tf: str) -> None:
            nonlocal fallback_seeded
            if len(bar_history.get(symbol, tf)) >= min_bars_for_tf(tf) * 2:
                return
            async with sem:
                min_bars = min_bars_for_tf(tf) * 2
                tf_secs = TF_SECONDS.get(tf, 60)
                lookback_secs = min_bars * tf_secs * SEED_LOOKBACK_MULTIPLIER
                try:
                    rows = await db.execute_query(
                        f"""
                        SELECT timestamp, open, high, low, close, volume
                        FROM market_data_ohlcv_tradeable
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
        await _gather_in_batches(fallback_tasks)

        self.logger.info(
            "Seeded bar_history and published intelligence",
            seeded_bars=seeded_bars,
            fallback_bars=fallback_seeded,
            published_events=published_events,
        )
