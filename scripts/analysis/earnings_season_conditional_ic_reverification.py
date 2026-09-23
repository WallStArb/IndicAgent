#!/usr/bin/env python3
"""Re-verify RESEARCH.md Assumption A1 (Phase 176 Plan 01, Task 1) -- the claim that
`up_vol_body_diff`'s Spearman IC roughly doubles in earnings season (+0.0197 in-season
vs +0.0103 off-season) -- against the live corpus, on the CORRECTED 14-42-day window
(D-04). A prior research session attempted this and was blocked by an active
`decompress_chunk()` on `feature_vectors`; this script re-attempts the measurement with
a mandatory contention pre-check so it never compounds an in-progress corpus job.

Task 2 extends this module with a `--sweep` mode: the same in-season vs off-season
Spearman IC comparison applied across the entire 57-feature vol/volume family, with
BH-FDR correction applied exactly once across that fixed family
(`src.intelligence.statistics.ic_math.apply_bh_fdr`, this project's own primitive --
see `services/tag_calibrator.py`'s documented one-call-per-family convention), so the
result carries a stated multiple-comparisons denominator rather than an implied one.

Corrected earnings-season window (D-04, supersedes the origin todo's 0-42 day window):
in-season iff START_DAYS <= days_since_quarter_end <= END_DAYS, with START_DAYS=14,
END_DAYS=42 by default; quarter ends are Mar 31 / Jun 30 / Sep 30 / Dec 31.

SQL identifier safety is two independent mechanisms, both mandatory: (1) an allow-list
membership check via `_validated_identifier` -- rejection is by allow-list membership,
never by character filtering; (2) parameterized composition via `psycopg.sql.Identifier`
inside `psycopg.sql.SQL(...).format(...)`. Every SQL template in this module is a plain
string literal, never an f-string -- the `{feat}`-style placeholders are consumed by
`sql.SQL.format`, not by Python string interpolation. Non-identifier values (`--tf`, the
window bounds) are passed as `%s`/named query parameters, never interpolated.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Collection, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from src.intelligence.feature_factory import FeatureVector  # noqa: E402

# ---------------------------------------------------------------------------
# Pure window classifier -- the definition every later plan's production
# `_days_since_quarter_end`/`_earnings_season_flag` must match.
# ---------------------------------------------------------------------------

_QUARTER_END_MONTH_DAYS: tuple[tuple[int, int], ...] = ((3, 31), (6, 30), (9, 30), (12, 31))


def days_since_quarter_end(d: date) -> int:
    """Calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31),
    always >= 0. The quarter-end day itself returns 0. Pure function of `d` alone --
    no market-holiday table (matches this codebase's other calendar primitives).
    """
    quarter_ends = [
        date(y, m, day) for y in (d.year - 1, d.year) for m, day in _QUARTER_END_MONTH_DAYS
    ]
    last_qe = max(qe for qe in quarter_ends if qe <= d)
    return (d - last_qe).days


def is_earnings_season(d: date, start_days: int, end_days: int) -> bool:
    """True iff `d` falls START_DAYS-END_DAYS calendar days (inclusive on BOTH
    boundaries) after the most recent quarter end.
    """
    n = days_since_quarter_end(d)
    return start_days <= n <= end_days


# ---------------------------------------------------------------------------
# SQL identifier safety -- allow-list membership + psycopg.sql.Identifier.
# Both allow-lists are built by construction, never by hand.
# ---------------------------------------------------------------------------

_FEATURE_ALLOWLIST: frozenset[str] = frozenset(f.name for f in dataclasses.fields(FeatureVector))

_RETURN_COLUMN_CHOICES: tuple[str, ...] = (
    "return_fast",
    "return_mid",
    "return_slow",
    "return_extended",
)


def _validated_identifier(name: str, allowed: Collection[str]) -> sql.Identifier:
    """Return `name` as a `psycopg.sql.Identifier` iff it is a member of `allowed`.

    Raises ValueError naming the rejected value otherwise. Rejection is by
    allow-list membership only, never by character filtering -- a string that
    happens to contain no special characters but isn't in `allowed` is rejected
    exactly the same as one that does.
    """
    if name not in allowed:
        raise ValueError(f"rejected identifier not in allow-list: {name!r}")
    return sql.Identifier(name)


# ---------------------------------------------------------------------------
# DB connection + contention guard (Pitfall 5: corpus DB contention is real).
# ---------------------------------------------------------------------------


def _connect() -> Any:
    """Open a psycopg connection. Password is read from PGPASSWORD only -- never
    an argparse flag, never a literal in a SQL string (CLAUDE.md DB-access
    convention: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent).
    """
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        dbname=os.getenv("PGDATABASE", "indicagent"),
    )


_CONTENTION_QUERY = """
    SELECT pid, state, wait_event, query_start, query
    FROM pg_stat_activity
    WHERE state = 'active'
      AND (
          query ILIKE '%decompress_chunk%'
          OR query ILIKE '%compress_chunk%'
          OR query ILIKE '%autovacuum%'
      )
      AND (
          query ILIKE '%feature_vectors%'
          OR query ILIKE '%_timescaledb_internal._hyper_%'
      )
"""


def _check_contention(conn: Any) -> list[dict[str, Any]]:
    """Query pg_stat_activity for active decompress_chunk/compress_chunk/autovacuum
    backends against feature_vectors or its internal hypertable chunks. No
    operator-supplied value reaches this query -- it is a plain literal.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CONTENTION_QUERY)
        return list(cur.fetchall())


def _print_contention_block(rows: Sequence[dict[str, Any]]) -> None:
    print("CONTENTION DETECTED")
    for row in rows:
        print(
            f"  pid={row['pid']} state={row['state']} "
            f"wait_event={row['wait_event']} query_start={row['query_start']}"
        )


