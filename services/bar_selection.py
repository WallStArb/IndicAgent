"""The canonical vendor-row writer for direct timeframes (1m, 5m, 4h), phase 191 plan 02.

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Canonical section, single_writer).
Selection, not authoring: the canonical row of each slot is chosen from `ohlcv_raw` by
src/intelligence/bars/selection.py (a pure function of raw rows and bar_source_policy) and
written to market_data_ohlcv. 1d is the daily rule's and 15m/1h are the grid's, so they are
refused here.

The caller owns the connection and its transaction; this module never commits. Policy rows and
the CVR bar_kind sort_order arrive as arguments (read-only inputs the caller loads), which keeps
the writer testable. New slots INSERT; a slot whose selected row differs from the stored one is
replaced by a plain multi-row INSERT ... ON CONFLICT DO UPDATE (never an UPDATE statement), the
shape _history_fetch.py and the ingress contract already use. A replaced canonical row is not
logged to ohlcv_revision: ohlcv_raw holds both vendors' values, and canonical is rebuildable
from raw. A selected row with NULL volume is skipped and counted, not filled: market_data_ohlcv
volume is NOT NULL and missing is never a placeholder.

Review fixes (plan 191-07). Each (symbol, timeframe) is selected under a transaction-scoped advisory
lock taken in sorted symbol order, so two writers of different vendors on one series cannot
interleave their read-select-write steps; every insert, new slots included, carries the upsert
tail, so a row that appeared anyway is overwritten by the deterministic choice rather than
colliding on the canonical unique key. A slot with raw candidates but no ranked vendor is counted
(`unselected`), not hidden: the loader reports it and fails on it. Extended-hours candidates are
dropped before ranking (src/intelligence/bars/selection.py, session rule) and counted `off_grid`.

Session-level fallback (second review of plan 191-07, finding 3). Selection takes each session
whole from one vendor (src/intelligence/bars/selection.py), so a write is widened to the whole
NYSE sessions its window touches (America/New_York midnight to midnight): a vendor switch is
written across the session, never half of it. Slots the chosen vendor does not hold when no
vendor is complete are retracted from canonical (`dropped`; missing is NaN, never the other
vendor's bar). Every session not taken plainly (from its primary, complete, holding every
calendar slot) is logged (`bar_selection.session_choice`), counted on the result and kept in
bar_session_choice (migration 480; third review of plan 191-07, finding 4), whose sole writer is
`record_session_choices`.

Since plan 191-13 the canonical row carries the winning raw row's (vendor, kind) directly, the
same identity it held in ohlcv_raw.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import structlog

from src.intelligence.bars.selection import (
    SESSION_TZ,
    Candidate,
    PolicyRow,
    SessionChoice,
    select_slots,
    session_date,
)
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES
from src.intelligence.bars.vendor_kind import BAR_VENDORS

DIRECT_TIMEFRAMES = frozenset({"1m", "5m", "4h"}) - DERIVATION_OWNED_TIMEFRAMES

_INSERT_HEAD = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, vendor, kind) VALUES "
)
_UPSERT_TAIL = (
    " ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, vendor = EXCLUDED.vendor, kind = EXCLUDED.kind"
)
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_ROW = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
_PARAMS_PER_ROW = _ROW.count("%s")
_MAX_PARAMS = 65535  # psycopg's bind-parameter limit per statement

_READ_RAW_SQL = (
    'SELECT "timestamp", symbol, timeframe, vendor, kind, open, high, low, close, volume '
    'FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s '
    'AND "timestamp" < %s'
)
_ONE_US = timedelta(microseconds=1)

logger = structlog.get_logger(__name__)


def session_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """[start, end) widened to whole NYSE session dates: America/New_York midnight of start's
    session date to the midnight after the session date of the last instant before `end`."""
    first = session_date(start)
    last = session_date(end - _ONE_US)
    return (
        datetime.combine(first, time.min, SESSION_TZ),
        datetime.combine(last + timedelta(days=1), time.min, SESSION_TZ),
    )


_POLICY_SQL = (
    "SELECT timeframe, symbol, valid_from, valid_to, primary_source, fallback_source "
    "FROM bar_source_policy_current WHERE timeframe = %s AND (symbol IS NULL OR symbol = %s)"
)

_READ_CANONICAL_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, vendor, kind FROM market_data_ohlcv '
    'WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s AND "timestamp" < %s'
)


@dataclass(frozen=True)
class SelectionResult:
    new: int
    changed: int
    unchanged: int
    skipped_null_volume: int
    unselected: int = 0
    off_grid: int = 0
    sessions_fallback: int = 0  # sessions taken whole from a vendor other than the primary
    sessions_incomplete: int = 0  # sessions no ranked vendor held whole
    dropped: int = 0  # slots left out by the session rule (canonical rows retracted)
    excluded: int = 0  # slots holding only never-selected kinds (reported, not a failure)


def _canonical_row(c: Candidate) -> tuple:
    return (
        c.timestamp,
        c.symbol,
        c.timeframe,
        c.open,
        c.high,
        c.low,
        c.close,
        c.volume,
        c.vendor,
        c.kind,
    )


def _write(cur: Any, rows: list[tuple], *, batch_rows: int) -> None:
    size = min(batch_rows, _MAX_PARAMS // _PARAMS_PER_ROW)
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        cur.execute(
            _INSERT_HEAD + ",".join([_ROW] * len(chunk)) + _UPSERT_TAIL,
            [value for row in chunk for value in row],
        )


def select_and_write(
    conn: Any,
    *,
    symbols: Sequence[str],
    timeframe: str,
    start: datetime,
    end: datetime,
    policy_rows: Sequence[PolicyRow] | None,
    kind_order: Mapping[str, int],
    batch_rows: int,
    exclude: frozenset[datetime] | set[datetime] = frozenset(),
) -> SelectionResult:
    """Select the canonical rows of the whole sessions [start, end) touches for `symbols` from
    ohlcv_raw and write them (module docstring). `exclude` names stamps left exactly as they
    are (a repair's slots awaiting a re-serve): neither written nor retracted. `policy_rows`
    None reads each series' policy under its selection lock (the ingress path: a cached policy
    could predate a --reselect that committed while this caller waited for the lock).

    Raises ValueError for a timeframe other than 1m, 5m or 4h and LookupError when a held slot
    has no policy row (nothing for that symbol is written before the raise).
    """
    if timeframe not in DIRECT_TIMEFRAMES:
        raise ValueError(
            f"bar_selection writes direct timeframes {sorted(DIRECT_TIMEFRAMES)} only; "
            f"{timeframe!r} belongs to the daily rule or the grid"
        )
    if batch_rows < 1:
        raise ValueError(f"batch_rows must be >= 1, got {batch_rows}")
    n_new = n_changed = n_unchanged = n_skipped = n_unselected = n_off_grid = n_excluded = 0
    n_fallback = n_incomplete = n_dropped = 0
    start, end = session_window(start, end)
    vendors = sorted(BAR_VENDORS)
    with conn.cursor() as cur:
        for symbol in sorted(set(symbols)):
            cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
            series_policy = policy_rows
            if series_policy is None:
                cur.execute(_POLICY_SQL, (timeframe, symbol))
                series_policy = [PolicyRow(*row) for row in cur.fetchall()]
            cur.execute(_READ_RAW_SQL, (symbol, timeframe, start, end))
            candidates = [Candidate(*row) for row in cur.fetchall()]
            outcome = select_slots(candidates, series_policy, kind_order)
            n_unselected += outcome.n_unselected
            n_excluded += outcome.n_excluded
            n_off_grid += outcome.n_off_grid
            for choice in outcome.choices:
                n_fallback += choice.vendor != choice.ranking[0]
                n_incomplete += not choice.complete
                # one line per non-trivial session; the durable record is bar_session_choice, so
                # this is debug detail, never info in a full-corpus loop (CLAUDE.md logging rule)
                logger.debug(
                    "bar_selection.session_choice",
                    symbol=symbol,
                    timeframe=timeframe,
                    session=choice.session.isoformat(),
                    ranking=list(choice.ranking),
                    vendor=choice.vendor,
                    complete=choice.complete,
                    n_slots=choice.n_slots,
                    n_vendor_slots=choice.n_vendor_slots,
                    n_grid_slots=choice.n_grid_slots,
                    n_vendor_grid_slots=choice.n_vendor_grid_slots,
                )
            record_session_choices(cur, symbol, timeframe, outcome.sessions, outcome.choices)
            for _symbol, _tf, ts in (*outcome.dropped, *outcome.unselected):
                if ts in exclude:
                    continue
                cur.execute(_RETRACT_SQL, (symbol, timeframe, ts, vendors))
                n_dropped += cur.rowcount
            winners = [w for w in outcome.winners if w.timestamp not in exclude]
            if not winners:
                continue
            cur.execute(_READ_CANONICAL_SQL, (symbol, timeframe, start, end))
            stored = {row[0]: tuple(row[1:]) for row in cur.fetchall()}
            new_rows: list[tuple] = []
            changed_rows: list[tuple] = []
            for winner in winners:
                if winner.volume is None:
                    n_skipped += 1
                    continue
                row = _canonical_row(winner)
                old = stored.get(winner.timestamp)
                if old is None:
                    new_rows.append(row)
                elif old == row[3:]:
                    n_unchanged += 1
                else:
                    changed_rows.append(row)
            _write(cur, new_rows, batch_rows=batch_rows)
            _write(cur, changed_rows, batch_rows=batch_rows)
            n_new += len(new_rows)
            n_changed += len(changed_rows)
    return SelectionResult(
        n_new,
        n_changed,
        n_unchanged,
        n_skipped,
        n_unselected,
        n_off_grid,
        n_fallback,
        n_incomplete,
        n_dropped,
        n_excluded,
    )


# The durable record of the session choices (migration 480; third review of plan 191-07,
# finding 4): sessions selected that are plain now lose their row, the others are upserted.
_CLEAR_CHOICES_SQL = (
    "DELETE FROM bar_session_choice WHERE symbol = %s AND timeframe = %s "
    "AND session_date = ANY(%s) AND NOT (session_date = ANY(%s))"
)
_UPSERT_CHOICE_SQL = (
    "INSERT INTO bar_session_choice (symbol, timeframe, session_date, vendor, ranking, complete, "
    "n_slots, n_vendor_slots, n_grid_slots, n_vendor_grid_slots, dropped, n_primary_grid_slots) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (symbol, timeframe, session_date) DO UPDATE SET vendor = EXCLUDED.vendor, "
    "ranking = EXCLUDED.ranking, complete = EXCLUDED.complete, n_slots = EXCLUDED.n_slots, "
    "n_vendor_slots = EXCLUDED.n_vendor_slots, n_grid_slots = EXCLUDED.n_grid_slots, "
    "n_vendor_grid_slots = EXCLUDED.n_vendor_grid_slots, dropped = EXCLUDED.dropped, "
    "n_primary_grid_slots = EXCLUDED.n_primary_grid_slots, "
    "decided_at = now() WHERE (bar_session_choice.vendor, bar_session_choice.ranking, "
    "bar_session_choice.complete, bar_session_choice.n_slots, bar_session_choice.n_vendor_slots, "
    "bar_session_choice.n_grid_slots, bar_session_choice.n_vendor_grid_slots, "
    "bar_session_choice.dropped, bar_session_choice.n_primary_grid_slots) IS DISTINCT FROM "
    "(EXCLUDED.vendor, EXCLUDED.ranking, EXCLUDED.complete, EXCLUDED.n_slots, "
    "EXCLUDED.n_vendor_slots, EXCLUDED.n_grid_slots, EXCLUDED.n_vendor_grid_slots, "
    "EXCLUDED.dropped, EXCLUDED.n_primary_grid_slots)"
)


def record_session_choices(
    cur: Any,
    symbol: str,
    timeframe: str,
    sessions: Sequence[date],
    choices: Sequence[SessionChoice],
) -> None:
    """Make bar_session_choice hold exactly `choices` for the `sessions` selected (migration
    480): the sole writer of the table, on the selection's own transaction and lock."""
    if not sessions:
        return
    cur.execute(
        _CLEAR_CHOICES_SQL,
        (symbol, timeframe, list(sessions), [c.session for c in choices]),
    )
    for c in choices:
        cur.execute(
            _UPSERT_CHOICE_SQL,
            (
                symbol,
                timeframe,
                c.session,
                c.vendor,
                list(c.ranking),
                c.complete,
                c.n_slots,
                c.n_vendor_slots,
                c.n_grid_slots,
                c.n_vendor_grid_slots,
                list(c.dropped),
                c.n_primary_grid_slots,
            ),
        )


# A retraction only ever removes a row a ranked vendor could have written; the vendor list is
# the fence (every mapped (vendor, kind) has one of BAR_VENDORS' vendors).
_RETRACT_SQL = (
    'DELETE FROM market_data_ohlcv WHERE symbol = %s AND timeframe = %s AND "timestamp" = %s '
    "AND vendor = ANY(%s)"
)
