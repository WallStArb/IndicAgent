"""The canonical summary card: counts and content digests before a drop, compared after a rebuild.

Massive admission step 7 (docs/plans/2026-11-10-massive-admission-db-design.md section 8 step 7;
runbook docs/operations/massive-step7-runbook.md). Derived data is dropped only after its card
exists (the unified design's cache rule); the card is also the pre-image the rebuild is proven
against where ops_selection_gate does not reach (1d, 15m, 1h are derivation-owned).

--card OUT_DIR   read-only. One gzip CSV per timeframe of market_data_ohlcv, one row per
                 (symbol, vendor, kind, UTC month): the row count and an order-independent
                 content digest (the sum of 60-bit md5 prefixes of each row's exact bits:
                 epoch microseconds, float8send of open, high, low, close, volume or 'null'),
                 plus card.json: per (timeframe, vendor, kind) totals, the derived-row inventory
                 (DERIVED_COUNTS: what the deletion list may drop) and each file's sha256.
                 Mandatory beside it: a physical export (every column, COPY CSV) of the
                 canonical 1d rows of every name whose latest 1d lineage_missing or
                 canonical_recompute verdict is red. Raw cannot rebuild those rows, so the
                 TRUNCATE loses them; the export is their only pre-image (CTVA and SCCO on
                 2026-11-11). card.json lists the red verdicts and the exported names.
--compare BEFORE AFTER --from YYYY-MM-01 [--to YYYY-MM-01] [--expected TF:SYMBOL ...]
                 file-only. Every (timeframe, symbol, vendor, kind, month) group inside
                 [from, to) must match in count and digest; exit 0 when identical, 1 otherwise,
                 with every differing group listed in the report (never a sample). A
                 difference on an --expected (timeframe, symbol), the pre-classified red
                 lineage names, is reported apart and does not fail the compare.

Only SELECT statements run (statement_timeout off for this session, one connection, one
timeframe at a time so the server's hash aggregate stays small).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from src.config.settings import get_settings  # noqa: E402

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
_FIELDS = ("timeframe", "symbol", "vendor", "kind", "month", "n", "digest")
_CARD_SQL = """
SELECT symbol, vendor, kind,
       to_char(date_trunc('month', "timestamp" AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS month,
       count(*) AS n,
       sum(('x' || left(md5(concat_ws('|',
           (extract(epoch FROM "timestamp") * 1000000)::bigint,
           encode(float8send(open), 'hex'), encode(float8send(high), 'hex'),
           encode(float8send(low), 'hex'), encode(float8send(close), 'hex'),
           coalesce(volume::text, 'null'))), 15))::bit(60)::bigint)::text AS digest
FROM market_data_ohlcv
WHERE timeframe = %s
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4
"""
# What the step 7 deletion list may drop or must rescope, counted on the card so a deletion
# is judged against numbers taken before anything moved (label -> read-only SQL).
DERIVED_COUNTS: Mapping[str, str] = {
    "bar_quality_flag by timeframe, rule, quarantine, before 2016-01-04": (
        "SELECT timeframe, rule, quarantine, (\"timestamp\" < '2016-01-04') AS pre_2016, "
        "count(*) FROM bar_quality_flag GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4"
    ),
    "bar_session_choice by timeframe, vendor, before 2016-01-04": (
        "SELECT timeframe, vendor, (session_date < '2016-01-04') AS pre_2016, count(*) "
        "FROM bar_session_choice GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
    ),
    "bar_content_digest_current by timeframe": (
        "SELECT timeframe, count(*), sum(n_rows) FROM bar_content_digest_current "
        "GROUP BY 1 ORDER BY 1"
    ),
    "market_regimes": "SELECT count(*) FROM market_regimes",
}
# The 1d verdicts that say raw cannot rebuild a name's canonical rows (D7, design section 6).
LINEAGE_CHECKS = ("lineage_missing", "canonical_recompute")
_RED_LINEAGE_SQL = """
SELECT subject, metric_name FROM (
  SELECT DISTINCT ON (subject, metric_name) subject, metric_name, passed
  FROM integrity_monitor
  WHERE monitor_type = 'bar_integrity' AND metric_name = ANY(%s) AND subject LIKE '%%|1d'
  ORDER BY subject, metric_name, evaluated_at DESC, passed ASC
) latest WHERE NOT passed ORDER BY 1, 2
"""
RED_EXPORT = "export_1d_red_lineage.csv.gz"
_EXPORT_SQL = (
    "COPY (SELECT * FROM market_data_ohlcv WHERE timeframe = '1d' AND symbol = ANY({}) "
    'ORDER BY symbol, "timestamp") TO STDOUT WITH (FORMAT csv, HEADER)'
)


def red_lineage(cur: Any) -> list[str]:
    """`SYMBOL|1d|check` of every latest red 1d lineage verdict."""
    cur.execute(_RED_LINEAGE_SQL, (list(LINEAGE_CHECKS),))
    return [f"{subject}|{check}" for subject, check in cur.fetchall()]


def export_red_lineage(cur: Any, path: Path, symbols: list[str]) -> tuple[int, str]:
    """COPY the named symbols' canonical 1d rows to a gzip CSV; (rows, sha256)."""
    sql = _EXPORT_SQL.format("ARRAY[" + ",".join(["%s"] * len(symbols)) + "]::text[]")
    raw = bytearray()
    with cur.copy(sql, symbols) as copy:
        for block in copy:
            raw += block
    payload = gzip.compress(bytes(raw), mtime=0)
    path.write_bytes(payload)
    lines = bytes(raw).count(b"\n")
    return max(lines - 1, 0), hashlib.sha256(payload).hexdigest()


def card_rows(cur: Any, timeframe: str) -> list[dict[str, Any]]:
    cur.execute(_CARD_SQL, (timeframe,))
    return [
        dict(zip(_FIELDS, (timeframe, s, v, k, m, int(n), d), strict=True))
        for s, v, k, m, n, d in cur.fetchall()
    ]


def write_csv_gz(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    """Write the rows (deterministic bytes: gzip mtime 0) and return the file's sha256."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = gzip.compress(buffer.getvalue().encode(), mtime=0)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def read_card(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("canonical_*.csv.gz")):
        with gzip.open(path, "rt", newline="") as handle:
            rows.extend({**r, "n": int(r["n"])} for r in csv.DictReader(handle))
    return rows


def totals(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    out: Counter[str] = Counter()
    for r in rows:
        out[f"{r['timeframe']}|{r['vendor']}|{r['kind']}"] += int(r["n"])
    return dict(sorted(out.items()))


def compare_cards(
    before: Iterable[Mapping[str, Any]],
    after: Iterable[Mapping[str, Any]],
    start: str,
    end: str | None,
    expected: Iterable[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Every group with start <= month < end: identical count and digest, or listed. A group on
    one side only is a difference (a vendor or kind change moves the key). Differences on an
    `expected` (timeframe, symbol) are listed apart and not counted."""

    def window(rows: Iterable[Mapping[str, Any]]) -> dict[tuple, tuple[int, str]]:
        return {
            (r["timeframe"], r["symbol"], r["vendor"], r["kind"], r["month"]): (
                int(r["n"]),
                r["digest"],
            )
            for r in rows
            if r["month"] >= start and (end is None or r["month"] < end)
        }

    b, a = window(before), window(after)
    allowed = set(expected)
    found = [
        {"key": list(key), "before": b.get(key), "after": a.get(key)}
        for key in sorted(b.keys() | a.keys())
        if b.get(key) != a.get(key)
    ]
    differences = [d for d in found if (d["key"][0], d["key"][1]) not in allowed]
    by_tf = dict(Counter(d["key"][0] for d in differences))
    return {
        "window": [start, end],
        "groups_before": len(b),
        "groups_after": len(a),
        "rows_before": sum(n for n, _ in b.values()),
        "rows_after": sum(n for n, _ in a.values()),
        "n_differences": len(differences),
        "differences_by_timeframe": by_tf,
        "differences": differences,
        "expected_differences": [d for d in found if (d["key"][0], d["key"][1]) in allowed],
    }


def _month_start(text: str) -> str:
    day = date.fromisoformat(text)
    if day.day != 1:
        raise argparse.ArgumentTypeError(f"{text}: the card's unit is a UTC month; pass YYYY-MM-01")
    return text


def run_card(out_dir: Path, timeframes: Iterable[str]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    meta: dict[str, Any] = {"started": datetime.now(UTC).isoformat(), "files": {}, "derived": {}}
    all_rows: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET TIME ZONE 'UTC'")
        for tf in timeframes:
            rows = card_rows(cur, tf)
            name = f"canonical_{tf}.csv.gz"
            meta["files"][name] = write_csv_gz(out_dir / name, rows)
            all_rows.extend(rows)
            print(f"{tf}: {len(rows)} groups, {sum(r['n'] for r in rows)} rows", flush=True)
        for label, sql in DERIVED_COUNTS.items():
            cur.execute(sql)
            meta["derived"][label] = [[str(v) for v in row] for row in cur.fetchall()]
        red = red_lineage(cur)
        names = sorted({subject.split("|", 1)[0] for subject in red})
        n_rows, digest = export_red_lineage(cur, out_dir / RED_EXPORT, names) if names else (0, "")
        meta["red_lineage"] = {"verdicts": red, "exported_symbols": names, "rows": n_rows}
        if names:
            meta["files"][RED_EXPORT] = digest
        print(f"red 1d lineage verdicts: {red}; exported {n_rows} canonical 1d rows", flush=True)
        conn.rollback()
    meta["totals"] = totals(all_rows)
    meta["finished"] = datetime.now(UTC).isoformat()
    (out_dir / "card.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(json.dumps(meta["totals"], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--card", type=Path, metavar="OUT_DIR")
    mode.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--timeframes", nargs="+", default=list(TIMEFRAMES))
    parser.add_argument("--from", dest="start", type=_month_start, default=None)
    parser.add_argument("--to", dest="end", type=_month_start, default=None)
    parser.add_argument("--out", type=Path, default=None, help="--compare: report path")
    parser.add_argument(
        "--expected",
        nargs="*",
        default=[],
        metavar="TF:SYMBOL",
        help="--compare: pre-classified differences (the dispositioned red lineage names)",
    )
    args = parser.parse_args(argv)
    if args.card:
        return run_card(args.card, args.timeframes)
    if args.start is None:
        parser.error("--compare needs --from")
    before, after = (read_card(d) for d in args.compare)
    expected = [tuple(item.split(":", 1)) for item in args.expected]
    report = compare_cards(before, after, args.start, args.end, expected)
    out = args.out or args.compare[1] / f"compare_{args.start}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = {k: v for k, v in report.items() if k not in ("differences", "expected_differences")}
    summary["n_expected_differences"] = len(report["expected_differences"])
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"report: {out}")
    return 0 if report["n_differences"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
