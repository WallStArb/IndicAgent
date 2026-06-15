"""I7 CandlestickPatternSetup — confluence-gated candlestick setup consuming I5 outputs.

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
from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import (
    capture_signal_features,
    clamp01,
    compose_confidence,
    get_min_ctf_score,
    get_min_regime_weight,
)
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

# Module-level constants — static across all bars, extracted from hot path.
_FALLBACK_WEIGHTS: dict[str, float] = {
    "hammer": 0.65,
    "shooting_star": 0.65,
    "engulfing": 0.55,
    "three_white_soldiers": 0.75,
    "three_black_crows": 0.75,
    "pin_bar": 0.45,
    "morning_star": 0.80,
    "evening_star": 0.80,
    "three_inside_up": 0.65,
    "three_inside_down": 0.65,
    "dark_cloud_cover": 0.70,
    "piercing_line": 0.70,
    "harami_cross": 0.60,
    # Phase 42 bootstrap priors
    "abandoned_baby": 0.70,
    "kicker": 0.70,
    "harami": 0.60,
    "tweezer": 0.60,
    "belt_hold": 0.55,
}

_PRIORITY_RANKS: dict[str, int] = {
    "hammer": 0,
    "shooting_star": 0,
    "engulfing": 1,
    "three_white_soldiers": 1,
    "three_black_crows": 1,
    # Phase 42 Tier 1 reliability (abandoned_baby, kicker high win rate)
    "abandoned_baby": 1,
    "kicker": 1,
    "pin_bar": 2,
    "morning_star": 2,
    "evening_star": 2,
    # Phase 42 Tier 2 reliability
    "harami": 2,
    "three_inside_up": 3,
    "three_inside_down": 3,
    "dark_cloud_cover": 3,
    "piercing_line": 3,
    "tweezer": 3,
    "belt_hold": 3,
    "harami_cross": 4,
}

_SR_AUTO_PATTERNS: frozenset[str] = frozenset({"hammer", "shooting_star"})


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
    shadow_only: bool = True
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "confluence_score",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "pattern", "structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    requires_i6_confluence: bool = True
    regime_threshold: float = 0.5
    volume_boost_ratio: float = 1.3
    sr_proximity_atr: float = 0.3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
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

        # ── Dual gate (before OHLCV access) ─────────────────────────────────
        # Gate 1: regime gate (any-regime uses hmm_trending_weight)
        if hmm_trending_weight(features) < get_min_regime_weight():
            return no_signal()

        # ECL annotation: ctf_score is extrinsic context, not an emission gate (Phase 123)
        _ctf_raw = features.get("ctf_score")
        ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
        ctf_confirmed: bool | None = (
            (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
        )
        # No return no_signal() — signal fires if intrinsic criteria met

        # ── OHLCV access (after dual gate) ───────────────────────────────────
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        vol = df["volume"].to_numpy(dtype=float)

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

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

        # Get pattern weights injected by service (15-min DB cache), or use fallback priors.
        # _FALLBACK_WEIGHTS match bootstrap priors from 42-02; active when cache not yet warm.
        pattern_weights: dict[str, float] = frames.get("pattern_weights") or _FALLBACK_WEIGHTS

        # Phase 42: 10 new candlestick patterns (harami directional, abandoned baby, tweezer,
        # belt hold, kicker) — read from I5 features dict (CNDL-01: no raw price re-detection)
        harami_bull = float(features.get("harami_bull", 0.0))
        harami_bear = float(features.get("harami_bear", 0.0))
        abandoned_baby_bull = float(features.get("abandoned_baby_bull", 0.0))
        abandoned_baby_bear = float(features.get("abandoned_baby_bear", 0.0))
        tweezer_top = float(features.get("tweezer_top", 0.0))
        tweezer_bottom = float(features.get("tweezer_bottom", 0.0))
        belt_hold_bull = float(features.get("belt_hold_bull", 0.0))
        belt_hold_bear = float(features.get("belt_hold_bear", 0.0))
        kicker_bull = float(features.get("kicker_bull", 0.0))
        kicker_bear = float(features.get("kicker_bear", 0.0))

        # Map (pattern_name, direction) → flag value for all 24 directional patterns.
        # Direction: 1=bullish, -1=bearish, 0=neutral (direction assigned dynamically).
        # harami_cross direction follows trend — resolved after trend gate below.
        pattern_flags: dict[tuple[str, int], float] = {
            ("hammer", 1): hammer,
            ("shooting_star", -1): shooting_star,
            ("engulfing", 1): engulfing_bull,
            ("engulfing", -1): engulfing_bear,
            ("three_white_soldiers", 1): three_white_soldiers,
            ("three_black_crows", -1): three_black_crows,
            ("pin_bar", 1): pin_bar_bull,
            ("pin_bar", -1): pin_bar_bear,
            ("morning_star", 1): morning_star,
            ("evening_star", -1): evening_star,
            ("three_inside_up", 1): three_inside_up,
            ("three_inside_down", -1): three_inside_down,
            ("dark_cloud_cover", -1): dark_cloud_cover,
            ("piercing_line", 1): piercing_line,
            # Phase 42: 10 new patterns
            ("harami", 1): harami_bull,
            ("harami", -1): harami_bear,
            ("abandoned_baby", 1): abandoned_baby_bull,
            ("abandoned_baby", -1): abandoned_baby_bear,
            ("tweezer", -1): tweezer_top,  # bearish reversal (forms at highs)
            ("tweezer", 1): tweezer_bottom,  # bullish reversal (forms at lows)
            ("belt_hold", 1): belt_hold_bull,
            ("belt_hold", -1): belt_hold_bear,
            ("kicker", 1): kicker_bull,
            ("kicker", -1): kicker_bear,
        }

        # Build candidates list using pattern_weights (injected by service or fallback priors).
        # Candidate: (priority_rank, direction, pattern_name, base_confidence, sr_auto_satisfied)
        candidates = []
        for (pattern_name, direction), flag_value in pattern_flags.items():
            if flag_value <= 0.0:
                continue
            priority = _PRIORITY_RANKS.get(pattern_name, 3)
            base_conf = pattern_weights.get(pattern_name, _FALLBACK_WEIGHTS.get(pattern_name, 0.55))
            sr_auto = pattern_name in _SR_AUTO_PATTERNS
            candidates.append((priority, direction, pattern_name, base_conf, sr_auto))

        # harami_cross has no intrinsic direction — align with trend (resolved after trend gate)
        if harami_cross > 0.0:
            trend_dir_local = 1 if float(features.get("trend_regime", 0.0)) > 0 else -1
            base_conf = pattern_weights.get(
                "harami_cross", _FALLBACK_WEIGHTS.get("harami_cross", 0.60)
            )
            candidates.append((4, trend_dir_local, "harami_cross", base_conf, False))

        if not candidates:
            return no_signal()

        # CNDL-02: Trend regime gate (mandatory; binary trend_regime check stays as quality filter)
        trend_regime = float(features.get("trend_regime", 0.0))
        if abs(trend_regime) < self.regime_threshold:
            return no_signal()

        # Filter candidates to those agreeing with trend direction
        trend_dir = 1 if trend_regime > 0 else -1
        matching = [(r, d, n, bc, sr) for (r, d, n, bc, sr) in candidates if d == trend_dir]
        if not matching:
            return no_signal()

        # Select highest priority (lowest rank, then highest base_confidence)
        best = min(matching, key=lambda x: (x[0], -x[3]))
        _, direction, pattern_name, base_conf, sr_auto = best

        # CNDL-02: Volume confirmation
        vol_sma20 = float(features.get("volume_sma_20") or 0.0)
        if vol_sma20 <= 0:
            vol_sma20 = float(np.mean(vol[-21:-1])) if len(vol) >= 2 else 0.0
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
            if (
                not sr_confirms
                and isinstance(nearest_resistance, (int, float))
                and nearest_resistance > 0
            ):  # noqa: E501
                if abs(price - nearest_resistance) <= sr_threshold:
                    sr_confirms = True

        # At least one optional factor must confirm (unless sr_auto)
        if not sr_auto and not volume_confirms and not sr_confirms:
            return no_signal()

        # CNDL-03: Signal fields
        entry = float(close[-1])

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        # pattern_confidence: base weight from pattern_weights / fallback priors
        pattern_confidence_score = clamp01(base_conf)

        # body_ratio: measures candle body quality (close vs high-low range)
        candle_high = float(high[-1])
        candle_low = float(low[-1])
        candle_range = candle_high - candle_low
        candle_body = abs(float(close[-1]) - float(open_[-1]))
        body_ratio = clamp01(candle_body / max(1e-9, candle_range))

        # volume_confirmation: volume relative to SMA
        if volume_confirms:
            volume_confirmation = clamp01((float(vol[-1]) / max(1e-9, vol_sma20) - 1.0) / 1.0)
        else:
            volume_confirmation = 0.2  # below-average volume

        # zone_proximity: S/R confirms = high quality; fallback for sr_auto patterns
        zone_proximity = 0.7 if sr_confirms else 0.3

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "pattern_confidence_score": round(pattern_confidence_score, 4),
            "body_ratio": round(body_ratio, 4),
            "volume_confirmation": round(volume_confirmation, 4),
            "zone_proximity": round(zone_proximity, 4),
        }

        # Weights sum to 1.0
        raw_conf = (
            0.35 * pattern_confidence_score
            + 0.25 * body_ratio
            + 0.25 * volume_confirmation
            + 0.15 * zone_proximity
        )

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

        confidence = compose_confidence(raw_conf)

        suffix = "long" if direction == 1 else "short"
        signal_type = f"candlestick_{pattern_name}_{suffix}"
        regime_ctx = "bullish" if direction == 1 else "bearish"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        ctx = capture_signal_features(features, direction, "session", confidence)
        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            confluence_score=float(confluence_score),
            supporting_factors=supporting,
            features_snapshot=ctx,
            context_features=ctx,
            ctf_score=ctf_score,
            ctf_confirmed=ctf_confirmed,
            factor_scores=factor_scores,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CandlestickPatternSetupPlugin()
