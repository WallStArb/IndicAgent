"""S2: refit weights applied to the sleeve's features, one alpha per (session, symbol).

A session in [T_k, T_k+1) uses refit k's weights for its equity-regime stratum, composed as the
trainer does: alpha = X @ (w * ic_sign) with a NULL feature counted as 0. No label, no weights
for the day's stratum, or no feature row for the symbol gives NaN (no position), counted per
year and reason.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from scripts.analysis.sleeve_walk_forward.results import RefitOutput
from src.intelligence.research.panel import fwd_span

REASONS = ("no_label", "no_stratum_weights", "no_feature_row")


def score_panel(
    refits: list[RefitOutput],
    features: np.ndarray,
    has_row: np.ndarray,
    feature_index: dict[str, int],
    labels: np.ndarray,
    sessions: np.ndarray,
    refit_dates: list[np.datetime64],
    end: np.datetime64,
) -> tuple[np.ndarray, dict[int, dict[str, int]]]:
    if [r.refit_date for r in refits] != list(refit_dates):
        raise ValueError("refit outputs do not match the pinned refit dates, in order")
    n, m = has_row.shape
    alpha = np.full((n, m), np.nan)
    counts: dict[int, dict[str, int]] = defaultdict(lambda: dict.fromkeys(REASONS, 0))
    starts = np.searchsorted(sessions, np.array(refit_dates))
    if (starts >= len(sessions)).any() or (
        sessions[np.minimum(starts, len(sessions) - 1)] != np.array(refit_dates)
    ).any():
        raise ValueError("every refit date must be a session: no day is scored before its refit")
    stops = np.append(starts[1:], np.searchsorted(sessions, end, side="right"))
    for refit, lo, hi in zip(refits, starts, stops):
        for d in range(lo, hi):
            year = int(str(sessions[d])[:4])
            stratum = refit.strata.get(labels[d]) if labels[d] else None
            if stratum is None:
                counts[year]["no_label" if not labels[d] else "no_stratum_weights"] += m
                continue
            cols = [feature_index[f] for f in stratum.feature_names]
            x = np.nan_to_num(features[d][:, cols])
            alpha[d] = np.where(has_row[d], x @ (stratum.weights * stratum.ic_signs), np.nan)
            counts[year]["no_feature_row"] += int((~has_row[d]).sum())
    return alpha, dict(counts)


# fwd[D] reaches FWD_SPAN_SESSIONS sessions past D (exit at D+2's open; pre-registration
# section 3, research.panel.forward_returns at horizon 1).
FWD_SPAN_SESSIONS = fwd_span(1)
