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

Bulk path (docs/plans/2026-11-11-bulk-raw-load-path-design.md, sections 4 and 5): `RawBatch` is
the columnar carrier of one (timeframe, vendor, kind) family, validated, deduplicated and cut into
series-chunks by `build_raw_batch` with the same refusals as the row path. `stage_and_classify`
COPYs it into a session temp table, takes the same series locks and classifies every row against
the stored rows in ONE join (same rules as `classify` plus the serve-time split);
`write_classified` then writes revisions, new rows and replacements set-based from the stage, and
checks each rowcount against the classification. The contract writes the ohlcv_load rows between
the two calls, exactly as it does between `preview_series` and `write_raw`.
"""

from __future__ import annotations

import math
import numbers
import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import groupby
from typing import Any

import numpy as np
import pandas as pd

from src.config.config_service import ConfigService
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.intelligence.bars.vendor_kind import VENDOR_DERIVED, pair_token
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
    'AND "timestamp" = ANY(%s) AND "timestamp" >= %s AND "timestamp" <= %s'
)


def _read_stored(
    cur: Any, symbol: str, timeframe: str, vendor: str, kind: str, stamps: Iterable[datetime]
) -> list[tuple]:
    """The stored rows of one series at `stamps`, one bounded read per calendar year. A single
    `= ANY` over a multi-year array cannot prune chunks and took 22 s for a 10-year 1d offer
    (measured 2026-10-27, 340 raw chunks); per-year bounds let each read touch only its year's
    chunks (3 s for the same offer, unchanged for a one-day offer)."""
    wanted = sorted(set(stamps))
    rows: list[tuple] = []
    for _year, group in groupby(wanted, key=lambda ts: ts.year):
        batch = list(group)
        keep = set(batch)
        cur.execute(_READ_STORED_SQL, (symbol, timeframe, vendor, kind, batch, batch[0], batch[-1]))
        rows.extend(r for r in cur.fetchall() if r[0] in keep)
    return rows


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
    """One vendor-served bar. Volume is an integer or None (missing is None, never NaN).
    `answered_at` is the bar's own serve time when it differs from the call's (a loader batching
    many day files into one call: each file has its own LastModified); None takes the call's."""

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
    answered_at: datetime | None = None


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
    if row.answered_at is not None:
        _check_answered_at(row.answered_at, latest_allowed)
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
    fetched = _read_stored(cur, symbol, timeframe, vendor, kind, stamps)
    stored = {r[0]: (r[1], r[2], r[3], r[4], r[5], vendor, kind) for r in fetched}
    served = {r[0]: r[7] for r in fetched}
    delta = classify({ts: _values(keyed[ts]) for ts in stamps}, stored)
    replaced: dict[datetime, tuple] = {}
    superseded: dict[datetime, tuple] = {}
    for ts, (new, old) in sorted(delta.changed.items()):
        stored_at = served[ts]
        if stored_at is None or (keyed[ts].answered_at or answered_at) >= stored_at:
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
            token = pair_token(vendor, kind)
            new_rows += [
                _raw_params(keyed[ts], keyed[ts].answered_at or answered_at, request_id, load_id)
                for ts in found.delta.new_timestamps
            ]
            for ts, old in found.replaced.items():
                changed_rows.append(
                    _raw_params(
                        keyed[ts], keyed[ts].answered_at or answered_at, request_id, load_id
                    )
                )
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


# --------------------------------------------------------------------------------------
# Columnar bulk path (bulk raw load path design, sections 4 and 5)
# --------------------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US_PER_S = 1_000_000

# Row classes of the bulk classification (the CASE in _CLASSIFY_SQL).
CLS_NEW, CLS_UNCHANGED, CLS_REPLACE, CLS_SUPERSEDED = 0, 1, 2, 3
_N_CLASSES = 4


def us_to_datetime(us: int) -> datetime:
    """UTC microseconds since the epoch as a tz-aware datetime (exact integer arithmetic)."""
    return _EPOCH + timedelta(microseconds=int(us))


def datetime_to_us(ts: datetime) -> int:
    """A tz-aware datetime as UTC microseconds since the epoch (exact)."""
    delta = ts - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _US_PER_S + delta.microseconds


