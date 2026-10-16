"""The single writer of ohlcv_raw, the one table of vendor answers (phase 191 plan 02, single_writer).

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Schema, Ingress contract).
`write_raw` classifies every incoming row against the stored row of the SAME
(symbol, timeframe, vendor, kind, timestamp) key:

- unchanged: nothing written, nothing logged;
- new: inserted;
- changed, and the offer was answered at or after the stored row's `served_at` (or the stored row
  has none): the old values go to ohlcv_revision (origin raw, the old row's request_id) and the
  row is replaced with served_at = the offer's answer time and this write's request_id and
  load_id;
- changed, and the offer is OLDER than the stored row (an artifact replayed after a newer serve, a
  late page): raw keeps the newer answer and the offered values go to ohlcv_revision as origin
  `superseded` under this load and request (migration 485), so nothing served is lost.

Last-wins is by serve time, not write order (fourth review of plan 191-07, finding 1): `served_at`
is when the vendor answered (the request's answer time, an artifact's recorded fetch time),
passed in by the caller as `answered_at`, never the database clock. It is the serve time of the
stored value's answer; an unchanged re-serve does not move it. The replacing upsert also carries
the serve-time guard in SQL, so even a writer that bypassed the classification could not put an
older answer over a newer one.

A different vendor (or kind) at the same slot is a different key, hence a new row: a cross-vendor
difference is a disagreement for selection to resolve, never a revision.

Nothing is refused or held (owner decision 2026-10-14, D-191-N): a vendor's own newer re-serve
always replaces its stored value and the old value is logged, so every overwrite is
recoverable. `preview_series` classifies one series without writing so the ingress contract can
record the load's counts (and run the restatement detector) before `write_raw` logs revisions
under that load.

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
sources, finite values, required lineage ids and answer time, the future-timestamp guard.
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
from src.intelligence.bars.vendor_kind import VENDOR_DERIVED
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
ORIGIN_SUPERSEDED = "superseded"
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
# served_at is the answer time of the offer (the caller's `answered_at`), never now().
_RAW_ROW = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
_INSERT_SQL = f"INSERT INTO ohlcv_raw ({', '.join(_RAW_COLUMNS)}) VALUES " "{values}"
# The serve-time guard in SQL: an offer never replaces a newer stored answer.
_UPSERT_TAIL = (
    ' ON CONFLICT ("timestamp", symbol, timeframe, vendor, kind) DO UPDATE SET '
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, served_at = EXCLUDED.served_at, "
    "request_id = EXCLUDED.request_id, load_id = EXCLUDED.load_id "
    "WHERE ohlcv_raw.served_at IS NULL OR EXCLUDED.served_at >= ohlcv_raw.served_at"
)

_READ_STORED_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, request_id, served_at FROM ohlcv_raw '
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
    # changed offers older than the stored answer: logged as superseded, raw untouched
    superseded: int = 0
    superseded_timestamps: tuple[datetime, ...] = ()


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
    # The trailing pair is the row's identity; it is identical on both sides of a same-key
    # comparison and rides the write contract unchanged (plan 191-13).
    return (
        float(row.open),
        float(row.high),
        float(row.low),
        float(row.close),
        None if row.volume is None else int(row.volume),
        row.vendor,
        row.kind,
    )


def _raw_params(
    row: RawRow, served_at: datetime, request_id: uuid.UUID, load_id: uuid.UUID
) -> list[Any]:
    values = _values(row)
    return [
        row.timestamp,
        row.symbol,
        row.timeframe,
        row.vendor,
        row.kind,
        *values[:5],
        served_at,
        request_id,
        load_id,
    ]


def _write_raw_rows(cur: Any, rows: list[list[Any]], *, batch_rows: int, tail: str = "") -> None:
    if not rows:
        return
    size = min(batch_rows, _MAX_PARAMS // _RAW_ROW.count("%s"))
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


def _check_answered_at(answered_at: datetime | None, latest_allowed: datetime) -> datetime:
    if answered_at is None or answered_at.tzinfo is None:
        raise ValueError(
            "write_raw requires a tz-aware answered_at (the vendor's answer time; served_at is "
            "never the write time)"
        )
    if answered_at > latest_allowed:
        raise ValueError(f"answered_at {answered_at!r} is in the future (clock error)")
    return answered_at


@dataclass(frozen=True)
class _Classified:
    delta: RawDelta
    replaced: dict[datetime, tuple]  # timestamp -> old values of a row the offer replaces
    superseded: dict[datetime, tuple]  # timestamp -> offered values older than the stored row
    old_request: dict[datetime, Any]


def _classify_series(
    cur: Any,
    series: tuple[str, str, str, str],
    keyed: dict[datetime, RawRow],
    answered_at: datetime,
) -> _Classified:
    """Lock the series, read its stored rows at the offered stamps and classify by value, then
    split the changed rows by serve time (module docstring)."""
    symbol, timeframe, vendor, kind = series
    stamps = sorted(keyed)
    _lock_series(cur, symbol, timeframe, vendor, kind)
    cur.execute(_READ_STORED_SQL, (symbol, timeframe, vendor, kind, stamps))
    fetched = cur.fetchall()
    stored = {r[0]: (r[1], r[2], r[3], r[4], r[5], vendor, kind) for r in fetched}
    served = {r[0]: r[7] for r in fetched}
    delta = classify({ts: _values(keyed[ts]) for ts in stamps}, stored)
    replaced: dict[datetime, tuple] = {}
    superseded: dict[datetime, tuple] = {}
    for ts, (new, old) in sorted(delta.changed.items()):
        stored_at = served[ts]
        if stored_at is None or answered_at >= stored_at:
            replaced[ts] = old[:5]
        else:
            superseded[ts] = new[:5]
    return _Classified(
        RawDelta(
            symbol=symbol,
            timeframe=timeframe,
            vendor=vendor,
            kind=kind,
            n_stored=len(stored),
            new=len(delta.new),
            changed=len(replaced),
            unchanged=delta.unchanged,
            changed_old=replaced,
            new_timestamps=tuple(sorted(delta.new)),
            superseded=len(superseded),
            superseded_timestamps=tuple(sorted(superseded)),
        ),
        replaced,
        superseded,
        {r[0]: r[6] for r in fetched},
    )


def write_raw(
    conn: Any,
    rows: Iterable[RawRow],
    *,
    load_id: uuid.UUID,
    request_id: uuid.UUID,
    answered_at: datetime,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    batch_rows: int,
    future_tolerance_s: int,
    now: datetime | None = None,
) -> list[RawDelta]:
    """Classify and write one chunk of vendor-served bars; return one RawDelta per series.

    `answered_at` is when the vendor answered this chunk (tz-aware); it becomes the served_at of
    every row written and decides, against each stored row's served_at, whether a changed offer
    replaces the stored answer or is logged as superseded (module docstring). `vendor_codes` and
    `kind_codes` are the caller's cached VocabularyService.active_codes sets. A key offered
    twice with different values raises ValueError before any SQL. Never commits: the caller's
    transaction owns the write.
    """
    if load_id is None or request_id is None:
        raise ValueError(
            "write_raw requires load_id and request_id (only the backfill writes NULLs)"
        )
    if batch_rows < 1:
        raise ValueError(f"batch_rows must be >= 1, got {batch_rows}")
    latest_allowed = (now or datetime.now(UTC)) + timedelta(seconds=future_tolerance_s)
    answered_at = _check_answered_at(answered_at, latest_allowed)

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
            found = _classify_series(cur, series, keyed, answered_at)
            # New revision rows carry the composite "vendor/kind" token in old_source (the D2
            # digest rule token); historical rows keep their labels.
            token = f"{vendor}/{kind}"
            new_rows += [
                _raw_params(keyed[ts], answered_at, request_id, load_id)
                for ts in found.delta.new_timestamps
            ]
            for ts, old in found.replaced.items():
                changed_rows.append(_raw_params(keyed[ts], answered_at, request_id, load_id))
                revisions.append(
                    (load_id, symbol, timeframe, ts, *old, token, vendor, kind)
                    + (found.old_request[ts], _ORIGIN)
                )
            for ts, offered in found.superseded.items():
                revisions.append(
                    (load_id, symbol, timeframe, ts, *offered, token, vendor, kind)
                    + (request_id, ORIGIN_SUPERSEDED)
                )
            deltas.append(found.delta)
        # Old values first, then the replacements, so a failure never leaves a silent restatement.
        _write_revisions(cur, revisions)
        _write_raw_rows(cur, new_rows, batch_rows=batch_rows)
        _write_raw_rows(cur, changed_rows, batch_rows=batch_rows, tail=_UPSERT_TAIL)
    return deltas


def preview_series(conn: Any, rows: Iterable[RawRow], *, answered_at: datetime) -> RawDelta:
    """What `write_raw` would find for ONE (symbol, timeframe, vendor, kind) series answered at
    `answered_at`, writing nothing. The ohlcv_load row (the role may INSERT but not UPDATE it)
    must carry the counts before `write_raw` records revisions under it, so classification
    precedes the write by design. The series advisory lock taken here is held to the end of the
    caller's transaction, so `write_raw`'s own read sees exactly these stored rows. Raises
    ValueError when the rows span more than one series."""
    grouped = _group_by_series(rows)
    if len(grouped) != 1:
        raise ValueError(f"preview_series takes exactly one series, got {sorted(grouped)}")
    ((series, keyed),) = grouped.items()
    with conn.cursor() as cur:
        return _classify_series(cur, series, keyed, answered_at).delta


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
