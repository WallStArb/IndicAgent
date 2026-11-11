"""Massive per-year loader for 5m and 1d, newest year first (todo 600, design section 8 step 5).

Dry run is the default and the only mode run so far: it reads the day files of the year, maps
file tickers to instruments through the evidenced ticker_event spans, and prints what step 5's
gate checks (docs/plans/2026-11-10-massive-admission-db-design.md):

- spans loaded and spans edge-failed, by reason (a span whose ticker string is not served at its
  first and last archive session is not loaded and keeps the incumbent);
- row balance per year: traded minutes in, bars out, unmapped tickers excluded and counted;
- expected unselected slots: the Massive-only on-grid slots, i.e. mapped bars whose
  (instrument, slot) no incumbent vendor holds in ohlcv_raw. While Massive is unranked each one
  reports UNSELECTED, so the live load's unselected count must equal this number.

`--apply` writes through the shared load engine (``load_series``), one day file per call, each
with its lineage (file key, ETag, sha256, the ticker_event used, untraded rows, the volume
definition epoch; the selection horizon is added by the contract). No real load has been run:
the lead rules on the first year after the gates.

The loader fails loudly, before reading a file, when an active instrument has neither a span nor
a gap-list row.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pyarrow.csv as pacsv

from services.bar_load import LoadPolicy, load_series
from services.ohlcv_ingress_contract import read_raw_params
from src.config.settings import get_settings
from src.intelligence.bars.massive_flat import FlatBars, file_trading_date
from src.intelligence.bars.massive_symbol_map import (
    SpanVerdict,
    TickerSpan,
    judge_span,
    tickers_on,
    unaccounted_instruments,
)
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


def account_day(
    day: date,
    bars: FlatBars,
    mapping: dict[str, TickerSpan],
    incumbent: set[tuple[str, Any]],
    slot_of,
) -> DayReport:
    """The row balance of one day file against the ticker map and the incumbent slots.
    `incumbent` holds (symbol, slot) of every incumbent raw row of the day; `slot_of(t_ns)` maps
    a bar stamp to the slot key (a UTC stamp for 5m, a session date for 1d)."""
    names = bars.tickers[bars.ticker_index]
    mapped_mask = np.isin(names, list(mapping)) if mapping else np.zeros(len(names), dtype=bool)
    report = DayReport(day, file_tickers=len(bars.tickers))
    report.mapped_tickers = len({str(n) for n in names[mapped_mask]})
    report.unmapped_tickers = len(bars.tickers) - report.mapped_tickers
    report.bars_out = int(mapped_mask.sum())
    report.bars_unmapped = int((~mapped_mask).sum())
    report.untraded_rows = bars.n_untraded_rows
    if bars.traded_minutes is not None:
        report.traded_minutes_in = int(bars.traded_minutes.sum())
        mapped_names = set(mapping)
        in_map = np.array([str(t) in mapped_names for t in bars.tickers], dtype=bool)
        report.traded_minutes_mapped = int(bars.traded_minutes[in_map].sum())
    report.unmapped_sample = sorted({str(n) for n in names[~mapped_mask]})[:5]
    for name, t_ns in zip(names[mapped_mask], bars.t_ns[mapped_mask], strict=True):
        if (mapping[str(name)].symbol, slot_of(int(t_ns))) not in incumbent:
            report.massive_only += 1
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


class ArchiveIndex:
    """The archive's sessions and the ticker strings each served, from the day files (one column
    read per file, cached)."""

    def __init__(self, root: Path = MASSIVE_FILES_ROOT) -> None:
        self._files = {
            file_trading_date(p): p for p in sorted((root / "day_aggs_v1").rglob("*.csv.gz"))
        }
        self.sessions = sorted(self._files)
        self._cache: dict[date, frozenset[str]] = {}

    def present_on(self, day: date) -> frozenset[str]:
        if day not in self._cache:
            table = pacsv.read_csv(
                self._files[day], convert_options=pacsv.ConvertOptions(include_columns=["ticker"])
            )
            self._cache[day] = frozenset(table["ticker"].to_pylist())
        return self._cache[day]


def incumbent_slots(
    cur: Any, timeframe: str, first: date, last: date
) -> dict[date, set[tuple[str, Any]]]:
    """(symbol, slot) of every incumbent raw row of the sessions first..last (inclusive), by
    session date: the 5m stamp (UTC date), or the 1d session date (IBKR stamps 1d at 00:00 UTC,
    Alpaca at midnight New York). One query per range."""
    slots: dict[date, set[tuple[str, Any]]] = {}
    if timeframe == "5m":
        cur.execute(
            "SELECT symbol, \"timestamp\" FROM ohlcv_raw WHERE timeframe = '5m' "
            'AND vendor = ANY(%s) AND "timestamp" >= %s AND "timestamp" < %s',
            (
                list(_INCUMBENT_VENDORS),
                datetime.combine(first, datetime.min.time(), UTC),
                datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC),
            ),
        )
        for symbol, stamp in cur.fetchall():
            slots.setdefault(stamp.astimezone(UTC).date(), set()).add((symbol, stamp))
        return slots
    cur.execute(
        "SELECT symbol, CASE WHEN vendor = 'alpaca' THEN (\"timestamp\" AT TIME ZONE "
        "'America/New_York')::date ELSE (\"timestamp\" AT TIME ZONE 'UTC')::date END "
        "FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = ANY(%s) "
        'AND "timestamp" >= %s::date - 1 AND "timestamp" < %s::date + 2',
        (list(_INCUMBENT_VENDORS), first, last),
    )
    for symbol, session in cur.fetchall():
        if first <= session <= last:
            slots.setdefault(session, set()).add((symbol, session))
    return slots


class IncumbentSlots:
    """Incumbent slots by session, fetched one calendar month at a time (the per-day query was the
    dry run's cost: 853 s a year)."""

    def __init__(self, conn: Any, timeframe: str) -> None:
        self._conn, self._timeframe = conn, timeframe
        self._month: tuple[int, int] | None = None
        self._slots: dict[date, set[tuple[str, Any]]] = {}

    def of(self, day: date) -> set[tuple[str, Any]]:
        if self._month != (day.year, day.month):
            first = day.replace(day=1)
            last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            with self._conn.cursor() as cur:
                self._slots = incumbent_slots(cur, self._timeframe, first, last)
            self._month = (day.year, day.month)
        return self._slots.get(day, set())


def _slot_of(timeframe: str, day: date):
    if timeframe == "5m":
        return lambda t_ns: datetime.fromtimestamp(t_ns / 1_000_000_000, UTC)
    return lambda _t_ns: day


def year_files(timeframe: str, year: int, root: Path = MASSIVE_FILES_ROOT) -> list[Path]:
    dataset = "minute_aggs_v1" if timeframe == "5m" else "day_aggs_v1"
    return sorted((root / dataset / f"{year}").rglob("*.csv.gz"), reverse=True)  # newest first


def verdict_table(verdicts: list[SpanVerdict]) -> dict[str, int]:
    counts = Counter(
        "loaded" if v.reason is None else f"trimmed:{v.reason}" if v.loadable else v.reason
        for v in verdicts
    )
    return dict(sorted(counts.items()))


def run(args: argparse.Namespace) -> int:
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
        for year in args.years:
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
            reports[year] = []
            for path in year_files(args.timeframe, year):
                day = file_trading_date(path)
                bars = _read(args.timeframe, path)
                mapping = tickers_on(loadable, day)
                reports[year].append(
                    account_day(day, bars, mapping, slots.of(day), _slot_of(args.timeframe, day))
                )
                if args.apply:
                    _apply(conn, ingress, path, day, bars, mapping)
            _print_year(args.timeframe, year, reports[year], time.monotonic() - t0)
        _write_report(args, reports, verdicts)
    finally:
        conn.close()
    return 0


def _read(timeframe: str, path: Path) -> FlatBars:
    from src.intelligence.bars.massive_flat import read_day_file, read_minute_file

    return read_minute_file(path) if timeframe == "5m" else read_day_file(path)


def _apply(conn, ingress, path: Path, day: date, bars: FlatBars, mapping) -> None:
    """Write one day file's mapped frames through the load engine, each with its lineage."""
    record = manifest_record(path)
    answered_at = massive_answered_at(path, "")
    policy = LoadPolicy(
        vendor=ingress.source,
        timeframe=ingress.timeframe,
        caller=f"massive-{ingress.timeframe}-load",
        kind=ingress.kind,
    )
    with conn.cursor() as cur:
        params = read_raw_params(cur)
        epoch = volume_epoch_id(cur, day)
    frames = ingress.read_artifacts(path, list(mapping))
    for ticker, frame in frames.items():
        span = mapping[ticker]
        load_series(
            conn,
            policy,
            span.symbol,
            frame,
            params=params,
            write=True,
            answered_at=answered_at,
            lineage={
                "file_key": record["key"],
                "etag": record["etag"],
                "sha256": record["sha256"],
                "ticker_event_id": span.ticker_event_id,
                "ticker": ticker,
                "n_untraded_rows": bars.n_untraded_rows,
                "definition_epoch_id": epoch,
            },
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
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = parser.parse_args(argv)
    if args.years != sorted(args.years, reverse=True):
        parser.error("--years must be newest first")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
