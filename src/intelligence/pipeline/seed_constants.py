"""Shared constants for I3 trend-field seeding (A7 fix).

Both the live FeaturePipelineExecutor and the replay script seed _last_events /
intelligence_cache from intelligence_features using these constants. Keeping them
in one place prevents live/replay divergence.
"""

# asyncpg placeholder variant ($1, $2) — used by FeaturePipelineExecutor
_I3_SEED_QUERY: str = """
    SELECT regime_features->>'trend_direction'    AS trend_direction,
           regime_features->>'trend_strength'     AS trend_strength,
           regime_features->>'trend_bars_elapsed' AS trend_bars_elapsed,
           regime_features->>'trend_confirmed'    AS trend_confirmed
    FROM intelligence_features
    WHERE symbol = $1 AND tf = $2
    ORDER BY ts DESC
    LIMIT 1
"""

# psycopg2 placeholder variant (%s) — used by run_historical_pipeline.py replay path
_I3_SEED_QUERY_PG: str = _I3_SEED_QUERY.replace("$1", "%s").replace("$2", "%s")

# Column order matches _I3_SEED_QUERY SELECT list — used to build dicts from positional rows.
_I3_SEED_COLS: tuple[str, ...] = (
    "trend_direction",
    "trend_strength",
    "trend_bars_elapsed",
    "trend_confirmed",
)

# Fields that arrive as JSONB text and must be coerced to float for extract_trend_sign().
_I3_NUMERIC_KEYS: frozenset[str] = frozenset(
    {"trend_direction", "trend_strength", "trend_bars_elapsed"}
)
