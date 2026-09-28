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


# The migration-381 APR seeds plus the reused alpha.quant.*/alpha.forward_returns.*
# keys, exactly as they live in config_state (plan 05's known-answer tests build
# ScrubParams from this mirror; the values are pinned by plan 04's migration).
_SEEDED_APR: dict[str, object] = {
    "threshold.bar_scrub.jump_sigma": 8.0,
    "threshold.bar_scrub.jump_vol_window": 60,
    "threshold.bar_scrub.stale_run_min": 5,
    "threshold.bar_scrub.volume_outlier_mad": 10.0,
    "threshold.bar_scrub.volume_window": 60,
    "threshold.bar_scrub.corroboration_max_clearable_ratio": 2.5,
    "threshold.bar_scrub.view_disagreement_rel": 0.02,
    "threshold.bar_scrub.quarantine_rules": (
        '["ohlc_invariant","non_positive_price","price_sanity",'
        '"split_seam","legacy_price_sanity_status"]'
    ),
    "infra.bar_scrub.symbol_batch": 50,
    "alpha.quant.price_sanity.magnitude_threshold": 10.0,
    "alpha.quant.price_sanity.neighbor_agreement_threshold": 2.0,
    "alpha.quant.cross_symbol_corroboration.min_symbols": 4,
    "alpha.quant.cross_symbol_corroboration.window_minutes": 60,
    "alpha.quant.max_abs_return.1d": 0.50,
    "alpha.quant.max_abs_return.5m": 0.25,
    "alpha.forward_returns.gap_multiplier": 3,
    "alpha.forward_returns.gap_max_seconds": 14400,
}


def seeded_apr() -> dict[str, object]:
    """Copy of the seeded APR mirror (mutations by a test stay local)."""
    return dict(_SEEDED_APR)


def three_bar_window(row: dict, *, step_seconds: int = 86_400) -> tuple[dict[str, np.ndarray], int]:
    """Rebuild a report/CSV row as a three-bar window plus its middle index.

    The previous bar is a flat bar whose close is the row's prev_close, the next bar
    a flat bar whose open is the row's next_open; either neighbor is omitted when the
    row reports it as None/empty (series boundary). Returns (arrays, middle_index)
    where arrays is keyed by the SymbolBars field names (ts_seconds/open/high/low/
    close/volume). Neighbor volume is a token positive print: no volume- or
    window-based rule can fire on a three-bar window, so only the neighbor prices
    are load-bearing here.
    """
    ts = int(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp())
    stamps: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    def _flat(price: float, stamp: int) -> None:
        stamps.append(stamp)
        opens.append(price)
        highs.append(price)
        lows.append(price)
        closes.append(price)
        volumes.append(1.0)

    prev_close = row.get("prev_close")
    next_open = row.get("next_open")
    if prev_close is not None and prev_close != "":
        _flat(float(prev_close), ts - step_seconds)
    middle = len(stamps)
    stamps.append(ts)
    opens.append(float(row["open"]))
    highs.append(float(row["high"]))
    lows.append(float(row["low"]))
    closes.append(float(row["close"]))
    volumes.append(float(row["volume"]) if row.get("volume") is not None else 0.0)
    if next_open is not None and next_open != "":
        _flat(float(next_open), ts + step_seconds)
    return {
        "ts_seconds": np.array(stamps, dtype=np.int64),
        "open": np.array(opens, dtype=np.float64),
        "high": np.array(highs, dtype=np.float64),
        "low": np.array(lows, dtype=np.float64),
        "close": np.array(closes, dtype=np.float64),
        "volume": np.array(volumes, dtype=np.float64),
    }, middle
