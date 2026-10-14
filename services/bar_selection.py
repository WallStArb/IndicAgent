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

Held keys (second review of plan 191-07, finding 4). Selection never promotes a raw row that holds
a refused value (D-191-I): a key is held when its current raw value equals a `pending` revision
of a refused load of the series, or when its raw row was served by a refused load (its load_id,
or for a backfill copy its served_at) and the raw backfill logged the vendor's own value it
displaced there (a `raw-backfill-191` revision with other values). Such a candidate is left out
before ranking and counted (`held`); canonical keeps its row at the slot until a decision or a
re-serve. The ingress contract never writes a refused value to raw, so in the live path the set
is empty; the rule lives in the writer so that no reselection, from any caller, can promote a
legacy one. `read_held_keys` is the one definition; the selection gate reads it too.

Session-level fallback (second review of plan 191-07, finding 3). Selection takes each session
whole from one vendor (src/intelligence/bars/selection.py), so a write is widened to the whole
NYSE sessions its window touches (America/New_York midnight to midnight): a vendor switch is
written across the session, never half of it. Slots the chosen vendor does not hold when no
vendor is complete are retracted from canonical (`dropped`; missing is NaN, never the other
vendor's bar). Every session not taken from its primary is logged
(`bar_selection.session_choice`) and counted on the result.

Until plan 13 renames the column, the canonical row carries the `source` label of its
(vendor, kind). `canonical_columns` and `_INSERT_HEAD` are the only two places that change then.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import structlog

from src.intelligence.bars.selection import (
    SESSION_TZ,
    Candidate,
    PolicyRow,
    select_slots,
    session_date,
)
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES
from src.intelligence.bars.vendor_kind import VENDOR_KIND_TO_LABEL, vendor_kind_to_label

DIRECT_TIMEFRAMES = frozenset({"1m", "5m", "4h"}) - DERIVATION_OWNED_TIMEFRAMES

_INSERT_HEAD = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
)
_UPSERT_TAIL = (
    " ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source"
)
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_ROW = "(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
_PARAMS_PER_ROW = _ROW.count("%s")
_MAX_PARAMS = 65535  # psycopg's bind-parameter limit per statement

_READ_RAW_SQL = (
    'SELECT "timestamp", symbol, timeframe, vendor, kind, open, high, low, close, volume '
    'FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s '
    'AND "timestamp" < %s'
)
_REFUSED_LOADS_SQL = (
    "SELECT load_id, source, loaded_at FROM ohlcv_load "
    "WHERE symbol = %s AND timeframe = %s AND outcome = 'refused'"
)
_PENDING_SQL = (
    'SELECT "timestamp", vendor, kind, old_open, old_high, old_low, old_close, old_volume '
    "FROM ohlcv_revision WHERE load_id = ANY(%s) AND symbol = %s AND timeframe = %s "
    'AND origin = \'pending\' AND "timestamp" >= %s AND "timestamp" < %s'
)
# The vendor values the raw backfill displaced with a refused serve (raw-backfill-191 logged them).
_DISPLACED_SQL = (
    'SELECT v."timestamp", v.vendor, v.kind, v.old_open, v.old_high, v.old_low, v.old_close, '
    "v.old_volume FROM ohlcv_load l JOIN ohlcv_revision v "
    "ON v.load_id = l.load_id AND v.symbol = l.symbol AND v.timeframe = l.timeframe "
    "WHERE l.symbol = %s AND l.timeframe = %s AND l.caller = 'raw-backfill-191' "
    'AND v.origin <> \'pending\' AND v."timestamp" >= %s AND v."timestamp" < %s'
)
# Lineage of the raw rows a refused load can have served (load_id, or served_at for the copies).
_LINEAGE_SQL = (
    'SELECT "timestamp", vendor, kind, served_at, load_id FROM ohlcv_raw '
    'WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s AND "timestamp" < %s '
    "AND (load_id = ANY(%s) OR (load_id IS NULL AND served_at = ANY(%s)))"
)

HeldKey = tuple[datetime, str, str]  # (timestamp, vendor, kind)
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


def held_keys(
    candidates: Iterable[Candidate],
    *,
    pending: Mapping[HeldKey, set[tuple]],
    refused_served: set[HeldKey],
    displaced: Mapping[HeldKey, set[tuple]],
) -> set[HeldKey]:
    """The candidates whose current raw value is a held refused value (module docstring): equal
    to a pending value of the key, or served by a refused load where the backfill logged another
    own value it displaced."""
    out: set[HeldKey] = set()
    for c in candidates:
        key = (c.timestamp, c.vendor, c.kind)
        values = (c.open, c.high, c.low, c.close, c.volume)
        if values in pending.get(key, ()):
            out.add(key)
        elif key in refused_served and any(v != values for v in displaced.get(key, ())):
            out.add(key)
    return out


