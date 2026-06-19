"""trad_LVNBreakout — I7 trend setup consuming I4 VolumeProfile LVN fields.

Fires when price is within a Low Volume Node (area of thin historical volume)
and a trending move with volume expansion suggests rapid price acceleration
through the LVN to the next HVN.

Renaissance principles:
- Segment relentlessly: fires only in trending regime (continuous hmm_regime_weight gate)
- Instrument everything: LVN width, volume ratio all logged
- Earn the right through proof: in_lvn + rel_volume >= 1.5 + trending required
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
)
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_VOL_THRESHOLD: float = 1.5


@dataclass
class LVNBreakoutPlugin:
    """Trend setup: price in LVN with volume expansion in trending regime.

    Gates:
    - in_lvn == 1.0 (currently in a low-volume node)
    - hmm_regime_weight (up or down) >= 0.30 — continuous trending gate
    - abs(ctf_score) >= 0.25 — I6 confluence gate
    - rel_volume >= 1.5 (or fallback to bar_vol/avg_vol ratio)
    - Direction: long if close > open (up bar), short if close < open (down bar)

    Targets: T1 = nearest_hvn_above (long) or nearest_hvn_below (short)
    """

    name: str = "trad_LVNBreakout"
    shadow_only: bool = True
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
    capability_tags: frozenset[str] = frozenset({"trading", "trend"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
    regime_type: str = "trend"
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        vol_threshold = (
            cfg.get_sync("threshold.lvn_breakout.vol_threshold", _VOL_THRESHOLD)
            if cfg
            else _VOL_THRESHOLD
        )
        w_vol = cfg.get_sync("weights.lvn_breakout.vol", 0.30) if cfg else 0.30
        w_trend = cfg.get_sync("weights.lvn_breakout.trend_clarity", 0.25) if cfg else 0.25
        w_lvn = cfg.get_sync("weights.lvn_breakout.lvn_inverse", 0.25) if cfg else 0.25
        w_close = cfg.get_sync("weights.lvn_breakout.close_strength", 0.20) if cfg else 0.20

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
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Gate: in_lvn required ─────────────────────────────────────────────
        in_lvn = features.get("in_lvn")
        if in_lvn is None:
            return no_signal()
        if float(in_lvn) != 1.0:
            return no_signal()

        # ── Gate 1: continuous trending regime ────────────────────────────────
        if hmm_trending_weight(features) < get_min_regime_weight():
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # ── Volume gate (ORB15 fallback pattern) ─────────────────────────────
        rel_volume = features.get("rel_volume")
        if rel_volume is not None and isinstance(rel_volume, (int, float)):
            vol_ok = float(rel_volume) >= vol_threshold
            volume_ratio = float(rel_volume)
        else:
            bar_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else 0.0
            vol_ok = avg_vol > 0 and bar_vol >= vol_threshold * avg_vol
            volume_ratio = (bar_vol / avg_vol) if avg_vol > 0 else 0.0

        if not vol_ok:
            return no_signal()

        # ── Direction from bar close strength ─────────────────────────────────
        close_arr = df["close"].to_numpy(dtype=float)
        open_arr = df["open"].to_numpy(dtype=float)
        entry = float(close_arr[-1])
        bar_open = float(open_arr[-1])

        if entry > bar_open:
            direction = 1  # up bar — long breakout
        elif entry < bar_open:
            direction = -1  # down bar — short breakout
        else:
            return no_signal()  # doji — no directional conviction

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "lvn_breakout_long" if direction == 1 else "lvn_breakout_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )
        if not frame.viable:
            return no_signal()

        # ── Override T1 with nearest HVN in breakout direction ────────────────
        hvn_above = features.get("nearest_hvn_above")
        hvn_below = features.get("nearest_hvn_below")

        targets: list[float] = []
        if direction == 1 and hvn_above is not None:
            hvn_t1 = float(hvn_above)
            if hvn_t1 > entry:
                targets.append(round(hvn_t1, 2))
        elif direction == -1 and hvn_below is not None:
            hvn_t1 = float(hvn_below)
            if hvn_t1 < entry:
                targets.append(round(hvn_t1, 2))

        # Add frame targets as additional levels
        for t in frame.targets:
            price = round(t.price, 2)
            if price not in targets:
                targets.append(price)

        # If HVN target not available, use frame targets
        if not targets:
            targets = [round(t.price, 2) for t in frame.targets]

        # ── LVN width computation ─────────────────────────────────────────────
        lvn_above = features.get("nearest_lvn_above")
        lvn_below = features.get("nearest_lvn_below")
        if lvn_above is not None and lvn_below is not None and atr > 0:
            lvn_width_atr = abs(float(lvn_above) - float(lvn_below)) / atr
        else:
            lvn_width_atr = 0.0

        # ── Confidence scoring ────────────────────────────────────────────────
        vol_score = clamp01((volume_ratio - vol_threshold) / vol_threshold)

        # Trend regime clarity via hmm_prob: 0.25 weight
        # Pre-existing intrinsic factor — preserved per plan (LVNBreakout is in no-rewrite set)
        hmm_prob = float(features.get("hmm_probability", 0.7))
        trend_clarity = clamp01((hmm_prob - 0.5) * 2.0)

        # LVN width inverse: 0.25 weight (thinner LVN = faster move through it)
        lvn_inverse = max(0.0, 1.0 - lvn_width_atr / 2.0)

        # Bar close strength: 0.20 weight
        bar_range = abs(float(df["high"].iloc[-1]) - float(df["low"].iloc[-1]))
        if bar_range > 0:
            close_strength = clamp01(abs(entry - bar_open) / bar_range)
        else:
            close_strength = 0.5

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "vol_score": round(vol_score, 4),
            "trend_clarity": round(trend_clarity, 4),
            "lvn_inverse": round(lvn_inverse, 4),
            "close_strength": round(close_strength, 4),
        }

        raw_conf = (
            w_vol * vol_score
            + w_trend * trend_clarity
            + w_lvn * lvn_inverse
            + w_close * close_strength
        )

        # ── Supporting factors ────────────────────────────────────────────────
        regime_up = hmm_regime_weight(features, "up")
        regime_down = hmm_regime_weight(features, "down")
        supporting: list[str] = [
            "in_lvn=1.0",
            f"lvn_width_atr={lvn_width_atr:.3f}",
            f"lvn_breakout_volume_ratio={volume_ratio:.2f}",
        ]
        if regime_up >= regime_down:
            supporting.append("trending_up")
        else:
            supporting.append("trending_down")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "trending_up" if regime_up >= regime_down else "trending_down"

        signal = make_signal_from_frame(
            frame,
            symbol="",
            timeframe="",
            timestamp="",
            signal_type=signal_type,
            setup_plugin="trad_LVNBreakout",
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        signal["targets"] = targets
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LVNBreakoutPlugin()
