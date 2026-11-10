"""Massive flat-file reader: one day file in, per-ticker 5m (or served 1d) frames out.

Pure compute over arrays. The only side effect is reading the file handed in (never written).
Definitions are code constants with tests, not APR keys: a switch on any of them would change
canonical bars without a reselect (admission design section 3).

Minute reader, in this order (design section 4):

1. Cut minutes to the NYSE regular session first: open inclusive, close exclusive, early closes
   and the irregular 15:56 close of 2005-06-01 come from ``nyse_sessions``. Cutting before
   aggregation keeps an after-close minute out of the last bucket.
2. Bucket by the 5-minute floor of ``window_start`` (UTC nanoseconds).
3. Per bucket, from traded minutes only: first open, max high, min low, last close, summed
   volume. A bucket with no traded minute has no bar (no_fill). A row with volume at or below
   zero is not a traded minute and is excluded, counted in ``n_untraded_rows``.
4. Volume is summed exactly, then rounded half to even once per bucket to an integer. Files from
   2026-02-23 carry fractional volume (at most 6 decimals); the reader holds volume as integer
   microshares so the sum and the tie rule are exact, with no float drift. A value with more
   than 6 decimals raises rather than rounding silently.
5. ``transactions`` is not loaded.

Prices are as served (unadjusted); the adjustment basis is a selection concern (section 5).

Loud failures (a file is never silently emptied): a file with rows but no in-session minute, a
row outside the 04:00 to 20:00 ET (inclusive) extended-hours window of its trading date (a mis-dated file),
a duplicate (ticker, window_start), a null, or a volume past 6 decimals.

Definitions worth knowing: the session open is floored to the 5m grid by ``nyse_sessions`` (the
delayed 09:32 open of 2006-12-27 cuts at 09:30 and the first bar is the first trade); the last
bucket of an irregular close (15:56 on 2005-06-01) holds only the in-session minutes; a bar can
carry volume 0 when its summed fractional volume rounds below one share.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from src.intelligence.bars.sessions import nyse_sessions

#: Aggregation bucket width. A definition of the 5m grid, not a tunable.
BUCKET_NS = 300 * 1_000_000_000
#: Volume is read as integer microshares: the finest fractional volume Massive serves is 6 decimals.
VOLUME_SCALE = 1_000_000
#: Relative slack for the float product ``volume * VOLUME_SCALE`` (about two float64 ulps).
_FLOAT_REL_TOL = 4e-16
#: Columns read from a minute or day file (``transactions`` is deliberately absent).
_PRICE_COLUMNS = ("open", "high", "low", "close")
_READ_COLUMNS = ("ticker", "volume", *_PRICE_COLUMNS, "window_start")
_SESSION_TZ = ZoneInfo("America/New_York")
_FILE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\.csv\.gz$")


@dataclass(frozen=True)
class FlatBars:
    """Bars as parallel arrays sorted by (ticker, t_ns); ``ticker_index`` points into ``tickers``.

    ``volume`` is whole shares (int64) for both the aggregated 5m bars and a day file.
    """

    tickers: np.ndarray
    ticker_index: np.ndarray
    t_ns: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    n_untraded_rows: int = 0
    # in-session traded minute rows per ticker (aligned with ``tickers``; empty for a day file),
    # so a loader can balance minutes in against bars out per instrument
    traded_minutes: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.t_ns)

    def frames(self, symbols: Collection[str] | None = None) -> dict[str, pd.DataFrame]:
        """Per-ticker canonical ``t, o, h, l, c, v`` frames (the ``VendorIngress`` contract),
        restricted to ``symbols`` when given."""
        out: dict[str, pd.DataFrame] = {}
        if len(self) == 0:
            return out
        starts = np.flatnonzero(np.r_[True, self.ticker_index[1:] != self.ticker_index[:-1]])
        ends = np.r_[starts[1:], len(self)]
        stamps = pd.to_datetime(self.t_ns, unit="ns", utc=True)
        for start, end in zip(starts, ends, strict=True):
            name = str(self.tickers[self.ticker_index[start]])
            if symbols is not None and name not in symbols:
                continue
            out[name] = pd.DataFrame(
                {
                    "t": stamps[start:end],
                    "o": self.open[start:end],
                    "h": self.high[start:end],
                    "l": self.low[start:end],
                    "c": self.close[start:end],
                    "v": self.volume[start:end],
                }
            )
        return out


def _read_table(path: Path) -> pa.Table:
    """The file's columns with pinned types, so int-vs-float inference never changes the result."""
    convert = pacsv.ConvertOptions(
        include_columns=list(_READ_COLUMNS),
        column_types={
            "ticker": pa.string(),
            "volume": pa.float64(),
            "window_start": pa.int64(),
            **{name: pa.float64() for name in _PRICE_COLUMNS},
        },
    )
    table = pacsv.read_csv(path, convert_options=convert)
    nulls = {name: table[name].null_count for name in table.column_names if table[name].null_count}
    if nulls:
        raise ValueError(f"{path}: null values {nulls}")
    return table


