"""The single writer of ohlcv_raw, the one table of vendor answers (phase 191 plan 02, single_writer).

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Schema, Ingress contract).
`write_raw` classifies every incoming row against the stored row of the SAME
(symbol, timeframe, vendor, kind, timestamp) key:

- unchanged: nothing written, nothing logged;
- new: inserted;
- changed: the old values go to ohlcv_revision (origin raw, the old row's request_id) and the row
  is replaced last-wins with served_at = now() and this write's request_id and load_id.

A different vendor (or kind) at the same slot is a different key, hence a new row: a cross-vendor
difference is a disagreement for selection to resolve, never a revision.

The refusal decision is not made here. `preview_series` classifies one series without writing, the
ingress contract applies `should_refuse` against the vendor's own stored overlap, and a series it
refuses never reaches `write_raw`: `hold_pending` logs the offered values that differ from the
stored row (changed and new) as ohlcv_revision rows of origin `pending` and leaves the raw rows
untouched, so selection, which reads only current raw, cannot promote a refused value. A refusal
therefore lasts until an explicit decision (a waived write) replaces the stored row. For origin
`pending` the old_* columns hold the OFFERED value that was held, not a replaced one.

A chunk that holds one key twice with different values raises: that is a vendor answer
contradicting itself, evidence that must not be dropped silently by a last-wins dict. Every
function that reads a series' stored rows first takes a transaction-scoped advisory lock on the
series, so two writers of one series cannot both log the same old value.

Connection contract: the caller owns the connection and its open transaction, and has already
inserted the ohlcv_load row `load_id` names (ohlcv_revision.load_id is a foreign key). This
module never commits or rolls back. A replacement is a plain multi-row INSERT ... ON CONFLICT DO
UPDATE (TimescaleDB DML decompression handles compressed chunks natively), not
compressed_hypertable_write_session, which only serves the hardened feature tables and would
commit the caller's transaction (amendment 2026-10-13 to plan 191-02).

All validation runs before any SQL: CVR vendor and kind codes, canonical-only labels, placeholder
sources, finite values, required lineage ids, the future-timestamp guard.
"""

from __future__ import annotations

import math
import numbers
import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.config.config_service import ConfigService
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.intelligence.bars.vendor_kind import VENDOR_DERIVED, VENDOR_KIND_TO_LABEL
from src.intelligence.bars.write_contract import BarValues, classify

BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
FUTURE_TOLERANCE_KEY = "threshold.bar_integrity.future_bar_tolerance_s"
# Defaults mirror the migration seeds (380 and 473); ConfigService.get falls back to them.
_DEFAULT_BATCH_ROWS = 50_000
_DEFAULT_FUTURE_TOLERANCE_S = 3600

# Kinds that exist only on canonical rows (D-191-A): a selection outcome or a derivation, never
# something a vendor serves.
CANONICAL_ONLY_KINDS = frozenset({"fallback", "5m_grid"})

# psycopg's bind-parameter limit per statement (a protocol limit, not a tunable).
_MAX_PARAMS = 65535
_REVISION_BATCH = 1000
_ORIGIN = "raw"
_ORIGIN_PENDING = "pending"
# Transaction-scoped advisory lock per (symbol, timeframe, vendor, kind): taken before the stored
# rows are read, released at the caller's COMMIT or ROLLBACK. Re-entrant within one session, so
# preview_series and write_raw may both take it.
_LOCK_SERIES_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"

_RAW_COLUMNS = (
    '"timestamp"',
    "symbol",
    "timeframe",
    "vendor",
    "kind",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "served_at",
    "request_id",
    "load_id",
)
# served_at is the database clock (the write's transaction time), so it takes no parameter.
_RAW_ROW = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)"
_RAW_PARAMS_PER_ROW = _RAW_ROW.count("%s")
_INSERT_SQL = f"INSERT INTO ohlcv_raw ({', '.join(_RAW_COLUMNS)}) VALUES " "{values}"
_UPSERT_TAIL = (
    ' ON CONFLICT ("timestamp", symbol, timeframe, vendor, kind) DO UPDATE SET '
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, served_at = EXCLUDED.served_at, "
    "request_id = EXCLUDED.request_id, load_id = EXCLUDED.load_id"
)

_READ_STORED_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, request_id FROM ohlcv_raw '
    "WHERE symbol = %s AND timeframe = %s AND vendor = %s AND kind = %s "
    'AND "timestamp" = ANY(%s)'
)

