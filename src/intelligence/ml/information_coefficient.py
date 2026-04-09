"""Information Coefficient (IC) computation for IndicAgent signal quality measurement.

IC = Pearson r(calibrated_confidence, pnl_r) per plugin per regime.

Renaissance principle: "Earn the right through proof." IC is the quantifiable measure of
whether a signal's confidence score has predictive power. IC > 0.05 with p < 0.05 and
N >= 30 is the minimum bar for a signal to be considered non-noise.

Interpretation:
  IC > 0.05: weak but statistically significant predictive power
  IC > 0.10: meaningful signal alpha
  IC > 0.20: strong signal — Renaissance-grade
  IC <= 0.05 or p > 0.05: signal is noise at current sample size
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

# Minimum sample size gate — below this, IC is unreliable (FEED-02 from CLAUDE.md)
IC_MIN_SAMPLE_SIZE: int = 30

# Statistical significance threshold
IC_P_VALUE_THRESHOLD: float = 0.05

# IC threshold below which a signal is considered noise
IC_NOISE_THRESHOLD: float = 0.05


@dataclass(frozen=True)
class ICResult:
    """Information Coefficient result for one (plugin, timeframe, regime, symbol) slice."""

    setup_plugin: str
    timeframe: str
    regime_type: str
    symbol: str | None  # None = global (all symbols)
    window_days: int
    sample_size: int
    wins: int
    win_rate: float | None
    avg_pnl_r: float | None
    ic_score: float | None
    ic_p_value: float | None
    ic_n: int
    ic_significant: bool

    @property
    def is_noise(self) -> bool:
        """True if IC is not statistically significant or below noise threshold."""
        if self.ic_score is None or self.ic_p_value is None:
            return True
        return self.ic_p_value >= IC_P_VALUE_THRESHOLD or self.ic_score < IC_NOISE_THRESHOLD

    @property
    def grade(self) -> str:
        """Human-readable quality grade."""
        if self.ic_score is None:
            return "insufficient_data"
        if self.is_noise:
            return "noise"
        if self.ic_score >= 0.20:
            return "strong"
        if self.ic_score >= 0.10:
            return "meaningful"
        return "weak"


def compute_ic(
    confidences: list[float],
    pnl_rs: list[float | None],
) -> tuple[float | None, float | None, int]:
    """Compute Pearson IC between confidence scores and continuous pnl_r outcomes.

    Args:
        confidences: calibrated_confidence values per signal
        pnl_rs:      zone pnl_r per signal (None = never_activated, skipped)

    Returns:
        (ic_score, p_value, n_used) -- None values if insufficient data
    """
    # Filter to resolved signals only (pnl_r IS NOT NULL)
    pairs = [
        (c, r) for c, r in zip(confidences, pnl_rs, strict=True)
        if r is not None and c is not None
    ]

    if len(pairs) < IC_MIN_SAMPLE_SIZE:
        return None, None, len(pairs)

    conf_arr = np.array([c for c, _ in pairs], dtype=float)
    pnl_arr = np.array([r for _, r in pairs], dtype=float)

    # Guard: zero-variance inputs produce nan correlation
    if conf_arr.std() < 1e-9 or pnl_arr.std() < 1e-9:
        logger.warning("ic_zero_variance n=%d", len(pairs))
        return None, None, len(pairs)

    ic_score, p_value = stats.pearsonr(conf_arr, pnl_arr)
    return float(ic_score), float(p_value), len(pairs)


def is_ic_significant(ic_score: float | None, p_value: float | None, n: int) -> bool:
    """Return True only if IC passes all statistical gates."""
    if ic_score is None or p_value is None:
        return False
    return (
        n >= IC_MIN_SAMPLE_SIZE
        and p_value < IC_P_VALUE_THRESHOLD
        and ic_score >= IC_NOISE_THRESHOLD
    )
