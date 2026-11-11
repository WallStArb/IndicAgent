"""Massive per-year loader for 5m and 1d, newest year first (todo 600, design section 8 step 5).

Dry run is the default and the only mode run so far: it reads the day files of the year, maps
file tickers to instruments through the evidenced ticker_event spans, and prints what step 5's
gate checks (docs/plans/2026-11-10-massive-admission-db-design.md):

- spans loaded and spans edge-failed, by reason (a span whose ticker string is not served at its
  first and last archive session is not loaded and keeps the incumbent);
- row balance per year: traded minutes in, bars out, unmapped tickers excluded and counted;
- expected unselected slots: the Massive-only on-grid slots, i.e. mapped bars whose
  (instrument, slot) no incumbent vendor holds in ohlcv_raw. While Massive is unranked the load
  defers selection and reports RAW-ONLY; the unselected count is measured by
  ops_selection_gate --compare --start/--end before and after the year, whose difference must
  equal this number (admission design, step 5 amendment 2026-11-11).

`--apply` writes one calendar month at a time through the bulk raw path (``load_batch``; bulk
raw load path design, docs/plans/2026-11-11-bulk-raw-load-path-design.md): one RawBatch a month,
one load row per symbol series-chunk with its lineage (file key, ETag, sha256 and LastModified
of each file, the ticker_events used, untraded rows, the volume definition epochs), packed into
transactions of whole series-chunks. Each year starts with a disk headroom check and ends with a
recompression of ohlcv_raw's partial chunks. Rerunning the same command is the resume.

The loader fails loudly, before reading a file, when an active instrument has neither a span nor
a gap-list row.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import sys
import time
from collections import Counter
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pyarrow.csv as pacsv

from services.bar_load import (
    CHUNK_ROWS,
    LoadResult,
    load_batch,
    load_status,
    ns_to_us,
    resolve_kind,
    whole_volume,
)
from services.ohlcv_ingress_contract import read_raw_params
from services.ohlcv_raw_writer import RawBatch, build_raw_batch, datetime_to_us
from src.config.config_service import ConfigService
from src.config.settings import get_settings
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.massive_flat import FlatBars, file_trading_date
from src.intelligence.bars.massive_symbol_map import (
    SpanVerdict,
    TickerSpan,
    judge_span,
    tickers_on,
    unaccounted_instruments,
)
from src.intelligence.bars.selection import NEVER_SELECTED_KINDS
from src.intelligence.bars.vendor_ingress import (
    MASSIVE_FILES_ROOT,
    manifest_record,
    massive_answered_at,
    vendor_ingress,
)

_INCUMBENT_VENDORS = ("ibkr", "alpaca")
_MAP_ROOT = Path("data/ticker_entity_map")
_LOG_DIR = Path("logs")


@dataclass
class DayReport:
    """What one day file contributes: the balance of rows in against bars out."""

    day: date
    file_tickers: int = 0
    mapped_tickers: int = 0
    unmapped_tickers: int = 0
    traded_minutes_in: int = 0  # in-session traded minutes of every ticker (5m only)
    traded_minutes_mapped: int = 0
    bars_out: int = 0  # bars of mapped tickers
    bars_unmapped: int = 0  # bars of tickers with no loadable span that day, excluded and counted
    untraded_rows: int = 0
    massive_only: int = 0  # mapped bars no incumbent vendor holds: the expected unselected
    unmapped_sample: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DaySlots:
    """The incumbent raw rows of one session as parallel arrays: the instrument symbol and the
    slot key (UTC microseconds for 5m; 0 for 1d, whose slot is the session itself)."""

    symbols: np.ndarray  # object (str)
    keys: np.ndarray  # int64

    @staticmethod
    def empty() -> DaySlots:
        return DaySlots(np.empty(0, dtype=object), np.empty(0, dtype=np.int64))


def slot_keys(timeframe: str, t_ns: np.ndarray) -> np.ndarray:
    """The slot key of each bar stamp: UTC microseconds for 5m, 0 for 1d (one slot a session)."""
    if timeframe == "5m":
        return ns_to_us(t_ns)
    return np.zeros(len(t_ns), dtype=np.int64)


def pairs_in(
    codes: np.ndarray, keys: np.ndarray, held_codes: np.ndarray, held_keys: np.ndarray
) -> np.ndarray:
    """Whether each (code, key) pair is among the held pairs; a code of -1 never is. Keys are
    offset to the smallest so a code and a key pack into one int64 exactly."""
    out = np.zeros(len(codes), dtype=bool)
    if not len(codes) or not len(held_keys):
        return out
    base = min(int(keys.min()), int(held_keys.min()))
    span = max(int(keys.max()), int(held_keys.max())) - base + 1
    if (int(held_codes.max()) + 1) * span >= 2**62:
        raise ValueError("slot keys span too wide to pack with the symbol codes")
    known = codes >= 0
    packed = codes[known] * span + (keys[known] - base)
    out[known] = np.isin(packed, held_codes * span + (held_keys - base))
    return out


def account_day(
    day: date,
    bars: FlatBars,
    mapping: dict[str, TickerSpan],
    incumbent: DaySlots,
    timeframe: str,
) -> DayReport:
    """The row balance of one day file against the ticker map and the incumbent slots, over
    arrays: `incumbent` holds the (symbol, slot key) of every incumbent raw row of the session
    (`slot_keys`); a mapped bar whose instrument has no incumbent row at its slot is Massive-only
    (an expected unselected slot)."""
    tickers = [str(t) for t in bars.tickers]
    in_map = np.array([t in mapping for t in tickers], dtype=bool)
    mapped_mask = in_map[bars.ticker_index]  # per-ticker lookup, then a gather: no per-row strings
    present = np.zeros(len(tickers), dtype=bool)
    present[bars.ticker_index] = True
    report = DayReport(day, file_tickers=len(tickers))
    report.mapped_tickers = int((present & in_map).sum())
    report.unmapped_tickers = len(tickers) - report.mapped_tickers
    report.bars_out = int(mapped_mask.sum())
    report.bars_unmapped = int((~mapped_mask).sum())
    report.untraded_rows = bars.n_untraded_rows
    if bars.traded_minutes is not None:
        report.traded_minutes_in = int(bars.traded_minutes.sum())
        report.traded_minutes_mapped = int(bars.traded_minutes[in_map].sum())
    unmapped = sorted(t for t, p, m in zip(tickers, present, in_map, strict=True) if p and not m)
    report.unmapped_sample = unmapped[:5]
    held = incumbent.symbols.tolist()
    names = {s: i for i, s in enumerate(sorted(set(held)))}
    ticker_code = np.array(
        [names.get(mapping[t].symbol, -1) if t in mapping else -1 for t in tickers], dtype=np.int64
    )
    held_mask = pairs_in(
        ticker_code[bars.ticker_index[mapped_mask]],
        slot_keys(timeframe, bars.t_ns[mapped_mask]),
        np.array([names[s] for s in held], dtype=np.int64),
        incumbent.keys,
    )
    report.massive_only = int((~held_mask).sum())
    return report


def read_gap_symbols(path: Path) -> set[str]:
    """Every symbol on the identity worker's gap list (instrument or span scope)."""
    with path.open(newline="") as handle:
        return {row["symbol"] for row in csv.DictReader(handle)}


