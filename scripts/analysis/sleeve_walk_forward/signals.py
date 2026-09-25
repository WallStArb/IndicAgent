"""Parameter-free signal sources: pure functions from snapshot price arrays to
alpha[session, symbol], evaluated by S3/S4 (edge-proof program, "Phase 181 queue").

A signal source has no fitted parameters, so it needs no S1 refit and no V4 fidelity check.
Its alpha at session d uses only closes through d; S3 enters at the next open. A missing close
gives NaN alpha (no position that day), never a filled value. Each source pins its direction
and is scored with portfolio.fixed_sign_returns, not the calibrated arms.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Callable
from typing import Any

import numpy as np

from scripts.analysis.sleeve_walk_forward.portfolio import FIXED_SIGN_ARM, fixed_sign_returns
from scripts.analysis.sleeve_walk_forward.score import FWD_SPAN_SESSIONS

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


@dataclasses.dataclass(frozen=True)
class SignalSource:
    compute: Callable[[np.ndarray], np.ndarray]  # closes [n, m] -> alpha [n, m]
    lookback: int  # sessions of closes alpha[d] reads before d
    direction: float  # pre-registered sign: +1 means long when alpha > 0
    n_tested: int  # ledger count pinned by the source's pre-registration, used by s4
    arm: str = FIXED_SIGN_ARM

    def evaluate_kwargs(self) -> dict[str, Any]:
        """evaluate()'s construction and shift memory for this source."""
        return {
            "construction": functools.partial(fixed_sign_returns, direction=self.direction),
            "memory": self.lookback + FWD_SPAN_SESSIONS,
        }


SIGNALS: dict[str, SignalSource] = {
    # docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md sections 3 and 6.
    "tsmom": SignalSource(tsmom, TSMOM_LOOKBACK_SESSIONS, direction=1.0, n_tested=18),
}
