"""Bar load engine: filtered vendor frames into market_data_ohlcv, first-writer-stays.

The load path shared by every bar campaign and the nightly leaf (todo 521 T2/T4):
one policy names the vendor and timeframe; the engine owns everything vendor-
blind -- the slot grid from the calendar, first-writer-stays (a timestamp any
other source already holds is dropped before the contract ever sees it, so the
engine only ever inserts), the chunk loop, the ingress write contract, and the
same-transaction coverage upsert (`persist_chunk_atomically`, the fetcher's
pattern).

Slot rules are the admission-build plan's pins: bar-OPEN stamps on the session
grid from `nyse_sessions` (78 slots full day, 42 early closes), extended-hours
bars dropped at load, no slot fabricated in either direction. The grid filter
runs vectorized on the frame; only surviving rows are converted to tuples, per
chunk. Vendor provenance is carried in the row tuples' source column; the
ingress contract derives and enforces it.

Provenance of this engine: the Alpaca 5m admission build
(docs/plans/2026-10-09-alpaca-5m-admission-build.md). Row-level
ohlcv_request/ohlcv_observation capture starts with the T4 nightly leaf; for
campaign loads the archived request log is the provenance artifact, a recorded
gap in the canonical-truth-registry's Alpaca row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.intraday_raw_archive import insert_fetched_archive_rows
from services.ohlcv_coverage_writer import (
    DESTINATION_GRID as COVERAGE_DESTINATION_GRID,
)
from services.ohlcv_coverage_writer import (
    CoverageDelta,
)
from services.ohlcv_ingress_contract import (
    DESTINATION_GRID,
    MARKET_DATA_UPSERT_TAIL,
    ContractParams,
    apply_ingress_contract,
    write_market_data_batches,
)
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES

# Chunk size is bounded by existing_timestamps' client-side array rendering: a
# 100k-stamp chunk blew psycopg's 1 GiB query buffer (ProgramLimitExceeded,
# observed 2026-10-10); 10k keeps the rendered array at sub-MB scale. One
# measured limit for both write paths (grid and archive).
CHUNK_ROWS = 10_000


def archive_frame_to_tuples(
    frame: pd.DataFrame, symbol: str, *, source: str, timeframe: str
) -> list[tuple]:
    """One non-authored frame -> archive 10-tuples (the schema `insert_fetched_archive_rows`
    reads; base stays NULL). Kept beside `frame_to_tuples` so the two column mappings
    cannot drift."""
    return [
        (
            ts.to_pydatetime(),
            symbol,
            timeframe,
            float(o),
            float(h),
            float(low),
            float(c),
            int(v),
            source,
            None,
        )
        for ts, o, h, low, c, v in zip(
            frame["t"], frame["o"], frame["h"], frame["l"], frame["c"], frame["v"], strict=True
        )
    ]


def archive_rows(
    conn,
    rows: list[tuple],
    *,
    caller: str,
    params: ContractParams | None = None,
    chunk_rows: int = CHUNK_ROWS,
) -> int:
    """Chunk raw archive rows into the single-writer contract (todo 528 R1).

    Chunked at CHUNK_ROWS because the archive path renders the same psycopg
    arrays as the grid path; each chunk commits in its own transaction, and
    the archive contract's identical-row skip makes a rerun idempotent.
    """
    archived = 0
    for i in range(0, len(rows), chunk_rows):
        chunk = rows[i : i + chunk_rows]
        with conn.transaction():
            with conn.cursor() as cur:
                archived += insert_fetched_archive_rows(cur, chunk, caller=caller, params=params)
    return archived


def _archive_rows(
    conn, policy: LoadPolicy, symbol: str, params: ContractParams | None, *frames: pd.DataFrame
) -> int:
    """Archive each non-authored frame raw under the policy's vendor (todo 528 R1)."""
    archived = 0
    for frame in frames:
        rows = archive_frame_to_tuples(
            frame, symbol, source=policy.vendor, timeframe=policy.timeframe
        )
        archived += archive_rows(conn, rows, caller=policy.caller, params=params)
    return archived


# Known debt: the atomic persist helper lives under scripts/ because the fetcher
# grew it first. Lifting it beside this engine is blocked while the IBKR drain
# imports it live (todo 523); reconcile at the drain's completion.


