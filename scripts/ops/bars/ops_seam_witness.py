"""Seam witness: is a series continuous by LEVEL across a vendor seam? (todo 600, step 7 check a).

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 8 step 7, amendment (a)
(the 2016-01-04 seam, Massive 2015 into Alpaca 2016) and section 8b (the archive-end seam);
runbook docs/operations/massive-step7-runbook.md. Read-only.

The reference is Massive's own raw series (1d `sip_flat`, 5m `sip_flat_agg`) on the split-adjusted
basis selection uses (split_rescale.scales_for_sessions over splits_known_at(now)), the one
series that runs straight through every seam. The incoming series is canonical (default) or one
raw (vendor, kind) as served (`--incoming raw:alpaca/sip_rth`, for a seam where canonical has
no Massive on one side). Per name, log k = ln(incoming / reference) on common bars (1d: by
session date; 5m: by stamp), its median over the last `--sessions` sessions before the seam and
the first `--sessions` from it on: the 592 rule, level over the span, never the junction step.

Verdicts (level_seams.span_verdict, then the split reading):

- canonical_matches_massive: both spans at the reference level (|log k| <= level tolerance).
- reconciled_split: an off span sits exactly one contiguous run of the name's recorded splits
  away (an Alpaca capture-epoch seam or a split missing on one side): listed with the factor.
- one_sided: one span has no common bar (the seam's far side has no reference or no incoming
  bar); the near side's level is reported.
- unexplained: anything else. The gate: zero unexplained on split-free names; every other row is
  for the disagreement ledger (design 8a).

The level tolerance is design 8a's scale-factor bound (10 bp on the median log ratio), a
definition recorded in the report, not a tunable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from services.bar_selection import read_split_rows  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.integrity_checks import run_products  # noqa: E402
from src.intelligence.bars.level_seams import span_verdict  # noqa: E402
from src.intelligence.bars.selection import session_date  # noqa: E402
from src.intelligence.bars.split_rescale import (  # noqa: E402
    SplitFactor,
    scales_for_sessions,
    splits_known_at,
)

LEVEL_TOL = 0.001  # design 8a scale factor: median log close ratio within 10 bp
REFERENCE_KIND = {"1d": "sip_flat", "5m": "sip_flat_agg"}
_CALENDAR_DAYS_PER_SESSION = 1.6  # read window padding, not a judgement threshold

_CANONICAL_SQL = """
SELECT "timestamp", close FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s AND "timestamp" < %s
"""
_RAW_SQL = """
SELECT "timestamp", close FROM ohlcv_raw
WHERE symbol = %s AND timeframe = %s AND vendor = %s AND kind = %s
  AND "timestamp" >= %s AND "timestamp" < %s
"""
_NAMES_SQL = """
SELECT DISTINCT symbol FROM ohlcv_raw
WHERE timeframe = %s AND vendor = 'massive' AND kind = %s AND "timestamp" >= %s
  AND "timestamp" < %s
ORDER BY symbol
"""


@dataclass(frozen=True)
class SeamRow:
    symbol: str
    verdict: str
    log_k_before: float | None
    log_k_after: float | None
    n_before: int
    n_after: int
    factor: float | None = None


def judge(
    symbol: str,
    before: Sequence[float],
    after: Sequence[float],
    split_factors: Sequence[float],
    level_tol: float = LEVEL_TOL,
) -> SeamRow:
    """One name's seam verdict from its log k values either side (module docstring). Pure."""
    kb = statistics.median(before) if before else None
    ka = statistics.median(after) if after else None
    levels = (kb, ka, len(before), len(after))
    if kb is None or ka is None:
        return SeamRow(symbol, "one_sided", *levels)
    reading = span_verdict(kb, ka, level_tol)
    if reading == "canonical_matches_massive":
        return SeamRow(symbol, reading, *levels)
    off = [k for k in (kb, ka) if abs(k) > level_tol]
    for product in run_products(split_factors):
        for sign in (1.0, -1.0):
            if all(abs(k - sign * math.log(product)) <= level_tol for k in off):
                factor = product if sign > 0 else 1.0 / product
                return SeamRow(symbol, "reconciled_split", *levels, factor)
    return SeamRow(symbol, "unexplained", *levels)