def latest_gap_list(root: Path = _MAP_ROOT) -> Path:
    candidates = sorted(root.glob("*/gap_list.csv"))
    if not candidates:
        raise FileNotFoundError(f"no gap_list.csv under {root}")
    return candidates[-1]


def read_spans(cur: Any) -> list[TickerSpan]:
    cur.execute(
        "SELECT ticker_event_id::text, symbol, ticker, valid_from, valid_to FROM ticker_event "
        "WHERE vendor = 'massive' AND retired_at IS NULL ORDER BY symbol, valid_from"
    )
    return [TickerSpan(*row) for row in cur.fetchall()]


def read_active_symbols(cur: Any) -> list[str]:
    cur.execute("SELECT symbol FROM instruments WHERE is_active")
    return [row[0] for row in cur.fetchall()]


def volume_epoch_id(cur: Any, day: date) -> str | None:
    """The definition_epoch in force for Massive volume on `day` (the latest effective_from on or
    before it); None before the first epoch."""
    cur.execute(
        "SELECT definition_epoch_id::text FROM definition_epoch WHERE vendor = 'massive' "
        "AND column_name = 'volume' AND retired_at IS NULL AND effective_from <= %s "
        "ORDER BY effective_from DESC LIMIT 1",
        (day,),
    )
    row = cur.fetchone()
    return None if row is None else row[0]


