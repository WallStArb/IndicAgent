"""trad_LVNBreakout — I7 trend setup consuming I4 VolumeProfile LVN fields.

Fires when price is within a Low Volume Node (area of thin historical volume)
and a trending move with volume expansion suggests rapid price acceleration
through the LVN to the next HVN.

Renaissance principles:
- Segment relentlessly: fires only in trending regime (hmm_regime in 1, 2)
- Instrument everything: LVN width, volume ratio all logged
- Earn the right through proof: in_lvn + rel_volume >= 1.5 + trending required
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .trade_framer import frame_trade

# Volume expansion threshold for LVN breakout
_VOL_THRESHOLD: float = 1.5


@dataclass
class LVNBreakoutPlugin:
    """Trend setup: price in LVN with volume expansion in trending regime.

    Gates:
    - in_lvn == 1.0 (currently in a low-volume node)
    - hmm_regime in (1, 2) — must be trending (not ranging)
    - rel_volume >= 1.5 (or fallback to bar_vol/avg_vol ratio)
    - Direction: long if close > open (up bar), short if close < open (down bar)

    Targets: T1 = nearest_hvn_above (long) or nearest_hvn_below (short)
    """

    name: str = "trad_LVNBreakout"
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "trend"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        # ── Gate: in_lvn required ─────────────────────────────────────────────
        in_lvn = features.get("in_lvn")
        if in_lvn is None:
            return self._no_signal()
        if float(in_lvn) != 1.0:
            return self._no_signal()

        # ── Gate: trending regime ─────────────────────────────────────────────
        hmm = features.get("hmm_regime")
        if hmm is None:
            return self._no_signal()
        hmm = int(hmm)
        if hmm not in (1, 2):
            return self._no_signal()

        # ── ATR ───────────────────────────────────────────────────────────────
        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # ── Volume gate (ORB15 fallback pattern) ─────────────────────────────
        rel_volume = features.get("rel_volume")
        if rel_volume is not None and isinstance(rel_volume, (int, float)):
            vol_ok = float(rel_volume) >= _VOL_THRESHOLD
            volume_ratio = float(rel_volume)
        else:
            bar_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].mean())
            vol_ok = avg_vol > 0 and bar_vol >= _VOL_THRESHOLD * avg_vol
            volume_ratio = (bar_vol / avg_vol) if avg_vol > 0 else 0.0

        if not vol_ok:
            return self._no_signal()

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
            return self._no_signal()  # doji — no directional conviction

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "lvn_breakout_long" if direction == 1 else "lvn_breakout_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            return self._no_signal()

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
        # Volume ratio: 0.3 weight
        vol_score = min(1.0, max(0.0, (volume_ratio - _VOL_THRESHOLD) / _VOL_THRESHOLD))

        # Trend regime clarity via hmm_prob: 0.25 weight
        hmm_prob = float(features.get("hmm_probability", 0.7))
        trend_clarity = min(1.0, max(0.0, (hmm_prob - 0.5) * 2.0))

        # LVN width inverse: 0.25 weight (thinner LVN = faster move through it)
        lvn_inverse = max(0.0, 1.0 - lvn_width_atr / 2.0)

        # Bar close strength: 0.2 weight
        bar_range = abs(float(df["high"].iloc[-1]) - float(df["low"].iloc[-1]))
        if bar_range > 0:
            close_strength = abs(entry - bar_open) / bar_range
        else:
            close_strength = 0.5

        raw_conf = (
            0.30 * vol_score
            + 0.25 * trend_clarity
            + 0.25 * lvn_inverse
            + 0.20 * close_strength
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # ── Supporting factors ────────────────────────────────────────────────
        supporting: list[str] = [
            "in_lvn=1.0",
            f"lvn_width_atr={lvn_width_atr:.3f}",
            f"lvn_breakout_volume_ratio={volume_ratio:.2f}",
        ]
        if hmm == 1:
            supporting.append("trending_up")
        else:
            supporting.append("trending_down")

        regime_ctx = "trending_up" if hmm == 1 else "trending_down"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = LVNBreakoutPlugin()
