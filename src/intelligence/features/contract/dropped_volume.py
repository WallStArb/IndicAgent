"""The rule for a cumulative volume statistic with dropped (NULL-volume) bars (todo 560).

A dropped bar's weight is missing from a cumulative VWAP, so the error grows with the share of
dropped bars among the bars accumulated so far. One definition, used by the kernel registry's
volume guard and by the higher-timeframe series the backfill builds outside it.
"""

from __future__ import annotations

import numpy as np

# [initial_estimate] A share of 5% keeps the VWAP deviation below about 0.1 sigma on the probe
# series (todo 560). A declared property of the statistic, as `Kernel.memory_atol` is.
MAX_DROPPED_FRACTION = 0.05


def dropped_share_mask(
    dropped: np.ndarray, max_fraction: float = MAX_DROPPED_FRACTION
) -> np.ndarray:
    """Rows that are a dropped bar, or follow too many of them: dropped bars exceed
    `max_fraction` of the bars accumulated through the row. Prefix-causal."""
    share = np.cumsum(dropped) / np.arange(1, len(dropped) + 1)
    return dropped | (share > max_fraction)
