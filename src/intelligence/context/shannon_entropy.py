"""ShannonEntropyPlugin — I4 context plugin for market structure / predictability.

Shannon entropy of the log-return distribution measures how randomly distributed
price changes are across a histogram of bins. A structured, trending market has
returns concentrated in a small number of bins (low entropy). A chaotic, noisy
market has returns spread uniformly across all bins (high entropy).

Outputs:
  shannon_entropy  — normalised entropy in [0, 1]  (0 = perfectly structured, 1 = pure noise)
  entropy_quality  — universal gate score in [0.5, 1.0] (1.0 = structured, 0.5 = chaotic)

The entropy_quality score is consumed by _build_all_ranked() (aggregator, plan 29-05)
as a confidence multiplier that penalises all trading setups in chaotic markets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


def _shannon_entropy(close: np.ndarray, n_bins: int = 10) -> float:
    """Normalised Shannon entropy of the log-return distribution.

    Returns 1.0 (maximum noise) on failure or insufficient data.

    Parameters
    ----------
    close:
        Array of closing prices.  Requires at least 11 values (10 log-returns).
    n_bins:
        Number of histogram bins.  Defaults to 10.
    """
    log_returns = np.diff(np.log(close))
    if len(log_returns) < 10:
        return 1.0
    valid_returns = log_returns[np.isfinite(log_returns)]
    if len(valid_returns) < 10:
        return 1.0
    counts, _ = np.histogram(valid_returns, bins=n_bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    if len(probs) == 0:
        return 1.0
    raw_entropy = -np.sum(probs * np.log2(probs))
    max_entropy = np.log2(n_bins)
    return float(raw_entropy / max_entropy) if max_entropy > 0 else 1.0


def _entropy_quality(normalised_entropy: float) -> float:
    """Map normalised entropy to a universal quality gate score in [0.5, 1.0].

    Penalises high-entropy (noisy) markets by reducing all signal confidences.

    Scoring rationale (calibrated from live data 2026-03-16):
      entropy <= 0.65  — structured/trending market → 1.0
      entropy >= 0.95  — pure noise/chaos → 0.5
      0.65 < entropy < 0.95 — linear interpolation between 1.0 and 0.5

    Thresholds raised from 0.40/0.80 because financial log-returns on 5m/15m/1h bars
    routinely produce entropy of 0.70-0.79 (near-Gaussian, central limit theorem).
    The old thresholds penalised normal longer-TF markets by 40-47% with no signal
    degradation justification. 1m bars have lower entropy (avg ~0.33) and are unaffected.
    """
    if normalised_entropy <= 0.65:
        return 1.0
    if normalised_entropy >= 0.95:
        return 0.5
    return 1.0 - 0.5 * ((normalised_entropy - 0.65) / 0.30)


@dataclass
class ShannonEntropyPlugin:
    """I4 context plugin: Shannon entropy of return distribution + quality gate.

    Computes the normalised Shannon entropy of log-returns over the last
    ``min_lookback`` bars.  High entropy = chaotic market = reduced confidence
    across all trading setups via the entropy_quality gate in _build_all_ranked().

    Outputs
    -------
    shannon_entropy : float in [0, 1]
    entropy_quality : float in [0.5, 1.0]
    """

    name: str = "ctx_ShannonEntropy"
    outputs: frozenset[str] = frozenset({"shannon_entropy", "entropy_quality"})
    min_lookback: int = 10
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        # Need at least 10 log-returns → at least 11 close values
        if len(close) < 11:
            return {}

        entropy = _shannon_entropy(close)
        quality = _entropy_quality(entropy)

        return {
            "shannon_entropy": round(entropy, 4),
            "entropy_quality": round(quality, 4),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        """Incremental path delegates to compute_full (entropy is window-based)."""
        return self.compute_full(windows)


plugin = ShannonEntropyPlugin()
