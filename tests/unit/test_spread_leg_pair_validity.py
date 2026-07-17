"""Data-contract guard: every `instrument_tags` row with tag='spread_leg' must carry
evidence whose `pair` key resolves to a real `instruments.symbol`, and every named pair
must be symmetric (reciprocal).

Modeled on tests/unit/test_market_data_ohlcv_boundary.py's allow-list-and-assert shape,
but sourcing from a live DB read rather than a filesystem grep -- D-09 (Phase 146
146-CONTEXT.md) frames spread_leg's evidence contract as a data-contract check, not a
call-site grep, so the assertion target is the live `indicagent` database, not source
files.

`evidence->'pair'` is either a JSON string (a single spread partner) or a JSON array of
strings (a hub instrument legitimately paired against multiple legs -- e.g. SPY pairs
with both IPO and EZU). `_normalize_pairs()` below handles both shapes uniformly.

DB-backed: connects to the live `indicagent` database (not `indicagent_test` --
conftest.py's DATABASE_URL points at the isolated test DB, but spread_leg's real data
only exists in the live corpus). Skips gracefully if the DB is unreachable, matching
the house pattern in tests/unit/intelligence/trading/test_pg_enum_enforcement.py.
"""

from __future__ import annotations

import functools

import psycopg2
import pytest

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _normalize_pairs(evidence: dict | None) -> list[str]:
    """Extract the `pair` key from a spread_leg evidence blob as a list of symbols.

    Returns [] if evidence is missing/None or the `pair` key is absent -- callers treat
    an empty list as "no pair asserted" and fail the validity assertion accordingly.
    """
    if not evidence:
        return []
    pair = evidence.get("pair")
    if pair is None:
        return []
    if isinstance(pair, list):
        return list(pair)
    return [pair]


@functools.lru_cache(maxsize=1)
def _fetch_spread_leg_rows() -> dict[str, dict | None] | None:
    """Returns {symbol: evidence_dict_or_None} for every spread_leg row, or None if the
    live DB is unreachable (callers must pytest.skip on None, not fail)."""
    try:
        conn = psycopg2.connect(_LIVE_DB_DSN)
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol, evidence FROM instrument_tags WHERE tag = 'spread_leg'")
            return dict(cur.fetchall())
    finally:
        conn.close()


@functools.lru_cache(maxsize=1)
def _fetch_valid_symbols() -> frozenset[str] | None:
    """Returns the full set of instruments.symbol values, or None if unreachable."""
    try:
        conn = psycopg2.connect(_LIVE_DB_DSN)
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM instruments")
            return frozenset(row[0] for row in cur.fetchall())
    finally:
        conn.close()


def test_every_spread_leg_pair_resolves_to_a_valid_symbol():
    """Every instrument_tags row with tag='spread_leg' must have a non-missing
    evidence->'pair' value, and every named pair symbol must exist in instruments.symbol."""
    rows = _fetch_spread_leg_rows()
    valid_symbols = _fetch_valid_symbols()
    if rows is None or valid_symbols is None:
        pytest.skip("Cannot connect to the live indicagent DB")

    missing_pair: list[str] = []
    unresolved: list[str] = []
    for symbol, evidence in rows.items():
        pairs = _normalize_pairs(evidence)
        if not pairs:
            missing_pair.append(symbol)
            continue
        for pair_symbol in pairs:
            if pair_symbol not in valid_symbols:
                unresolved.append(f"{symbol}->{pair_symbol}")

    assert not missing_pair, (
        f"spread_leg row(s) with no evidence->'pair' key: {sorted(missing_pair)}. "
        "Every spread_leg row must carry a structured {'pair': <symbol>} evidence entry "
        "(migration 237, D-09) -- fix the row's evidence or delete it if unrecoverable."
    )
    assert not unresolved, (
        f"spread_leg pair(s) naming a symbol that does not exist in instruments.symbol: "
        f"{sorted(unresolved)}. A pair must reference a real, currently-known instrument."
    )


def test_spread_leg_pairs_are_symmetric():
    """If symbol A's spread_leg evidence names B as a pair, B must have its own
    spread_leg row whose evidence names A back (reciprocal reference).

    This is a real assertion, not a tautology: deleting or corrupting one side of a
    reciprocal pair (e.g. removing UUP's row while FXE still names UUP as its pair)
    would make this test fail.
    """
    rows = _fetch_spread_leg_rows()
    if rows is None:
        pytest.skip("Cannot connect to the live indicagent DB")

    partners: dict[str, list[str]] = {
        symbol: _normalize_pairs(evidence) for symbol, evidence in rows.items()
    }

    asymmetric: list[str] = []
    for symbol, pair_list in partners.items():
        for partner in pair_list:
            if partner not in partners:
                asymmetric.append(f"{symbol}->{partner} (partner has no spread_leg row at all)")
                continue
            if symbol not in partners[partner]:
                asymmetric.append(
                    f"{symbol}->{partner} (reciprocal missing: {partner}'s evidence does "
                    f"not name {symbol} back; {partner}'s pairs are {partners[partner]})"
                )

    assert not asymmetric, "spread_leg pair reference(s) are not symmetric:\n" + "\n".join(
        sorted(asymmetric)
    )
