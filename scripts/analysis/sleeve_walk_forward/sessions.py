"""Session-axis helpers. `sessions` is always the sorted NYSE session array (datetime64[D])
taken from the SPY 1d bar dates in the S0 snapshot."""

from __future__ import annotations

import numpy as np


def refit_dates(sessions: np.ndarray, years: range) -> list[np.datetime64]:
    out = []
    for year in years:
        in_year = sessions[
            (sessions >= np.datetime64(f"{year}-01-01"))
            & (sessions < np.datetime64(f"{year + 1}-01-01"))
        ]
        if len(in_year) == 0:
            raise ValueError(f"no session in {year}")
        out.append(in_year[0])
    return out


def label_cutoff(sessions: np.ndarray, refit: np.datetime64, embargo: int) -> int:
    """Index of the last session a training label's exit may fall on: `embargo` sessions
    before the refit date."""
    pos = int(np.searchsorted(sessions, refit))
    if pos >= len(sessions) or sessions[pos] != refit:
        raise ValueError(f"refit date {refit} is not a session")
    if pos - embargo < 0:
        raise ValueError(f"refit date {refit} has fewer than {embargo} prior sessions")
    return pos - embargo


def sub_period_masks(dates: np.ndarray, periods: tuple[tuple[str, str], ...]) -> list[np.ndarray]:
    return [(dates >= np.datetime64(a)) & (dates <= np.datetime64(b)) for a, b in periods]
