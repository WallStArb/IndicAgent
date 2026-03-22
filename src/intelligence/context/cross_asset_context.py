"""Cross-asset EQ_INDEX context plugin - I4 macro context layer.

Reads cross_asset payload from frames["cross_asset"] (injected by
FeaturePipelineService for EQ_INDEX symbols only) and emits
eq_spread_z and eq_pairs_confirming into I4Context.

For non-EQ_INDEX symbols, FeaturePipelineService does not inject
frames["cross_asset"], so this plugin returns {} and I4Context
defaults eq_spread_z and eq_pairs_confirming to None.

Phase 49 segmentation requirement: ML training matrix MUST segment
on symbol group before using eq_* features. Training on non-EQ
symbols (where these fields are None) without segmentation produces
uninformative coefficients.

Note: CrossAssetDivergencePlugin (I7) continues to read the full
frames["cross_asset"] payload directly - it needs ~10 fields
(low_vol_flag, eq_vol_imbalance, eq_corr_break, etc.) that are
not captured here. These two consumers serve different purposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec


@dataclass
class CrossAssetContextPlugin:
    """I4 macro context: EQ_INDEX sector spread z-score and pair confirmation count.

    Reads frames["cross_asset"] injected by FeaturePipelineService.
    EQ_INDEX symbols only - all others see {} (-> None in I4Context).
    Returns {} when cross_asset data not ready.
    """

    name: str = "ctx_CrossAssetContext"
    outputs: frozenset[str] = frozenset({"eq_spread_z", "eq_pairs_confirming"})
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "macro"})
    inputs: tuple[InputSpec, ...] = ()

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        xa = frames.get("cross_asset") or {}
        if not xa.get("ready"):
            return {}

        active = xa.get("active_pair", "ES_NQ")
        spread_key = "es_nq_spread_z" if active == "ES_NQ" else "es_rty_spread_z"
        eq_spread_z = xa.get(spread_key)

        raw_pairs = xa.get("pairs_confirming")
        eq_pairs_confirming = float(raw_pairs) if raw_pairs is not None else None

        return {
            "eq_spread_z": eq_spread_z,
            "eq_pairs_confirming": eq_pairs_confirming,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossAssetContextPlugin()
