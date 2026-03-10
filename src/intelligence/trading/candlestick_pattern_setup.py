"""I7 CandlestickPatternSetup — confluence-gated candlestick setup consuming I5 outputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class CandlestickPatternSetupPlugin:
    """I7 trading setup: fires when an I5 candlestick pattern aligns with trend regime.

    CNDL-01: All pattern flags come from I5 features dict — no raw OHLCV re-detection.
    CNDL-02: Mandatory trend regime gate (abs >= 0.5); direction must agree with regime.
             At least one optional factor (volume confirm or S/R proximity) required,
             except hammer/shooting_star which satisfy S/R automatically.
    CNDL-03: Emits 9 output fields: signal_type, direction, entry_price, stop_loss,
             targets, confidence, confluence_score, regime_context, supporting_factors.

    Priority order (lower rank = higher priority):
        0: hammer, shooting_star  (satisfy S/R automatically)
        1: engulfing_bull, engulfing_bear, three_white_soldiers, three_black_crows
        2: pin_bar_bull, pin_bar_bear, morning_star, evening_star
        3: three_inside_up/down, dark_cloud_cover, piercing_line
        4: harami_cross  (direction follows trend)
    """

    name: str = "trad_CandlestickPatternSetup"
    outputs: frozenset[str] = frozenset({
        "signal_type",
        "direction",
        "entry_price",
        "stop_loss",
        "targets",
        "confidence",
        "confluence_score",
        "regime_context",
        "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "pattern", "structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "any"
    regime_threshold: float = 0.5
    volume_boost_ratio: float = 1.3
    sr_proximity_atr: float = 0.3
    atr_stop_mult: float = 1.5
    atr_target_mults: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        vol = df["volume"].to_numpy(dtype=float)

        # ATR with fallback (same pattern as PatternCompletion and GapAnalysisSetup)
        atr = float(features.get("atr_14") or 0.0)
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # CNDL-01: Read I5 pattern flags (no re-detection of raw price)
        engulfing_bull = float(features.get("engulfing_bull", 0.0))
        engulfing_bear = float(features.get("engulfing_bear", 0.0))
        pin_bar_bull = float(features.get("pin_bar_bull", 0.0))
        pin_bar_bear = float(features.get("pin_bar_bear", 0.0))
        hammer = float(features.get("hammer_detected", 0.0))
        shooting_star = float(features.get("shooting_star_detected", 0.0))
        # New Tier 1 patterns (bootstrap-promoted via 15-GAP-02)
        three_white_soldiers = float(features.get("three_white_soldiers", 0.0))
        three_black_crows = float(features.get("three_black_crows", 0.0))
        morning_star = float(features.get("morning_star", 0.0))
        evening_star = float(features.get("evening_star", 0.0))
        three_inside_up = float(features.get("three_inside_up", 0.0))
        three_inside_down = float(features.get("three_inside_down", 0.0))
        harami_cross = float(features.get("harami_cross", 0.0))
        dark_cloud_cover = float(features.get("dark_cloud_cover", 0.0))
        piercing_line = float(features.get("piercing_line", 0.0))

        # Collect directional candidates with priority (lower rank = higher priority)
        # Candidate: (priority_rank, direction, pattern_name, base_confidence, sr_auto_satisfied)
        candidates = []
        if hammer > 0.0:
            candidates.append((0, 1, "hammer", 0.65, True))
        if shooting_star > 0.0:
            candidates.append((0, -1, "shooting_star", 0.65, True))
        if engulfing_bull > 0.0:
            candidates.append((1, 1, "engulfing", 0.55, False))
        if engulfing_bear > 0.0:
            candidates.append((1, -1, "engulfing", 0.55, False))
        if three_white_soldiers > 0.0:
            candidates.append((1, 1, "three_white_soldiers", 0.75, False))
        if three_black_crows > 0.0:
            candidates.append((1, -1, "three_black_crows", 0.75, False))
        if pin_bar_bull > 0.0:
            candidates.append((2, 1, "pin_bar", 0.45, False))
        if pin_bar_bear > 0.0:
            candidates.append((2, -1, "pin_bar", 0.45, False))
        if morning_star > 0.0:
            candidates.append((2, 1, "morning_star", 0.80, False))
        if evening_star > 0.0:
            candidates.append((2, -1, "evening_star", 0.80, False))
        if three_inside_up > 0.0:
            candidates.append((3, 1, "three_inside_up", 0.65, False))
        if three_inside_down > 0.0:
            candidates.append((3, -1, "three_inside_down", 0.65, False))
        if dark_cloud_cover > 0.0:
            candidates.append((3, -1, "dark_cloud_cover", 0.70, False))
        if piercing_line > 0.0:
            candidates.append((3, 1, "piercing_line", 0.70, False))
        if harami_cross > 0.0:
            # harami_cross has no intrinsic direction — align with trend
            trend_dir_local = 1 if float(features.get("trend_regime", 0.0)) > 0 else -1
            candidates.append((4, trend_dir_local, "harami_cross", 0.60, False))

        if not candidates:
            return self._no_signal()

        # CNDL-02: Trend regime gate (mandatory)
        trend_regime = float(features.get("trend_regime", 0.0))
        if abs(trend_regime) < self.regime_threshold:
            return self._no_signal()

        # Filter candidates to those agreeing with trend direction
        trend_dir = 1 if trend_regime > 0 else -1
        matching = [
            (r, d, n, bc, sr) for (r, d, n, bc, sr) in candidates if d == trend_dir
        ]
        if not matching:
            return self._no_signal()

        # Select highest priority (lowest rank, then highest base_confidence)
        best = min(matching, key=lambda x: (x[0], -x[3]))
        _, direction, pattern_name, base_conf, sr_auto = best

        # CNDL-02: Volume confirmation
        vol_sma20 = float(features.get("volume_sma_20") or 0.0)
        if vol_sma20 <= 0:
            vol_sma20 = float(np.mean(vol[-20:])) if len(vol) >= 20 else float(np.mean(vol))
        volume_confirms = vol_sma20 > 0 and vol[-1] > vol_sma20 * self.volume_boost_ratio

        # CNDL-02: S/R proximity confirmation
        sr_confirms = sr_auto  # hammer/shooting_star satisfy S/R automatically
        if not sr_confirms:
            nearest_support = features.get("nearest_support")
            nearest_resistance = features.get("nearest_resistance")
            price = float(close[-1])
            sr_threshold = self.sr_proximity_atr * atr
            if isinstance(nearest_support, (int, float)) and nearest_support > 0:
                if abs(price - nearest_support) <= sr_threshold:
                    sr_confirms = True
            if not sr_confirms and isinstance(nearest_resistance, (int, float)) and nearest_resistance > 0:  # noqa: E501
                if abs(price - nearest_resistance) <= sr_threshold:
                    sr_confirms = True

        # At least one optional factor must confirm (unless sr_auto)
        if not sr_auto and not volume_confirms and not sr_confirms:
            return self._no_signal()

        # CNDL-03: Signal fields
        entry = float(close[-1])
        if direction == 1:
            stop = entry - atr * self.atr_stop_mult
            targets = [round(entry + atr * m, 2) for m in self.atr_target_mults]
        else:
            stop = entry + atr * self.atr_stop_mult
            targets = [round(entry - atr * m, 2) for m in self.atr_target_mults]

        # Confidence: +0.10 per confirming factor (volume, S/R).
        # sr_confirms is True for hammer/shooting_star (sr_auto) and for explicit proximity.
        confidence = base_conf
        if volume_confirms:
            confidence += 0.10
        if sr_confirms:
            confidence += 0.10
        confidence = round(min(0.90, max(0.10, confidence)), 4)

        # confluence_score: mandatory trend factor + optional volume + optional S/R
        confluence_score = 1  # trend is mandatory
        if volume_confirms:
            confluence_score += 1
        if sr_confirms:
            confluence_score += 1

        supporting: list[str] = [pattern_name]
        if volume_confirms:
            supporting.append("volume_confirm")
        if sr_confirms:
            supporting.append("sr_proximity")

        suffix = "long" if direction == 1 else "short"
        signal_type = f"candlestick_{pattern_name}_{suffix}"
        regime_ctx = "bullish" if direction == 1 else "bearish"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(float(stop), 2),
            "targets": targets,
            "confidence": confidence,
            "confluence_score": confluence_score,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = CandlestickPatternSetupPlugin()
