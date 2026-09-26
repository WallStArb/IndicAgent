"""The Panel: S0's output, one (universe, tf, span) as dense [row, symbol] arrays.

A 1d panel has one row per session. An intraday panel is a regular grid: every session has the
same `bars_per_session` slots in the same time-of-day order, and a slot with no bar is a NaN row
(`valid` False where no symbol traded it, as on a half day). The grid is what lets the null
shift by whole sessions while every bar keeps its time of day (evaluate.session_shifts), and it
is what panel_null's dense-panel requirement asks for.

Missing prices are NaN, never filled: a missing input gives no position downstream.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np

from src.intelligence.research import store

_PRICE_FIELDS = ("open", "close", "volume")


@dataclasses.dataclass(frozen=True)
class Panel:
    tf: str
    symbols: tuple[str, ...]
    timestamps: np.ndarray  # [n]; datetime64[D] session dates on 1d, slot starts (UTC) intraday
    bars_per_session: int
    valid: np.ndarray  # bool [n], False for a grid slot no symbol traded
    open: np.ndarray  # [n, m], NaN where missing
    close: np.ndarray  # [n, m]
    volume: np.ndarray  # [n, m]
    # Legacy: each symbol's flat sector label, captured by S0 until 2026-09-25 and kept only so
    # older snapshots load (scripts/analysis/s1_grouping_comparison.py reads its own). S0 no
    # longer fills it: a present-day label on a historical panel is reference-data lookahead,
    # and phase 182 stopped maintaining the flat label. S1 groups names by prices.
    sectors: tuple[str, ...] = ()
    manifest: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        n, m = len(self.timestamps), len(self.symbols)
        if n % self.bars_per_session:
            raise ValueError(
                f"{n} rows is not a whole number of {self.bars_per_session}-bar sessions"
            )
        for name in _PRICE_FIELDS:
            if getattr(self, name).shape != (n, m):
                raise ValueError(f"{name} has shape {getattr(self, name).shape}, expected {(n, m)}")
        if self.valid.shape != (n,):
            raise ValueError("valid must be one entry per row")
        if self.sectors and len(self.sectors) != m:
            raise ValueError(f"{len(self.sectors)} sectors for {m} symbols")

    @property
    def n_sessions(self) -> int:
        return len(self.timestamps) // self.bars_per_session

    @property
    def session(self) -> np.ndarray:
        """int [n], each row's 0-based session index (the grid is regular)."""
        return np.repeat(np.arange(self.n_sessions), self.bars_per_session)


def daily_panel(
    closes: np.ndarray,
    *,
    dates: np.ndarray | None = None,
    opens: np.ndarray | None = None,
    symbols: tuple[str, ...] | None = None,
    volume: np.ndarray | None = None,
    manifest: dict | None = None,
) -> Panel:
    """A 1d Panel over given arrays (a sleeve snapshot's, or synthetic prices). Absent opens or
    volume are NaN; absent dates are consecutive days, absent symbols positional names."""
    n, m = closes.shape
    nan = np.full((n, m), np.nan)
    return Panel(
        tf="1d",
        symbols=symbols if symbols is not None else tuple(f"s{j}" for j in range(m)),
        timestamps=(
            dates if dates is not None else np.datetime64("2000-01-03", "D") + np.arange(n)
        ),
        bars_per_session=1,
        valid=np.ones(n, dtype=bool),
        open=opens if opens is not None else nan,
        close=closes,
        volume=volume if volume is not None else nan,
        manifest=manifest or {},
    )


def forward_returns(
    opens: np.ndarray,
    horizon: int = 1,
    session: np.ndarray | None = None,
    closes: np.ndarray | None = None,
) -> np.ndarray:
    """fwd[t] = ln(open[t + 1 + horizon] / open[t + 1]): alpha at row t's close, enter at the
    next open, exit `horizon` rows later at an open (Invariant 1, executable open-to-open).

    With `session` (intraday), a return whose entry and exit opens fall in different sessions
    is NaN, so no intraday target carries an overnight gap; a signal on a session's last bar
    enters at the next session's first open. The last 1 + horizon rows, and any row missing an
    open, are NaN. On a 1d panel (session None, horizon 1) this is phase 179's target.

    With `closes` as well, an exit that would fall past the entry session's final bar exits
    instead at that bar's close (a market-on-close order), so the session's last slots get a
    target without crossing the overnight gap. The final bar is the session's last row on which
    any symbol has a close (a half day ends early); a name with no close there gets NaN, never
    an earlier close. Nothing reads the next session."""
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    if closes is not None and session is None:
        raise ValueError("a close exit needs `session` to know where each session ends")
    if session is not None and len(session) > 1 and (np.diff(session) != 0).all():
        # One row per session (a 1d panel): every return would cross a session, all NaN.
        raise ValueError("`session` is for intraday grids; a 1d panel passes session=None")
    if closes is not None:
        return _forward_returns_close_exit(opens, closes, session, horizon)
    n = opens.shape[0]
    fwd = np.full(opens.shape, np.nan)
    if n <= 1 + horizon:
        return fwd
    with np.errstate(invalid="ignore", divide="ignore"):
        fwd[: n - 1 - horizon] = np.log(opens[1 + horizon :] / opens[1 : n - horizon])
    if session is not None:
        crosses = session[1 + horizon :] != session[1 : n - horizon]
        fwd[: n - 1 - horizon][crosses] = np.nan
    return fwd


