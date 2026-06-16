"""trad_CVDDivergence — I7 mean-reversion setup consuming CVD I1 features.

Fires when Cumulative Volume Delta direction disagrees with price direction
for N consecutive bars of confirmation. Also logs dual_divergence flag when
both OFI and CVD are diverging simultaneously.

Renaissance principles:
- Segment relentlessly: requires N=5 bar confirmation (not just 1-bar divergence)
- Instrument everything: dual_divergence flag always logged on signal fire
- Earn the right through proof: requires persistence before signal fires
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import clamp01, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import reset_consecutive_state, track_consecutive_state
from .trade_framer import frame_trade

_CONFIRMATION_BARS: int = 5
# Phase 118: cvd_divergence = slope_dir - price_dir; discrete values {-2,-1,0,1,2}.
# cvd_divergence is computed in-process (not persisted); distribution derived analytically:
# abs values when non-zero are 1.0 (partial divergence) or 2.0 (full divergence).
# Bounded 90d query on signal_ledger confirms 227836 CVDDivergence firings.
# Threshold = p75 of abs(cvd_divergence): 1.0 (filters zero-divergence noise; keeps top quartile).
# Upper ref = p90: 2.0 (full divergence = slope_dir opposite to price_dir = max magnitude).
# Queried 2026-06-09; n=227836 (90d). Feature is not persisted to intelligence_features.
_CVD_DIV_THRESHOLD: float = 1.0  # Phase 118: p75 of |cvd_divergence|, 90d, n=227836
_CVD_DIV_UPPER_REF: float = 2.0  # Phase 118: p90 magnitude ceiling for confidence normalization
_OFI_DUAL_THRESHOLD: float = 1.0  # OFI must also diverge at this level for dual flag


@dataclass
class CVDDivergencePlugin:
    """Mean-reversion setup: CVD slope opposes price direction for N bars.

    Gates:
    - cvd_divergence != 0 (CVD direction disagrees with price direction)
    - N=3 consecutive bars of confirmation
    (cvd_slope_5bar is logged in supporting_factors but not used as a gate)

    Additional metadata (always logged when signal fires):
    - dual_divergence = (abs(ofi_divergence) >= 1.0 AND abs(cvd_divergence) >= 1.0)

    Direction: opposite of price direction (mean reversion)
    Confidence: compose_confidence(4-factor: 0.40*div_mag + 0.25*dual + 0.20*persistence + 0.15*slope)
    """

    name: str = "trad_CVDDivergence"
    shadow_only: bool = True
    _config_service: Any = field(default=None, compare=False, repr=False)
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
            "dual_divergence",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "cvd", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        confirmation_bars = (
            int(cfg.get_sync("feature.cvd_divergence.confirmation_bars", _CONFIRMATION_BARS))
            if cfg
            else _CONFIRMATION_BARS
        )
        cvd_div_threshold = (
            cfg.get_sync("threshold.cvd_divergence.div_threshold", _CVD_DIV_THRESHOLD)
            if cfg
            else _CVD_DIV_THRESHOLD
        )
        cvd_div_upper_ref = (
            cfg.get_sync("feature.cvd_divergence.div_upper_ref", _CVD_DIV_UPPER_REF)
            if cfg
            else _CVD_DIV_UPPER_REF
        )
        ofi_dual_threshold = (
            cfg.get_sync("threshold.cvd_divergence.ofi_dual_threshold", _OFI_DUAL_THRESHOLD)
            if cfg
            else _OFI_DUAL_THRESHOLD
        )

        df = frames.get("main")
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        cvd_div = features.get("cvd_divergence")
        cvd_slope = features.get("cvd_slope_5bar")

        if cvd_div is None:
            return no_signal()

        cvd_div = float(cvd_div)
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        if abs(cvd_div) < cvd_div_threshold:
            # Sub-threshold CVD divergence invalidates any accumulated confirmation count
            reset_consecutive_state(frames, self._state, state_key)
            return no_signal()

        cvd_div_sign = 1 if cvd_div > 0 else -1
        _, count = track_consecutive_state(frames, self._state, state_key, cvd_div_sign, "div_sign")

        # Gate: require N confirmation bars
        if count < confirmation_bars:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Direction: opposite of price direction (mean reversion)
        # cvd_divergence = slope_dir - price_dir_5bar
        # Positive: CVD bullish vs price bearish → price should revert up → long
        # Negative: CVD bearish vs price bullish → price should revert down → short
        direction = 1 if cvd_div > 0 else -1

        # Check dual divergence
        ofi_div = features.get("ofi_divergence")
        ofi_div_f = float(ofi_div) if ofi_div is not None else 0.0
        dual_divergence = (
            abs(ofi_div_f) >= ofi_dual_threshold and abs(cvd_div) >= ofi_dual_threshold
        )

        # Confidence — 4-factor intrinsic gradient (Phase 118)
        # Factor 1: divergence magnitude — 0.0 at threshold, 1.0 at upper_ref (p90)
        span = max(1e-9, cvd_div_upper_ref - cvd_div_threshold)
        div_mag_score = clamp01((abs(cvd_div) - cvd_div_threshold) / span)

        # Factor 2: dual divergence confirmation (full weight when both CVD and price diverge)
        dual_score = 1.0 if dual_divergence else 0.3  # gradient-exempt — categorical gate

        # Factor 3: persistence beyond minimum bars — 0.0 at confirmation_bars, 1.0 at 2x
        extra_bars = max(0, count - confirmation_bars)
        persistence_score = clamp01(extra_bars / 5.0)

        # Factor 4: CVD slope alignment with is-None guard
        cvd_slope_raw = features.get("cvd_slope_5bar")
        if cvd_slope_raw is not None:
            slope_score = (
                1.0 if (float(cvd_slope_raw) * cvd_div > 0) else 0.2
            )  # gradient-exempt — alignment gate
        else:
            slope_score = 0.5  # neutral fallback when I1 omits the key

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "div_mag_score": round(div_mag_score, 4),
            "persistence_score": round(persistence_score, 4),
            "slope_score": round(slope_score, 4),
        }

        raw_conf = (
            0.40 * div_mag_score + 0.25 * dual_score + 0.20 * persistence_score + 0.15 * slope_score
        )
        confidence = compose_confidence(raw_conf)

        sig_type = signal_type_for_direction("cvd_divergence", direction)
        tf_result = frame_trade(
            sig_type, direction, entry, features, atr, regime_type=self.regime_type
        )
        if not tf_result.viable:
            return no_signal()

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        supporting: list[str] = [
            f"cvd_divergence={cvd_div:.3f}",
            f"confirmation_bars={count}",
        ]
        if cvd_slope is not None:
            supporting.append(f"cvd_slope_5bar={float(cvd_slope):.1f}")
        if dual_divergence:
            supporting.append("dual_divergence_confirmed")

        # exhaustion: not applicable — spike/divergence signals are regime-independent;
        # Phase 49 will learn gate behavior from shadow data
        signal = make_signal_from_frame(
            tf_result,
            symbol=frames.get("symbol", ""),
            timeframe=tf,
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        signal["dual_divergence"] = dual_divergence
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CVDDivergencePlugin()
