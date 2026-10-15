"""Ledger evidence of what a vendor load served (phase 191, third review of plan 191-07).

The ohlcv_load and ohlcv_request facts of one series and the exact stamps an applied vendor serve
answered (`served_ranges`): per-row lineage first, else the load's own bar count ending at the
asked end of the request it persisted, checked against its first and last UTC dates. A request
window is not a served range: IBKR counts a seconds duration in trading seconds, so its
`window_start` can begin hours after the first bar served (ADM af8b35f1: window 20:10 to 00:05,
bars 16:00 to 19:55).

Used by the one-time release of the held offers (ops_pending_release.py, D-191-N) to order a
held offer against the vendor's current raw value by serve time.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

# ohlcv_load callers that record values the ledgers already held (the raw backfill's
# reconstruction, the 191-07 repairs, the refusal re-judge and the held-offer release): never a
# vendor serve.
NON_SERVE_CALLERS = frozenset(
    {"raw-backfill-191", "raw-repair-191", "refusal-rejudge-191", "pending-release-191"}
)

Key = tuple[datetime, str, str]  # (timestamp, vendor, kind)

_LOADS_SQL = (
    "SELECT load_id, source, requested_start, requested_end, outcome, loaded_at, destination, "
    "caller, n_bars, n_new FROM ohlcv_load WHERE symbol = %s AND timeframe = %s"
)

_REQUESTS_SQL = (
    "SELECT source, window_start, window_end, answered_at FROM ohlcv_request "
    "WHERE symbol = %s AND timeframe = %s AND outcome = 'bars' AND window_start IS NOT NULL "
    "AND answered_at IS NOT NULL"
)

_RAW_LOADS_SQL = (
    'SELECT "timestamp", load_id FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s '
    "AND load_id IS NOT NULL"
)

_RAW_REQUESTS_SQL = (
    'SELECT r."timestamp", q.answered_at, q.source FROM ohlcv_raw r JOIN ohlcv_request q '
    "ON q.request_id = r.request_id WHERE r.symbol = %s AND r.timeframe = %s"
)


def utc_date(ts: datetime) -> date:
    """ohlcv_load.requested_start/end are the UTC dates of the load's first and last stamps."""
    return ts.astimezone(UTC).date()


@dataclass(frozen=True)
class LoadFact:
    """One ohlcv_load row of the series."""

    load_id: Any
    vendor: str
    first: date
    last: date
    outcome: str
    loaded_at: datetime
    destination: str
    caller: str
    n_bars: int | None = None
    n_new: int | None = None

    @property
    def is_serve(self) -> bool:
        return self.caller not in NON_SERVE_CALLERS


@dataclass(frozen=True)
class RequestFact:
    """One answered (`bars`) ohlcv_request row of the series."""

    vendor: str
    window_start: datetime
    window_end: datetime
    answered_at: datetime


def match_requests(
    loads: Iterable[LoadFact], requests: Iterable[RequestFact], match_s: float
) -> dict[Any, RequestFact]:
    """load_id -> the request it persisted: the latest answered request of the same vendor at
    most `match_s` seconds before the load (the retired path wrote no request id on the load;
    APR infra.selection_gate.request_load_match_s). A load with no such request is absent."""
    by_vendor: dict[str, list[RequestFact]] = defaultdict(list)
    for request in requests:
        by_vendor[request.vendor].append(request)
    answered: dict[str, list[datetime]] = {}
    for vendor, rows in by_vendor.items():
        rows.sort(key=lambda r: r.answered_at)
        answered[vendor] = [r.answered_at for r in rows]
    out: dict[Any, RequestFact] = {}
    tolerance = timedelta(seconds=match_s)
    for load in loads:
        stamps = answered.get(load.vendor)
        if not stamps:
            continue
        i = bisect.bisect_right(stamps, load.loaded_at) - 1
        if i >= 0 and load.loaded_at - stamps[i] <= tolerance:
            out[load.load_id] = by_vendor[load.vendor][i]
    return out


