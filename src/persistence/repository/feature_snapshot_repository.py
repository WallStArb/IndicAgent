"""FeatureSnapshotRepository — read-side queries for warmup seeding.

Provides historical bar and intelligence data to WarmupProvider at agent startup.
All methods accept an open DatabaseManager instance so connection lifecycle
is owned by the caller.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class FeatureSnapshotRepository:
    """Read-only access to intelligence_features and market_data_ohlcv_tradeable for warmup."""

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    async def get_recent_features(
        self,
        symbol: str,
        tf: str,
        limit: int,
        lookback_secs: int,
    ) -> list[dict[str, Any]]:
        """Return recent rows from intelligence_features, newest first.

        Each row has keys: ts, bar, technical_indicators, composite_events, market_context,
        pattern_detections, regime_features, confluence_scores, smc, cross_timeframe_context,
        bar_close_ts, i1_computed_at, computed_at.
        Returns [] on query failure.
        """
        try:
            return await self._db.execute_query(
                """
                SELECT ts, bar, technical_indicators, composite_events, market_context,
                       pattern_detections, regime_features, confluence_scores, smc,
                       cross_timeframe_context, bar_close_ts, i1_computed_at, computed_at
                FROM intelligence_features
                WHERE symbol = $1 AND tf = $2
                  AND ts > NOW() - ($3 * INTERVAL '1 second')
                ORDER BY ts DESC
                LIMIT $4
                """,
                symbol,
                tf,
                lookback_secs,
                limit,
            )
        except Exception as error:
            logger.warning(
                "feature_snapshot_query_failed",
                symbol=symbol,
                tf=tf,
                error=str(error),
            )
            return []

    async def get_ohlcv_fallback(
        self,
        symbol: str,
        tf: str,
        limit: int,
        lookback_secs: int,
    ) -> list[dict[str, Any]]:
        """Return recent rows from market_data_ohlcv_tradeable when intelligence_features
        is sparse.

        Each row has keys: timestamp, open, high, low, close, volume.
        Returns [] on query failure.

        Tradeable view, not the raw table (todo 124): this seeds live compute-agent
        warmup state (same category as bar_history_seeder.py's fallback path) -- a
        synthetic-fill placeholder bar would corrupt indicator warmup state at startup.
        """
        try:
            return await self._db.execute_query(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM market_data_ohlcv_tradeable
                WHERE symbol = $1 AND timeframe = $2
                  AND timestamp > NOW() - ($3 * INTERVAL '1 second')
                ORDER BY timestamp DESC
                LIMIT $4
                """,
                symbol,
                tf,
                lookback_secs,
                limit,
            )
        except Exception as error:
            logger.warning(
                "ohlcv_fallback_query_failed",
                symbol=symbol,
                tf=tf,
                error=str(error),
            )
            return []
