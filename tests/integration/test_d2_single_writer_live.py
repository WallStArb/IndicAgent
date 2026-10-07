"""Integration: D2 is the sole 1d writer and has derived the whole 1d history (plan 185-18).

Runs against the production database (not indicagent_test) because the point is the live
1d corpus and its lineage. Strictly read-only: SELECTs only, no rows are written.

Skipped when the live DB has no canonical_bar_lineage rows, i.e. before the historical
apply has run.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import date

import asyncpg
import pytest

from services.bar_derivation import (
    _D2V2_ROUTES,
    _SELECT_DAILY_OBSERVATIONS_SQL,
    _SELECT_DAILY_SPLITS_SQL,
)
from src.intelligence.bars import derivation as d

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_SAMPLE_SEED = 185
_SAMPLE_SIZE = 10
_ALLOWED_1D_SOURCES = {"ibkr_named", "ibkr_venue", "synthetic_fill"}

# Stored canonical-source 1d bars with volume > 0 that have no D1 observation and so no
# lineage: written by the pre-fence nightly (killed 2026-10-02) before the D1-only path
# landed. The next sanctioned 1d fetch of the name records its observation and D2 derives
# it, which empties this set; a stale entry fails the test.
_KNOWN_PRE_FENCE_ORPHANS = {("TLT", date(2026, 10, 1))}

_UNLINKED_SQL = """
SELECT m.symbol, m."timestamp"::date AS bar_date
FROM market_data_ohlcv m
WHERE m.timeframe = '1d' AND m.volume > 0 AND m.source IN ('ibkr_named', 'ibkr_venue')
  AND NOT EXISTS (
      SELECT 1 FROM canonical_bar_lineage l
      WHERE l.symbol = m.symbol AND l.timeframe = '1d' AND l."timestamp" = m."timestamp"
  )
"""


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(_LIVE_DB_URL)
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    try:
        n = await connection.fetchval("SELECT count(*) FROM canonical_bar_lineage")
        if not n:
            pytest.skip("canonical_bar_lineage is empty: the historical D2 apply has not run")
        yield connection
    finally:
        await connection.close()


async def _sample_symbols(conn: asyncpg.Connection) -> list[str]:
    symbols = [
        r["symbol"]
        for r in await conn.fetch(
            "SELECT symbol FROM instruments WHERE is_active AND compute_eligible_1d ORDER BY symbol"
        )
    ]
    return random.Random(_SAMPLE_SEED).sample(symbols, _SAMPLE_SIZE)


async def test_every_stored_1d_bar_with_volume_has_d2_lineage(conn):
    unlinked = {(r["symbol"], r["bar_date"]) for r in await conn.fetch(_UNLINKED_SQL)}
    assert unlinked == _KNOWN_PRE_FENCE_ORPHANS, (
        f"unlinked bars beyond the known pre-fence set: {sorted(unlinked - _KNOWN_PRE_FENCE_ORPHANS)}; "
        f"stale exceptions to delete: {sorted(_KNOWN_PRE_FENCE_ORPHANS - unlinked)}"
    )
    versions = {
        r["rule_version"]
        for r in await conn.fetch("SELECT DISTINCT rule_version FROM canonical_bar_lineage")
    }
    assert versions == {"d2-v1"}


async def test_no_1d_row_has_a_source_other_than_the_canonical_ones(conn):
    sources = {
        r["source"]
        for r in await conn.fetch(
            "SELECT DISTINCT source FROM market_data_ohlcv WHERE timeframe = '1d'"
        )
    }
    assert sources <= _ALLOWED_1D_SOURCES, sources - _ALLOWED_1D_SOURCES


async def test_stored_values_equal_derive_daily_for_a_sample_recomputed_from_d1(conn):
    venue_enabled = (
        await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = 'infra.bar_derivation.venue_bars_1d'"
        )
        == "true"
    )
    mismatches: list[str] = []
    for symbol in await _sample_symbols(conn):
        observations = [
            d.Observation(**{f: r[f] for f in d.Observation.__dataclass_fields__})
            for r in await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol, list(_D2V2_ROUTES))
        ]
        splits = [
            d.SplitRecord(**{f: r[f] for f in d.SplitRecord.__dataclass_fields__})
            for r in await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
        ]
        derived = {
            b.bar_date: b
            for b in d.derive_daily(observations, splits, venue_bars_enabled=venue_enabled)
        }
        stored = {
            r["bar_date"]: r
            for r in await conn.fetch(
                'SELECT "timestamp"::date AS bar_date, open, high, low, close, volume '
                "FROM market_data_ohlcv WHERE symbol = $1 AND timeframe = '1d' "
                "AND source IN ('ibkr_named', 'ibkr_venue')",
                symbol,
            )
        }
        assert derived, f"{symbol}: no derived bars"
        for bar_date, bar in derived.items():
            row = stored.get(bar_date)
            if row is None:
                mismatches.append(f"{symbol} {bar_date}: derived but not stored")
                continue
            for field in ("open", "high", "low", "close", "volume"):
                want = getattr(bar, field)
                if want is not None and row[field] != want:
                    mismatches.append(f"{symbol} {bar_date} {field}: {row[field]} != {want}")
    assert not mismatches, mismatches[:10]


async def test_digest_covers_every_1d_month_of_the_sample(conn):
    gaps: list[str] = []
    for symbol in await _sample_symbols(conn):
        months = {
            r["m"]
            for r in await conn.fetch(
                "SELECT DISTINCT date_trunc('month', \"timestamp\" AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS m "
                "FROM market_data_ohlcv WHERE symbol = $1 AND timeframe = '1d' "
                "AND source IN ('ibkr_named', 'ibkr_venue')",
                symbol,
            )
        }
        covered = {
            r["range_start"]
            for r in await conn.fetch(
                "SELECT range_start FROM bar_content_digest_current "
                "WHERE symbol = $1 AND timeframe = '1d'",
                symbol,
            )
        }
        gaps.extend(f"{symbol} {m:%Y-%m}" for m in sorted(months - covered))
    assert not gaps, gaps[:10]


async def test_no_scale_break_across_a_split_unless_flagged_pre_split_unrefetched(conn):
    """Vacuous while corporate_action_current is empty (0 rows on 2026-10-03)."""
    splits = await conn.fetch(
        "SELECT symbol, effective_date FROM corporate_action_current "
        "WHERE action_type ILIKE '%split%'"
    )
    by_symbol: dict[str, list[date]] = defaultdict(list)
    for r in splits:
        by_symbol[r["symbol"]].append(r["effective_date"])
    breaks: list[str] = []
    for symbol, dates in by_symbol.items():
        for effective in dates:
            pair = await conn.fetch(
                'SELECT "timestamp"::date AS bar_date, close FROM market_data_ohlcv '
                "WHERE symbol = $1 AND timeframe = '1d' AND source IN ('ibkr_named', 'ibkr_venue') "
                'AND "timestamp"::date <= $2 ORDER BY "timestamp" DESC LIMIT 2',
                symbol,
                effective,
            )
            if len(pair) < 2 or not pair[1]["close"]:
                continue
            ratio = pair[0]["close"] / pair[1]["close"]
            if 0.5 < ratio < 2.0:
                continue
            flagged = await conn.fetchval(
                "SELECT count(*) FROM bar_quality_flag WHERE symbol = $1 AND timeframe = '1d' "
                "AND rule = 'pre_split_unrefetched' AND \"timestamp\"::date = $2",
                symbol,
                pair[1]["bar_date"],
            )
            if not flagged:
                breaks.append(f"{symbol} {effective}: close ratio {ratio:.3f}")
    assert not breaks, breaks