@dataclass(frozen=True, eq=False)
class RawBatch:
    """Vendor-served bars of ONE (timeframe, vendor, kind) family as parallel arrays, validated,
    deduplicated and ordered by (symbol, timestamp); built only by `build_raw_batch`.

    `load_key` numbers the series-chunks (one symbol's rows in stamp order, cut every
    `chunk_rows`): each gets one ohlcv_load row. Rows of one key are contiguous and keys ascend.
    `n_offered[k]` counts the input rows of key k before identical repeats collapsed."""

    timeframe: str
    vendor: str
    kind: str
    symbols: np.ndarray  # object (str), per row
    ts_us: np.ndarray  # int64, UTC microseconds
    open: np.ndarray  # float64
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray  # int64 (0 where volume_null)
    volume_null: np.ndarray  # bool: missing volume is None, never 0
    served_us: np.ndarray  # int64, the row's own answer time
    load_key: np.ndarray  # int64, nondecreasing from 0
    n_offered: np.ndarray  # int64 per load key

    def __len__(self) -> int:
        return len(self.ts_us)

    @property
    def n_keys(self) -> int:
        return len(self.n_offered)

    def key_bounds(self) -> np.ndarray:
        """Row offsets of each key: key k holds rows [bounds[k], bounds[k + 1])."""
        bounds: np.ndarray = np.searchsorted(self.load_key, np.arange(self.n_keys + 1))
        return bounds

    def keys(self, first: int, stop: int) -> RawBatch:
        """The sub-batch of keys [first, stop), renumbered from 0 (whole series-chunks only)."""
        bounds = self.key_bounds()
        rows = slice(int(bounds[first]), int(bounds[stop]))
        return RawBatch(
            self.timeframe,
            self.vendor,
            self.kind,
            self.symbols[rows],
            self.ts_us[rows],
            self.open[rows],
            self.high[rows],
            self.low[rows],
            self.close[rows],
            self.volume[rows],
            self.volume_null[rows],
            self.served_us[rows],
            self.load_key[rows] - first,
            self.n_offered[first:stop],
        )

    def volumes(self) -> list[int | None]:
        """Volume per row as Python ints, None where missing."""
        return self.rows_volumes(0, len(self))

    def rows_volumes(self, start: int, stop: int) -> list[int | None]:
        """Volume of rows [start, stop) as Python ints, None where missing."""
        out: list[int | None] = list(self.volume[start:stop].tolist())
        for i in np.flatnonzero(self.volume_null[start:stop]).tolist():
            out[i] = None
        return out


def _where(symbol: str, timeframe: str, ts_us: int) -> str:
    return f"{symbol} {timeframe} {us_to_datetime(ts_us)!r}"


def _validate_batch(
    *,
    timeframe: str,
    vendor: str,
    kind: str,
    symbols: np.ndarray,
    ts_us: np.ndarray,
    prices: dict[str, np.ndarray],
    volume: np.ndarray,
    volume_null: np.ndarray,
    served_us: np.ndarray,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    latest_us: int,
) -> None:
    """`_validate_row` over arrays: the same checks in the same order, raising the same message
    for the first offending row in input order (the row path validates row by row)."""
    if len(ts_us) == 0:
        return
    where = _where(str(symbols[0]), timeframe, int(ts_us[0]))
    if SOURCE_SYNTHETIC_FILL in (vendor, kind):
        raise ValueError(f"ohlcv_raw refuses placeholder bars (synthetic_fill): {where}")
    if vendor == VENDOR_DERIVED:
        raise ValueError(
            f"ohlcv_raw stores what vendors served; vendor 'derived' is canonical only: {where}"
        )
    if kind in CANONICAL_ONLY_KINDS:
        raise ValueError(f"kind {kind!r} is canonical only, never served by a vendor: {where}")
    if vendor not in vendor_codes:
        raise ValueError(f"vendor {vendor!r} is not a CVR bar_vendor code: {where}")
    if kind not in kind_codes:
        raise ValueError(f"kind {kind!r} is not a CVR bar_kind code: {where}")
    # (offending mask, message for row i at `where` w), in _validate_row's order
    checks: list[tuple[np.ndarray, Any]] = [
        (
            ts_us > latest_us,
            lambda i, w: f"future bar refused: {w} is later than now plus {FUTURE_TOLERANCE_KEY}",
        ),
        (
            served_us > latest_us,
            lambda i, w: (
                f"answered_at {us_to_datetime(int(served_us[i]))!r} is in the future (clock error)"
            ),
        ),
    ]
    for name, values in prices.items():
        checks.append(
            (
                ~np.isfinite(values),
                lambda i, w, name=name, values=values: (
                    f"non-finite or non-numeric {name} {float(values[i])!r}: {w}"
                ),
            )
        )
    checks.append(
        (
            ~volume_null & (volume < 0),
            lambda i, w: (
                f"volume must be a non-negative integer or None, got {int(volume[i])!r}: {w}"
            ),
        )
    )
    bad = np.logical_or.reduce([mask for mask, _ in checks])
    if not bad.any():
        return
    first = int(np.argmax(bad))
    for mask, message in checks:
        if mask[first]:
            raise ValueError(message(first, _where(str(symbols[first]), timeframe, ts_us[first])))


