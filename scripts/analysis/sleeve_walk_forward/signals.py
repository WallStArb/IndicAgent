"""Pre-registered signal sources for the sleeve (edge-proof program, "Phase 181 queue").

The SignalSource type and its evaluation live in src/intelligence/research/signals.py; this
module pins the sources whose pre-registrations froze against this harness.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.panel import Panel
from src.intelligence.research.signals import SignalSource

# Statistic definition, APR-exempt: the 12-month lookback of Moskowitz, Ooi and Pedersen (2012)
# time-series momentum, in NYSE sessions.
TSMOM_LOOKBACK_SESSIONS = 252


def tsmom(closes: np.ndarray, lookback: int = TSMOM_LOOKBACK_SESSIONS) -> np.ndarray:
    """alpha[d, i] = ln(close[d, i] / close[d - lookback, i]); NaN for the first `lookback`
    rows and wherever either close is missing or non-positive."""
    alpha = np.full(closes.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        log_close = np.log(np.where(closes > 0, closes, np.nan))
    alpha[lookback:] = log_close[lookback:] - log_close[:-lookback]
    return alpha


def tsmom_panel(panel: Panel) -> np.ndarray:
    return tsmom(np.asarray(panel.close))


SIGNALS: dict[str, SignalSource] = {
    # docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md sections 3 and 6.
    "tsmom": SignalSource(tsmom_panel, TSMOM_LOOKBACK_SESSIONS, direction=1.0, n_tested=18),
}
