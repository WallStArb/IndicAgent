"""Screen feature_vectors_v2 for constant and all-NULL columns per timeframe (todo 564,
done-when 3): a dead column, one that carries no information on a timeframe, is named when
it appears in a stage's output instead of reading as real to the S0 read.

The screened columns are the registry's numeric feature columns
(`feature_vectors_v2_numeric_columns`). Each column is judged per name: on a name it is dead
when it is all NULL, has no finite value (all NaN or infinite), or holds one value across its
finite rows (NaN warmup rows and infinities do not make a constant column live). A column dead
on every screened name of a timeframe is named dead; one dead on some names is listed as
partial with the name count (a pooled screen would hide both a column broken on most names and
one constant within each name at a different level). The control canary_constant must hold its
declared value on every name; it is named only where it does not. Names with fewer than
--min-name-rows rows on a timeframe are not judged (any column is constant on one row).

The screen is one pass grouped by (tf, symbol) with count/min/max per column (no per-column
scan, no sort), serial so it never adds parallel workers beside a rebuild, in one snapshot with
no statement timeout. --tf and --symbol filters are served by the primary key
(symbol, tf, bar_ts) through Postgres 18 skip scan while the chunks are uncompressed; with no
--tf the pass reads the whole hypertable, so run that after the rebuild stops writing.

Run: .venv/bin/python scripts/ops/ops_feature_column_screen.py [--min-rows 1000]
     [--min-name-rows 252] [--tf 1d ...] [--symbol SPY ...]
Output: a JSON report under logs/ and the named columns on stdout. Exit 0 when no column is
dead, 1 when any column is dead on a timeframe, 2 when nothing was screened or a requested
--tf was missing or below --min-rows, so the completion record can gate on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path

import psycopg
from psycopg import IsolationLevel, sql

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.intelligence.features.feature_vector_persistence import (  # noqa: E402
    feature_vectors_v2_numeric_columns,
)
from src.intelligence.features.kernels.control import _CANARY_CONSTANT_VALUE  # noqa: E402

DECLARED_CONSTANTS = {"canary_constant": _CANARY_CONSTANT_VALUE}
REPORT_DIR = project_root / "logs"
STATS_PER_COLUMN = 4  # non-null count, finite count, finite min, finite max
COLUMNS_PER_PASS = 400  # 4 x 400 + 3 stays under Postgres's 1,664-entry target-list cap


def classify(non_null: int, finite: int, low: float | None, high: float | None) -> str | None:
    """Name why a column is dead on one name, or None when it carries information."""
    if non_null == 0:
        return "all_null"
    if finite == 0:
        return "no_finite"
    if low == high:
        return "constant"
    return None


def judge(column: str, non_null: int, finite: int, low, high) -> str | None:
    """classify(), except a declared constant is dead only when it does not hold its value."""
    why = classify(non_null, finite, low, high)
    if column not in DECLARED_CONSTANTS or why in ("all_null", "no_finite"):
        return why
    held = non_null == finite and low == high == DECLARED_CONSTANTS[column]
    return None if held else f"not_declared_constant ({low}..{high})"


def screen_rows(
    columns: tuple[str, ...], rows: list[tuple], min_rows: int, min_name_rows: int
) -> tuple[dict[str, dict], dict[str, int]]:
    """Roll the per-(tf, symbol) rows (tf, symbol, row count, then STATS_PER_COLUMN per column)
    up to a per-timeframe report, and the timeframes skipped below min_rows."""
    by_tf: dict[str, list[tuple]] = defaultdict(list)
    for tf, _symbol, n_rows, *stats in rows:
        by_tf[tf].append((n_rows, stats))
    report: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    for tf, names in sorted(by_tf.items()):
        n_rows = sum(n for n, _ in names)
        if n_rows < min_rows:
            skipped[tf] = n_rows
            continue
        judged = [stats for n, stats in names if n >= min_name_rows]
        reasons: dict[str, Counter] = defaultdict(Counter)
        for stats in judged:
            per_column = batched(stats, STATS_PER_COLUMN, strict=True)
            for column, column_stats in zip(columns, per_column, strict=True):
                why = judge(column, *column_stats)
                if why:
                    reasons[column][why] += 1
        dead = {c: dict(r) for c, r in reasons.items() if r.total() == len(judged)}
        partial = {c: dict(r) for c, r in reasons.items() if c not in dead}
        report[tf] = {
            "n_rows": n_rows,
            "n_names": len(names),
            "n_names_judged": len(judged),
            "dead": dict(sorted(dead.items())),
            "partial": dict(sorted(partial.items())),
        }
    return report, skipped


def _query(columns: tuple[str, ...], where: sql.Composable) -> sql.Composed:
    finite = "{c} > '-Infinity' AND {c} < 'Infinity'"  # NaN sorts above Infinity: excluded
    aggregates = sql.SQL(", ").join(
        sql.SQL(
            f"count({{c}}), count(*) FILTER (WHERE {finite}), "
            f"min({{c}}) FILTER (WHERE {finite}), max({{c}}) FILTER (WHERE {finite})"
        ).format(c=sql.Identifier(c))
        for c in columns
    )
    return sql.SQL(
        "SELECT tf, symbol, count(*), {aggs} FROM feature_vectors_v2{where} "
        "GROUP BY tf, symbol ORDER BY tf, symbol"
    ).format(aggs=aggregates, where=where)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-rows", type=int, default=1000, help="skip timeframes with fewer rows"
    )
    parser.add_argument(
        "--min-name-rows",
        type=int,
        default=252,
        help="do not judge a name with fewer rows on a timeframe",
    )
    parser.add_argument("--tf", action="append", help="restrict to these timeframes")
    parser.add_argument("--symbol", action="append", help="restrict to these symbols")
    args = parser.parse_args(argv)

    from src.config.settings import get_settings

    columns = feature_vectors_v2_numeric_columns()
    filters, params = [], []
    for key, values in (("tf", args.tf), ("symbol", args.symbol)):
        if values:
            filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(key)))
            params.append(values)
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(filters) if filters else sql.SQL("")

    rows_by_key: dict[tuple[str, str], list] = {}
    with psycopg.connect(get_settings().database_url) as conn:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ  # one snapshot for every pass
        conn.execute("SET max_parallel_workers_per_gather = 0")
        conn.execute("SET statement_timeout = 0")
        for part in batched(columns, COLUMNS_PER_PASS, strict=False):
            for tf, symbol, n_rows, *stats in conn.execute(_query(part, where), params):
                rows_by_key.setdefault((tf, symbol), [tf, symbol, n_rows]).extend(stats)
    rows = list(rows_by_key.values())
    report, skipped = screen_rows(columns, rows, args.min_rows, args.min_name_rows)

    for tf, n_rows in skipped.items():
        print(f"{tf}: {n_rows} rows, skipped (below --min-rows {args.min_rows})")
    for tf, entry in report.items():
        dead = ", ".join(entry["dead"]) or "none"
        print(
            f"{tf}: {entry['n_rows']} rows, {entry['n_names_judged']} of {entry['n_names']} "
            f"names judged; {len(entry['dead'])} of {len(columns)} dead: {dead}; "
            f"{len(entry['partial'])} partial (see report)"
        )
    missing = sorted(set(args.tf or ()) - set(report))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"feature_column_screen_{stamp}.json"
    payload = {
        "generated": stamp,
        "tf": args.tf,
        "symbols": args.symbol,
        "min_rows": args.min_rows,
        "min_name_rows": args.min_name_rows,
        "n_columns": len(columns),
        "skipped": skipped,
        "missing": missing,
        "report": report,
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True))
    print(f"report: {path}")
    if not report or missing:
        print(f"not screened: {missing or 'everything'}")
        return 2
    return 1 if any(r["dead"] for r in report.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