def build_raw_batch(
    *,
    timeframe: str,
    vendor: str,
    kind: str,
    symbols: np.ndarray,
    ts_us: np.ndarray,
    open: np.ndarray,  # noqa: A002 - the column's name
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    served_us: np.ndarray,
    vendor_codes: Collection[str],
    kind_codes: Collection[str],
    future_tolerance_s: int,
    chunk_rows: int,
    volume_null: np.ndarray | None = None,
    now: datetime | None = None,
) -> RawBatch:
    """Validate, deduplicate, order and cut one family's offered rows into a `RawBatch`.

    The row path's refusals (`_validate_row`, `_group_by_series`): a key offered twice with
    different values raises with the same message and count; identical repeats collapse, the
    last occurrence in input order kept. Rows are then ordered by (symbol, timestamp) and each
    symbol's rows cut into series-chunks of at most `chunk_rows` (`load_frame`'s chunking)."""
    if chunk_rows < 1:
        raise ValueError(f"chunk_rows must be >= 1, got {chunk_rows}")
    symbols = np.asarray(symbols, dtype=object)
    n = len(symbols)
    stamps = offered_stamps = np.asarray(ts_us, dtype=np.int64)
    o, h, lo, c = (np.asarray(a, dtype=np.float64) for a in (open, high, low, close))
    served = np.asarray(served_us, dtype=np.int64)
    null = np.zeros(n, dtype=bool) if volume_null is None else np.asarray(volume_null, dtype=bool)
    vol = np.where(null, 0, np.asarray(volume, dtype=np.int64))
    if any(len(a) != n for a in (stamps, o, h, lo, c, vol, null, served)):
        raise ValueError("build_raw_batch: column lengths differ")
    _validate_batch(
        timeframe=timeframe,
        vendor=vendor,
        kind=kind,
        symbols=symbols,
        ts_us=stamps,
        prices={"open": o, "high": h, "low": lo, "close": c},
        volume=vol,
        volume_null=null,
        served_us=served,
        vendor_codes=vendor_codes,
        kind_codes=kind_codes,
        latest_us=datetime_to_us(now or datetime.now(UTC)) + future_tolerance_s * _US_PER_S,
    )
    code, names = pd.factorize(symbols, sort=True)  # sorted names; faster than np.unique on str
    if (code < 0).any():  # factorize codes a missing symbol -1, which would index the last name
        raise ValueError(f"symbol missing on {int((code < 0).sum())} offered row(s)")
    order = np.lexsort((np.arange(n), stamps, code))  # by (symbol, stamp), input order on ties
    code, stamps = code[order], stamps[order]
    o, h, lo, c = (a[order] for a in (o, h, lo, c))
    vol, null, served = vol[order], null[order], served[order]
    repeat = (code[1:] == code[:-1]) & (stamps[1:] == stamps[:-1])
    differs = repeat & (
        (o[1:] != o[:-1])
        | (h[1:] != h[:-1])
        | (lo[1:] != lo[:-1])
        | (c[1:] != c[:-1])
        | (vol[1:] != vol[:-1])
        | (null[1:] != null[:-1])
    )
    if differs.any():
        later = np.sort(order[1:][differs])  # each contradicting row, in input order
        shown = ", ".join(
            f"{symbols[i]} {timeframe} {vendor}/{kind} {us_to_datetime(offered_stamps[i])!r}"
            for i in later[:5].tolist()
        )
        raise ValueError(
            f"chunk offers {len(later)} key(s) twice with different values "
            f"(first: {shown}); a vendor answer contradicting itself is not collapsed silently"
        )
    # (the [:n] slices make an empty offer an empty batch)
    keep = np.r_[~repeat, True][:n]  # the last occurrence of each key
    kept_of = (np.cumsum(np.r_[True, ~repeat]) - 1)[:n]  # each sorted input row's kept row
    code, stamps = code[keep], stamps[keep]
    o, h, lo, c = (a[keep] for a in (o, h, lo, c))
    vol, null, served = vol[keep], null[keep], served[keep]
    position = np.arange(len(code))
    symbol_start = np.r_[True, code[1:] != code[:-1]]
    symbol_first = np.maximum.accumulate(np.where(symbol_start, position, 0))
    cut = symbol_start | ((position - symbol_first) % chunk_rows == 0)
    load_key = np.cumsum(cut) - 1
    n_offered = np.bincount(load_key[kept_of], minlength=int(cut.sum())).astype(np.int64)
    return RawBatch(
        timeframe,
        vendor,
        kind,
        names[code],
        stamps,
        o,
        h,
        lo,
        c,
        vol,
        null,
        served,
        load_key.astype(np.int64),
        n_offered,
    )


