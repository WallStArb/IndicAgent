"""Signal sources: pure functions from a Panel to alpha[row, symbol] (S2).

A signal source has no fitted parameters, so it needs no refit and no fidelity check. Its alpha
at row t uses only data through t; S5 enters at the next open. A missing input gives NaN alpha
(no position), never a filled value. Each source pins its direction and is scored with
portfolio.fixed_sign_returns, not the calibrated arms.

`memory` is declared, not measured: the rows before t that alpha[t] can read (the lookback for
a finite window; for a recursive filter, the lag at which its impulse response falls below
1e-4 of its peak). The null's memory is that plus the forward return's span.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Callable
from typing import Any

import numpy as np

from src.intelligence.research.panel import Panel, fwd_span
from src.intelligence.research.portfolio import FIXED_SIGN_ARM, fixed_sign_returns


@dataclasses.dataclass(frozen=True)
class SignalSource:
    compute: Callable[[Panel], np.ndarray]  # panel -> alpha [n, m]
    memory: int  # rows of history alpha[t] reads before t
    direction: float  # pre-registered sign: +1 means long when alpha > 0
    n_tested: int  # ledger count pinned by the source's pre-registration
    horizon: int = 1  # forward return horizon in rows
    arm: str = FIXED_SIGN_ARM

    def evaluate_kwargs(self) -> dict[str, Any]:
        """evaluate()'s construction, shift memory and embargo for this source."""
        return {
            "construction": functools.partial(fixed_sign_returns, direction=self.direction),
            "memory": self.memory + fwd_span(self.horizon),
            "embargo": fwd_span(self.horizon),
        }
