"""ops_pending_release.py - release every held offer last-wins (owner decision D-191-N).

Owner decision 2026-10-14 (docs/plans/2026-10-12-unified-raw-bar-table-design.md, D-191-N): a
vendor's own re-serve always overwrites its raw value last-wins, the old value is logged, nothing
is held pending and there is no load-level refusal. This one-time pass ends the holds the retired
refusal left: every `pending` ohlcv_revision row (an offered value a refused load held).

Per (symbol, timeframe, vendor, kind) series, in one transaction under the raw series lock and
the selection lock:

1. Each held offer is timed at its serve: the answer time of the request its refused load
   persisted (_ledger_evidence.match_requests), else the load time.
2. The vendor's current raw value at the key is timed at its serve: the load that wrote it when
   that load is a vendor serve, else its served_at, else the latest applied vendor serve whose
   served range holds the key (_ledger_evidence.served_ranges), else unknown (older than any
   ledger record).
3. Latest answer wins. A held offer later than the raw value (or with no raw row) is written to
   raw through services/ohlcv_raw_writer.write_raw under a `pending-release-191` load (repair
   mode, served_at the offer's serve time): the displaced raw value is logged as a revision and
   the pending row is deleted (its value is the current raw row now). A held offer older than
   the raw value is a superseded answer: its pending row becomes an ordinary revision (origin
   raw), the value it would have replaced having been written later.
4. The sessions of the released keys are re-selected through services/bar_selection.py.

Every decision is itemized in the report (old raw value, offer, both serve times, source load).
Dry run by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from scripts.ops.bars import _ledger_evidence as ev  # noqa: E402
from scripts.ops.bars import ops_selection_gate as gate  # noqa: E402
from services.bar_selection import select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from services.ohlcv_raw_writer import RawRow, write_raw  # noqa: E402

CALLER = "pending-release-191"
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_SERIES_SQL = (
    "SELECT DISTINCT symbol, timeframe, vendor, kind FROM ohlcv_revision "
    "WHERE origin = 'pending' ORDER BY 1, 2, 3, 4"
)
_PENDING_SQL = (
    'SELECT v."timestamp", v.old_open, v.old_high, v.old_low, v.old_close, v.old_volume, '
    "v.load_id FROM ohlcv_revision v WHERE v.symbol = %s AND v.timeframe = %s "
    "AND v.vendor = %s AND v.kind = %s AND v.origin = 'pending'"
)
_RAW_AT_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, served_at, load_id FROM ohlcv_raw '
    'WHERE symbol = %s AND timeframe = %s AND vendor = %s AND kind = %s AND "timestamp" = ANY(%s)'
)
_VENDOR_KEYS_SQL = (
    'SELECT DISTINCT "timestamp" FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s '
    "AND vendor = %s ORDER BY 1"
)
_REVISION_LOADS_SQL = (
    'SELECT "timestamp", load_id FROM ohlcv_revision WHERE symbol = %s AND timeframe = %s '
    "AND origin <> 'pending'"
)
_DELETE_PENDING_SQL = (
    "DELETE FROM ohlcv_revision WHERE load_id = %s AND symbol = %s AND timeframe = %s "
    "AND \"timestamp\" = %s AND vendor = %s AND kind = %s AND origin = 'pending'"
)
_SUPERSEDE_PENDING_SQL = (
    "UPDATE ohlcv_revision SET origin = 'raw' WHERE load_id = %s AND symbol = %s "
    'AND timeframe = %s AND "timestamp" = %s AND vendor = %s AND kind = %s '
    "AND origin = 'pending'"
)
BAR = {"1m": timedelta(minutes=1), "5m": timedelta(minutes=5), "4h": timedelta(hours=4)}


@dataclass(frozen=True)
class Offer:
    ts: datetime
    values: tuple
    load_id: Any
    served_at: datetime  # when the vendor served the held value


@dataclass(frozen=True)
class Decision:
    offer: Offer
    raw: tuple | None
    raw_served: datetime | None  # None: unknown, older than any ledger record
    release: bool  # True: the offer is the latest answer and goes to raw


def decide(offers: Sequence[Offer], raw: Mapping[datetime, tuple], raw_served: Mapping) -> list:
    """Latest answer wins per key (module docstring, step 3). Pure."""
    out: list[Decision] = []
    by_key: dict[datetime, list[Offer]] = defaultdict(list)
    for offer in offers:
        by_key[offer.ts].append(offer)
    for ts, here in sorted(by_key.items()):
        latest = max(here, key=lambda o: o.served_at)
        current = raw.get(ts)
        served = raw_served.get(ts)
        for offer in here:
            wins = offer is latest and (
                current is None or served is None or offer.served_at > served
            )
            out.append(Decision(offer, current, served, wins))
    return out


def raw_serve_times(
    cur: Any,
    symbol: str,
    timeframe: str,
    vendor: str,
    raw: Mapping[datetime, tuple],
    loads: Sequence[ev.LoadFact],
    match_s: float,
) -> dict[datetime, datetime | None]:
    """timestamp -> when the vendor served the current raw value (module docstring, step 2)."""
    by_id = {load.load_id: load for load in loads}
    cur.execute(_VENDOR_KEYS_SQL, (symbol, timeframe, vendor))
    keys = [r[0] for r in cur.fetchall()]
    rows: dict[datetime, set[Any]] = defaultdict(set)
    cur.execute(ev._RAW_LOADS_SQL, (symbol, timeframe))
    for ts, load_id in cur.fetchall():
        rows[ts].add(load_id)
    cur.execute(_REVISION_LOADS_SQL, (symbol, timeframe))
    for ts, load_id in cur.fetchall():
        rows[ts].add(load_id)
    cur.execute(ev._REQUESTS_SQL, (symbol, timeframe))
    requests = [ev.RequestFact(*r) for r in cur.fetchall()]
    cur.execute(ev._RAW_REQUESTS_SQL, (symbol, timeframe))
    request_rows = cur.fetchall()
    ranges = ev.served_ranges(
        loads,
        requests,
        {vendor: keys},
        match_s,
        row_stamps=ev.load_row_stamps(rows, loads, requests, request_rows, match_s),
        bar=BAR.get(timeframe, timedelta(minutes=5)),
    )
    serves = sorted(
        (by_id[lid] for lid in ranges if by_id[lid].vendor == vendor), key=lambda x: x.loaded_at
    )
    bar = BAR.get(timeframe, timedelta(minutes=5))
    out: dict[datetime, datetime | None] = {}
    for ts, (_values, served_at, load_id) in raw.items():
        writer = by_id.get(load_id)
        if writer is not None and writer.is_serve and writer.outcome == "applied":
            out[ts] = writer.loaded_at
            continue
        if served_at is not None:
            out[ts] = served_at
            continue
        covering = [
            s for s in serves if ranges[s.load_id][0] <= ts and ts + bar <= ranges[s.load_id][1]
        ]
        out[ts] = covering[-1].loaded_at if covering else None
    return out


def release_series(
    conn: Any, series: tuple[str, str, str, str], params: Any, match_s: float, apply: bool
) -> dict[str, Any]:
    symbol, timeframe, vendor, kind = series
    with conn.cursor() as cur:
        cur.execute(_LOCK_SQL, ("|".join(series),))
        cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
        loads = ev.read_loads(cur, symbol, timeframe)
        cur.execute(ev._REQUESTS_SQL, (symbol, timeframe))
        requests = [ev.RequestFact(*r) for r in cur.fetchall()]
        matched = ev.match_requests(loads, requests, match_s)
        by_id = {load.load_id: load for load in loads}
        cur.execute(_PENDING_SQL, series)
        offers = []
        for ts, o, h, lo, c, v, load_id in cur.fetchall():
            request = matched.get(load_id)
            served = request.answered_at if request is not None else by_id[load_id].loaded_at
            offers.append(Offer(ts, (o, h, lo, c, v), load_id, served))
        stamps = sorted({o.ts for o in offers})
        cur.execute(_RAW_AT_SQL, (*series, stamps))
        raw = {r[0]: (tuple(r[1:6]), r[6], r[7]) for r in cur.fetchall()}
        raw_served = raw_serve_times(cur, symbol, timeframe, vendor, raw, loads, match_s)
    decisions = decide(offers, {ts: r[0] for ts, r in raw.items()}, raw_served)
    released = [d for d in decisions if d.release]
    superseded = [d for d in decisions if not d.release]
    report = {
        "series": list(series),
        "released": len(released),
        "released_new": sum(1 for d in released if d.raw is None),
        "superseded": len(superseded),
        "decisions": [
            {
                "timestamp": d.offer.ts.isoformat(),
                "offer": list(d.offer.values),
                "offer_load": str(d.offer.load_id),
                "offer_served_at": d.offer.served_at.isoformat(),
                "raw": None if d.raw is None else list(d.raw),
                "raw_served_at": None if d.raw_served is None else d.raw_served.isoformat(),
                "release": d.release,
            }
            for d in decisions
        ],
    }
    if not apply:
        return report
    load_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, "
            "requested_end, outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, "
            "caller, destination, n_unchanged, n_removed, n_archived) VALUES "
            "(%s, %s, %s, %s, %s, %s, 'applied', %s, %s, %s, %s, %s, %s, %s, 'raw', %s, 0, 0)",
            (
                load_id,
                symbol,
                timeframe,
                vendor,
                ev.utc_date(stamps[0]),
                ev.utc_date(stamps[-1]),
                len(released),
                sum(1 for d in released if d.raw is None),
                sum(1 for d in released if d.raw is not None and d.raw != d.offer.values),
                ev.utc_date(stamps[0]),
                ev.utc_date(stamps[-1]),
                "held offers released last-wins (D-191-N): "
                f"{len(released)} written, {len(superseded)} superseded by a later serve; "
                "source loads: " + ", ".join(sorted({str(d.offer.load_id)[:8] for d in released})),
                CALLER,
                sum(1 for d in released if d.raw == d.offer.values),
            ),
        )
    if released:
        rows = [
            RawRow(d.offer.ts, symbol, timeframe, vendor, kind, *d.offer.values) for d in released
        ]
        write_raw(
            conn,
            rows,
            load_id=load_id,
            request_id=None,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
            repair=True,
            served_at={d.offer.ts: d.offer.served_at for d in released},
        )
    with conn.cursor() as cur:
        for d in released:
            cur.execute(
                _DELETE_PENDING_SQL, (d.offer.load_id, symbol, timeframe, d.offer.ts, vendor, kind)
            )
        for d in superseded:
            cur.execute(
                _SUPERSEDE_PENDING_SQL,
                (d.offer.load_id, symbol, timeframe, d.offer.ts, vendor, kind),
            )
    if timeframe in BAR:
        result = select_and_write(
            conn,
            symbols=[symbol],
            timeframe=timeframe,
            start=min(stamps),
            end=max(stamps) + timedelta(microseconds=1),
            policy_rows=None,
            kind_order=params.kind_order,
            batch_rows=params.write.batch_rows,
        )
        report["canonical"] = {
            "new": result.new,
            "replaced": result.changed,
            "dropped": result.dropped,
            "sessions_fallback": result.sessions_fallback,
            "sessions_incomplete": result.sessions_incomplete,
        }
    report["release_load"] = str(load_id)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    _batch, timeout_s, match_s = asyncio.run(gate._read_apr())
    conn = gate.open_connection(timeout_s)
    reports: list[dict[str, Any]] = []
    totals: Counter = Counter()
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            cur.execute(_SERIES_SQL)
            series_list = [tuple(r) for r in cur.fetchall()]
        conn.rollback()
        for series in series_list:
            report = release_series(conn, series, params, match_s, args.apply)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            reports.append(report)
            totals.update(
                released=report["released"],
                released_new=report["released_new"],
                superseded=report["superseded"],
            )
            print(
                f"{series}: released {report['released']} (new {report['released_new']}), "
                f"superseded {report['superseded']} {report.get('canonical', '')}",
                flush=True,
            )
    finally:
        conn.close()
    payload = {
        "meta": {
            "mode": "apply" if args.apply else "dry-run",
            "generated": datetime.now(UTC).isoformat(),
        },
        "totals": dict(totals),
        "series": reports,
    }
    Path(args.out).write_text(json.dumps(payload, indent=1, default=str))
    print(json.dumps(payload["totals"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