def split_log_k(
    incoming: dict[object, float],
    reference: dict[object, float],
    session_of: dict[object, date],
    seam: date,
    sessions: int,
) -> tuple[list[float], list[float]]:
    """ln(incoming / reference) on common keys, the last `sessions` sessions before the seam and
    the first `sessions` from it on."""
    common = sorted(k for k in incoming.keys() & reference.keys() if incoming[k] > 0 < reference[k])
    days_before = sorted({session_of[k] for k in common if session_of[k] < seam})[-sessions:]
    days_after = sorted({session_of[k] for k in common if session_of[k] >= seam})[:sessions]
    keep_b, keep_a = set(days_before), set(days_after)

    def logs(days: set[date]) -> list[float]:
        return [math.log(incoming[k] / reference[k]) for k in common if session_of[k] in days]

    return logs(keep_b), logs(keep_a)


def _key(timeframe: str, ts: datetime, utc_date_stamp: bool) -> tuple[object, date]:
    """(join key, session date): 1d joins by session date (canonical and IBKR stamp 00:00 UTC,
    Massive and Alpaca midnight New York); 5m by stamp."""
    day = ts.astimezone(UTC).date() if utc_date_stamp else session_date(ts)
    return (day if timeframe == "1d" else ts), day


def _series(
    rows: Iterable[tuple[datetime, float]], timeframe: str, utc_date_stamp: bool
) -> tuple[dict[object, float], dict[object, date]]:
    values: dict[object, float] = {}
    days: dict[object, date] = {}
    for ts, close in rows:
        key, day = _key(timeframe, ts, utc_date_stamp)
        values[key], days[key] = close, day
    return values, days


def witness_name(cur, args, symbol: str, lo: datetime, hi: datetime) -> SeamRow:
    tf = args.timeframe
    splits: list[SplitFactor] = splits_known_at(read_split_rows(cur, symbol), datetime.now(UTC))
    cur.execute(_RAW_SQL, (symbol, tf, "massive", REFERENCE_KIND[tf], lo, hi))
    ref, ref_days = _series(cur.fetchall(), tf, utc_date_stamp=False)
    scales = scales_for_sessions(set(ref_days.values()), splits)
    ref = {k: v / scales[ref_days[k]] for k, v in ref.items()}
    if args.incoming == "canonical":
        cur.execute(_CANONICAL_SQL, (symbol, tf, lo, hi))
        utc_stamp = tf == "1d"
    else:
        vendor, kind = args.incoming.removeprefix("raw:").split("/")
        cur.execute(_RAW_SQL, (symbol, tf, vendor, kind, lo, hi))
        utc_stamp = tf == "1d" and vendor == "ibkr"
    inc, inc_days = _series(cur.fetchall(), tf, utc_date_stamp=utc_stamp)
    before, after = split_log_k(inc, ref, {**ref_days, **inc_days}, args.seam, args.sessions)
    factors = [s.factor for s in sorted(splits, key=lambda s: s.effective_date)]
    return judge(symbol, before, after, factors)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seam", type=date.fromisoformat, required=True)
    parser.add_argument("--timeframe", choices=sorted(REFERENCE_KIND), default="1d")
    parser.add_argument("--incoming", default="canonical", help="canonical or raw:VENDOR/KIND")
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--out", type=Path, required=True, help="CSV; a .json summary beside it")
    args = parser.parse_args(argv)
    pad = timedelta(days=int(args.sessions * _CALENDAR_DAYS_PER_SESSION) + 10)
    lo = datetime.combine(args.seam - pad, datetime.min.time(), UTC)
    hi = datetime.combine(args.seam + pad, datetime.min.time(), UTC)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    rows: list[SeamRow] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        if args.symbols:
            symbols = args.symbols
        else:
            cur.execute(_NAMES_SQL, (args.timeframe, REFERENCE_KIND[args.timeframe], lo, hi))
            symbols = [r[0] for r in cur.fetchall()]
        for symbol in symbols:
            rows.append(witness_name(cur, args, symbol, lo, hi))
        conn.rollback()
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]) if rows else ["symbol"]))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    counts = Counter(r.verdict for r in rows)
    summary = {
        "seam": args.seam.isoformat(),
        "timeframe": args.timeframe,
        "incoming": args.incoming,
        "sessions": args.sessions,
        "level_tol": LEVEL_TOL,
        "n_names": len(rows),
        "verdicts": dict(sorted(counts.items())),
        "unexplained": [r.symbol for r in rows if r.verdict == "unexplained"],
    }
    args.out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if not summary["unexplained"] else 1


if __name__ == "__main__":
    sys.exit(main())
