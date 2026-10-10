"""Capture completeness check (todo 528 rule R6): served = authored + archived.

Reads the `ohlcv_load` ledger and the two stores and prints, per
(source, timeframe), whether every vendor-served bar is accounted for:
canonical rows (grid destination) plus raw-archive rows (archive
destination) plus explicit refusals must cover the served count. Zero
`unexplained` is the invariant; nonzero rows mean bars reached the floor
somewhere and name the (source, timeframe) to investigate.

Caveats the report carries rather than hides: revision-refused grid chunks
are served-but-unstored until the engine routes them to the archive (todo
528 follow-up), so a `refused_bars` column separates them from true loss;
n_removed and re-loads make the ledger's served count an upper bound, so the
check is a monitor, not a proof.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import psycopg

from src.config.settings import get_settings

_LEDGER_SQL = """
SELECT source, timeframe, destination,
       sum(n_bars) AS served,
       sum(n_new + n_changed) AS written,
       sum(n_removed) AS removed
FROM ohlcv_load
WHERE caller NOT LIKE 'test-%'
GROUP BY source, timeframe, destination
"""

_STORE_SQL = """
SELECT source, timeframe, count(*) AS rows FROM {table} GROUP BY source, timeframe
"""


def _report(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(_LEDGER_SQL)
        ledger = pd.DataFrame(
            cur.fetchall(),
            columns=["source", "timeframe", "destination", "served", "written", "removed"],
        )
        frames = []
        for table, label in (
            ("market_data_ohlcv", "canonical"),
            ("ohlcv_intraday_raw_archive", "archive"),
        ):
            cur.execute(_STORE_SQL.format(table=table))
            df = pd.DataFrame(cur.fetchall(), columns=["source", "timeframe", label])
            frames.append(df.set_index(["source", "timeframe"]))
    stores = frames[0].join(frames[1], how="outer").fillna(0)

    grid = (
        ledger[ledger["destination"] == "market_data_ohlcv"]
        .groupby(["source", "timeframe"])[["served", "written", "removed"]]
        .sum()
    )
    arch = (
        ledger[ledger["destination"] == "archive"]
        .groupby(["source", "timeframe"])[["served"]]
        .sum()
        .rename(columns={"served": "archive_served"})
    )
    report = stores.join(grid, how="outer").join(arch, how="outer").fillna(0)
    for col in ("served", "written", "removed", "archive_served", "canonical", "archive"):
        report[col] = report[col].astype("int64")
    report["refused_bars"] = (report["served"] - report["written"] - report["removed"]).clip(
        lower=0
    )
    # Negative raw deltas mean the ledger covers a shorter window than the store
    # (legacy/pre-448 corpus): loss is only ever served bars with no store row.
    raw_grid = report["served"] - report["refused_bars"] - report["canonical"]
    raw_arch = report["archive_served"] - report["archive"]
    report["preledger_rows"] = (-(raw_grid.clip(upper=0)) - raw_arch.clip(upper=0)).clip(lower=0)
    report["unexplained"] = raw_grid.clip(lower=0) + raw_arch.clip(lower=0)
    return report.reset_index()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="exit 1 when any unexplained row is nonzero (default: report only)",
    )
    args = parser.parse_args()

    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        report = _report(conn)
    finally:
        conn.close()

    pd.set_option("display.width", 160)
    print(report.to_string(index=False))
    bad = report[report["unexplained"] != 0]
    if not bad.empty:
        print(f"UNEXPLAINED: {len(bad)} (source, timeframe) rows above")
        return 1 if args.gate else 0
    print("OK: every served bar is authored or archived (refusals separated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