def read_held_keys(
    cur: Any,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    candidates: Sequence[Candidate],
) -> set[HeldKey]:
    """The held keys among `candidates` (raw rows of [start, end) of one series). A series with
    no refused load has none and costs one indexed read."""
    cur.execute(_REFUSED_LOADS_SQL, (symbol, timeframe))
    refused = cur.fetchall()
    if not refused or not candidates:
        return set()
    load_ids = [r[0] for r in refused]
    cur.execute(_PENDING_SQL, (load_ids, symbol, timeframe, start, end))
    pending: dict[HeldKey, set[tuple]] = {}
    for ts, vendor, kind, *values in cur.fetchall():
        pending.setdefault((ts, vendor, kind), set()).add(tuple(values))
    cur.execute(_DISPLACED_SQL, (symbol, timeframe, start, end))
    displaced: dict[HeldKey, set[tuple]] = {}
    for ts, vendor, kind, *values in cur.fetchall():
        displaced.setdefault((ts, vendor, kind), set()).add(tuple(values))
    refused_served: set[HeldKey] = set()
    if displaced:
        by_id = {r[0]: r[1] for r in refused}
        by_time = {(r[1], r[2]) for r in refused}
        cur.execute(
            _LINEAGE_SQL, (symbol, timeframe, start, end, load_ids, [r[2] for r in refused])
        )
        for ts, vendor, kind, served_at, load_id in cur.fetchall():
            if (load_id is not None and by_id.get(load_id) == vendor) or (
                load_id is None and (vendor, served_at) in by_time
            ):
                refused_served.add((ts, vendor, kind))
    return held_keys(
        candidates, pending=pending, refused_served=refused_served, displaced=displaced
    )


# The series' policy rows, read under its selection lock when the caller passes none (ingress):
# a --reselect policy change commits while holding that lock, so a reader after it sees it.
_POLICY_SQL = (
    "SELECT timeframe, symbol, valid_from, valid_to, primary_source, fallback_source "
    "FROM bar_source_policy WHERE timeframe = %s AND (symbol IS NULL OR symbol = %s)"
)

_READ_CANONICAL_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, source FROM market_data_ohlcv '
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
    held: int = 0  # raw rows left out because they hold a refused value (read_held_keys)
    sessions_fallback: int = 0  # sessions taken whole from a vendor other than the primary
    sessions_incomplete: int = 0  # sessions no ranked vendor held whole
    dropped: int = 0  # slots left out by the session rule (canonical rows retracted)


def canonical_columns(vendor: str, kind: str) -> str:
    """The `source` label a canonical row carries for a selected (vendor, kind)."""
    return vendor_kind_to_label(vendor, kind)


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
        canonical_columns(c.vendor, c.kind),
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
    n_new = n_changed = n_unchanged = n_skipped = n_unselected = n_off_grid = n_held = 0
    n_fallback = n_incomplete = n_dropped = 0
    start, end = session_window(start, end)
    labels = sorted(VENDOR_KIND_TO_LABEL.values())
    with conn.cursor() as cur:
        for symbol in sorted(set(symbols)):
            cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
            series_policy = policy_rows
            if series_policy is None:
                cur.execute(_POLICY_SQL, (timeframe, symbol))
                series_policy = [PolicyRow(*row) for row in cur.fetchall()]
            cur.execute(_READ_RAW_SQL, (symbol, timeframe, start, end))
            candidates = [Candidate(*row) for row in cur.fetchall()]
            held = read_held_keys(cur, symbol, timeframe, start, end, candidates)
            n_held += len(held)
            outcome = select_slots(candidates, series_policy, kind_order, held)
            n_unselected += outcome.n_unselected
            n_off_grid += outcome.n_off_grid
            for choice in outcome.choices:
                n_fallback += choice.vendor != choice.ranking[0]
                n_incomplete += not choice.complete
                logger.info(
                    "bar_selection.session_choice",
                    symbol=symbol,
                    timeframe=timeframe,
                    session=choice.session.isoformat(),
                    ranking=list(choice.ranking),
                    vendor=choice.vendor,
                    complete=choice.complete,
                    n_slots=choice.n_slots,
                    n_vendor_slots=choice.n_vendor_slots,
                )
            for _symbol, _tf, ts in outcome.dropped:
                if ts in exclude:
                    continue
                cur.execute(_RETRACT_SQL, (symbol, timeframe, ts, labels))
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
        n_held,
        n_fallback,
        n_incomplete,
        n_dropped,
    )


_RETRACT_SQL = (
    'DELETE FROM market_data_ohlcv WHERE symbol = %s AND timeframe = %s AND "timestamp" = %s '
    "AND source = ANY(%s)"
)


def retract_unselected_slots(
    conn: Any,
    *,
    symbol: str,
    timeframe: str,
    timestamps: Sequence[datetime],
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
) -> int:
    """Delete the canonical vendor row at each of `timestamps` where selection from raw now
    yields no winner (missing is NaN, never a stale value). Only for slots a caller withdrew
    from raw on purpose (the one-time re-judgment of the retired path's refused loads,
    scripts/ops/bars/ops_refusal_rejudge.py); the routine selection never deletes. Same lock as
    `select_and_write`. Returns the rows deleted. Never commits."""
    if timeframe not in DIRECT_TIMEFRAMES:
        raise ValueError(f"retract covers direct timeframes only, not {timeframe!r}")
    if not timestamps:
        return 0
    labels = sorted(VENDOR_KIND_TO_LABEL.values())
    removed = 0
    # selection is per session (one vendor each), so the whole sessions of the stamps are read
    start, end = session_window(min(timestamps), max(timestamps) + _ONE_US)
    with conn.cursor() as cur:
        cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
        cur.execute(_READ_RAW_SQL, (symbol, timeframe, start, end))
        candidates = [Candidate(*row) for row in cur.fetchall()]
        held = read_held_keys(cur, symbol, timeframe, start, end, candidates)
        outcome = select_slots(candidates, policy_rows, kind_order, held)
        # a held slot keeps its canonical row (no decision yet); every other slot without a
        # winner is retracted
        keep = {w.timestamp for w in outcome.winners} | {
            c.timestamp for c in candidates if (c.timestamp, c.vendor, c.kind) in held
        }
        for ts in sorted(set(timestamps) - keep):
            cur.execute(_RETRACT_SQL, (symbol, timeframe, ts, labels))
            removed += cur.rowcount
    return removed
