"""trad_CrossAssetDivergence — I7 cross-asset spread divergence setup plugin.

Fires when |spread_z| > 2.0 on the active EQ_INDEX pair (ES/NQ or ES/RTY).
Direction is regime-biased:
  - Ranging (hmm_regime=0): mean reversion — fade the outperformer.
  - Trending up (hmm_regime=1): continuation — follow the leader.
  - Trending down (hmm_regime=2): continuation — follow the leader down.
  - Unknown regime: default to reversion (conservative).

All state lives in frames['cross_asset'] — plugin is fully stateless.
Consumes cross-asset features published by cross_asset_service.py (Plan 037-01).

Renaissance principles applied:
- Segment relentlessly: regime-biased direction, not a single-direction rule.
- Instrument everything: multi-pair confirmation, multi-TF confirmation,
  volume imbalance, and regime clarity all contribute to confidence.
- Earn the right through proof: low_vol_flag suppresses when spread std is
  degenerate; multi-layer gate before firing.

Version: 1.0.0
Last Updated: 2026-03-18
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from .trade_framer import frame_trade

# EQ_INDEX base symbols — only these fire cross-asset divergence setups.
_EQ_INDEX_BASES: frozenset[str] = frozenset({"ES", "NQ", "RTY", "YM"})

# Spread z-score threshold for signal to fire.
_FIRE_THRESHOLD: float = 2.0

# Confidence base formula: 0.55 + (|spread_z| - 2.0) * 0.05
_CONF_BASE: float = 0.55
_CONF_SPREAD_SCALE: float = 0.05

# Confidence multipliers and boosts.
_CONF_MULTI_PAIR_MULT: float = 1.2
_CONF_MULTI_TF_MULT: float = 1.2
_CONF_VOL_IMBALANCE_BOOST: float = 0.05
_CONF_VOL_IMBALANCE_THRESHOLD: float = 1.5
_CONF_REGIME_PROB_BOOST: float = 0.10
_CONF_REGIME_PROB_THRESHOLD: float = 0.75


@dataclass
class CrossAssetDivergencePlugin:
    """I7 trading setup: cross-asset spread divergence across EQ_INDEX group.

    Stateless — all cross-asset state injected via frames['cross_asset'].
    Guards:
      - symbol base must be in {"ES", "NQ", "RTY", "YM"}
      - frames['cross_asset']['ready'] must be True
      - low_vol_flag must be False (signal unreliable in zero-vol environment)
      - |spread_z| > 2.0 on the active pair

    Confidence:
      base = 0.55 + (|spread_z| - 2.0) * 0.05
      if pairs_confirming == 2: base *= 1.2
      if cross_asset_5m agrees in direction: base *= 1.2
      if eq_vol_imbalance > 1.5: base += 0.05
      if hmm_regime_prob >= 0.75: base += 0.10
      confidence = clamp(base, 0.0, 1.0)
    """

    name: str = "trad_CrossAssetDivergence"
    regime_type: str = "any"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "confidence",
            "entry",
            "stop",
            "target_1",
            "target_2",
            "target_full",
            "setup_variant",
            "supporting_factors",
            "stop_basis",
        }
    )
    inputs: tuple[InputSpec, ...] = ()
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "cross_asset", "divergence"})

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        # Guard: symbol must be in EQ_INDEX group
        symbol = str(features.get("symbol", ""))
        base = _resolve_base(symbol)
        if base is None:
            return self._no_signal()

        # Guard: cross_asset data must be present and ready
        xa = frames.get("cross_asset") or {}
        if not xa.get("ready"):
            return self._no_signal()

        # Guard: low_vol_flag means spread std is near-zero — signal unreliable
        if xa.get("low_vol_flag", False):
            return self._no_signal()

        # Determine active pair and its spread_z
        active_pair = xa.get("active_pair", "ES_NQ")
        if active_pair == "ES_NQ":
            spread_z = float(xa.get("es_nq_spread_z", 0.0) or 0.0)
        else:
            spread_z = float(xa.get("es_rty_spread_z", 0.0) or 0.0)

        # Guard: threshold gate (strict >)
        if abs(spread_z) <= _FIRE_THRESHOLD:
            return self._no_signal()

        spread_positive = spread_z > 0  # ES outperformed pair

        # Direction logic — regime-biased
        hmm_regime = features.get("hmm_regime")
        hmm_regime_prob = float(features.get("hmm_regime_prob", 0.0) or 0.0)

        if hmm_regime == 0:
            # Ranging: mean reversion — fade the outperformer
            direction = -1 if spread_positive else 1
            setup_variant = "cross_asset_reversion"
        elif hmm_regime == 1:
            # Trending up: continuation — follow the leader
            direction = 1 if spread_positive else -1
            setup_variant = "cross_asset_continuation"
        elif hmm_regime == 2:
            # Trending down: continuation — follow the leader down
            direction = -1 if spread_positive else 1
            setup_variant = "cross_asset_continuation"
        else:
            # Unknown / unavailable regime: default to reversion (conservative)
            direction = -1 if spread_positive else 1
            setup_variant = "cross_asset_reversion"

        # Confidence formula
        conf = _CONF_BASE + (abs(spread_z) - _FIRE_THRESHOLD) * _CONF_SPREAD_SCALE

        pairs_confirming = int(xa.get("pairs_confirming", 0) or 0)
        if pairs_confirming == 2:
            conf *= _CONF_MULTI_PAIR_MULT

        # Multi-TF confirmation: 5m snapshot agrees in direction
        xa_5m = frames.get("cross_asset_5m") or {}
        if xa_5m.get("ready"):
            z5m_key = "es_nq_spread_z" if active_pair == "ES_NQ" else "es_rty_spread_z"
            z5m = float(xa_5m.get(z5m_key, 0.0) or 0.0)
            # Same sign = same directional pressure
            if (z5m > 0) == spread_positive:
                conf *= _CONF_MULTI_TF_MULT

        eq_vol_imbalance = float(xa.get("eq_vol_imbalance", 1.0) or 1.0)
        if eq_vol_imbalance > _CONF_VOL_IMBALANCE_THRESHOLD:
            conf += _CONF_VOL_IMBALANCE_BOOST

        if hmm_regime_prob >= _CONF_REGIME_PROB_THRESHOLD:
            conf += _CONF_REGIME_PROB_BOOST

        confidence = float(min(max(conf, 0.0), 1.0))

        # Frame trade for stop/target computation
        df = frames.get("main")
        if df is None or len(df) < 2:
            return self._no_signal()

        atr = float(features.get("atr_14", 0.0) or 0.0)
        entry_price = float(df["close"].iloc[-1])

        signal_type = (
            "cross_asset_divergence_long"
            if direction == 1
            else "cross_asset_divergence_short"
        )
        tf = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry_price,
            features=features,
            atr=atr,
        )

        if not tf.viable:
            return self._no_signal()

        # Extract target prices from TradeFrame.targets list
        target_1 = float(tf.targets[0].price) if len(tf.targets) > 0 else 0.0
        target_2 = float(tf.targets[1].price) if len(tf.targets) > 1 else 0.0
        target_full = float(tf.targets[2].price) if len(tf.targets) > 2 else target_2

        supporting_factors: dict[str, Any] = {
            "active_pair": active_pair,
            "es_nq_spread_z": xa.get("es_nq_spread_z"),
            "es_rty_spread_z": xa.get("es_rty_spread_z"),
            "eq_corr_break": xa.get("eq_corr_break"),
            "eq_vol_imbalance": eq_vol_imbalance,
            "pairs_confirming": pairs_confirming,
            "data_quality_score": xa.get("data_quality_score"),
            "hmm_regime": hmm_regime,
            "hmm_regime_prob": hmm_regime_prob,
        }

        return {
            "signal_type": signal_type,
            "direction": direction,
            "confidence": confidence,
            "entry": float(tf.entry),
            "stop": float(tf.stop),
            "target_1": target_1,
            "target_2": target_2,
            "target_full": target_full,
            "stop_basis": tf.stop_basis,
            "setup_variant": setup_variant,
            "supporting_factors": supporting_factors,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


def _resolve_base(symbol: str) -> str | None:
    """Return the EQ_INDEX base for symbol, or None if not in the group.

    Matches symbols like "ESM6", "NQZ5", "RTYU6", "YMH6" to their base.
    The base is the shortest prefix in _EQ_INDEX_BASES that the symbol starts with,
    provided the symbol is longer than the base (to avoid matching "ES" == "ES").
    """
    for base in _EQ_INDEX_BASES:
        if symbol.startswith(base) and len(symbol) > len(base):
            return base
    return None


plugin = CrossAssetDivergencePlugin()