def vendor_keys_of(raw: Iterable[Key]) -> dict[str, list[datetime]]:
    """vendor -> its sorted raw stamps (any kind, deduplicated)."""
    out: dict[str, set[datetime]] = defaultdict(set)
    for ts, vendor, _kind in raw:
        out[vendor].add(ts)
    return {vendor: sorted(stamps) for vendor, stamps in out.items()}


def load_row_stamps(
    slot_loads: Mapping[datetime, set[Any]],
    loads: Iterable[LoadFact],
    requests: Iterable[RequestFact],
    request_rows: Iterable[tuple[datetime, datetime, str]],
    match_s: float,
) -> dict[Any, list[datetime]]:
    """load_id -> stamps the ledger ties to it: rows naming the load (`slot_loads`) and raw rows
    naming the request the load persisted (`request_rows`: (timestamp, answered_at, vendor))."""
    loads = list(loads)
    out: dict[Any, list[datetime]] = defaultdict(list)
    for ts, ids in slot_loads.items():
        for load_id in ids:
            out[load_id].append(ts)
    by_answer = {
        (request.vendor, request.answered_at): load_id
        for load_id, request in match_requests(loads, requests, match_s).items()
    }
    for ts, answered_at, vendor in request_rows:
        load_id = by_answer.get((vendor, answered_at))
        if load_id is not None:
            out[load_id].append(ts)
    return dict(out)


def served_ranges(
    loads: Iterable[LoadFact],
    requests: Iterable[RequestFact],
    vendor_keys: Mapping[str, Sequence[datetime]],
    match_s: float,
    *,
    row_stamps: Mapping[Any, Sequence[datetime]] | None = None,
    bar: timedelta = timedelta(minutes=5),
) -> dict[Any, tuple[datetime, datetime]]:
    """load_id -> [first served stamp, last served stamp + bar] of each applied vendor serve.

    Third review of plan 191-07, finding 1: a request window is not the served range. IBKR counts
    a seconds duration in trading seconds, so `window_start` (wall-clock end minus duration) can
    start hours after the first bar served (ADM af8b35f1: window 20:10 to 00:05, bars 16:00 to
    19:55). The range comes from the rows instead, in this order:
    1. `row_stamps`: stamps the ledger ties to the load (raw rows naming its load_id or its
       request_id, non-pending revision rows of the load); their first to last stamp.
    2. Legacy loads with no rows: the load's own `n_bars` vendor keys ending before the end of
       the request it persisted (`window_end` is the asked end, which is exact), accepted only
       when the first and last of those keys fall on the load's `first_bar` and `last_bar` UTC
       dates. A load with no matched request is accepted only when it is a single-date load
       whose bar count equals the vendor's keys on that date.
    A load none of these resolves has no range: nothing is claimed for it."""
    rows = row_stamps or {}
    matched = match_requests(loads, requests, match_s)
    out: dict[Any, tuple[datetime, datetime]] = {}
    for load in loads:
        if load.outcome != "applied" or not load.is_serve:
            continue
        stamps = rows.get(load.load_id)
        if stamps:
            out[load.load_id] = (min(stamps), max(stamps) + bar)
            continue
        n = load.n_bars or 0
        keys = vendor_keys.get(load.vendor, ())
        if n <= 0 or not keys:
            continue
        request = matched.get(load.load_id)
        if request is not None:
            i = bisect.bisect_left(keys, request.window_end)
            sel = keys[max(0, i - n) : i]
        elif load.first == load.last:
            day = [k for k in keys if utc_date(k) == load.first]
            sel = day if len(day) == n else []
        else:
            continue
        if len(sel) == n and utc_date(sel[0]) == load.first and utc_date(sel[-1]) == load.last:
            out[load.load_id] = (sel[0], sel[-1] + bar)
    return out


def read_loads(cur: Any, symbol: str, timeframe: str) -> list[LoadFact]:
    cur.execute(_LOADS_SQL, (symbol, timeframe))
    return [LoadFact(*row) for row in cur.fetchall()]
