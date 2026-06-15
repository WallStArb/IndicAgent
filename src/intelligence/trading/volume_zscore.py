"""Volume Z-Score (I1) -- rolling z-score of bar volume.

Per Phase 78 D-21 / P78-MATH-PLUGINS: replaces the LLM VolumeAgent with
deterministic math that lives in the I1 tier of the pipeline. Computed
once per bar, stored in intelligence_features.i1.volume_z_score, and
consumed by every downstream agent (skeptic_v2 reads it automatically
via _render_full_context iterating SignalContext.model_fields).

Migrated to IncrementalMixin (Phase 100):
- _compute_full_core: full z-score computation over entire history
- _compute_next_core: incremental update by appending latest volume to deque
- _seed_state: extracts {vol_history} deque from full computation

Renaissance principle: compute once per bar, store once, consume everywhere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin

_WINDOW = 20


@dataclass
class VolumeZscorePlugin(IncrementalMixin):
    """Rolling z-score of bar volume -- I1 measurement plugin.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch volume z-score via full history
    - _compute_next_core: single-bar incremental update via deque append
    - _seed_state: seeds {vol_history} deque

    SHADOW_SKIP=True: pure math, not a tradeable signal. Shadow enrollment
    is only relevant for I7 signal plugins.
    """

    name: str = "volume_zscore"
    regime_type: ClassVar[str] = "any"  # I1 measurement, not signal -- satisfies I7 directory guard
    SHADOW_SKIP: ClassVar[bool] = True
    outputs: frozenset[str] = frozenset({"volume_z_score"})
    min_lookback: int = _WINDOW + 1
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: tuple = (InputSpec(symbol=".*", lookback=_WINDOW + 5),)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_window(self) -> int:
        cfg = self._config_service
        return cfg.get_sync("feature.volume_zscore.window", _WINDOW) if cfg else _WINDOW

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute volume z-score from a full window DataFrame.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            {"volume_z_score": float}. Returns {"volume_z_score": 0.0} if
            insufficient data.
        """
        window = self._get_window()

        df = frames.get("main")
        if df is None or "volume" not in df.columns or len(df) < 2:
            return {"volume_z_score": 0.0}

        volumes = df["volume"].to_numpy(copy=False)

        history: deque = deque(maxlen=window)
        for v in volumes:
            history.append(float(v))

        return self._compute_z(history)

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract rolling volume history for incremental updates.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with {vol_history: deque(_WINDOW)}.
        """
        window = self._get_window()

        df = frames.get("main")
        if df is None or "volume" not in df.columns or len(df) < 2:
            return {}

        volumes = df["volume"].to_numpy(copy=False)
        history: deque = deque(maxlen=window)
        for v in volumes:
            history.append(float(v))

        return {"vol_history": history}

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental update: append latest bar volume to rolling window.

        State is guaranteed non-None by the mixin. Mutates state in place.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected key: {vol_history: deque}.

        Returns:
            {"volume_z_score": float}. Returns {"volume_z_score": 0.0} if
            data is insufficient.
        """
        df = frames.get("main")
        if df is None or "volume" not in df.columns or len(df) < 1:
            return {"volume_z_score": 0.0}

        history: deque = state["vol_history"]
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
            return {"volume_z_score": 0.0, "volume_sma_20": 0.0, "rel_volume": 1.0}

        # Prior history excludes the current bar
        prior = np.asarray(list(history)[:-1], dtype=float)
        mean = float(prior.mean())
        std = float(prior.std())
        rel_volume = round(float(history[-1]) / mean, 4) if mean > 0.0 else 1.0

        if std <= 0.0:
            return {"volume_z_score": 0.0, "volume_sma_20": mean, "rel_volume": rel_volume}

        z = float((history[-1] - mean) / std)
        return {"volume_z_score": z, "volume_sma_20": mean, "rel_volume": rel_volume}


plugin = VolumeZscorePlugin()
