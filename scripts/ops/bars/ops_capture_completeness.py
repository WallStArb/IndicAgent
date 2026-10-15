"""Capture completeness check (todo 528 rule R6, phase 191 plan 11): every served bar is in raw.

Reads the `ohlcv_load` ledger rows of destination `raw` and the raw plane (`ohlcv_raw`,
`ohlcv_revision`) and prints, per (source, timeframe), whether every vendor-served bar is
accounted for. Zero `unexplained` is the invariant; a nonzero row names the (source, timeframe)
to investigate. Four terms, each a loss or an unledgered write if nonzero:

- ledger_gap: served - (new + changed + unchanged + removed + superseded + refused_archived).
  Every served bar of a load is one of those outcomes (D-191-N: last-wins, nothing held).
- revision_gap: (changed + removed) - the load's ohlcv_revision rows of origin `raw`. A
  replaced or removed raw value is never dropped: its old value is in the revision log.
- lost_new: max(0, new - removed - current), where `current` counts raw rows whose last writer
  is a ledgered load. Each newly inserted key stays current unless a recorded removal took it.
- unledgered: max(0, current - new - changed). A raw row cannot carry a load_id the ledger
  never counted as a new or changed write (an unchanged re-serve does not move load_id).

One explained class, `restamped`: the one-time re-judgment of the retired refused loads
(caller refusal-rejudge-191, plan 191-07, tool deleted under D-191-N) restamped the served_at
and load_id of every row of each re-judged serve without changing a value; its n_bars counts
only the offers it judged. Rows a re-judge load last wrote are counted apart, and the upper
bound for them is relaxed to the restamp (their changed values are still in revision_gap).

The raw rows the plan 03 backfill wrote carry load_id NULL and predate the raw ledger: their
balance against the two old stores was checked when they were written (plans 03 and 04).
Ledger rows of the old destinations (d1, archive, vendor loads into market_data_ohlcv) are that
history and are not judged here; derived loads into market_data_ohlcv are not vendor serves.

`current` is counted per symbol from the small ledger (raw is compressed with segmentby symbol,
timeframe, vendor; every raw read filters all three), inside one repeatable-read snapshot so a
concurrent fetcher write lands on both sides or neither.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

import pandas as pd
import psycopg

from src.config.settings import get_settings

_LEDGER_SQL = """
SELECT l.source, l.timeframe,
       sum(l.n_bars) AS served,
       sum(l.n_new) AS new,
       sum(l.n_changed) AS changed,
       sum(coalesce(l.n_unchanged, 0)) AS unchanged,
       sum(l.n_removed) AS removed,
       sum(l.n_superseded) AS superseded,
       sum(l.n_archived) AS refused_archived,
       coalesce(sum(v.n), 0) AS revisions
FROM ohlcv_load l
LEFT JOIN (
    SELECT load_id, count(*) AS n FROM ohlcv_revision WHERE origin = 'raw' GROUP BY load_id
) v USING (load_id)
WHERE l.destination = 'raw' AND l.caller NOT LIKE 'test-%'
GROUP BY l.source, l.timeframe
"""

# The series whose raw rows a ledgered load last wrote, with the span to bound the chunk scan.
_SERIES_SQL = """
SELECT symbol, timeframe, source, caller = %(restamp)s, array_agg(load_id),
       min(first_bar), max(last_bar), sum(n_new + n_changed)
FROM ohlcv_load
WHERE destination = 'raw' AND caller NOT LIKE 'test-%%' AND n_new + n_changed > 0
GROUP BY symbol, timeframe, source, caller = %(restamp)s
"""

_CURRENT_SQL = """
SELECT count(*) FROM ohlcv_raw
WHERE symbol = %s AND timeframe = %s AND vendor = %s
  AND "timestamp" >= %s AND "timestamp" < %s
  AND load_id = ANY(%s)
"""

_RESTAMP_CALLER = "refusal-rejudge-191"

_COUNT_COLS = (
    "served",
    "new",
    "changed",
    "unchanged",
    "removed",
    "superseded",
    "refused_archived",
    "revisions",
    "current",
    "restamp_current",
    "restamp_written",
)


def _classify(report: pd.DataFrame) -> pd.DataFrame:
    """The pure arithmetic over the joined ledger-and-raw frame. Module-level so the rule is
    testable without a database."""
    report["ledger_gap"] = report["served"] - (
        report["new"]
        + report["changed"]
        + report["unchanged"]
        + report["removed"]
        + report["superseded"]
        + report["refused_archived"]
    )
    report["revision_gap"] = report["changed"] + report["removed"] - report["revisions"]
    report["lost_new"] = (
        report["new"] - report["removed"] - report["current"] - report["restamp_current"]
    ).clip(lower=0)
    report["unledgered"] = (
        report["current"] - (report["new"] + report["changed"] - report["restamp_written"])
    ).clip(lower=0)
    report["restamped"] = (report["restamp_current"] - report["restamp_written"]).clip(lower=0)
    report["unexplained"] = (
        report["ledger_gap"].abs()
        + report["revision_gap"].abs()
        + report["lost_new"]
        + report["unledgered"]
    )
    return report


def _build_report(ledger: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Join the ledger buckets and the current-row counts on (source, timeframe)."""
    report = ledger.set_index(["source", "timeframe"]).join(
        current.set_index(["source", "timeframe"]), how="outer"
    )
    report = report.fillna(0)
    for col in _COUNT_COLS:
        report[col] = report[col].astype("int64")
    return _classify(report)


def _report(conn: psycopg.Connection) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(_LEDGER_SQL)
        ledger = pd.DataFrame(cur.fetchall(), columns=["source", "timeframe", *_COUNT_COLS[:-3]])
        cur.execute(_SERIES_SQL, {"restamp": _RESTAMP_CALLER})
        series = cur.fetchall()
        counts: dict[tuple[str, str], list[int]] = {}
        for symbol, timeframe, source, restamp, load_ids, first, last, written in series:
            if first is None or last is None:
                raise SystemExit(f"raw load of {symbol} {timeframe} wrote bars but has no span")
            cur.execute(
                _CURRENT_SQL,
                (
                    symbol,
                    timeframe,
                    source,
                    first - timedelta(days=1),
                    last + timedelta(days=2),
                    load_ids,
                ),
            )
            bucket = counts.setdefault((source, timeframe), [0, 0, 0])
            n = int(cur.fetchone()[0])
            if restamp:
                bucket[1] += n
                bucket[2] += int(written)
            else:
                bucket[0] += n
    current = pd.DataFrame(
        [(s, tf, *b) for (s, tf), b in counts.items()],
        columns=["source", "timeframe", "current", "restamp_current", "restamp_written"],
    )
    return _build_report(ledger, current).reset_index()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="exit 1 when any unexplained row is nonzero (default: report only)",
    )
    args = parser.parse_args()

    with psycopg.connect(get_settings().database_url) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        report = _report(conn)
        conn.rollback()

    pd.set_option("display.width", 200)
    print(report.to_string(index=False))
    bad = report[report["unexplained"] != 0]
    if not bad.empty:
        print(f"UNEXPLAINED: {len(bad)} (source, timeframe) rows above")
        return 1 if args.gate else 0
    print("OK: every served raw bar is new, changed, unchanged, removed or superseded, and in raw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
