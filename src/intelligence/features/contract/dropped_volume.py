"""The rule for a cumulative volume statistic with dropped (NULL-volume) bars (todo 560).

A dropped bar's weight is missing from a cumulative VWAP, so the error grows with the share of
dropped bars among the bars accumulated since the first bar that has volume. Leading dropped bars
carry no weight and move the start of the accumulation, so they do not count toward the share (the
rows themselves are still NaN: there is no VWAP yet). One definition, used by the kernel
registry's volume guard and by the higher-timeframe series the backfill builds outside it. The
bound is the APR key `feature.volume.dropped_max_fraction`
(`FeatureFactoryConfig.dropped_volume_max_fraction`).
"""

from __future__ import annotations

import numpy as np


def dropped_share_mask(dropped: np.ndarray, max_fraction: float) -> np.ndarray:
    """Rows that are a dropped bar, or follow too many of them: dropped bars exceed `max_fraction`
    of the bars accumulated since the first bar with volume. Prefix-causal."""
    if dropped.all():
        return dropped.copy()
    start = int(np.argmin(dropped))  # first bar with volume
    counted = np.cumsum(dropped[start:])
    share = np.zeros(len(dropped))
    share[start:] = counted / np.arange(1, len(dropped) - start + 1)
    return dropped | (share > max_fraction)