# Session temp tables of the bulk path (design section 5), created inside the bar-writer role's
# context so later transactions under the role can use them. ON COMMIT DELETE ROWS empties them
# at every commit; a rollback of the creating transaction drops them and the next call recreates
# them. Stamps are staged as `timestamp` holding UTC and converted with AT TIME ZONE 'UTC'.
_STAGE_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS ohlcv_raw_stage (ord integer NOT NULL, "
    "load_key integer NOT NULL, ts_utc timestamp NOT NULL, symbol text NOT NULL, "
    "open float8 NOT NULL, high float8 NOT NULL, low float8 NOT NULL, close float8 NOT NULL, "
    "volume bigint, served_utc timestamp NOT NULL) ON COMMIT DELETE ROWS",
    "CREATE TEMP TABLE IF NOT EXISTS ohlcv_raw_stage_class (ord integer NOT NULL, "
    "cls smallint NOT NULL, old_open float8, old_high float8, old_low float8, old_close float8, "
    "old_volume bigint, old_request_id uuid) ON COMMIT DELETE ROWS",
    # a second batch inside one transaction starts from an empty stage
    "DELETE FROM ohlcv_raw_stage",
    "DELETE FROM ohlcv_raw_stage_class",
)
_COPY_STAGE_SQL = (
    "COPY ohlcv_raw_stage (ord, load_key, ts_utc, symbol, open, high, low, close, volume, "
    "served_utc) FROM STDIN (FORMAT BINARY)"
)
_STAGE_TYPES = [
    "int4",
    "int4",
    "timestamp",
    "text",
    "float8",
    "float8",
    "float8",
    "float8",
    "int8",
    "timestamp",
]
# One read of the stored rows: the subquery filters every segment-by column (symbol, timeframe,
# vendor) plus kind and a constant time range, so only these series' segments of the chunks the
# range touches are decompressed. Run unprepared so lo/hi exclude chunks at plan time. The CASE
# is `classify` (exact equality, volume NULL equals NULL) plus the serve-time split.
_CLASSIFY_SQL = (
    "INSERT INTO ohlcv_raw_stage_class "
    f"SELECT s.ord, CASE WHEN r.ts IS NULL THEN {CLS_NEW} "
    "WHEN (s.open, s.high, s.low, s.close) = (r.open, r.high, r.low, r.close) "
    f"AND s.volume IS NOT DISTINCT FROM r.volume THEN {CLS_UNCHANGED} "
    "WHEN r.served_at IS NULL OR (s.served_utc AT TIME ZONE 'UTC') >= r.served_at "
    f"THEN {CLS_REPLACE} ELSE {CLS_SUPERSEDED} END, "
    "r.open, r.high, r.low, r.close, r.volume, r.request_id "
    "FROM ohlcv_raw_stage s LEFT JOIN ("
    'SELECT "timestamp" AS ts, symbol, open, high, low, close, volume, served_at, request_id '
    "FROM ohlcv_raw WHERE timeframe = %(tf)s AND vendor = %(vendor)s AND kind = %(kind)s "
    'AND symbol = ANY(%(symbols)s) AND "timestamp" >= %(lo)s AND "timestamp" <= %(hi)s) r '
    "ON r.symbol = s.symbol AND r.ts = (s.ts_utc AT TIME ZONE 'UTC')"
)
_READ_CLASSES_SQL = "SELECT array_agg(cls ORDER BY ord) FROM ohlcv_raw_stage_class"
_READ_REPLACED_SQL = (
    "SELECT ord, old_open, old_high, old_low, old_close, old_volume FROM ohlcv_raw_stage_class "
    f"WHERE cls = {CLS_REPLACE} ORDER BY ord"
)
_STAGE_JOIN = "FROM ohlcv_raw_stage s JOIN ohlcv_raw_stage_class c USING (ord) "
_KEY_LOAD = "(%(load_ids)s::uuid[])[s.load_key + 1]"
_KEY_REQUEST = "(%(request_ids)s::uuid[])[s.load_key + 1]"


