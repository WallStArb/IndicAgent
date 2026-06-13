"""Macro cross-asset context plugin — I4 tier.

Reads ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime, and corr_z
from frames['cross_asset'] (injected by FeaturePipelineService via macro_signals
topic). The plugin itself has no symbol guard, but its only data source
(frames["cross_asset"]) is populated by FeaturePipelineService ONLY for EQ_INDEX
contract symbols (where resolve_eq_index_base is not None, as defined in
feature_pipeline_executor.py:205). In practice, macro fields are populated only
for ES/NQ/RTY/YM contracts. Returns {} when cross_asset data not ready.

Phase 121 Wave 2 (D-10): one plugin per data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec


def _to_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class MacroContextPlugin:
    """I4 macro context: flight-to-quality, yield curve slope, and stock-bond correlation.

    Reads frames["cross_asset"] injected by FeaturePipelineService from the
    macro_signals topic. No symbol-group guard in the plugin itself, but its data source
    (frames["cross_asset"]) is populated only for EQ_INDEX contract symbols in
    feature_pipeline_executor.py:205 (ES/NQ/RTY/YM contracts).
    Returns {} when cross_asset data not ready.
    """

    name: str = "ctx_MacroContext"
    outputs: frozenset[str] = frozenset(
        {"ftq_score", "ftq_regime", "yield_curve_slope", "yield_curve_regime", "corr_z"}
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "macro"})
    inputs: tuple[InputSpec, ...] = ()

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        xa = frames.get("cross_asset") or {}
        if not xa.get("ready"):
            return {}

        raw_ftq_regime = xa.get("ftq_regime")
        raw_ycr = xa.get("yield_curve_regime")
        return {
            "ftq_score": _to_float(xa.get("ftq_score")),
            "ftq_regime": str(raw_ftq_regime) if raw_ftq_regime is not None else None,
            "yield_curve_slope": _to_float(xa.get("yield_curve_slope")),
            "yield_curve_regime": str(raw_ycr) if raw_ycr is not None else None,
            "corr_z": _to_float(xa.get("corr_z")),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MacroContextPlugin()
