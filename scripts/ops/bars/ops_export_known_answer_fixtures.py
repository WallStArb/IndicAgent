#!/usr/bin/env python3
"""Export phase 185 known-answer bar fixtures to tests/fixtures/bars/ (read-only).

Phase 185 D-10 requires every scrubbing rule to be validated on known answers that live
in the repo, not in a session's scratchpad. This script captures those answers once from
the live database into CSV fixtures that pure-rule tests read without a database:

1. price_sanity_status_rows.csv -- every market_data_ohlcv row with a non-null
   price_sanity_status, all timeframes, plus each row's live prev_close/next_open
   neighbors (nearest traded bars around it in the tradeable view; empty at a series
   boundary). Raw-table read is required here: the tradeable view hides
   confirmed_corrupt rows, which are exactly the ones the fixture exists to preserve
   (plan 04 migrates these rows into bar_quality_flag). Plan 05's known-answer tests
   rebuild each row's three-bar window from the neighbor columns.
2. seam_candidates_mrna_alms.csv -- MRNA and ALMS 1d bars from 2026-07-01 through
   the latest stored date (D-24's first split-seam candidates).
3. spy_5m_2025_11_28_half_day.csv -- SPY 5m bars on the 2025-11-28 early close
   (session-anchored grid edge cases).
4. spy_5m_dst_2025_03_10_2025_11_03.csv -- SPY 5m bars on both 2025 DST transition
   sessions (America/New_York date semantics).
5. spy_1d_2024.csv -- SPY 1d bars for calendar 2024.

Safety: SELECT-only against the database. No INSERT, UPDATE, DELETE, or DDL anywhere.

Usage:
    .venv/bin/python scripts/ops/bars/ops_export_known_answer_fixtures.py
    .venv/bin/python scripts/ops/bars/ops_export_known_answer_fixtures.py --output-dir /tmp/bars
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import psycopg

from src.config.settings import Settings
from src.core.service_utils import format_iso_ts

_SEAM_SYMBOLS = ("MRNA", "ALMS")
_SEAM_1D_START = "2026-07-01"

_ET_DATE_SQL = "(timestamp AT TIME ZONE 'America/New_York')::date"

_COLS = (
    "timestamp, symbol, timeframe, open, high, low, close, volume, source, base, "
    "price_sanity_status"
)


def _write_cursor_rows(cur: psycopg.Cursor, path: Path) -> int:
    """Write the cursor's result set to a CSV with a header row. Returns row count."""
    header = [d.name for d in cur.description] if cur.description is not None else []
    n = 0
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        if header:
            writer.writerow(header)
        for row in cur:
            writer.writerow(
                format_iso_ts(v) if _is_timestamp(d) else v
                for v, d in zip(row, cur.description, strict=True)
            )
            n += 1
    return n


def _is_timestamp(desc) -> bool:
    return desc.type_code is not None and desc.name == "timestamp"


def export_status_rows(conn: psycopg.Connection, path: Path) -> int:
    """Every non-null price_sanity_status row from the RAW table (all timeframes),
    with prev_close/next_open taken from the nearest traded bars in the tradeable
    view (the same neighbor semantics the dry-run classifier and bar_auditor use).
    NULL when the row sits at a series boundary.
    """
    sql = """
        SELECT h.timestamp, h.symbol, h.timeframe, h.open, h.high, h.low, h.close,
               h.volume, h.source, h.base, h.price_sanity_status,
               (SELECT p.close FROM market_data_ohlcv_tradeable p
                 WHERE p.symbol = h.symbol AND p.timeframe = h.timeframe
                   AND p.timestamp < h.timestamp
                 ORDER BY p.timestamp DESC LIMIT 1) AS prev_close,
               (SELECT nx.open FROM market_data_ohlcv_tradeable nx
                 WHERE nx.symbol = h.symbol AND nx.timeframe = h.timeframe
                   AND nx.timestamp > h.timestamp
                 ORDER BY nx.timestamp ASC LIMIT 1) AS next_open
        FROM market_data_ohlcv h
        WHERE h.price_sanity_status IS NOT NULL
        ORDER BY h.timestamp, h.symbol, h.timeframe
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return _write_cursor_rows(cur, path)


def export_seam_candidates(conn: psycopg.Connection, path: Path) -> int:
    """MRNA and ALMS 1d bars from 2026-07-01 through the latest stored 1d date."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT max(timestamp)
            FROM market_data_ohlcv_tradeable
            WHERE symbol = ANY(%s) AND timeframe = '1d'
            """,
            (list(_SEAM_SYMBOLS),),
        )
        latest = cur.fetchone()[0]
        cur.execute(
            f"""
            SELECT {_COLS}
            FROM market_data_ohlcv_tradeable
            WHERE symbol = ANY(%s) AND timeframe = '1d'
              AND timestamp >= %s AND timestamp <= %s
            ORDER BY symbol, timestamp
            """,
            (list(_SEAM_SYMBOLS), _SEAM_1D_START, latest),
        )
        return _write_cursor_rows(cur, path)


def export_spy_5m_et_dates(conn: psycopg.Connection, path: Path, dates: list[str]) -> int:
    """SPY 5m bars on the given America/New_York session dates (from the tradeable view)."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_COLS}
            FROM market_data_ohlcv_tradeable
            WHERE symbol = 'SPY' AND timeframe = '5m'
              AND {_ET_DATE_SQL} = ANY(%s)
            ORDER BY timestamp
            """,
            (dates,),
        )
        return _write_cursor_rows(cur, path)


def export_spy_1d_year(conn: psycopg.Connection, path: Path, year: int) -> int:
    """SPY 1d bars for one calendar year (1d bars are stamped midnight UTC)."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_COLS}
            FROM market_data_ohlcv_tradeable
            WHERE symbol = 'SPY' AND timeframe = '1d'
              AND timestamp >= %s AND timestamp < %s
            ORDER BY timestamp
            """,
            (f"{year}-01-01", f"{year + 1}-01-01"),
        )
        return _write_cursor_rows(cur, path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/bars"),
        help="Directory to write the CSV fixtures into (default: tests/fixtures/bars).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    exports = [
        ("price_sanity_status_rows.csv", export_status_rows),
        ("seam_candidates_mrna_alms.csv", export_seam_candidates),
        (
            "spy_5m_2025_11_28_half_day.csv",
            lambda c, p: export_spy_5m_et_dates(c, p, ["2025-11-28"]),
        ),
        (
            "spy_5m_dst_2025_03_10_2025_11_03.csv",
            lambda c, p: export_spy_5m_et_dates(c, p, ["2025-03-10", "2025-11-03"]),
        ),
        ("spy_1d_2024.csv", lambda c, p: export_spy_1d_year(c, p, 2024)),
    ]
    with psycopg.connect(settings.database_url) as conn:
        for name, exporter in exports:
            path = args.output_dir / name
            n = exporter(conn, path)
            print(f"{path}: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