_REVISION_COLUMNS = (
    "load_id",
    "symbol",
    "timeframe",
    '"timestamp"',
    "old_open",
    "old_high",
    "old_low",
    "old_close",
    "old_volume",
    "old_source",
    "vendor",
    "kind",
    "request_id",
    "origin",
)
_REVISION_ROW = "(" + ",".join(["%s"] * len(_REVISION_COLUMNS)) + ")"


@dataclass(frozen=True)
class RawRow:
    """One vendor-served bar. Volume is an integer or None (missing is None, never NaN)."""

    timestamp: datetime
    symbol: str
    timeframe: str
    vendor: str
    kind: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


@dataclass(frozen=True)
class RawDelta:
    """What one (symbol, timeframe, vendor, kind) series' write found."""

    symbol: str
    timeframe: str
    vendor: str
    kind: str
    n_stored: int
    new: int
    changed: int
    unchanged: int
    # timestamp -> old (open, high, low, close, volume) of each replaced row
    changed_old: dict[datetime, tuple] = field(default_factory=dict)
    # timestamps of the rows the series did not store yet
    new_timestamps: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class RawWriteParams:
    batch_rows: int
    future_tolerance_s: int


async def read_write_params(config: ConfigService) -> RawWriteParams:
    """Both APR values the writer takes, read once by the caller at init."""
    return RawWriteParams(
        batch_rows=int(await config.get(BATCH_ROWS_KEY, default=_DEFAULT_BATCH_ROWS)),
        future_tolerance_s=int(
            await config.get(FUTURE_TOLERANCE_KEY, default=_DEFAULT_FUTURE_TOLERANCE_S)
        ),
    )


def _label(vendor: str, kind: str) -> str:
    return VENDOR_KIND_TO_LABEL.get((vendor, kind), vendor)


def _validate_row(
    row: RawRow,
    *,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    latest_allowed: datetime,
) -> RawRow:
    where = f"{row.symbol} {row.timeframe} {row.timestamp!r}"
    if SOURCE_SYNTHETIC_FILL in (row.vendor, row.kind):
        raise ValueError(f"ohlcv_raw refuses placeholder bars (synthetic_fill): {where}")
    if row.vendor == VENDOR_DERIVED:
        raise ValueError(
            f"ohlcv_raw stores what vendors served; vendor 'derived' is canonical only: {where}"
        )
    if row.kind in CANONICAL_ONLY_KINDS:
        raise ValueError(f"kind {row.kind!r} is canonical only, never served by a vendor: {where}")
    if row.vendor not in vendor_codes:
        raise ValueError(f"vendor {row.vendor!r} is not a CVR bar_vendor code: {where}")
    if row.kind not in kind_codes:
        raise ValueError(f"kind {row.kind!r} is not a CVR bar_kind code: {where}")
    if row.timestamp.tzinfo is None:
        raise ValueError(f"naive timestamp refused (UTC required): {where}")
    if row.timestamp > latest_allowed:
        raise ValueError(
            f"future bar refused: {where} is later than now plus {FUTURE_TOLERANCE_KEY}"
        )
    for name in ("open", "high", "low", "close"):
        value = getattr(row, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, numbers.Real)
            or not math.isfinite(value)
        ):
            raise ValueError(f"non-finite or non-numeric {name} {value!r}: {where}")
    volume = row.volume
    if volume is not None and (
        isinstance(volume, bool) or not isinstance(volume, numbers.Integral) or volume < 0
    ):
        raise ValueError(f"volume must be a non-negative integer or None, got {volume!r}: {where}")
    return row


def _values(row: RawRow) -> BarValues:
    # The sixth slot is the label; it is identical on both sides of a same-key comparison.
    return (
        float(row.open),
        float(row.high),
        float(row.low),
        float(row.close),
        None if row.volume is None else int(row.volume),
        _label(row.vendor, row.kind),
    )


def _raw_params(row: RawRow, request_id: uuid.UUID, load_id: uuid.UUID) -> list[Any]:
    values = _values(row)
    return [
        row.timestamp,
        row.symbol,
        row.timeframe,
        row.vendor,
        row.kind,
        *values[:5],
        request_id,
        load_id,
    ]


