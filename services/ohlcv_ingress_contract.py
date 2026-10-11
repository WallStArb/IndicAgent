"""The ingress write contract for IBKR bar writes (phase 185 plan 39).

Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md) section 4,
applied to the two ingress bar tables, market_data_ohlcv (5m, 1m) and
ohlcv_intraday_raw_archive (the 15m/1h parity sample). One call per chunk:

1. read the stored rows for the chunk's keys;
2. classify each incoming row as new, changed or unchanged by exact value
   (src/intelligence/bars/write_contract.classify; a bar missing from an answer is not a
   deletion);
3. refuse the whole chunk, before any bar write, when changed / stored exceeds
   threshold.bar_integrity.max_revision_ratio and at least
   threshold.bar_integrity.revision_ratio_min_stored rows are stored (a fetcher tail window
   holds about 78 5m bars and IBKR restates recent bars, so a small window is written and
   recorded, never refused);
4. otherwise write the new rows and the changed rows (through the callbacks the bar table's own
   writer module supplies, so each bar table keeps one INSERT owner), record the old values of
   changed rows in ohlcv_revision and one ohlcv_load row per series (source = the chunk's row vendor).

Everything runs on the caller's cursor, so the caller's one transaction covers the request rows,
the bars, the load record and the coverage update. This module owns the INSERTs into ohlcv_load
and ohlcv_revision for source ibkr and reads the bar tables; it owns no bar-table write.

A refused chunk raises RevisionRefused. The persist helper rolls the chunk back, then records the
request rows and the refused load row (record_refused_load) in a second transaction, so the item
fails loudly and the refusal is a finding, never a silent drop.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from src.intelligence.bars.write_contract import (
    BarValues,
    WriteDelta,
    classify,
    revision_ratio,
    should_refuse,
)

LOAD_SOURCE = "ibkr"
# ohlcv_load.caller of an ingress chunk written outside a fetch context that names its own.
DEFAULT_CALLER = "ibkr-history-fetch"
DESTINATION_GRID = "market_data_ohlcv"
DESTINATION_ARCHIVE = "archive"
OUTCOME_APPLIED = "applied"
OUTCOME_REFUSED = "refused"

# destination -> the bar table the stored rows are read from (a fixed map, never caller text).
_STORED_TABLES = {
    DESTINATION_GRID: "market_data_ohlcv",
    DESTINATION_ARCHIVE: "ohlcv_intraday_raw_archive",
}

MAX_RATIO_KEY = "threshold.bar_integrity.max_revision_ratio"
MIN_STORED_KEY = "threshold.bar_integrity.revision_ratio_min_stored"

_REVISION_BATCH = 1000
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
    "origin",
)

# Bar row layout shared by market_data_ohlcv 9-tuples and archive 10-tuples.
_TS, _SYMBOL, _TIMEFRAME, _OPEN, _HIGH, _LOW, _CLOSE, _VOLUME, _SOURCE = range(9)

_INSERT_LOAD_SQL = (
    "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, "
    "outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, destination, "
    "n_unchanged, n_removed, n_archived) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

# The grid table's write shape, shared by every ingress caller (todo 301 promotes the
# fetcher's private copies onto these; new writers use these directly). New rows INSERT
# (tail=""); a changed row is rewritten by the full-row upsert tail, never DO NOTHING
# (CI: the no-first-write-wins fence), because the contract has already classified the
# chunk and recorded the old values in ohlcv_revision.
MARKET_DATA_INSERT_HEAD = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
)
MARKET_DATA_UPSERT_TAIL = (
    " ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source"
)
_MARKET_DATA_ROW_PLACEHOLDERS = "(%s, %s, %s, %s, %s, %s, %s, %s, %s)"


def write_market_data_batches(cur: Any, rows: list[tuple], *, tail: str = "") -> None:
    """Batched parameterized write of grid 9-tuples: MARKET_DATA_INSERT_HEAD, the
    placeholder rows, then `tail` (MARKET_DATA_UPSERT_TAIL for rewrites)."""
    for start in range(0, len(rows), 1000):
        chunk = rows[start : start + 1000]
        values = ",".join([_MARKET_DATA_ROW_PLACEHOLDERS] * len(chunk))
        cur.execute(
            MARKET_DATA_INSERT_HEAD + values + tail, [value for row in chunk for value in row]
        )


@dataclass(frozen=True)
class ContractParams:
    """The two APR thresholds the refusal reads."""

    max_ratio: float
    min_stored: int


@dataclass(frozen=True)
class SeriesLoad:
    """One series' write record: what a chunk offered and what the contract found."""

    symbol: str
    timeframe: str
    destination: str
    caller: str
    source: str
    n_bars: int
    n_stored: int
    n_new: int
    n_changed: int
    n_unchanged: int
    first_bar: date
    last_bar: date


