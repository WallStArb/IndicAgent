"""Alpaca 5m campaign loader (todo 521, T2): scratch parquet -> market_data_ohlcv.

Loads the puller's per-name parquet files through the ingress write contract
with first-writer-stays: a timestamp any other source already holds is
dropped before the contract ever sees it, so this loader only ever inserts.
Slot rules are the admission-build plan's pins: bar-OPEN stamps on the
session grid from `nyse_sessions` (78 slots full day, 42 early closes),
extended-hours bars dropped at load, no slot fabricated in either direction.
Expected-slot arithmetic reads the same calendar the derivation reads.

Coverage: each chunk's `ohlcv_coverage` row is upserted in the same
transaction as its bars (`persist_chunk_atomically`, the fetcher's own
pattern). `ohlcv_load` rows carry source 'alpaca' via the contract's source
parameter. Row-level ohlcv_request/ohlcv_observation capture starts with the
T4 nightly leaf; for this one-time campaign the archived request log
(logs/alpaca_depth/) is the provenance artifact, a recorded gap in the
canonical-truth-registry's Alpaca row.

Known sharp edge (documented, not built around): if a chunk were ever
refused, the refused ohlcv_load row would record the contract's default
source (ibkr) because persist_chunk_atomically owns the refusal path.
Refusals require stored overlap, which first-writer-stays removes by
construction; if one ever fires, treat it as a finding, not a failure to
route around.

Dry run is the default: without --apply this plans and prints, writing
nothing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import DESTINATION_GRID, CoverageDelta
from services.ohlcv_ingress_contract import apply_ingress_contract, read_stored
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES, SOURCE_ALPACA

CALLER = "alpaca-5m-load"
TIMEFRAME = "5m"
CHUNK_ROWS = 100_000
SQL_BATCH = 1000

_INSERT_ROWS_SQL = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
)

_UPDATE_ROWS_SQL = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
    "%s ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source"
)


def session_grid(sessions: dict, symbol_dates: set) -> dict:
    """Open-stamped 5m grid per session date: open inclusive, close exclusive.

    A 16:00-ET close yields slots 09:30..15:55 (78); a 13:00 close yields
    09:30..12:55 (42). Both come from the calendar via `nyse_sessions`, never
    a hardcoded count.
    """
    grid: dict = {}
    for day, (open_ts, close_ts) in sessions.items():
        if day not in symbol_dates:
            continue
        stamps = set()
        stamp = open_ts
        while stamp < close_ts:
            stamps.add(stamp)
            stamp += timedelta(minutes=5)
        grid[day] = stamps
    return grid


def filter_to_grid(rows: list[tuple], grid: dict) -> tuple[list[tuple], int]:
    """Keep 9-tuples whose timestamp is an in-grid slot; return (kept, dropped)."""
    kept, dropped = [], 0
    for row in rows:
        day = row[0].date()
        if row[0] in grid.get(day, ()):
            kept.append(row)
        else:
            dropped += 1
    return kept, dropped


def drop_stored(rows: list[tuple], stored: set) -> tuple[list[tuple], int]:
    """First-writer-stays: drop 9-tuples any other source already holds."""
    kept = [row for row in rows if row[0] not in stored]
    return kept, len(rows) - len(kept)


def rows_from_parquet(path: Path, symbol: str) -> list[tuple]:
    """Puller parquet -> 9-tuples in the ingress row layout, source alpaca."""
    frame = pd.read_parquet(path)
    out: list[tuple] = []
    for ts, o, h, low, c, v in zip(
        frame["t"], frame["o"], frame["h"], frame["l"], frame["c"], frame["v"], strict=True
    ):
        stamp = pd.Timestamp(ts).to_pydatetime()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        out.append(
            (
                stamp.astimezone(UTC),
                symbol,
                TIMEFRAME,
                float(o),
                float(h),
                float(low),
                float(c),
                int(v),
                SOURCE_ALPACA,
            )
        )
    return out


def _write_batches(cur, rows: list[tuple], sql_head: str) -> None:
    for start in range(0, len(rows), SQL_BATCH):
        batch = rows[start : start + SQL_BATCH]
        args = b",".join(
            cur.mogrify("(%s, %s, %s, %s, %s, %s, %s, %s, %s)", row) for row in batch
        ).decode()
        cur.execute(sql_head + "(" + args + ")")


def write_new(cur, rows: list[tuple]) -> None:
    _write_batches(cur, rows, _INSERT_ROWS_SQL)


def write_changed(cur, rows: list[tuple]) -> None:
    _write_batches(cur, rows, _UPDATE_ROWS_SQL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-dir", type=Path, default=Path("data/scratch/alpaca-pilot/depth"))
    parser.add_argument("--symbols", nargs="*", help="subset; default every parquet in the dir")
    parser.add_argument("--apply", action="store_true", help="write; default plans and prints")
    args = parser.parse_args()

    if TIMEFRAME in DERIVATION_OWNED_TIMEFRAMES:
        raise SystemExit("5m is a derivation-owned timeframe; refusing (writer fence)")

    conn_info = "host=localhost user=postgres password=postgres dbname=indicagent"
    symbols = args.symbols or sorted(
        p.name.split("_")[0] for p in args.scratch_dir.glob("*_5Min.parquet")
    )
    planned_total = applied_total = skipped_stored = dropped_extended = 0

    with psycopg.connect(conn_info) as conn:
        for symbol in symbols:
            path = args.scratch_dir / f"{symbol}_5Min.parquet"
            if not path.exists():
                print(f"{symbol}: no parquet, skipping", flush=True)
                continue
            rows = rows_from_parquet(path, symbol)
            if not rows:
                continue
            days = {row[0].date() for row in rows}
            sessions = nyse_sessions(min(days), max(days))
            grid = session_grid(sessions, days)
            rows, dropped = filter_to_grid(rows, grid)
            dropped_extended += dropped
            stored = set()
            if rows:
                with conn.cursor() as cur:
                    stored = existing_stamps(cur, symbol, {row[0] for row in rows})
            rows, skipped = drop_stored(rows, stored)
            skipped_stored += skipped
            planned_total += len(rows)
            if not args.apply:
                print(
                    f"{symbol}: {len(rows)} new ({skipped} stored, {dropped} extended)", flush=True
                )
                continue
            written = 0
            for start in range(0, len(rows), CHUNK_ROWS):
                chunk = rows[start : start + CHUNK_ROWS]
                offer, _ = persist_chunk_atomically(
                    conn,
                    request_rows=[],
                    archive_rows=chunk,
                    write_archive_rows=_contract_writer,
                    coverage=CoverageDelta(
                        symbol, TIMEFRAME, DESTINATION_GRID, fetched_at=datetime.now(UTC)
                    ),
                )
                written += offer
            applied_total += written
            print(f"{symbol}: applied {written} of {len(rows)} planned", flush=True)

    mode = "APPLIED" if args.apply else "PLANNED"
    print(
        f"{mode}: {applied_total or planned_total} rows, "
        f"{skipped_stored} stored-held dropped, {dropped_extended} extended dropped"
    )
    return 0


def existing_stamps(cur, symbol: str, stamps: set) -> set:
    """Stored stamps among the candidates (first-writer-stays read)."""
    found: set = set()
    ordered = sorted(stamps)
    for start in range(0, len(ordered), SQL_BATCH):
        found.update(
            read_stored(
                cur, "market_data_ohlcv", symbol, TIMEFRAME, ordered[start : start + SQL_BATCH]
            ).keys()
        )
    return found


def _contract_writer(cur, rows: list[tuple]) -> int:
    """persist_chunk_atomically's injected writer: the ingress contract, source alpaca."""
    return apply_ingress_contract(
        cur,
        rows,
        destination=DESTINATION_GRID,
        caller=CALLER,
        write_new=write_new,
        write_changed=write_changed,
        source=SOURCE_ALPACA,
    )


if __name__ == "__main__":
    sys.exit(main())
