"""trad_OFISpike — I7 any-regime setup consuming OFI I1 features.

Fires when a single-bar OFI exceeds 2 sigma above the rolling mean.
Stateless: reads pre-computed ofi_spike_z from I1 OFIPlugin.

Renaissance principles:
- Instrument everything: z-score magnitude logged
- Segment relentlessly: fires in any regime (microstructure signal is regime-agnostic)
- Degrade gracefully: missing ofi_spike_z → no signal (don't estimate)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from .microstructure_utils import detect_spike_signal


@dataclass
class OFISpikePlugin:
    """Any-regime setup: single-bar OFI exceeds 2 sigma.

    Stateless: reads pre-computed ofi_spike_z from I1.
    Gate: abs(ofi_spike_z) > 2.0
    Direction: sign of ofi_spike_z (positive = buy spike, negative = sell spike)
    Confidence: compose_confidence(0.50 + abs(ofi_spike_z) * 0.05)
    """

    name: str = "trad_OFISpike"
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
    capability_tags: frozenset[str] = frozenset({"trading", "spike", "ofi"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "any"
    shadow_only: bool = True

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        return detect_spike_signal(
            frames,
            spike_feature_key="ofi_spike_z",
            signal_name_prefix="ofi_spike",
            min_lookback=self.min_lookback,
            setup_plugin=self.name,
            regime_type=self.regime_type,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFISpikePlugin()
