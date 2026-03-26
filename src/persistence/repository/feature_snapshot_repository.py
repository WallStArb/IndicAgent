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
    """Read-only access to intelligence_features and market_data_ohlcv for warmup."""

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

        Each row has keys: ts, bar, i1, i2, i3, i4, i5, smc, i6,
        bar_close_ts, i1_computed_at, computed_at.
        Returns [] on query failure.
        """
        try:
            return await self._db.execute_query(
                f"""
                SELECT ts, bar, i1, i2, i3, i4, i5, smc, i6,
                       bar_close_ts, i1_computed_at, computed_at
                FROM intelligence_features
                WHERE symbol = $1 AND tf = $2
                  AND ts > NOW() - INTERVAL '{lookback_secs} seconds'
                ORDER BY ts DESC
                LIMIT {limit}
                """,
                symbol,
                tf,
            )
        except Exception as exc:
            logger.warning(
                "feature_snapshot_query_failed",
                symbol=symbol,
                tf=tf,
                error=str(exc),
            )
            return []

    async def get_ohlcv_fallback(
        self,
        symbol: str,
        tf: str,
        limit: int,
        lookback_secs: int,
    ) -> list[dict[str, Any]]:
        """Return recent rows from market_data_ohlcv when intelligence_features is sparse.

        Each row has keys: timestamp, open, high, low, close, volume.
        Returns [] on query failure.
        """
        try:
            return await self._db.execute_query(
                f"""
                SELECT timestamp, open, high, low, close, volume
                FROM market_data_ohlcv
                WHERE symbol = $1 AND timeframe = $2
                  AND timestamp > NOW() - INTERVAL '{lookback_secs} seconds'
                ORDER BY timestamp DESC
                LIMIT {limit}
                """,
                symbol,
                tf,
            )
        except Exception as exc:
            logger.warning(
                "ohlcv_fallback_query_failed",
                symbol=symbol,
                tf=tf,
                error=str(exc),
            )
            return []