def _forward_returns_close_exit(
    opens: np.ndarray, closes: np.ndarray, session: np.ndarray, horizon: int
) -> np.ndarray:
    n = opens.shape[0]
    fwd = np.full(opens.shape, np.nan)
    rows = np.arange(n)
    has_bar = np.isfinite(closes).any(axis=1)
    final = np.full(int(session.max()) + 1, -1)
    np.maximum.at(final, session[has_bar], rows[has_bar])
    entry = rows[:-1] + 1
    last = final[session[entry]]  # entry session's final bar
    exit_row = entry + horizon
    live = entry <= last  # the entry row is not past the session's final bar
    at_open = live & (exit_row <= last)
    at_close = live & ~at_open
    t_open, t_close = rows[:-1][at_open], rows[:-1][at_close]
    with np.errstate(invalid="ignore", divide="ignore"):
        fwd[t_open] = np.log(opens[exit_row[at_open]] / opens[entry[at_open]])
        fwd[t_close] = np.log(closes[last[at_close]] / opens[entry[at_close]])
    return fwd


def fwd_span(horizon: int = 1) -> int:
    """Rows a forward return reaches past its signal row: the embargo and null memory term."""
    return 1 + horizon


def save(panel: Panel, out_dir: Path, extra: dict[str, np.ndarray] | None = None) -> Path:
    """`extra` arrays (S0's dividend grid) are written into the same content-hashed directory;
    without them the bytes are exactly those of earlier snapshots. load() ignores them."""
    arrays = {
        "timestamps": panel.timestamps,
        "valid": panel.valid,
        **{name: getattr(panel, name) for name in _PRICE_FIELDS},
        **(extra or {}),
    }
    meta = {
        "tf": panel.tf,
        "symbols": list(panel.symbols),
        "bars_per_session": panel.bars_per_session,
        "sectors": list(panel.sectors),
        "manifest": panel.manifest,
    }
    return store.write(out_dir, "panel", arrays, meta)


def load(path: Path) -> Panel:
    """Verify the content hash, then load memory-mapped."""
    store.verify(path)
    meta = store.read_meta(path)
    return Panel(
        tf=meta["tf"],
        symbols=tuple(meta["symbols"]),
        bars_per_session=int(meta["bars_per_session"]),
        sectors=tuple(meta.get("sectors", ())),  # panels saved before sectors were captured
        manifest=meta["manifest"],
        **{name: store.read_array(path, name) for name in ("timestamps", "valid", *_PRICE_FIELDS)},
    )


def bar_returns(panel: Panel) -> np.ndarray:
    """[n, m] log return of each bar: close over the previous row's close, except that a
    session's first bar on an intraday grid is its own open to close, so no bar return spans
    the overnight gap. On a 1d panel every row is close to close. NaN where either price is
    missing."""
    with np.errstate(invalid="ignore", divide="ignore"):
        log_close = np.log(np.where(panel.close > 0, panel.close, np.nan))
        out = np.full(log_close.shape, np.nan)
        out[1:] = log_close[1:] - log_close[:-1]
        if panel.bars_per_session > 1:
            first = slice(0, None, panel.bars_per_session)
            out[first] = log_close[first] - np.log(
                np.where(panel.open[first] > 0, panel.open[first], np.nan)
            )
    return out


def select_symbols(panel: Panel, symbols: list[str]) -> Panel:
    """The panel restricted to `symbols` present in it, in the panel's order. A requested symbol
    the panel lacks is not an error (the rule is S0 symbols intersected with the rule's names)."""
    keep = [j for j, s in enumerate(panel.symbols) if s in set(symbols)]
    if not keep:
        raise ValueError("the members' universe shares no symbol with the panel")
    idx = np.asarray(keep)
    return dataclasses.replace(
        panel,
        symbols=tuple(panel.symbols[j] for j in keep),
        open=np.asarray(panel.open)[:, idx],
        close=np.asarray(panel.close)[:, idx],
        volume=np.asarray(panel.volume)[:, idx],
        sectors=tuple(panel.sectors[j] for j in keep) if panel.sectors else (),
        valid=np.isfinite(np.asarray(panel.close)[:, idx]).any(axis=1),
    )