class SessionTickers(Collection[str]):
    """The ticker strings one session served, as a bitset over the index's ticker ids."""

    def __init__(self, ids: Mapping[str, int], bits: np.ndarray) -> None:
        self._ids, self._bits = ids, bits

    def __contains__(self, ticker: object) -> bool:
        i = self._ids.get(ticker) if isinstance(ticker, str) else None
        return (
            i is not None
            and i < 8 * len(self._bits)
            and bool(self._bits[i >> 3] >> (7 - (i & 7)) & 1)
        )

    def __iter__(self) -> Iterator[str]:
        return (t for t in self._ids if t in self)

    def __len__(self) -> int:
        return int(np.unpackbits(self._bits).sum())


class ArchiveIndex:
    """The archive's sessions and the ticker strings each served, from the day files (one column
    read per file, cached as one bitset a session over a shared ticker id map). A frozenset of
    fresh strings a session held about 1.07 MB each, 6.2 GB for 5,829 sessions (tracemalloc
    2026-11-11), the loader's 6.95 GB RSS; the bitset holds the same answers in a few MB."""

    def __init__(self, root: Path = MASSIVE_FILES_ROOT) -> None:
        self._files = {
            file_trading_date(p): p for p in sorted((root / "day_aggs_v1").rglob("*.csv.gz"))
        }
        self.sessions = sorted(self._files)
        self._ids: dict[str, int] = {}
        self._bits: dict[date, SessionTickers] = {}

    def present_on(self, day: date) -> SessionTickers:
        if day not in self._bits:
            table = pacsv.read_csv(
                self._files[day], convert_options=pacsv.ConvertOptions(include_columns=["ticker"])
            )
            ids = [self._ids.setdefault(t, len(self._ids)) for t in table["ticker"].to_pylist()]
            mask = np.zeros(len(self._ids), dtype=bool)
            mask[ids] = True
            self._bits[day] = SessionTickers(self._ids, np.packbits(mask))
        return self._bits[day]


_DAY_US = 86_400 * 1_000_000
_EPOCH_DATE = date(1970, 1, 1)


