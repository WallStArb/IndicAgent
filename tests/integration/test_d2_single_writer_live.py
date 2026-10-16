"""Integration: the d2-v2 daily rule is the sole 1d writer and has derived the whole 1d history
(plans 185-18, 185-36, 185-38, 185-41).

Runs against the production database (not indicagent_test) because the point is the live 1d corpus
and its lineage. Strictly read-only: the connection is set read-only, so a stray write raises.

Asserts the d2-v2 design: the canonical 1d identities are (tradier, consolidated), (ibkr,
fallback) and (ibkr, named) (the last only on dates an exception policy row names IBKR primary);
the canonical_bar_lineage view is complete on every visible bar; a seeded sample recomputed with
derive_daily_v2 equals the stored bars; every month with bars has a current digest; no scale
break across a recorded split.

The sample recompute reads the daily stage's own inputs, the current ohlcv_raw 1d rows (phase 191
plan 08). A sampled name whose inputs were served after its last applied daily load is not
comparable (canonical is legitimately behind until the stage runs) and is skipped; most of the
sample must stay comparable. Skipped when ohlcv_raw holds no 1d rows.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date

import asyncpg
import pytest

from services.bar_derivation import _SELECT_POLICY_1D_SQL, read_daily_inputs
from src.intelligence.bars.daily_rule import RULE_VERSION, PolicyRow, derive_daily_v2
from src.intelligence.bars.sources import CANONICAL_1D_SOURCES

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_SAMPLE_SEED = 185
_SAMPLE_RANDOM = 14
_ALLOWED_1D_PAIRS = {("tradier", "consolidated"), ("ibkr", "fallback"), ("ibkr", "named")}
# two ANY arrays, not a composite-array parameter: the cross product they admit holds no rows
_ALLOWED_1D_VENDORS = sorted({v for v, _k in _ALLOWED_1D_PAIRS})
_ALLOWED_1D_KINDS = sorted({k for _v, k in _ALLOWED_1D_PAIRS})
_WINDOW_KEY = "threshold.bar_integrity.fallback_basis_window_sessions"
_TOLERANCE_KEY = "threshold.bar_integrity.fallback_basis_tolerance_bp"

# Stored (ibkr, named) bars on dates whose resolved 1d policy row (the symbol's row beats the
# default, daily_rule.resolve_policy) does not name IBKR primary. Since migration 456 the default
# names IBKR from 2026-10-07.
_IBKR_NAMED_OUTSIDE_EXCEPTION_SQL = """
SELECT m.symbol, (m."timestamp" AT TIME ZONE 'UTC')::date AS bar_date
FROM market_data_ohlcv m
CROSS JOIN LATERAL (SELECT (m."timestamp" AT TIME ZONE 'UTC')::date AS d) day
WHERE m.timeframe = '1d' AND m.vendor = 'ibkr' AND m.kind = 'named'
  AND COALESCE(
      (SELECT p.primary_source FROM bar_source_policy p
       WHERE p.timeframe = '1d' AND p.symbol = m.symbol
         AND p.valid_from <= day.d AND (p.valid_to IS NULL OR day.d < p.valid_to) LIMIT 1),
      (SELECT p.primary_source FROM bar_source_policy p
       WHERE p.timeframe = '1d' AND p.symbol IS NULL
         AND p.valid_from <= day.d AND (p.valid_to IS NULL OR day.d < p.valid_to) LIMIT 1)
  ) IS DISTINCT FROM 'ibkr'
"""

# Visible (tradeable-view) 1d bars of the canonical pairs whose lineage row has no request ids,
# or that have no lineage row at all.
_UNLINEAGED_SQL = """
SELECT t.symbol, (t."timestamp" AT TIME ZONE 'UTC')::date AS bar_date
FROM market_data_ohlcv_tradeable t
LEFT JOIN canonical_bar_lineage l
  ON l.symbol = t.symbol AND l.timeframe = '1d' AND l."timestamp" = t."timestamp"
WHERE t.timeframe = '1d' AND t.vendor = ANY($1::text[]) AND t.kind = ANY($2::text[])
  AND (l."timestamp" IS NULL OR l.request_ids IS NULL)