def _replaced_or_offered(column: str) -> str:
    return f"CASE c.cls WHEN {CLS_REPLACE} THEN c.old_{column} ELSE s.{column} END"


# Old values first, as write_raw: a replaced row logs the stored values under the stored row's
# request (origin raw), a superseded offer logs the offered values under this load's request.
_BULK_REVISION_SQL = (
    f"INSERT INTO ohlcv_revision ({', '.join(_REVISION_COLUMNS)}) "
    f"SELECT {_KEY_LOAD}, s.symbol, %(tf)s, s.ts_utc AT TIME ZONE 'UTC', "
    + ", ".join(_replaced_or_offered(c) for c in ("open", "high", "low", "close", "volume"))
    + ", %(token)s, %(vendor)s, %(kind)s, "
    f"CASE c.cls WHEN {CLS_REPLACE} THEN c.old_request_id ELSE {_KEY_REQUEST} END, "
    f"CASE c.cls WHEN {CLS_REPLACE} THEN %(origin_raw)s ELSE %(origin_superseded)s END "
    + _STAGE_JOIN
    + f"WHERE c.cls IN ({CLS_REPLACE}, {CLS_SUPERSEDED})"
)
_BULK_RAW_INSERT = (
    f"INSERT INTO ohlcv_raw ({', '.join(_RAW_COLUMNS)}) "
    "SELECT s.ts_utc AT TIME ZONE 'UTC', s.symbol, %(tf)s, %(vendor)s, %(kind)s, "
    "s.open, s.high, s.low, s.close, s.volume, s.served_utc AT TIME ZONE 'UTC', "
    f"{_KEY_REQUEST}, {_KEY_LOAD} "
    + _STAGE_JOIN
    + "WHERE c.cls = {cls} ORDER BY s.symbol, s.ts_utc"
)
# New rows are a plain INSERT (a racing insert fails loudly on the primary key); replacements
# carry the row path's serve-time guard.
_BULK_NEW_SQL = _BULK_RAW_INSERT.format(cls=CLS_NEW)
_BULK_REPLACE_SQL = _BULK_RAW_INSERT.format(cls=CLS_REPLACE) + _UPSERT_TAIL


@dataclass(frozen=True, eq=False)
class Classified:
    """A staged batch classified against the stored rows (the classes stay server-side in the
    session temp tables until `write_classified`). `cls` is each row's class; `replaced_old` the
    stored (open, high, low, close, volume) of each replaced row by row index; `counts[k, cls]`
    the rows of key k in each class."""

    batch: RawBatch
    cls: np.ndarray
    replaced_old: dict[int, tuple]
    counts: np.ndarray  # shape (n_keys, 4), columns indexed by the CLS_* codes


def _stage(cur: Any, batch: RawBatch) -> None:
    for statement in _STAGE_DDL:
        cur.execute(statement)
    columns = (
        range(len(batch)),
        batch.load_key.tolist(),
        batch.ts_us.astype("datetime64[us]").tolist(),  # naive UTC, staged as timestamp
        batch.symbols.tolist(),
        batch.open.tolist(),
        batch.high.tolist(),
        batch.low.tolist(),
        batch.close.tolist(),
        batch.volumes(),
        batch.served_us.astype("datetime64[us]").tolist(),
    )
    with cur.copy(_COPY_STAGE_SQL) as copy:
        copy.set_types(_STAGE_TYPES)
        for row in zip(*columns, strict=True):
            copy.write_row(row)


