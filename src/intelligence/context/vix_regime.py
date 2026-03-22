"""VIX regime context plugin - I4 macro context layer.

Reads pre-computed VIX context from frames["vix"] (injected by
FeaturePipelineService using a fixed 1h lookback TF) and emits
vix_level and vix_z into I4Context.

Design decisions:
- VIX_REGIME_TF="1h" in feature_pipeline_service gives z_window=20
  over 20 trading hours - captures session-scale fear elevation.
  Complementary to GARCH (multi-week structural vol regime).
- Returns {} when VIX data unavailable - I4Context defaults vix_level
  and vix_z to None. Downstream plugins must treat None as "no data",
  not as "VIX is zero".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec


@dataclass
class VIXRegimePlugin:
    """I4 macro context: VIX fear-regime level and z-score.

    Reads frames["vix"] injected by FeaturePipelineService.
    All symbols receive VIX context (VIX is a global fear gauge).
    Returns {} when VIX bars are insufficient (< z_window=20 at 1h TF).
    """

    name: str = "ctx_VIXRegime"
    outputs: frozenset[str] = frozenset({"vix_level", "vix_z"})
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "macro"})
    inputs: tuple[InputSpec, ...] = ()

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        vix = frames.get("vix") or {}
        if not vix.get("ready"):
            return {}
        return {
            "vix_level": vix.get("level"),
            "vix_z": vix.get("z_score"),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VIXRegimePlugin()