def incumbent_slots(cur: Any, timeframe: str, first: date, last: date) -> dict[date, DaySlots]:
    """The incumbent raw rows of the sessions first..last (inclusive) by session date, as
    (symbol, slot key) arrays (`slot_keys`): a 5m row's UTC microseconds under its UTC date, a 1d
    row's session date (IBKR stamps 1d at 00:00 UTC, Alpaca at midnight New York). One query per
    range. Never-selected kinds (iex_rth) hold no slot: a slot only they hold is excluded before
    the load and unselected once a Massive row lands, so it is Massive-only, as the gate's
    windowed --compare counts it."""
    if timeframe == "5m":
        cur.execute(
            'SELECT symbol, (extract(epoch FROM "timestamp") * 1000000)::bigint FROM ohlcv_raw '
            "WHERE timeframe = '5m' AND vendor = ANY(%s) AND kind <> ALL(%s) "
            'AND "timestamp" >= %s AND "timestamp" < %s',
            (
                list(_INCUMBENT_VENDORS),
                sorted(NEVER_SELECTED_KINDS),
                datetime.combine(first, datetime.min.time(), UTC),
                datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC),
            ),
        )
        rows = cur.fetchall()
        symbols = np.array([r[0] for r in rows], dtype=object)
        keys = np.array([r[1] for r in rows], dtype=np.int64)
        sessions = keys // _DAY_US
    else:
        cur.execute(
            "SELECT symbol, CASE WHEN vendor = 'alpaca' THEN (\"timestamp\" AT TIME ZONE "
            "'America/New_York')::date ELSE (\"timestamp\" AT TIME ZONE 'UTC')::date END "
            "FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = ANY(%s) AND kind <> ALL(%s) "
            'AND "timestamp" >= %s::date - 1 AND "timestamp" < %s::date + 2',
            (list(_INCUMBENT_VENDORS), sorted(NEVER_SELECTED_KINDS), first, last),
        )
        rows = [r for r in cur.fetchall() if first <= r[1] <= last]
        symbols = np.array([r[0] for r in rows], dtype=object)
        keys = np.zeros(len(rows), dtype=np.int64)
        sessions = np.array([(r[1] - _EPOCH_DATE).days for r in rows], dtype=np.int64)
    out: dict[date, DaySlots] = {}
    for day in np.unique(sessions).tolist():
        rows_of = sessions == day
        out[_EPOCH_DATE + timedelta(days=day)] = DaySlots(symbols[rows_of], keys[rows_of])
    return out


class IncumbentSlots:
    """Incumbent slots by session, fetched one calendar month at a time (the per-day query was the
    dry run's cost: 853 s a year)."""

    def __init__(self, conn: Any, timeframe: str) -> None:
        self._conn, self._timeframe = conn, timeframe
        self._month: tuple[int, int] | None = None
        self._slots: dict[date, DaySlots] = {}

    def of(self, day: date) -> DaySlots:
        if self._month != (day.year, day.month):
            first = day.replace(day=1)
            last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            with self._conn.cursor() as cur:
                self._slots = incumbent_slots(cur, self._timeframe, first, last)
            self._month = (day.year, day.month)
        return self._slots.get(day, DaySlots.empty())


def year_files(
    timeframe: str, year: int, root: Path = MASSIVE_FILES_ROOT, month: int | None = None
) -> list[Path]:
    dataset = "minute_aggs_v1" if timeframe == "5m" else "day_aggs_v1"
    folder = root / dataset / f"{year}" / ("" if month is None else f"{month:02d}")
    return sorted(folder.rglob("*.csv.gz"), reverse=True)  # newest first


def verdict_table(verdicts: list[SpanVerdict]) -> dict[str, int]:
    counts = Counter(
        "loaded" if v.reason is None else f"trimmed:{v.reason}" if v.loadable else v.reason
        for v in verdicts
    )
    return dict(sorted(counts.items()))