def _write_raw_rows(cur: Any, rows: list[list[Any]], *, batch_rows: int, tail: str = "") -> None:
    size = min(batch_rows, _MAX_PARAMS // _RAW_PARAMS_PER_ROW)
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        sql = _INSERT_SQL.format(values=",".join([_RAW_ROW] * len(chunk))) + tail
        cur.execute(sql, [value for row in chunk for value in row])


def _write_revisions(cur: Any, revisions: list[tuple]) -> None:
    for start in range(0, len(revisions), _REVISION_BATCH):
        chunk = revisions[start : start + _REVISION_BATCH]
        cur.execute(
            f"INSERT INTO ohlcv_revision ({', '.join(_REVISION_COLUMNS)}) VALUES "
            + ",".join([_REVISION_ROW] * len(chunk)),
            [value for row in chunk for value in row],
        )


def _lock_series(cur: Any, symbol: str, timeframe: str, vendor: str, kind: str) -> None:
    cur.execute(_LOCK_SERIES_SQL, ("|".join((symbol, timeframe, vendor, kind)),))


def _group_by_series(
    rows: Iterable[RawRow],
    *,
    vendor_codes: Collection[str] | None = None,
    kind_codes: Collection[str] | None = None,
    latest_allowed: datetime | None = None,
) -> dict[tuple[str, str, str, str], dict[datetime, RawRow]]:
    """Rows keyed by series then timestamp. Validates each row when the codes are given. A key
    offered twice with different values raises (identical repeats collapse)."""
    by_series: dict[tuple[str, str, str, str], dict[datetime, RawRow]] = defaultdict(dict)
    contradictions: list[str] = []
    for row in rows:
        if vendor_codes is not None and kind_codes is not None and latest_allowed is not None:
            _validate_row(
                row, vendor_codes=vendor_codes, kind_codes=kind_codes, latest_allowed=latest_allowed
            )
        keyed = by_series[(row.symbol, row.timeframe, row.vendor, row.kind)]
        earlier = keyed.get(row.timestamp)
        if earlier is not None and _values(earlier) != _values(row):
            contradictions.append(
                f"{row.symbol} {row.timeframe} {row.vendor}/{row.kind} {row.timestamp!r}"
            )
        keyed[row.timestamp] = row
    if contradictions:
        shown = ", ".join(contradictions[:5])
        raise ValueError(
            f"chunk offers {len(contradictions)} key(s) twice with different values "
            f"(first: {shown}); a vendor answer contradicting itself is not collapsed silently"
        )
    return by_series


def write_raw(
    conn: Any,
    rows: Iterable[RawRow],
    *,
    load_id: uuid.UUID,
    request_id: uuid.UUID,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    batch_rows: int,
    future_tolerance_s: int,
    now: datetime | None = None,
) -> list[RawDelta]:
    """Classify and write one chunk of vendor-served bars; return one RawDelta per series.

    `vendor_codes` and `kind_codes` are the caller's cached VocabularyService.active_codes
    sets. A key offered twice with different values raises ValueError before any SQL. Never
    commits: the caller's transaction owns the write.
    """
    if load_id is None or request_id is None:
        raise ValueError(
            "write_raw requires load_id and request_id (only the backfill writes NULLs)"
        )
    if batch_rows < 1:
        raise ValueError(f"batch_rows must be >= 1, got {batch_rows}")
    latest_allowed = (now or datetime.now(UTC)) + timedelta(seconds=future_tolerance_s)

    by_series = _group_by_series(
        rows, vendor_codes=vendor_codes, kind_codes=kind_codes, latest_allowed=latest_allowed
    )
    if not by_series:
        return []

    deltas: list[RawDelta] = []
    new_rows: list[list[Any]] = []
    changed_rows: list[list[Any]] = []
    revisions: list[tuple] = []
    with conn.cursor() as cur:
        for series, keyed in sorted(by_series.items()):
            symbol, timeframe, vendor, kind = series
            stamps = sorted(keyed)
            _lock_series(cur, symbol, timeframe, vendor, kind)
            cur.execute(_READ_STORED_SQL, (symbol, timeframe, vendor, kind, stamps))
            fetched = cur.fetchall()
            label = _label(vendor, kind)
            stored = {r[0]: (r[1], r[2], r[3], r[4], r[5], label) for r in fetched}
            old_request = {r[0]: r[6] for r in fetched}
            delta = classify({ts: _values(keyed[ts]) for ts in stamps}, stored)
            new_rows += [_raw_params(keyed[ts], request_id, load_id) for ts in sorted(delta.new)]
            for ts in sorted(delta.changed):
                changed_rows.append(_raw_params(keyed[ts], request_id, load_id))
                old = delta.changed[ts][1]
                revisions.append(
                    (
                        load_id,
                        symbol,
                        timeframe,
                        ts,
                        *old[:5],
                        label,
                        vendor,
                        kind,
                        old_request[ts],
                        _ORIGIN,
                    )
                )
            deltas.append(
                RawDelta(
                    symbol=symbol,
                    timeframe=timeframe,
                    vendor=vendor,
                    kind=kind,
                    n_stored=len(stored),
                    new=len(delta.new),
                    changed=len(delta.changed),
                    unchanged=delta.unchanged,
                    changed_old={ts: old[:5] for ts, (_new, old) in delta.changed.items()},
                    new_timestamps=tuple(sorted(delta.new)),
                )
            )
        # Old values first, then the replacements, so a failure never leaves a silent restatement.
        _write_revisions(cur, revisions)
        _write_raw_rows(cur, new_rows, batch_rows=batch_rows)
        _write_raw_rows(cur, changed_rows, batch_rows=batch_rows, tail=_UPSERT_TAIL)
    return deltas


def preview_series(conn: Any, rows: Iterable[RawRow]) -> RawDelta:
    """What `write_raw` would find for ONE (symbol, timeframe, vendor, kind) series, writing
    nothing. The refusal decision needs the counts before any write (a refused series writes no
    raw row), and the ohlcv_load row (the role may INSERT but not UPDATE it) must carry them
    before `write_raw` records revisions under it, so classification precedes the write by
    design; plan 191-05 therefore keeps this function rather than deferring the revision foreign
    key. The series advisory lock taken here is held to the end of the caller's transaction, so
    `write_raw`'s own read sees exactly these stored rows. Raises ValueError when the rows span
    more than one series."""
    grouped = _group_by_series(rows)
    if len(grouped) != 1:
        raise ValueError(f"preview_series takes exactly one series, got {sorted(grouped)}")
    ((series, keyed),) = grouped.items()
    symbol, timeframe, vendor, kind = series
    stamps = sorted(keyed)
    label = _label(vendor, kind)
    with conn.cursor() as cur:
        _lock_series(cur, symbol, timeframe, vendor, kind)
        cur.execute(_READ_STORED_SQL, (symbol, timeframe, vendor, kind, stamps))
        stored = {r[0]: (r[1], r[2], r[3], r[4], r[5], label) for r in cur.fetchall()}
    delta = classify({ts: _values(keyed[ts]) for ts in stamps}, stored)
    return RawDelta(
        symbol=symbol,
        timeframe=timeframe,
        vendor=vendor,
        kind=kind,
        n_stored=len(stored),
        new=len(delta.new),
        changed=len(delta.changed),
        unchanged=delta.unchanged,
        changed_old={ts: old[:5] for ts, (_new, old) in delta.changed.items()},
        new_timestamps=tuple(sorted(delta.new)),
    )


def hold_pending(
    conn: Any,
    rows: Iterable[RawRow],
    *,
    load_id: uuid.UUID,
    request_id: uuid.UUID,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    future_tolerance_s: int,
    now: datetime | None = None,
) -> int:
    """Log refused rows as pending revisions and leave ohlcv_raw untouched.

    `rows` are the offered rows of a refused series that differ from the stored row (changed and
    new; unchanged rows need no hold). Each becomes an ohlcv_revision row of origin `pending`
    under the refused load, with the OFFERED value in the old_* columns. Validation is the same as
    `write_raw`'s, before any SQL. Returns the number of rows held. Never commits.
    """
    if load_id is None or request_id is None:
        raise ValueError("hold_pending requires load_id and request_id")
    latest_allowed = (now or datetime.now(UTC)) + timedelta(seconds=future_tolerance_s)
    held: list[tuple] = []
    for (symbol, timeframe, vendor, kind), keyed in sorted(
        _group_by_series(
            rows, vendor_codes=vendor_codes, kind_codes=kind_codes, latest_allowed=latest_allowed
        ).items()
    ):
        label = _label(vendor, kind)
        for ts in sorted(keyed):
            values = _values(keyed[ts])
            held.append(
                (
                    load_id,
                    symbol,
                    timeframe,
                    ts,
                    *values[:5],
                    label,
                    vendor,
                    kind,
                    request_id,
                    _ORIGIN_PENDING,
                )
            )
    if held:
        with conn.cursor() as cur:
            _write_revisions(cur, held)
    return len(held)


def read_stored_closes(
    conn: Any,
    symbol: str,
    timeframe: str,
    vendor: str,
    kind: str,
    timestamps: Iterable[datetime],
) -> dict[datetime, float]:
    """The stored raw closes of ONE (symbol, timeframe, vendor, kind) series at `timestamps`:
    a vendor's own answers only, for the update lane's overlap judgment (stored close versus
    the fresh close of the same source)."""
    with conn.cursor() as cur:
        cur.execute(_READ_STORED_SQL, (symbol, timeframe, vendor, kind, sorted(set(timestamps))))
        return {row[0]: row[4] for row in cur.fetchall()}