def _codes(table: pa.Table) -> tuple[np.ndarray, np.ndarray]:
    """Ticker dictionary (sorted names) and the per-row code."""
    encoded = pc.dictionary_encode(table["ticker"]).combine_chunks()
    names = encoded.dictionary.to_numpy(zero_copy_only=False)
    order = np.argsort(names, kind="stable")
    rank = np.empty(len(order), dtype=np.int32)
    rank[order] = np.arange(len(order), dtype=np.int32)
    codes = encoded.indices.to_numpy(zero_copy_only=False)
    return names[order], rank[codes]


def _volume_microshares(volume: np.ndarray) -> np.ndarray:
    """Exact integer microshares from served float volume; raises past 6 decimals."""
    product = volume * VOLUME_SCALE
    scaled = np.rint(product)
    # float64 spacing near 1e15 microshares is 0.125, so the tolerance grows with the magnitude
    if not np.allclose(scaled, product, rtol=_FLOAT_REL_TOL, atol=1e-3):
        raise ValueError("volume carries more than 6 decimals; the exact-sum rule does not hold")
    micro: np.ndarray = scaled.astype(np.int64)
    return micro


def round_half_even_microshares(micro: np.ndarray) -> np.ndarray:
    """Round integer microshares to whole shares, ties to the even integer (exact integer math)."""
    whole, rest = np.divmod(micro, VOLUME_SCALE)
    half = VOLUME_SCALE // 2
    up = (rest > half) | ((rest == half) & (whole % 2 == 1))
    rounded: np.ndarray = whole + up.astype(np.int64)
    return rounded


def aggregate_minutes_to_5m(
    tickers: np.ndarray,
    ticker_index: np.ndarray,
    window_start_ns: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume_micro: np.ndarray,
    *,
    session_open_ns: int,
    session_close_ns: int,
) -> FlatBars:
    """Session cut, 5m bucket and traded-minute aggregation over minute arrays (pure).

    Inputs may arrive in any order and are sorted here. ``(ticker, window_start)`` must be unique.
    """
    in_session = (window_start_ns >= session_open_ns) & (window_start_ns < session_close_ns)
    if len(window_start_ns) and not in_session.any():
        raise ValueError("rows but no in-session minute: a mis-dated or non-session file")
    traded = in_session & (volume_micro > 0)
    n_untraded = int(np.count_nonzero(in_session & ~traded))
    keep = np.flatnonzero(traded)
    traded_minutes = np.bincount(ticker_index[keep], minlength=len(tickers))
    code, stamp = ticker_index[keep], window_start_ns[keep]
    order = np.lexsort((stamp, code))
    keep, code, stamp = keep[order], code[order], stamp[order]
    open_, high, low, close, volume_micro = (
        a[keep] for a in (open_, high, low, close, volume_micro)
    )
    if len(stamp) > 1 and np.any((code[1:] == code[:-1]) & (stamp[1:] == stamp[:-1])):
        raise ValueError("duplicate (ticker, window_start) minute rows")
    bucket = stamp - stamp % BUCKET_NS
    if len(keep) == 0:
        empty = np.empty(0)
        return FlatBars(
            tickers,
            code,
            bucket,
            empty,
            empty,
            empty,
            empty,
            empty.astype(np.int64),
            n_untraded,
            traded_minutes,
        )
    starts = np.flatnonzero(np.r_[True, (code[1:] != code[:-1]) | (bucket[1:] != bucket[:-1])])
    last = np.r_[starts[1:], len(keep)] - 1
    return FlatBars(
        tickers=tickers,
        ticker_index=code[starts],
        t_ns=bucket[starts],
        open=open_[starts],
        high=np.maximum.reduceat(high, starts),
        low=np.minimum.reduceat(low, starts),
        close=close[last],
        volume=round_half_even_microshares(np.add.reduceat(volume_micro, starts)),
        n_untraded_rows=n_untraded,
        traded_minutes=traded_minutes,
    )


