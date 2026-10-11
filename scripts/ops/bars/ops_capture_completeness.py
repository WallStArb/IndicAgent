"""Capture completeness check (todo 528 rule R6): served = authored + archived.

Reads the `ohlcv_load` ledger and the two stores and prints, per
(source, timeframe), whether every vendor-served bar is accounted for:
canonical rows (grid destination) plus raw-archive rows (archive
destination) plus explicit refusals must cover the served count. Zero
`unexplained` is the invariant; nonzero rows mean bars reached the floor
somewhere and name the (source, timeframe) to investigate.

Caveats the report carries rather than hides: a revision-refused chunk's
served rows are captured by the raw archive (todo 528) and the archived
count rides the refusal row's n_archived; `refused_bars` is the remainder a
refusal did not archive (rows the archive already held under another
source), separated from true loss; n_removed and re-loads make the ledger's
served count an upper bound, so the check is a monitor, not a proof.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import psycopg

from src.config.settings import get_settings

_LEDGER_SQL = """
SELECT source, timeframe, destination, outcome,
       sum(n_bars) AS served,
       sum(n_new + n_changed) AS written,
       sum(n_removed) AS removed,
       sum(n_archived) AS refused_archived
FROM ohlcv_load
WHERE caller NOT LIKE 'test-%'
GROUP BY source, timeframe, destination, outcome
"""

_STORE_SQL = """
SELECT source, timeframe, count(*) AS rows FROM {table} GROUP BY source, timeframe
"""


def _classify(report: pd.DataFrame) -> pd.DataFrame:
    """The pure arithmetic over the joined ledger-and-stores frame: the refused split and
    the unexplained loss. Module-level so the rule is testable without a database."""
    # A refused chunk's served rows are captured by the raw archive (todo 528) and the
    # count rides the refusal row's n_archived: it is neither loss nor refusal remainder.
    report["refused_bars"] = (
        report["served"] - report["written"] - report["removed"] - report["refused_archived"]
    ).clip(lower=0)
    # Negative raw deltas mean the ledger covers a shorter window than the store
    # (legacy/pre-448 corpus): loss is only ever served bars with no store row.
    raw_grid = (
        report["served"] - report["refused_bars"] - report["canonical"] - report["refused_archived"]
    )
    raw_arch = report["archive_served"] + report["refused_archived"] - report["archive"]
    report["preledger_rows"] = (-(raw_grid.clip(upper=0)) - raw_arch.clip(upper=0)).clip(lower=0)
    report["unexplained"] = raw_grid.clip(lower=0) + raw_arch.clip(lower=0)
    return report


def _build_report(
    ledger: pd.DataFrame, canonical: pd.DataFrame, archive: pd.DataFrame
) -> pd.DataFrame:
    """Join the ledger's buckets and the two stores into the frame `_classify` consumes.

    A refusal's n_archived is by nature cross-destination (refused grid rows land in the
    archive store), so refused grid rows form their own bucket joined in once, never a
    column of a destination partition that would drop it. An archive-destination refusal
    is not in the bucket: its served bars already count in archive_served and its
    upserted rows return to the same store, so the refused_archived adjustment would
    double-count it there (the rare legacy path stays visible in the ohlcv_load ledger)."""
    stores = canonical.join(archive, how="outer")
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
    refused = (
        ledger[(ledger["outcome"] == "refused") & (ledger["destination"] == "market_data_ohlcv")]
        .groupby(["source", "timeframe"])[["refused_archived"]]
        .sum()
    )
    report = stores.join(grid, how="outer").join(arch, how="outer").join(refused, how="outer")
    report = report.fillna(0)
    for col in (
        "served",
        "written",
        "removed",
        "refused_archived",
        "archive_served",
        "canonical",
        "archive",
    ):
        report[col] = report[col].astype("int64")
    return _classify(report)


def _report(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(_LEDGER_SQL)
        ledger = pd.DataFrame(
            cur.fetchall(),
            columns=[
                "source",
                "timeframe",
                "destination",
                "outcome",
                "served",
                "written",
                "removed",
                "refused_archived",
            ],
        )
        frames = []
        for table, label in (
            ("market_data_ohlcv", "canonical"),
            ("ohlcv_intraday_raw_archive", "archive"),
        ):
            cur.execute(_STORE_SQL.format(table=table))
            df = pd.DataFrame(cur.fetchall(), columns=["source", "timeframe", label])
            frames.append(df.set_index(["source", "timeframe"]))
    return _build_report(ledger, frames[0], frames[1]).reset_index()


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
