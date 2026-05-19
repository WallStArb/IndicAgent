"""Volume Z-Score (I1) — rolling z-score of bar volume.

Per Phase 78 D-21 / P78-MATH-PLUGINS: replaces the LLM VolumeAgent with
deterministic math that lives in the I1 tier of the pipeline. Computed
once per bar, stored in intelligence_features.i1.volume_z_score, and
consumed by every downstream agent (skeptic_v2 reads it automatically
via _render_full_context iterating AIContext.model_fields).

Renaissance principle: compute once per bar, store once, consume everywhere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec

_WINDOW = 20


@dataclass
class VolumeZscorePlugin:
    """Rolling z-score of bar volume — I1 measurement plugin.

    SHADOW_SKIP=True: pure math, not a tradeable signal. Shadow enrollment
    is only relevant for I7 signal plugins.
    """

    name: str = "volume_zscore"
    regime_type: ClassVar[str] = "any"  # I1 measurement, not signal — satisfies I7 directory guard
    SHADOW_SKIP: ClassVar[bool] = True
    outputs: frozenset[str] = frozenset({"volume_z_score"})
    min_lookback: int = _WINDOW + 1
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: tuple = (InputSpec(symbol=".*", lookback=_WINDOW + 5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute volume z-score from a full window DataFrame.

        Seeds incremental state for compute_next calls.
        Returns {"volume_z_score": 0.0} if insufficient data.
        """
        df = frames.get("main")
        if df is None or "volume" not in df.columns or len(df) < 2:
            return {"volume_z_score": 0.0}

        volumes = df["volume"].tolist()

        # Build rolling window from the full series
        history: deque = deque(maxlen=_WINDOW)
        for v in volumes:
            history.append(float(v))

        # Store state for incremental updates
        self._state["vol_history"] = history

        return self._compute_z(history)

    def compute_next(
        self, windows: dict[str, pd.DataFrame], *, state: dict | None = None
    ) -> dict[str, Any]:
        """Incremental update: append latest bar volume to rolling window."""
        if not self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or "volume" not in df.columns or len(df) < 1:
            return {"volume_z_score": 0.0}

        history: deque = self._state["vol_history"]
        vol = float(df["volume"].iloc[-1])
        history.append(vol)

        return self._compute_z(history)

    @staticmethod
    def _compute_z(history: deque) -> dict[str, Any]:
        """Compute z-score of most recent bar relative to prior history.

        Compares the last value in history to the distribution formed by
        all prior values (history[:-1]). Returns 0.0 if insufficient data
        or zero standard deviation.
        """
        if len(history) < 2:
            return {"volume_z_score": 0.0}

        # Prior history excludes the current bar
        prior = np.asarray(list(history)[:-1], dtype=float)
        mean = float(prior.mean())
        std = float(prior.std())

        if std <= 0.0:
            return {"volume_z_score": 0.0}

        z = float((history[-1] - mean) / std)
        return {"volume_z_score": z}


plugin = VolumeZscorePlugin()
