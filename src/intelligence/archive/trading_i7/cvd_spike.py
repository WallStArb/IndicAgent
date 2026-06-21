"""trad_CVDSpike — I7 any-regime setup consuming CVD I1 features.

Fires when a single-bar CVD exceeds 2 sigma above the rolling mean.
Symmetric with trad_OFISpike but based on Cumulative Volume Delta.
Stateless: reads pre-computed cvd_spike_z from I1 CVDPlugin.

Renaissance principles:
- Instrument everything: z-score magnitude logged
- Segment relentlessly: fires in any regime (microstructure signal is regime-agnostic)
- Degrade gracefully: missing cvd_spike_z → no signal
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from .microstructure_utils import detect_spike_signal


@dataclass
class CVDSpikePlugin:
    """Any-regime setup: single-bar CVD exceeds 2 sigma.

    Stateless: reads pre-computed cvd_spike_z from I1.
    Gate: abs(cvd_spike_z) > 2.0
    Direction: sign of cvd_spike_z (positive = buy pressure spike, negative = sell)
    Confidence: compose_confidence(0.50 + abs(cvd_spike_z) * 0.05)

    Symmetric with trad_OFISpike.
    """

    name: str = "trad_CVDSpike"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "spike", "cvd"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "any"
    shadow_only: bool = True

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        return detect_spike_signal(
            frames,
            spike_feature_key="cvd_spike_z",
            signal_name_prefix="cvd_spike",
            min_lookback=self.min_lookback,
            setup_plugin=self.name,
            regime_type=self.regime_type,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CVDSpikePlugin()
