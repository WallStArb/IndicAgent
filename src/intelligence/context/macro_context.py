"""Macro cross-asset context plugin — I4 tier.

Reads ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime, and corr_z
from frames['cross_asset'] (injected by FeaturePipelineService via macro_signals
topic). Applies to ALL symbols — no EQ_INDEX guard needed (macro context is
instrument-agnostic). Returns {} when cross_asset data not ready (same
graceful-degradation contract as CrossAssetContextPlugin).

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
    macro_signals topic. All symbols receive macro context — no symbol-group guard.
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
