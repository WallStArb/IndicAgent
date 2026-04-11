"""TrainingDataQuery — labeled training data from intelligence_features + signal_ledger.

No lookahead: WHERE f.ts < sl.activated_at enforced in SQL.
Returns polars DataFrame with all FeatureVector fields + outcome columns.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Class-level constant so tests can inspect the SQL for no-lookahead clause
_NO_LOOKAHEAD_SQL = "f.ts < sl.activated_at"

_BASE_SQL = f"""
SELECT
    f.ts,
    f.symbol,
    f.tf,
    -- i1 features (from JSONB)
    (f.i1->>'atr_14')::float          AS atr,
    (f.i1->>'rsi_14')::float          AS rsi,
    (f.i1->>'adx')::float             AS adx,
    (f.i1->>'macd')::float            AS macd,
    (f.i1->>'macd_signal')::float     AS macd_signal,
    (f.i1->>'volume_ratio')::float    AS volume_ratio,
    -- i4 features
    (f.i4->>'hmm_regime')::int        AS hmm_regime,
    (f.i4->>'hmm_regime_prob')::float AS hmm_prob,
    (f.i4->>'hurst_exponent')::float  AS hurst_exponent,
    (f.i4->>'kalman_trend')::float    AS kalman_trend,
    (f.i4->>'vol_percentile')::float  AS vol_percentile,
    (f.i4->>'garch_vol_ratio')::float AS garch_vol_ratio,
    -- i6 features
    (f.i6->>'ctf_score')::float       AS ctf_score,
    (f.i6->>'ctf_trend_alignment')::float AS ctf_trend_alignment,
    (f.i6->>'ctf_regime_agreement')::float AS ctf_regime_agreement,
    -- i7 CIS
    (f.i7->'cis'->>'score')::float    AS cis_score,
    -- Signal outcome columns
    sl.outcome,
    sl.pnl_r,
    sl.mae,
    sl.mfe,
    sl.bars_in_trade
FROM intelligence_features f
JOIN signal_ledger sl
  ON sl.symbol = f.symbol
 AND sl.feature_ts = f.ts
 AND sl.feature_tf = f.tf
 AND {_NO_LOOKAHEAD_SQL}   -- No lookahead: feature must precede outcome
WHERE f.symbol = $1
  AND f.tf = $2
  AND f.ts >= $3
  AND f.ts <= $4
  AND sl.outcome IS NOT NULL  -- only labeled rows (lifecycle complete)
ORDER BY f.ts
"""

_REGIME_SQL = _BASE_SQL.replace(
    "ORDER BY f.ts",
    "  AND (f.i4->>'hmm_regime')::int = $5\nORDER BY f.ts",
)


class TrainingDataQuery:
    """Fetch labeled training data for a given (symbol, tf, date_range)."""

    _NO_LOOKAHEAD_SQL = _NO_LOOKAHEAD_SQL
    _BASE_SQL = _BASE_SQL

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def query(
        self,
        symbol: str,
        tf: str,
        start_date: Any,
        end_date: Any,
        regime: int | None = None,
    ) -> Any:
        """Return polars DataFrame with feature columns + outcome labels.

        regime: if provided, filters WHERE hmm_regime = $5.
        Requires polars to be installed (pip install polars).
        """
        import polars as pl

        params: list = [symbol, tf, start_date, end_date]

        if regime is not None:
            sql = _REGIME_SQL
            params.append(regime)
        else:
            sql = _BASE_SQL

        async with self._pool.acquire() as conn:
            records = await conn.fetch(sql, *params)

        if not records:
            logger.warning("training_data.no_rows", symbol=symbol, tf=tf)
            return pl.DataFrame()

        # Convert asyncpg Records to polars DataFrame
        rows = [dict(r) for r in records]
        df = pl.from_dicts(rows)
        logger.info("training_data.fetched", symbol=symbol, tf=tf, rows=len(df))
        return df