def batch_symbols(batch: RawBatch) -> list[str]:
    """The batch's symbols, sorted (rows are ordered by symbol, so each key's first row)."""
    return sorted(set(batch.symbols[batch.key_bounds()[:-1]].tolist()))


def lock_series(cur: Any, batch: RawBatch) -> None:
    """The row path's series lock (statement, key and sorted order) for every series of the
    batch; timeframe, vendor and kind are constant in a batch."""
    cur.executemany(
        _LOCK_SERIES_SQL,
        [("|".join((s, batch.timeframe, batch.vendor, batch.kind)),) for s in batch_symbols(batch)],
    )


def classify_params(batch: RawBatch) -> dict[str, Any]:
    """The parameters of `_CLASSIFY_SQL`: the family, the symbols and the constant time range."""
    return {
        "tf": batch.timeframe,
        "vendor": batch.vendor,
        "kind": batch.kind,
        "symbols": batch_symbols(batch),
        "lo": us_to_datetime(batch.ts_us.min()),
        "hi": us_to_datetime(batch.ts_us.max()),
    }


def write_params(
    batch: RawBatch, load_ids: list[uuid.UUID], request_ids: list[uuid.UUID]
) -> dict[str, Any]:
    """The parameters of the bulk revision and raw statements."""
    return {
        "tf": batch.timeframe,
        "vendor": batch.vendor,
        "kind": batch.kind,
        "token": pair_token(batch.vendor, batch.kind),
        "load_ids": load_ids,
        "request_ids": request_ids,
        "origin_raw": _ORIGIN,
        "origin_superseded": ORIGIN_SUPERSEDED,
    }


def stage_and_classify(cur: Any, batch: RawBatch) -> Classified:
    """Stage `batch`, lock its series and classify every row against the stored rows in one join
    (module docstring). Runs on the caller's cursor and transaction under the bar-writer role and
    writes nothing outside the session temp tables."""
    if len(batch) == 0:
        raise ValueError("stage_and_classify: empty batch")
    _stage(cur, batch)
    lock_series(cur, batch)
    cur.execute(_CLASSIFY_SQL, classify_params(batch), prepare=False)
    cur.execute(_READ_CLASSES_SQL)
    (classes,) = cur.fetchone()
    cls = np.asarray(classes or [], dtype=np.int64)
    if len(cls) != len(batch):
        raise RuntimeError(f"classification returned {len(cls)} rows for {len(batch)} staged")
    replaced_old: dict[int, tuple] = {}
    if (cls == CLS_REPLACE).any():
        cur.execute(_READ_REPLACED_SQL)
        replaced_old = {row[0]: tuple(row[1:]) for row in cur.fetchall()}
    counts = np.bincount(
        batch.load_key * _N_CLASSES + cls, minlength=batch.n_keys * _N_CLASSES
    ).reshape(batch.n_keys, _N_CLASSES)
    return Classified(batch, cls, replaced_old, counts)


def write_classified(
    cur: Any,
    classified: Classified,
    *,
    load_ids: list[uuid.UUID],
    request_ids: list[uuid.UUID],
) -> None:
    """Write a classified batch from the stage: revisions first, then new rows, then the guarded
    replacements, one statement each. `load_ids[k]` and `request_ids[k]` belong to key k; the
    ohlcv_load rows must exist already (foreign key). Every rowcount must equal the
    classification: a shortfall means the stored rows moved under the series lock (a writer that
    bypassed it) and raises, rolling back the caller's transaction."""
    batch = classified.batch
    if len(load_ids) != batch.n_keys or len(request_ids) != batch.n_keys:
        raise ValueError(f"need {batch.n_keys} load and request ids, one per series-chunk")
    n_new, _, n_replace, n_superseded = classified.counts.sum(axis=0).tolist()
    params = write_params(batch, load_ids, request_ids)
    for sql, expected, what in (
        (_BULK_REVISION_SQL, n_replace + n_superseded, "revision"),
        (_BULK_NEW_SQL, n_new, "new raw"),
        (_BULK_REPLACE_SQL, n_replace, "replacing raw"),
    ):
        if not expected:
            continue
        cur.execute(sql, params)
        if cur.rowcount != expected:
            raise RuntimeError(
                f"bulk raw write: {cur.rowcount} {what} rows written, {expected} classified "
                f"({batch.timeframe} {batch.vendor}/{batch.kind}); the stored rows moved under "
                "the series lock"
            )