# ---------------------------------------------------------------------------
# Partition-and-score -- shared by the single-feature path (Task 1) and the
# family sweep (Task 2). Returns (ic, n) per partition, never logs per row.
# ---------------------------------------------------------------------------


def _spearman_ic_n(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    """Spearman IC and n for one (feature, partition) pair.

    NaN reported (not silently coerced to 0.0) for n<2 or a degenerate
    (zero-variance) input on either side -- an unmeasurable cell, not a
    genuine zero correlation.
    """
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    n = len(x)
    if n < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), n
    ic, _ = spearmanr(x, y)
    return float(ic), n


def _partition_and_score(
    bar_dates: Sequence[date],
    feature_vals: np.ndarray,
    return_vals: np.ndarray,
    start_days: int,
    end_days: int,
) -> tuple[tuple[float, int], tuple[float, int]]:
    """Partition rows by is_earnings_season and compute (ic, n) per partition.

    Returns ((in_season_ic, in_season_n), (off_season_ic, off_season_n)).
    """
    mask = np.array([is_earnings_season(d, start_days, end_days) for d in bar_dates], dtype=bool)
    in_partition = _spearman_ic_n(feature_vals[mask], return_vals[mask])
    off_partition = _spearman_ic_n(feature_vals[~mask], return_vals[~mask])
    return in_partition, off_partition


# ---------------------------------------------------------------------------
# Single-feature A1 verdict decision -- pure, no DB.
# ---------------------------------------------------------------------------


def _a1_verdict(in_ic: float, in_n: int, off_ic: float, off_n: int) -> str:
    """CONFIRMED when in-season |IC| >= 1.7x off-season |IC| and both n >= 1000;
    WEAKER when the ratio is in (1.1x, 1.7x) (including >= 1.7x with insufficient
    n on either side -- a real directional effect exists but n is too small to
    confirm with confidence); REFUTED when the ratio is <= 1.1x or the IC sign
    flips between partitions. BLOCKED is decided only on the contention-guard
    exit path in main(), never here.
    """
    if (
        np.isfinite(in_ic)
        and np.isfinite(off_ic)
        and in_ic != 0
        and off_ic != 0
        and np.sign(in_ic) != np.sign(off_ic)
    ):
        return "REFUTED"
    if not np.isfinite(in_ic) or not np.isfinite(off_ic):
        return "REFUTED"
    if off_ic == 0:
        ratio = float("inf") if in_ic != 0 else 1.0
    else:
        ratio = abs(in_ic) / abs(off_ic)
    if ratio >= 1.7 and in_n >= 1000 and off_n >= 1000:
        return "CONFIRMED"
    if ratio > 1.1:
        return "WEAKER"
    return "REFUTED"


# ---------------------------------------------------------------------------
# Single-feature corpus query + runner.
# ---------------------------------------------------------------------------

_SINGLE_FEATURE_TEMPLATE = sql.SQL("""
    SELECT fv.bar_ts, fv.{feat} AS feature_value, fr.{ret} AS return_value
    FROM feature_vectors fv
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol
        AND fr.tf = fv.tf
        AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE fv.tf = %(tf)s
      AND fv.{feat} IS NOT NULL
      AND fr.{ret} IS NOT NULL
    ORDER BY fv.bar_ts
    """)


def _run_single_feature(conn: Any, args: argparse.Namespace) -> None:
    feature_id = _validated_identifier(args.feature, allowed=_FEATURE_ALLOWLIST)
    return_id = _validated_identifier(args.return_column, allowed=set(_RETURN_COLUMN_CHOICES))
    query = _SINGLE_FEATURE_TEMPLATE.format(feat=feature_id, ret=return_id)
    print("Composed query (values not substituted):")
    print(query.as_string(conn))

    with conn.cursor() as cur:
        cur.execute(query, {"tf": args.tf})
        rows = cur.fetchall()

    if not rows:
        print(f"A1_VERDICT=REFUTED (no rows returned for feature={args.feature!r} tf={args.tf!r})")
        return

    bar_dates = [_as_date(r[0]) for r in rows]
    feature_vals = np.array([r[1] for r in rows], dtype=np.float64)
    return_vals = np.array([r[2] for r in rows], dtype=np.float64)

    (in_ic, in_n), (off_ic, off_n) = _partition_and_score(
        bar_dates, feature_vals, return_vals, args.start_days, args.end_days
    )
    verdict = _a1_verdict(in_ic, in_n, off_ic, off_n)

    ratio = abs(in_ic) / abs(off_ic) if off_ic not in (0, float("nan")) else float("nan")
    print(f"In-season IC: {in_ic!r} (n={in_n})")
    print(f"Off-season IC: {off_ic!r} (n={off_n})")
    print(f"Ratio (|in|/|off|): {ratio!r}")
    print(f"A1_VERDICT={verdict}")


def _as_date(bar_ts: Any) -> date:
    if isinstance(bar_ts, datetime):
        return bar_ts.date()
    if isinstance(bar_ts, date):
        return bar_ts
    raise TypeError(f"unexpected bar_ts type: {type(bar_ts)!r}")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-days", type=int, default=14)
    parser.add_argument("--end-days", type=int, default=42)
    parser.add_argument("--feature", default="up_vol_body_diff")
    parser.add_argument("--tf", default="1d")
    parser.add_argument("--return-column", default="return_fast", choices=_RETURN_COLUMN_CHOICES)
    parser.add_argument("--skip-contention-check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    conn = _connect()
    try:
        if not args.skip_contention_check:
            contention_rows = _check_contention(conn)
            if contention_rows:
                _print_contention_block(contention_rows)
                print("A1_VERDICT=BLOCKED")
                return 2
        _run_single_feature(conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
