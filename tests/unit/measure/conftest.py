"""Synthetic panels for the measure tests."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.measure.params import MeasureParams
from src.intelligence.research.panel import Panel

N_SYMBOLS = 12
SLOTS = 26


def make_panel(
    symbols: tuple[str, ...],
    n_sessions: int,
    bars_per_session: int,
    *,
    seed: int = 0,
    start: str = "2026-01-05",
    nan_open_rows: tuple[int, ...] = (),
    tf: str | None = None,
) -> Panel:
    rng = np.random.default_rng(seed)
    n = n_sessions * bars_per_session
    m = len(symbols)
    open_ = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(n, m)), axis=0))
    for row in nan_open_rows:
        open_[row, 0] = np.nan
    if bars_per_session == 1:
        stamps = np.datetime64(start, "D") + np.arange(n)
        tf_name = tf or "1d"
    else:
        days = np.datetime64(start, "D") + np.arange(n_sessions)
        slot = np.arange(bars_per_session) * 15
        base = days.astype("datetime64[m]") + np.timedelta64(13 * 60 + 30, "m")
        stamps = (base[:, None] + slot[None, :].astype("timedelta64[m]")).ravel()
        tf_name = tf or "15m"
    return Panel(
        tf=tf_name,
        symbols=symbols,
        timestamps=stamps,
        bars_per_session=bars_per_session,
        valid=np.ones(n, dtype=bool),
        open=open_,
        close=open_ * 1.001,
        volume=np.full((n, m), 1000.0),
    )


@pytest.fixture
def symbols() -> tuple[str, ...]:
    return tuple(f"S{j:02d}" for j in range(N_SYMBOLS))


@pytest.fixture
def daily_panel_fx(symbols):
    return make_panel(symbols, 60, 1, nan_open_rows=(7, 30))


@pytest.fixture
def intraday_panel_fx(symbols):
    return make_panel(symbols, 10, SLOTS, nan_open_rows=(SLOTS * 3 - 1,))


@pytest.fixture
def params() -> MeasureParams:
    return MeasureParams(
        min_stride=1,
        bootstrap_block_size=5,
        bootstrap_resamples=50,
        rng_seed=7,
        fdr_alpha=0.05,
        min_obs=30,
        symbol_chunk_size=5,
        bootstrap_threads=1,
        bootstrap_chunk_resamples=20,
        monitor_window_sessions=10,
        hac_max_lag=2,
        degenerate_std=1e-8,
        monitor_degenerate_std=1e-10,
    )


def all_present(shape: tuple[int, int]) -> np.ndarray:
    """Every (bar, symbol) slot received a feature row."""
    return np.ones(shape, dtype=bool)
