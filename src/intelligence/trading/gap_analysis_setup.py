"""I7 Gap Analysis setup detection plugin.

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import (
    _validate_weights_sum,
    clamp01,
    compose_confidence,
)
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class GapAnalysisSetupPlugin:
    """Gap analysis setup: fires when a significant gap (open vs prior close) is detected.

    GAP-01: Detects directional gaps using open[-1] vs close[-2].
    GAP-02: Classifies bias as 'continuation' (large gap + high volume) or 'fade'.
    GAP-03: Derives entry, stop, targets and confidence from gap size and ATR.

    Time gate: when I4 SessionContext is present and bars_since_session_start > 30,
    restricts to NY session only (session_ny == 1).
    """

    name: str = "trad_GapAnalysisSetup"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "bias",
            "gap_size_atr",
            "confidence",
            "entry_type",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "gap"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "any"
    shadow_only: bool = True
    min_gap_atr_mult: float = 0.8
    continuation_atr_mult: float = 1.0
    volume_confirm_ratio: float = 1.5
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        min_gap_atr = (
            cfg.get_sync("threshold.gap_analysis.min_gap_atr", self.min_gap_atr_mult)
            if cfg
            else self.min_gap_atr_mult
        )
        continuation_atr = (
            cfg.get_sync("threshold.gap_analysis.continuation_atr", self.continuation_atr_mult)
            if cfg
            else self.continuation_atr_mult
        )
        volume_confirm_ratio = (
            cfg.get_sync("threshold.gap_analysis.volume_confirm_ratio", self.volume_confirm_ratio)
            if cfg
            else self.volume_confirm_ratio
        )
        w_geo = cfg.get_sync("weights.gap_analysis.geo", 0.40) if cfg else 0.40
        w_vol = cfg.get_sync("weights.gap_analysis.vol", 0.25) if cfg else 0.25
        w_timing = cfg.get_sync("weights.gap_analysis.timing", 0.20) if cfg else 0.20
        w_type = cfg.get_sync("weights.gap_analysis.type", 0.15) if cfg else 0.15
        _validate_weights_sum(
            {"geo": w_geo, "vol": w_vol, "timing": w_timing, "type": w_type},
            "trad_GapAnalysisSetup",
        )
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }
        df = frames.get("main")

        # Time gate (I4 SessionContext) — only active when feature is present
        bars_since = features.get("bars_since_session_start")
        if bars_since is not None and float(bars_since) > 30:
            session_ny = features.get("session_ny", 1.0)
            if not session_ny:
                return no_signal()

        # GAP-01: Gap detection — close[-2] is prior bar close, open[-1] is current bar open
        prior_close = float(close[-2])

        gap_size = float(open_[-1]) - prior_close
        direction = 1 if gap_size > 0 else (-1 if gap_size < 0 else 0)
        if direction == 0:
            return no_signal()

        symbol = frames.get("symbol", "")
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # Minimum gap gate
        if abs(gap_size) < min_gap_atr * atr:
            return no_signal()

        gap_size_atr = abs(gap_size) / atr

        # GAP-02: Volume check
        vol = df["volume"].to_numpy(dtype=float)
        if len(vol) > 21:
            vol_mean = np.mean(vol[-21:-1])
        elif len(vol) > 1:
            vol_mean = np.mean(vol[:-1])
        else:
            vol_mean = 1.0
        vol_ratio = vol[-1] / vol_mean if vol_mean > 0 else 1.0
        high_volume = vol_ratio >= volume_confirm_ratio

        # GAP-02: Bias classification
        if gap_size_atr >= continuation_atr and high_volume:
            bias = "continuation"
        else:
            bias = "fade"

        # GAP-03: Entry — bias-dependent
        if bias == "fade":
            # Fade trades AGAINST the gap direction: upward gap → short, downward gap → long.
            # direction here reflects gap direction; fade_direction is the trade direction.
            fade_direction = -direction
            entry_type = "at_limit"
            entry = float(open_[-1])
            direction = fade_direction
        else:
            entry_type = "at_pullback"
            entry = float(open_[-1] + (-direction * 0.25 * atr))

        # GAP-03: 4-factor intrinsic confidence — each factor clamped to [0, 1] before weighting
        # geo_score: 0.0 at the min_gap_atr gate, 1.0 at (min_gap_atr + 1.7) ATR gaps
        _geo_range = 1.7  # span from gate to max-confidence (gate zero-point to 2.5+ ATR)
        geo_score = clamp01((gap_size_atr - min_gap_atr) / _geo_range)
        # vol_score: 0.0 at 1x average volume, 1.0 at 3x average volume
        vol_score = clamp01((vol_ratio - 1.0) / 2.0)
        # timing_score: early-session gaps are more meaningful; floors at 0.2 so a valid
        # later-session gap is down-weighted but never rejected (Codex MEDIUM concern).
        # When I4 SessionContext is absent, default to neutral 0.5 (no penalty).
        # Use an explicit is-None guard: 0 is a legitimate value at the open and must not
        # be treated as missing data (do NOT use `or 30.0`).
        if bars_since is not None:
            timing_score = max(0.2, 1.0 - float(bars_since) / 30.0)
        else:
            timing_score = 0.5  # I4 SessionContext unavailable — neutral, no penalty; shadow mode will generate monitoring data
        # type_score: continuation gaps have stronger directional conviction than fade gaps
        type_score = 0.8 if bias == "continuation" else 0.5
        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "geo_score": round(geo_score, 4),
            "vol_score": round(vol_score, 4),
            "timing_score": round(timing_score, 4),
            "type_score": round(type_score, 4),
        }

        # Weighted sum (coefficients sum to 1.0)
        raw_conf = (
            w_geo * geo_score + w_vol * vol_score + w_timing * timing_score + w_type * type_score
        )

        # Supporting factors
        supporting: list[str] = []
        if gap_size_atr >= 1.0:
            supporting.append("large_gap")
        if high_volume:
            supporting.append("volume_confirm")
        supporting.append(f"{bias}_bias")

        confidence = compose_confidence(raw_conf)

        bias_abbr = "cont" if bias == "continuation" else "fade"
        signal_type = f"gap_{bias_abbr}_{'long' if direction == 1 else 'short'}"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        signal = make_signal_from_frame(
            tf,
            symbol=symbol,
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="gap_open",
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        signal["bias"] = bias
        signal["gap_size_atr"] = round(gap_size_atr, 4)
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = GapAnalysisSetupPlugin()