@dataclass(frozen=True)
class LoadPolicy:
    """Which vendor and timeframe this loader writes, and under what caller name.

    Policy is named, never passed ad hoc: the vendor travels in the row tuples'
    source column (the contract derives and enforces it), and the timeframe
    selects the slot rule. A timeframe in DERIVATION_OWNED_TIMEFRAMES is
    refused outright (writer fence).
    """

    vendor: str
    timeframe: str
    caller: str

    def __post_init__(self) -> None:
        if self.timeframe in DERIVATION_OWNED_TIMEFRAMES:
            raise ValueError(
                f"{self.timeframe!r} is a derivation-owned timeframe; the load engine "
                "writes raw provider bars only (writer fence)"
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


def grid_stamps_utc(grid: dict) -> set:
    """The grid's stamps as UTC, for vectorized frame filtering."""
    return {stamp.astimezone(UTC) for stamps in grid.values() for stamp in stamps}


def filter_frame_to_grid(frame: pd.DataFrame, utc_stamps: set) -> pd.DataFrame:
    """Keep only rows whose stamp is an in-grid RTH slot (vectorized)."""
    return frame.loc[frame["t"].isin(utc_stamps)].reset_index(drop=True)


def drop_stored_rows(frame: pd.DataFrame, stored: set) -> pd.DataFrame:
    """First-writer-stays: drop rows any other source already holds (vectorized)."""
    return frame.loc[~frame["t"].isin(stored)].reset_index(drop=True)


def frame_to_tuples(frame: pd.DataFrame, symbol: str, policy: LoadPolicy) -> list[tuple]:
    """One filtered chunk's frame -> ingress 9-tuples, vendor from the policy."""
    stamps = frame["t"].dt.to_pydatetime()
    return [
        (
            ts,
            symbol,
            policy.timeframe,
            float(o),
            float(h),
            float(low),
            float(c),
            int(v),
            policy.vendor,
        )
        for ts, o, h, low, c, v in zip(
            stamps, frame["o"], frame["h"], frame["l"], frame["c"], frame["v"], strict=True
        )
    ]


def stored_range_stamps(
    cur,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    exclude_source: str | None = None,
) -> set:
    """Stored stamps of one series in a range (first-writer-stays read).

    One indexed range query, not an ANY(array) over every candidate stamp: the
    array form crashed a backend at ~460k stamps; the range read is O(stored).
    ``exclude_source`` drops one vendor's own rows, so the caller sees stamps
    held by *others* only (the archive rule: a vendor never archives the
    canonical answer it authored itself).
    """
    sql = (
        'SELECT "timestamp" FROM market_data_ohlcv '
        "WHERE symbol = %s AND timeframe = %s "
        'AND "timestamp" >= %s AND "timestamp" <= %s'
    )
    args: list = [symbol, timeframe, start, end]
    if exclude_source is not None:
        sql += " AND source <> %s"
        args.append(exclude_source)
    cur.execute(sql, args)
    return {row[0] for row in cur.fetchall()}


def split_series(
    conn, symbol: str, timeframe: str, frame: pd.DataFrame, *, vendor: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The R1 four-way split of one vendor frame: (new, held, own, extended).

    `new` rows are in-grid stamps nobody holds (canonical candidates); `held`
    rows are in-grid stamps ANOTHER source authored (archive them raw); `own`
    rows are stamps this vendor already authored (a no-op: the canonical row is
    the vendor's persisted answer, never re-archived); `extended` rows sit
    outside the session grid (archive them raw). The one definition of
    "non-authored": `load_series` consumes it and the raw-recovery backfill
    reuses it, so the slot rule and the stored reads cannot drift apart.
    """
    days = set(frame["t"].dt.date.unique())
    utc_stamps = grid_stamps_utc(session_grid(nyse_sessions(min(days), max(days)), days))
    in_grid_mask = frame["t"].isin(utc_stamps)
    extended = frame.loc[~in_grid_mask]
    grid = frame.loc[in_grid_mask].reset_index(drop=True)
    if grid.empty:
        empty = grid
        return empty, empty, empty, extended
    start, end = grid["t"].min().to_pydatetime(), grid["t"].max().to_pydatetime()
    with conn.cursor() as cur:
        all_stored = stored_range_stamps(cur, symbol, timeframe, start, end)
        other_stored = stored_range_stamps(
            cur, symbol, timeframe, start, end, exclude_source=vendor
        )
    new = grid.loc[~grid["t"].isin(all_stored)].reset_index(drop=True)
    held = grid.loc[grid["t"].isin(other_stored)]
    own = grid.loc[grid["t"].isin(all_stored) & ~grid["t"].isin(other_stored)].reset_index(
        drop=True
    )
    return new, held, own, extended


def load_series(
    conn,
    policy: LoadPolicy,
    symbol: str,
    frame: pd.DataFrame,
    *,
    params: ContractParams,
    write: bool,
    chunk_rows: int = CHUNK_ROWS,
    on_chunk=None,
) -> tuple[int, int, int]:
    """Plan one symbol's frame; write it when `write` is True (a dry run plans only).

    Returns (applied_or_planned_rows, skipped_stored, dropped_extended): the
    last two count rows that canonical authoring did not store -- first-writer-
    held rows and extended-hours rows. Since todo 528 (R1: capture universal)
    the engine archives both raw with source=policy.vendor through the
    single-writer archive contract instead of dropping them; nothing reaches
    the floor. The frame must carry a tz-aware UTC `t` column plus the OHLCV
    columns. Everything vendor-blind above this docstring is the engine; the
    policy only names the writer.
    """
    new, held, own, extended = split_series(
        conn, symbol, policy.timeframe, frame, vendor=policy.vendor
    )
    dropped_extended = len(extended)
    skipped_stored = len(held) + len(own)
    if write:
        _archive_rows(conn, policy, symbol, params, extended, held)
    frame = new

    def write_new(cur, rows: list[tuple]) -> None:
        write_market_data_batches(cur, rows)

    def write_changed(cur, rows: list[tuple]) -> None:
        write_market_data_batches(cur, rows, tail=MARKET_DATA_UPSERT_TAIL)

    def writer(cur, rows: list[tuple]) -> int:
        return apply_ingress_contract(
            cur,
            rows,
            destination=DESTINATION_GRID,
            caller=policy.caller,
            write_new=write_new,
            write_changed=write_changed,
            params=params,
        )

    applied = 0
    if write:
        for start in range(0, len(frame), chunk_rows):
            chunk = frame_to_tuples(frame.iloc[start : start + chunk_rows], symbol, policy)
            _, offer = (
                persist_chunk_atomically(  # (requests, bars): the campaign writes no requests
                    conn,
                    request_rows=[],
                    archive_rows=chunk,
                    write_archive_rows=writer,
                    coverage=CoverageDelta(
                        symbol,
                        policy.timeframe,
                        COVERAGE_DESTINATION_GRID,
                        fetched_at=datetime.now(UTC),
                        provider=policy.vendor,
                    ),
                )
            )
            applied += offer
            if on_chunk:
                on_chunk(start + len(chunk), len(frame))
    return applied if write else len(frame), skipped_stored, dropped_extended
