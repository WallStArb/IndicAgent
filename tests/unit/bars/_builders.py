"""Shared synthetic bar-series and fake-session builders for tests/unit/bars.

Pure functions only: no database, no filesystem except load_dry_run_report's read of
the committed fixture report. Series are built the same way the dividend-writer tests
build theirs: a seeded log-normal random walk rounded to the cent, with OHLC fields
derived so the invariants (high >= max(open, close), low <= min(open, close)) always
hold unless a test deliberately breaks them.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_ET = ZoneInfo("America/New_York")

_FIXTURE_REPORT = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "bars"
    / ("corrupt_1d_dry_run_2026_09_26.txt")
)

_SECTIONS = ("CONFIRMED_CORRUPT", "MARKET_EVENT", "AMBIGUOUS", "PLAUSIBLE")

_NUMERIC_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "prev_close",
        "next_open",
        "max_ratio",
        "neighbor_ratio",
    }
)


def random_walk_closes(n: int, start_price: float, seed: int, sigma: float = 0.012) -> np.ndarray:
    """Seeded log-normal random walk of n closes, rounded to the cent."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma, n)
    return np.round(start_price * np.exp(np.cumsum(steps)), 2)


def daily_bars(
    dates: list[pd.Timestamp],
    closes: np.ndarray,
    *,
    spread: float = 0.005,
    volume: int = 1_000_000,
) -> dict[str, np.ndarray]:
    """Build a daily bar series from closes with OHLC invariants holding.

    open is the prior close (first bar opens at its own close), high and low widen
    max(open, close) / min(open, close) by the relative spread. Returns arrays keyed
    open/high/low/close/volume/date.
    """
    closes = np.asarray(closes, dtype=float)
    open_ = np.empty_like(closes)
    open_[0] = closes[0]
    open_[1:] = closes[:-1]
    high = np.maximum(open_, closes) * (1.0 + spread)
    low = np.minimum(open_, closes) * (1.0 - spread)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": closes,
        "volume": np.full(len(closes), volume, dtype=np.int64),
        "date": np.array(dates, dtype=object),
    }


def fake_session(
    date_str: str, open_hhmm_et: str, close_hhmm_et: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Session open/close as UTC timestamps for an America/New_York wall-clock time.

    DST-correct: "2025-03-10" 09:30 ET is 13:30 UTC (EDT), "2025-11-03" 09:30 ET is
    14:30 UTC (EST).
    """
    d = pd.Timestamp(date_str).date()

    def _et(hhmm: str) -> pd.Timestamp:
        h, m = (int(part) for part in hhmm.split(":"))
        return pd.Timestamp(datetime.combine(d, time(h, m), tzinfo=_ET)).tz_convert(UTC)

    return _et(open_hhmm_et), _et(close_hhmm_et)


def five_minute_bars(
    session_open_utc: pd.Timestamp,
    session_close_utc: pd.Timestamp,
    seed: int,
) -> dict[str, np.ndarray]:
    """Five-minute bars stamped at bar start inside [session_open, session_close).

    Bar count is the exact session span divided by five minutes (78 for a full
    session, 42 for the 2025-11-28 early close), so a derived grid can be checked
    bar-for-bar against these inputs.
    """
    span = session_close_utc - session_open_utc
    n = int(span.total_seconds() // 300)
    if n < 1:
        raise ValueError(f"session span {span} yields no five-minute bars")
    closes = random_walk_closes(n, 100.0, seed)
    open_ = np.empty_like(closes)
    open_[0] = closes[0]
    open_[1:] = closes[:-1]
    high = np.maximum(open_, closes) * 1.002
    low = np.minimum(open_, closes) * 0.998
    stamps = pd.date_range(session_open_utc, periods=n, freq="5min")
    return {
        "timestamp": stamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": closes,
        "volume": np.full(n, 10_000, dtype=np.int64),
    }


def load_dry_run_report(section: str) -> list[dict]:
    """Parse the committed dry-run report fixture by section name.

    section is one of CONFIRMED_CORRUPT / MARKET_EVENT / AMBIGUOUS / PLAUSIBLE.
    Returns one dict per markdown table row, numeric fields cast to float, with the
    symbol/tf/timestamp/implausible_fields/reason columns kept as strings.
    """
    if section not in _SECTIONS:
        raise ValueError(f"unknown section {section!r}, expected one of {_SECTIONS}")
    lines = _FIXTURE_REPORT.read_text().splitlines()
    column_names: list[str] = []
    rows: list[dict] = []
    in_section = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            in_section = line[3:].startswith(section)
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if not column_names:
            column_names = cells
            continue
        row = dict(zip(column_names, cells, strict=True))
        for field in _NUMERIC_FIELDS & row.keys():
            raw = row[field]
            if raw in ("None", "", "n/a"):
                row[field] = None
            else:
                row[field] = float("inf") if raw == "inf" else float(raw)
        rows.append(row)
    if not rows:
        raise ValueError(f"section {section} has no rows in {_FIXTURE_REPORT}")
    return rows