def run(args: argparse.Namespace) -> int:
    # structlog to logs/, never stdout: selection and flag lines are per series
    setup_service_logging(str(_LOG_DIR / "ops_massive_load.log"))
    ingress = vendor_ingress("massive", args.timeframe)
    gap_path = args.gap_list or latest_gap_list()
    gap_symbols = read_gap_symbols(gap_path)
    conn = psycopg.connect(get_settings().database_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            spans = read_spans(cur)
            active = read_active_symbols(cur)
        missing = unaccounted_instruments(active, spans, gap_symbols)
        if missing:
            print(
                f"FAIL: {len(missing)} active instruments have no span and no gap row: {missing[:20]}"
            )
            return 2
        index = ArchiveIndex()
        reports: dict[int, list[DayReport]] = {}
        verdicts: dict[int, list[SpanVerdict]] = {}
        status = 0
        for year in args.years:
            refusal = disk_headroom_refusal() if args.apply else None
            if refusal:
                # stop before the year; the report of the years already loaded is still written
                print(f"FAIL: {year} not started, disk headroom: {refusal}", flush=True)
                status = 2
                break
            window = (date(year, 1, 1), date(year, 12, 31))
            year_verdicts = [
                judge_span(s, index.sessions, index.present_on, window)
                for s in spans
                if s.valid_to is None or s.valid_to > window[0]
                if s.valid_from <= window[1]
            ]
            loadable = [v.trimmed for v in year_verdicts if v.trimmed is not None]
            print(f"{year} spans: {verdict_table(year_verdicts)}", flush=True)
            verdicts[year] = year_verdicts
            t0 = time.monotonic()
            slots = IncumbentSlots(conn, args.timeframe)
            batch, loaded = MonthBatch(), LoadResult()
            reports[year] = []
            for path in year_files(args.timeframe, year, month=args.month):
                day = file_trading_date(path)
                bars = _read(args.timeframe, path)
                mapping = tickers_on(loadable, day)
                reports[year].append(account_day(day, bars, mapping, slots.of(day), args.timeframe))
                if args.apply:
                    if batch.month != (day.year, day.month):
                        batch, loaded = _flush(conn, ingress, batch, loaded)
                        batch.month = (day.year, day.month)
                    with conn.cursor() as cur:
                        batch.add(day, path, bars, mapping, volume_epoch_id(cur, day))
            if args.apply:
                batch, loaded = _flush(conn, ingress, batch, loaded)
                word = load_status(
                    apply=True,
                    unselected=loaded.n_unselected,
                    basis_flagged=loaded.n_basis_flagged,
                    selection_deferred=loaded.n_selection_deferred,
                )
                print(f"{year} {args.timeframe} load: {word} {loaded}", flush=True)
                recompress_raw(conn)
            _print_year(args.timeframe, year, reports[year], time.monotonic() - t0)
        _write_report(args, reports, verdicts)
    finally:
        conn.close()
    return status


_RAW_COMPRESSION_JOB_SQL = (
    "SELECT job_id FROM timescaledb_information.jobs "
    "WHERE hypertable_name = 'ohlcv_raw' AND proc_name = 'policy_compression'"
)
# The filesystem holding the database volume and the share of it that must stay free (the same
# APR keys the compressed write session checks, todo 426).
_DISK_PATH_KEY = "infra.compressed_hypertable_write_session.disk_path"
_MIN_FREE_KEY = "infra.compressed_hypertable_write_session.min_free_after_fraction"
_DISK_PATH_DEFAULT, _MIN_FREE_DEFAULT = "/", 0.10  # the migration seeds, as _batch_utils reads them


def recompress_raw(conn: Any) -> None:
    """Run ohlcv_raw's compression policy job now, so the chunks a loaded year left partial are
    recompressed before the next year: the uncompressed heap stays bounded at about one year of
    Massive rows (bulk raw load path design, section 8)."""
    with conn.cursor() as cur:
        cur.execute(_RAW_COMPRESSION_JOB_SQL)
        jobs = [row[0] for row in cur.fetchall()]
        if len(jobs) != 1:
            raise RuntimeError(f"expected one ohlcv_raw compression job, found {jobs}")
        t0 = time.monotonic()
        cur.execute("CALL run_job(%s)", (jobs[0],))
    print(f"recompressed ohlcv_raw (job {jobs[0]}) in {time.monotonic() - t0:.0f}s", flush=True)


def disk_refusal(free: int, total: int, min_free_fraction: float) -> str | None:
    """Why a year must not start: less than `min_free_fraction` of the filesystem is free."""
    if free >= min_free_fraction * total:
        return None
    return (
        f"{free / 1e9:.0f} GB free of {total / 1e9:.0f} GB, under the {min_free_fraction:.0%} "
        f"that must stay free ({_MIN_FREE_KEY})"
    )


async def _read_disk_apr() -> tuple[str, float]:
    config = ConfigService(get_settings().database_url)
    await config.initialize()
    try:
        path = str(await config.get(_DISK_PATH_KEY, default=_DISK_PATH_DEFAULT))
        floor = float(await config.get(_MIN_FREE_KEY, default=_MIN_FREE_DEFAULT))
    finally:
        await config.close()
    return path, floor


def disk_headroom_refusal() -> str | None:
    """Why a year must not start (the filesystem is below its free-space floor), else None."""
    path, floor = asyncio.run(_read_disk_apr())
    usage = shutil.disk_usage(path)
    refusal = disk_refusal(usage.free, usage.total, floor)
    if refusal is None:
        print(f"disk headroom: {usage.free / 1e9:.0f} GB free on {path}", flush=True)
    return refusal


def _read(timeframe: str, path: Path) -> FlatBars:
    from src.intelligence.bars.massive_flat import read_day_file, read_minute_file

    return read_minute_file(path) if timeframe == "5m" else read_day_file(path)


class MonthBatch:
    """One calendar month of day files as columnar arrays, written as ONE RawBatch through the
    bulk path (`load_batch`): one load row per symbol series-chunk, packed into transactions of
    whole series-chunks. Every row keeps its own file's serve time (LastModified); each symbol's
    lineage lists every file (date, ETag, sha256, LastModified), its ticker events and volume
    definition epochs."""

    def __init__(self) -> None:
        self.month: tuple[int, int] | None = None
        # per day file: symbol, t_ns, open, high, low, close, volume, served (UTC microseconds)
        self.parts: list[tuple[np.ndarray, ...]] = []
        self.files: dict[str, list[list[str]]] = {}
        self.spans: dict[str, dict[str, str]] = {}  # symbol -> ticker_event_id -> ticker
        self.epochs: dict[str, set[str | None]] = {}
        self.untraded = 0

    def add(self, day: date, path: Path, bars: FlatBars, mapping, epoch: str | None) -> None:
        record = manifest_record(path)
        served_us = datetime_to_us(massive_answered_at(path, ""))
        self.untraded += bars.n_untraded_rows
        entry = [day.isoformat(), record["etag"], record["sha256"], record["last_modified"]]
        tickers = [str(t) for t in bars.tickers]
        symbol_of = np.array([mapping[t].symbol if t in mapping else "" for t in tickers], object)
        in_map = np.array([t in mapping for t in tickers], dtype=bool)
        rows = np.flatnonzero(in_map[bars.ticker_index])
        index = bars.ticker_index[rows]
        self.parts.append(
            (
                symbol_of[index],
                bars.t_ns[rows],
                bars.open[rows],
                bars.high[rows],
                bars.low[rows],
                bars.close[rows],
                bars.volume[rows],
                np.full(len(rows), served_us, dtype=np.int64),
            )
        )
        for ticker in (tickers[i] for i in np.unique(index).tolist()):
            span = mapping[ticker]
            self.files.setdefault(span.symbol, []).append(entry)
            self.spans.setdefault(span.symbol, {})[span.ticker_event_id] = ticker
            self.epochs.setdefault(span.symbol, set()).add(epoch)

    def raw_batch(self, ingress, params) -> RawBatch:
        parts, self.parts = self.parts, []  # the per-day arrays go once concatenated
        symbols, t_ns, o, h, low, c, v, served = (np.concatenate(col) for col in zip(*parts))
        del parts
        return build_raw_batch(
            timeframe=ingress.timeframe,
            vendor=ingress.source,
            kind=resolve_kind(ingress.source, ingress.kind),
            symbols=symbols,
            ts_us=ns_to_us(t_ns),
            open=o,
            high=h,
            low=low,
            close=c,
            volume=whole_volume(v),
            served_us=served,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            future_tolerance_s=params.write.future_tolerance_s,
            # a series-chunk must fit one packed transaction (APR copy_batch_rows)
            chunk_rows=min(CHUNK_ROWS, params.write.batch_rows),
        )

    def lineage(self) -> dict[str, dict[str, Any]]:
        return {
            symbol: {
                "files": files,  # [date, etag, sha256, last_modified]
                "ticker_events": self.spans[symbol],
                "definition_epoch_ids": sorted(map(str, self.epochs[symbol])),
                "n_untraded_rows_all_files": self.untraded,
            }
            for symbol, files in self.files.items()
        }

    def flush(self, conn, ingress, params) -> LoadResult:
        """Raw-only capture (Massive is not a fetcher source: no request rows, no coverage)."""
        return load_batch(
            conn,
            self.raw_batch(ingress, params),
            caller=f"massive-{ingress.timeframe}-load",
            params=params,
            lineage_by_symbol=self.lineage(),
        )


def _flush(conn, ingress, batch: MonthBatch, loaded: LoadResult) -> tuple[MonthBatch, LoadResult]:
    """Write the collected month; returns an empty batch and the running total."""
    if not any(len(part[0]) for part in batch.parts):  # no mapped bar this month
        return MonthBatch(), loaded
    with conn.cursor() as cur:
        params = read_raw_params(cur)
    return MonthBatch(), _sum(loaded, batch.flush(conn, ingress, params))


def _sum(total: LoadResult, result: LoadResult) -> LoadResult:
    return LoadResult(
        **{f.name: getattr(total, f.name) + getattr(result, f.name) for f in fields(LoadResult)}
    )


def _print_year(timeframe: str, year: int, days: list[DayReport], seconds: float) -> None:
    total = lambda f: sum(getattr(d, f) for d in days)  # noqa: E731
    print(
        f"{year} {timeframe}: {len(days)} files in {seconds:.0f}s | "
        f"traded minutes in {total('traded_minutes_in')} (mapped {total('traded_minutes_mapped')}) | "
        f"bars out {total('bars_out')} | unmapped bars excluded {total('bars_unmapped')} "
        f"(max {max((d.unmapped_tickers for d in days), default=0)} tickers/day) | "
        f"untraded rows {total('untraded_rows')} | "
        f"expected unselected (Massive-only slots) {total('massive_only')}",
        flush=True,
    )


def _trimmed_entry(v: SpanVerdict, window: tuple[date, date]) -> dict[str, Any]:
    """One span that failed an edge: what was loaded and the gap days inside the year (the
    incumbent keeps them)."""
    iso = lambda d: None if d is None else d.isoformat()  # noqa: E731
    trimmed = v.trimmed
    return {
        "symbol": v.span.symbol,
        "ticker": v.span.ticker,
        "reason": v.reason,
        "valid_from": iso(v.span.valid_from),
        "valid_to": iso(v.span.valid_to),
        "loaded_from": trimmed and iso(trimmed.valid_from),
        "loaded_to": trimmed and iso(trimmed.valid_to),
        "gap_days": [d.isoformat() for d in v.trimmed_days if window[0] <= d <= window[1]],
    }


def _write_report(
    args, reports: dict[int, list[DayReport]], verdicts: dict[int, list[SpanVerdict]]
) -> None:
    out = (
        args.out
        or _LOG_DIR / f"massive_load_dryrun_{args.timeframe}_{'-'.join(map(str, args.years))}.json"
    )
    payload = {
        "timeframe": args.timeframe,
        "years": args.years,
        "apply": args.apply,
        "spans": {str(y): verdict_table(v) for y, v in verdicts.items()},
        "trimmed_spans": {
            str(y): [_trimmed_entry(v, (date(y, 1, 1), date(y, 12, 31))) for v in vs if v.reason]
            for y, vs in verdicts.items()
        },
        "span_presence": {
            str(y): [
                {
                    "symbol": v.span.symbol,
                    "ticker": v.span.ticker,
                    "sessions": v.n_window_sessions,
                    "present": v.n_window_present,
                }
                for v in vs
                if v.loadable
            ]
            for y, vs in verdicts.items()
        },
        "days": {
            str(year): [d.__dict__ | {"day": d.day.isoformat()} for d in days]
            for year, days in reports.items()
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, default=str))
    print(f"report: {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeframe", required=True, choices=["5m", "1d"])
    parser.add_argument("--years", required=True, nargs="+", type=int, help="newest first")
    parser.add_argument("--gap-list", type=Path, default=None, help="default: newest identity map")
    parser.add_argument("--month", type=int, default=None, choices=range(1, 13), help="one month")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = parser.parse_args(argv)
    if args.years != sorted(args.years, reverse=True):
        parser.error("--years must be newest first")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