"""

_MONTHS_WITHOUT_DIGEST_SQL = """
SELECT b.symbol, b.month
FROM (
    SELECT symbol, date_trunc('month', "timestamp", 'UTC') AS month
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = '1d' AND vendor = ANY($1::text[]) AND kind = ANY($2::text[])
    GROUP BY 1, 2
) b
WHERE NOT EXISTS (
    SELECT 1 FROM bar_content_digest_current c
    WHERE c.symbol = b.symbol AND c.timeframe = '1d' AND c.range_start = b.month
)
"""

# A name with a d2-v3 raw input inside its stored span served after its last applied daily load:
# canonical is behind there until the daily stage runs again. Dates after the stored end (the
# sessions since the cutover) are left out of the comparison instead.
_SERVED_SINCE_LAST_LOAD_SQL = """
SELECT EXISTS (
    SELECT 1 FROM ohlcv_raw r
    WHERE r.symbol = $1 AND r.timeframe = '1d'
      AND (r.vendor, r.kind) IN (('ibkr', 'smart_trades'), ('tradier', 'consolidated'))
      AND r."timestamp" <= (SELECT max("timestamp") FROM market_data_ohlcv
                            WHERE symbol = $1 AND timeframe = '1d')
      AND r.served_at > COALESCE(
          (SELECT max(loaded_at) FROM ohlcv_load
           WHERE symbol = $1 AND timeframe = '1d' AND source = 'derived'
             AND outcome = 'applied' AND caller = 'bar_derivation-daily'),
          '-infinity'::timestamptz)
)
"""

# Category candidates for the sample, each a set of symbols present in the 1d corpus.
_EXCEPTION_NAMES_SQL = """
SELECT DISTINCT symbol FROM market_data_ohlcv
WHERE timeframe = '1d' AND vendor = 'ibkr' AND kind = 'named'
"""
_FALLBACK_NAMES_SQL = """
SELECT DISTINCT symbol FROM market_data_ohlcv
WHERE timeframe = '1d' AND vendor = 'ibkr' AND kind = 'fallback'
"""
# Tradier-owned names that also hold IBKR SMART TRADES raw rows: both vendors observed (the 236 that
# moved to Tradier in 185-36 are this kind).
_BOTH_VENDORS_NAMES_SQL = """
SELECT symbol FROM (
    SELECT DISTINCT symbol FROM market_data_ohlcv
    WHERE timeframe = '1d' AND vendor = 'tradier'
) t
WHERE EXISTS (
    SELECT 1 FROM ohlcv_raw r
    WHERE r.symbol = t.symbol AND r.timeframe = '1d' AND r.vendor = 'ibkr'
      AND r.kind = 'smart_trades'
)
"""


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(_LIVE_DB_URL)
    try:
        await connection.execute("SET default_transaction_read_only = on")
        n = await connection.fetchval(
            "SELECT count(*) FROM (SELECT 1 FROM ohlcv_raw WHERE timeframe = '1d' LIMIT 1) s"
        )
        if not n:
            pytest.skip("ohlcv_raw holds no 1d rows: the raw backfill has not run")
        yield connection
    finally:
        await connection.close()


async def _sample_symbols(conn: asyncpg.Connection) -> list[str]:
    """Seeded sample: a few random compute_1d names plus one of each kind the rule treats
    differently (an IBKR exception name, a fallback name, a both-vendors name, a Tradier-only
    name)."""
    rng = random.Random(_SAMPLE_SEED)
    universe = [
        r["symbol"]
        for r in await conn.fetch(
            "SELECT symbol FROM instruments WHERE is_active AND compute_eligible_1d ORDER BY symbol"
        )
    ]
    chosen: list[str] = []

    async def pick(sql: str) -> None:
        names = sorted({r["symbol"] for r in await conn.fetch(sql)} & set(universe) - set(chosen))
        assert names, f"no sample candidate for: {sql.strip().splitlines()[0]}"
        chosen.append(rng.choice(names))

    for sql in (_EXCEPTION_NAMES_SQL, _FALLBACK_NAMES_SQL, _BOTH_VENDORS_NAMES_SQL):
        await pick(sql)
    chosen.extend(rng.sample(sorted(set(universe) - set(chosen)), _SAMPLE_RANDOM))
    return chosen


async def test_the_corpus_holds_only_d2v2_canonical_identities(conn):
    pairs = {
        (r["vendor"], r["kind"])
        for r in await conn.fetch(
            "SELECT DISTINCT vendor, kind FROM market_data_ohlcv WHERE timeframe = '1d'"
        )
    }
    assert pairs <= _ALLOWED_1D_PAIRS, pairs - _ALLOWED_1D_PAIRS
    assert _ALLOWED_1D_PAIRS <= set(CANONICAL_1D_SOURCES)
    assert ("tradier", "consolidated") in pairs


async def test_ibkr_named_bars_sit_only_under_an_ibkr_exception_policy_row(conn):
    outside = await conn.fetch(_IBKR_NAMED_OUTSIDE_EXCEPTION_SQL)
    assert not outside, [(r["symbol"], r["bar_date"]) for r in outside[:10]]


async def test_every_visible_1d_bar_has_lineage_with_request_ids(conn):
    unlineaged = await conn.fetch(_UNLINEAGED_SQL, _ALLOWED_1D_VENDORS, _ALLOWED_1D_KINDS)
    assert not unlineaged, [(r["symbol"], r["bar_date"]) for r in unlineaged[:10]]
    versions = {
        r["rule_version"]
        for r in await conn.fetch("SELECT DISTINCT rule_version FROM canonical_bar_lineage")
    }
    assert versions == {RULE_VERSION}


async def test_stored_values_equal_derive_daily_v2_for_a_sample_recomputed_from_d1(conn):
    window = int(
        await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = $1", _WINDOW_KEY
        )
    )
    tolerance = float(
        await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = $1", _TOLERANCE_KEY
        )
    )
    policy = [
        PolicyRow(
            timeframe=r["timeframe"],
            symbol=r["symbol"],
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            ingress_mode=r["ingress_mode"],
            primary_source=r["primary_source"],
            fallback_source=r["fallback_source"],
        )
        for r in await conn.fetch(_SELECT_POLICY_1D_SQL)
    ]
    mismatches: list[str] = []
    sample = await _sample_symbols(conn)
    compared = 0
    for symbol in sample:
        if await conn.fetchval(_SERVED_SINCE_LAST_LOAD_SQL, symbol):
            continue
        compared += 1
        observations, splits = await read_daily_inputs(conn, symbol)
        derived = {
            b.bar_date: b
            for b in derive_daily_v2(
                observations,
                policy,
                splits,
                symbol=symbol,
                basis_window_sessions=window,
                basis_tolerance_bp=tolerance,
            ).bars
        }
        stored = {
            r["bar_date"]: r
            for r in await conn.fetch(
                "SELECT (\"timestamp\" AT TIME ZONE 'UTC')::date AS bar_date, open, high, low, "
                "close, volume, vendor, kind FROM market_data_ohlcv "
                "WHERE symbol = $1 AND timeframe = '1d' "
                "AND vendor = ANY($2::text[]) AND kind = ANY($3::text[])",
                symbol,
                _ALLOWED_1D_VENDORS,
                _ALLOWED_1D_KINDS,
            )
        }
        assert derived, f"{symbol}: no derived bars"
        stored_end = max(stored, default=None)
        for bar_date in sorted(set(derived) | set(stored)):
            if stored_end is not None and bar_date > stored_end:
                continue
            bar, row = derived.get(bar_date), stored.get(bar_date)
            if row is None:
                mismatches.append(f"{symbol} {bar_date}: derived but not stored")
            elif bar is None:
                mismatches.append(f"{symbol} {bar_date}: stored but not derived")
            else:
                for field in ("open", "high", "low", "close", "volume", "vendor", "kind"):
                    if row[field] != getattr(bar, field):
                        mismatches.append(
                            f"{symbol} {bar_date} {field}: {row[field]} != {getattr(bar, field)}"
                        )
    assert not mismatches, mismatches[:10]
    assert compared * 2 >= len(sample), f"only {compared} of {len(sample)} sampled names comparable"


async def test_digest_covers_every_1d_month_with_bars(conn):
    gaps = await conn.fetch(_MONTHS_WITHOUT_DIGEST_SQL, _ALLOWED_1D_VENDORS, _ALLOWED_1D_KINDS)
    assert not gaps, [(r["symbol"], f"{r['month']:%Y-%m}") for r in gaps[:10]]


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
                "WHERE symbol = $1 AND timeframe = '1d' "
                "AND vendor = ANY($3::text[]) AND kind = ANY($4::text[]) "
                'AND "timestamp"::date <= $2 ORDER BY "timestamp" DESC LIMIT 2',
                symbol,
                effective,
                _ALLOWED_1D_VENDORS,
                _ALLOWED_1D_KINDS,
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