def session_bounds_ns(trading_date: date) -> tuple[int, int]:
    """NYSE regular session [open, close) of a trading date as UTC nanoseconds."""
    session = nyse_sessions(trading_date, trading_date).get(trading_date)
    if session is None:
        raise ValueError(f"{trading_date} is not an NYSE session")
    open_dt, close_dt = session
    return int(open_dt.timestamp()) * 1_000_000_000, int(close_dt.timestamp()) * 1_000_000_000


def extended_bounds_ns(trading_date: date) -> tuple[int, int]:
    """UTC nanoseconds of the first and last minute starts an extended-hours file can hold: 04:00
    and 20:00 ET, both inclusive (the archive has late prints stamped exactly 20:00 ET)."""

    def at(hour: int) -> int:
        stamp = datetime.combine(trading_date, time(hour), tzinfo=_SESSION_TZ)
        return int(stamp.timestamp()) * 1_000_000_000

    return at(4), at(20)


def file_trading_date(path: Path) -> date:
    """The trading date a ``YYYY-MM-DD.csv.gz`` flat file is named for."""
    match = _FILE_DATE.search(path.name)
    if match is None:
        raise ValueError(f"{path}: not a YYYY-MM-DD.csv.gz flat file")
    return date.fromisoformat(match.group(1))


def read_minute_file(path: Path, trading_date: date | None = None) -> FlatBars:
    """One ``minute_aggs_v1`` day file -> regular-session 5m bars (read-only on the file)."""
    path = Path(path)
    day = trading_date or file_trading_date(path)
    table = _read_table(path)
    names, codes = _codes(table)
    open_ns, close_ns = session_bounds_ns(day)
    first_ns, last_ns = extended_bounds_ns(day)
    stamps = table["window_start"].to_numpy()
    if len(stamps) and (stamps.min() < first_ns or stamps.max() > last_ns):
        raise ValueError(f"{path}: rows outside the 04:00 to 20:00 ET window of {day}")
    return aggregate_minutes_to_5m(
        names,
        codes,
        stamps,
        table["open"].to_numpy(),
        table["high"].to_numpy(),
        table["low"].to_numpy(),
        table["close"].to_numpy(),
        _volume_microshares(table["volume"].to_numpy()),
        session_open_ns=open_ns,
        session_close_ns=close_ns,
    )


def read_day_file(path: Path) -> FlatBars:
    """One ``day_aggs_v1`` file as served except volume, rounded half to even to whole shares by
    the same rule as the minute reader (the archived file keeps the served float). Unadjusted,
    ``window_start`` as served, one row per ticker; nothing is cut or aggregated."""
    path = Path(path)
    table = _read_table(path)
    names, codes = _codes(table)
    order = np.argsort(codes, kind="stable")
    if np.any(np.diff(codes[order]) == 0):
        raise ValueError(f"{path}: more than one day row for a ticker")
    return FlatBars(
        tickers=names,
        ticker_index=codes[order],
        t_ns=table["window_start"].to_numpy()[order],
        open=table["open"].to_numpy()[order],
        high=table["high"].to_numpy()[order],
        low=table["low"].to_numpy()[order],
        close=table["close"].to_numpy()[order],
        volume=round_half_even_microshares(_volume_microshares(table["volume"].to_numpy())[order]),
    )