class RevisionRefused(RuntimeError):  # noqa: N818 - the plan and design name this refusal
    """A chunk revised more than the allowed share of the rows it overlaps; nothing was
    written to the destination. The offered rows ride on the refusal (`rows`) so the raw
    archive can capture them (todo 528): vendor-served observations are never dropped,
    canonical authoring is."""

    def __init__(
        self, load: SeriesLoad, *, ratio: float, max_ratio: float, rows: list[tuple] | None = None
    ) -> None:
        self.load = load
        self.ratio = ratio
        self.max_ratio = max_ratio
        self.rows = rows or []
        super().__init__(
            f"revision refused for {load.symbol} {load.timeframe} ({load.destination}): "
            f"{load.n_changed} of {load.n_stored} stored rows changed "
            f"(ratio {ratio:.4f} > {max_ratio:.4f}); {load.n_new} new, {load.n_unchanged} unchanged"
        )

    @property
    def detail(self) -> str:
        return (
            f"refused: changed {self.load.n_changed} / stored {self.load.n_stored} = "
            f"{self.ratio:.4f} > max {self.max_ratio:.4f}; new {self.load.n_new}, "
            f"unchanged {self.load.n_unchanged}"
        )


def read_params(cur: Any) -> ContractParams:
    """Read the refusal thresholds from config_state; a missing key is a loud error."""
    cur.execute(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
        ([MAX_RATIO_KEY, MIN_STORED_KEY],),
    )
    values = {key: value for key, value in cur.fetchall()}
    missing = {MAX_RATIO_KEY, MIN_STORED_KEY} - set(values)
    if missing:
        raise RuntimeError(
            f"write contract thresholds missing from config_state: {sorted(missing)}"
        )
    return ContractParams(
        max_ratio=float(values[MAX_RATIO_KEY]), min_stored=int(float(values[MIN_STORED_KEY]))
    )


def _values(row: Sequence[Any]) -> BarValues:
    return (
        row[_OPEN],
        row[_HIGH],
        row[_LOW],
        row[_CLOSE],
        row[_VOLUME],
        row[_SOURCE],
    )


def read_stored(
    cur: Any, destination: str, symbol: str, timeframe: str, timestamps: list[datetime]
) -> dict[datetime, BarValues]:
    """The stored values of one series at the given timestamps."""
    table = _STORED_TABLES[destination]
    cur.execute(
        f'SELECT "timestamp", open, high, low, close, volume, source FROM {table} '
        'WHERE symbol = %s AND timeframe = %s AND "timestamp" = ANY(%s)',
        (symbol, timeframe, timestamps),
    )
    return {row[0]: (row[1], row[2], row[3], row[4], row[5], row[6]) for row in cur.fetchall()}


