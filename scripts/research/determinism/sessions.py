"""Session-axis helpers. `sessions` is always the sorted session array (datetime64[D]) the S0
snapshot builds from every universe symbol's 1d feature-row dates (snapshot.session_calendar).

Promoted from scripts/analysis/sleeve_walk_forward/sessions.py (phase 186-03, D-11): only
refit_dates moves; label_cutoff belongs to the deleted refit path.
"""

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
