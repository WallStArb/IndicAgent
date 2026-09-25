"""One-sided Newey-West HAC t-test of a mean (methodology-change-ledger E16, pinned (a)).

Bartlett kernel, lag L = floor(4 * (n / 100) ** (2 / 9)) with n the number of finite values,
variance gamma_0 + 2 * sum_{k=1..L} (1 - k / (L + 1)) gamma_k (no floor), t = mean /
sqrt(variance / n), p = P(T > t) under Student t with n - 1 degrees of freedom. This is exactly
the statistic E16's size simulations used (scripts/analysis/e16_null_size/): a floored or
otherwise adjusted variance would be a different, unvalidated test. The lag covers the tested
series' own dependence, not a predictor's memory.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
from scipy.stats import t as student_t


@dataclasses.dataclass(frozen=True)
class HacTestResult:
    mean: float
    se: float  # HAC standard error of the mean
    t: float
    p: float  # one-sided, H1: mean > 0
    lag: int
    n: int


def newey_west_lag(n: int) -> int:
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def hac_mean_test(values: np.ndarray) -> HacTestResult:
    x = np.asarray(values, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        raise ValueError(f"HAC test needs at least 2 finite values, got {n}")
    mean = float(x.mean())
    d = x - mean
    lag = newey_west_lag(n)
    variance = float(d @ d) / n
    for k in range(1, lag + 1):
        variance += 2.0 * (1.0 - k / (lag + 1)) * float(d[k:] @ d[:-k]) / n
    if not variance > 0:
        raise ValueError("HAC test undefined: non-positive long-run variance")
    se = math.sqrt(variance / n)
    t = mean / se
    return HacTestResult(mean, se, t, float(student_t.sf(t, n - 1)), lag, n)
