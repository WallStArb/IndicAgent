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

        # ftq_score — float or None
        raw_ftq_score = xa.get("ftq_score")
        try:
            ftq_score = float(raw_ftq_score) if raw_ftq_score is not None else None
        except (TypeError, ValueError):
            ftq_score = None

        # ftq_regime — string or None
        raw_ftq_regime = xa.get("ftq_regime")
        ftq_regime = str(raw_ftq_regime) if raw_ftq_regime is not None else None

        # yield_curve_slope — float or None
        raw_ycs = xa.get("yield_curve_slope")
        try:
            yield_curve_slope = float(raw_ycs) if raw_ycs is not None else None
        except (TypeError, ValueError):
            yield_curve_slope = None

        # yield_curve_regime — string or None
        raw_ycr = xa.get("yield_curve_regime")
        yield_curve_regime = str(raw_ycr) if raw_ycr is not None else None

        # corr_z — float or None
        raw_corr_z = xa.get("corr_z")
        try:
            corr_z = float(raw_corr_z) if raw_corr_z is not None else None
        except (TypeError, ValueError):
            corr_z = None

        return {
            "ftq_score": ftq_score,
            "ftq_regime": ftq_regime,
            "yield_curve_slope": yield_curve_slope,
            "yield_curve_regime": yield_curve_regime,
            "corr_z": corr_z,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MacroContextPlugin()