def _utc_date(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


def _record_load(
    cur: Any,
    load: SeriesLoad,
    *,
    outcome: str,
    detail: str | None,
    load_id: uuid.UUID,
    n_archived: int = 0,
) -> None:
    cur.execute(
        _INSERT_LOAD_SQL,
        (
            load_id,
            load.symbol,
            load.timeframe,
            load.source,
            load.first_bar,
            load.last_bar,
            outcome,
            load.n_bars,
            0 if outcome == OUTCOME_REFUSED else load.n_new,
            0 if outcome == OUTCOME_REFUSED else load.n_changed,
            load.first_bar,
            load.last_bar,
            detail,
            load.caller,
            load.destination,
            0 if outcome == OUTCOME_REFUSED else load.n_unchanged,
            0,
            n_archived,
        ),
    )


def record_refused_load(cur: Any, refusal: RevisionRefused, *, n_archived: int) -> None:
    """The refused chunk's ohlcv_load row (outcome refused, detail with the ratio and counts).

    `n_archived` is required (no silent zero): the count of the refusal's served rows the
    caller routed to the raw archive in the same transaction (todo 528, 0 only when the
    refusal carried no rows), so the completeness check never counts an archived refusal
    as loss and a catch site cannot forget the pairing."""
    _record_load(
        cur,
        refusal.load,
        outcome=OUTCOME_REFUSED,
        detail=refusal.detail,
        load_id=uuid.uuid4(),
        n_archived=n_archived,
    )


def _record_revisions(cur: Any, load_id: uuid.UUID, load: SeriesLoad, delta: WriteDelta) -> None:
    rows = [
        (
            load_id,
            load.symbol,
            load.timeframe,
            ts,
            old[0],
            old[1],
            old[2],
            old[3],
            old[4],
            old[5],
            "load",
        )
        for ts, (_new, old) in sorted(delta.changed.items())
    ]
    placeholder = "(" + ",".join(["%s"] * len(_REVISION_COLUMNS)) + ")"
    for i in range(0, len(rows), _REVISION_BATCH):
        batch = rows[i : i + _REVISION_BATCH]
        cur.execute(
            f"INSERT INTO ohlcv_revision ({', '.join(_REVISION_COLUMNS)}) VALUES "
            + ",".join([placeholder] * len(batch)),
            [value for row in batch for value in row],
        )


WriteRows = Callable[[Any, list[tuple]], None]


def apply_ingress_contract(
    cur: Any,
    rows: list[tuple],
    *,
    destination: str,
    caller: str,
    write_new: WriteRows,
    write_changed: WriteRows,
    params: ContractParams | None = None,
    waived: bool = False,
) -> int:
    """Apply the write contract to one chunk and return the number of rows offered.

    `write_new` and `write_changed` receive the full row tuples (one per key, last occurrence
    wins) and perform the bar table's own INSERT and upsert. Raises RevisionRefused, before any
    write, when any series in the chunk breaches the refusal.

    Each chunk's ohlcv_load row records one vendor: the `source` column of the row tuples
    (index _SOURCE), derived here rather than passed, so a load can never be labeled by a
    caller knob that disagrees with the bars it carries. A chunk spanning vendors is refused
    loudly.

    `waived` is the caller's statement that a recorded corporate action explains the revision
    (the fetcher's escalation re-fetch after a split, plan 189-10; the same waiver D2 applies):
    nothing is refused, every changed row is still recorded in ohlcv_revision, and the load
    row's detail names the waiver.
    """
    if not rows:
        return 0
    if destination not in _STORED_TABLES:
        raise ValueError(f"unknown ingress destination {destination!r}")
    params = params or read_params(cur)

    by_series: dict[tuple[str, str], dict[datetime, tuple]] = defaultdict(dict)
    for row in rows:
        by_series[(row[_SYMBOL], row[_TIMEFRAME])][row[_TS]] = row

    plans: list[tuple[SeriesLoad, WriteDelta, dict[datetime, tuple]]] = []
    for (symbol, timeframe), keyed in sorted(by_series.items()):
        vendors = {row[_SOURCE] for row in keyed.values()}
        if len(vendors) > 1:
            raise ValueError(
                f"chunk for {symbol!r} {timeframe!r} spans sources {sorted(vendors)}; "
                "split it by vendor so the ohlcv_load row names the true writer"
            )
        source = vendors.pop()
        incoming = {ts: _values(row) for ts, row in keyed.items()}
        stored = read_stored(cur, destination, symbol, timeframe, sorted(incoming))
        delta = classify(incoming, stored)
        stamps = sorted(incoming)
        load = SeriesLoad(
            symbol=symbol,
            timeframe=timeframe,
            destination=destination,
            caller=caller,
            source=source,
            n_bars=len(incoming),
            n_stored=len(stored),
            n_new=len(delta.new),
            n_changed=len(delta.changed),
            n_unchanged=delta.unchanged,
            first_bar=_utc_date(stamps[0]),
            last_bar=_utc_date(stamps[-1]),
        )
        if should_refuse(
            delta, len(stored), params.max_ratio, min_stored=params.min_stored, waived=waived
        ):
            raise RevisionRefused(
                load,
                ratio=revision_ratio(delta, len(stored)),
                max_ratio=params.max_ratio,
                rows=[keyed[ts] for ts in stamps],
            )
        plans.append((load, delta, keyed))

    for load, delta, keyed in plans:
        load_id = uuid.uuid4()
        detail = (
            f"waived: recorded corporate action; changed {load.n_changed} / stored "
            f"{load.n_stored}"
            if waived
            else None
        )
        _record_load(cur, load, outcome=OUTCOME_APPLIED, detail=detail, load_id=load_id)
        if delta.changed:
            _record_revisions(cur, load_id, load, delta)
        if delta.new:
            write_new(cur, [keyed[ts] for ts in sorted(delta.new)])
        if delta.changed:
            write_changed(cur, [keyed[ts] for ts in sorted(delta.changed)])
    return len(rows)
