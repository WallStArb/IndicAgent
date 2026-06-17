"""trad_CrossAssetDivergence — I7 cross-asset spread divergence setup plugin.

Fires when |spread_z| > 2.0 on the active EQ_INDEX pair (ES/NQ or ES/RTY).
Direction is regime-biased:
  - Ranging (hmm_regime=0): mean reversion — fade the outperformer.
  - Trending up (hmm_regime=1): continuation — follow the leader.
  - Trending down (hmm_regime=2): continuation — follow the leader down.
  - Unknown regime: default to reversion (conservative).

All state lives in frames['cross_asset'] — plugin is fully stateless.
Consumes cross-asset features published by cross_asset_service.py (Plan 037-01).

# live-only: requires cross_asset_service real-time state (frames['cross_asset']).
# Historical replay processes single symbols; cross-instrument bar arrays are not
# pre-loaded. _CORPUS_EXCLUDABLE = True — zero emissions in replay is architectural,
# not a bug. See Phase 131 D-02.

Renaissance principles applied:
- Segment relentlessly: regime-biased direction, not a single-direction rule.
- Instrument everything: multi-pair confirmation, multi-TF confirmation,
  volume imbalance, and regime clarity all contribute to confidence.
- Earn the right through proof: low_vol_flag suppresses when spread std is
  degenerate; multi-layer gate before firing.

Version: 1.1.0
Last Updated: 2026-03-21
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..cross_asset_features import resolve_eq_index_base
from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import compose_confidence
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

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
      confidence = compose_confidence(base)
    """

    name: str = "trad_CrossAssetDivergence"
    _CORPUS_EXCLUDABLE: bool = True  # live-only: requires cross_asset_service real-time state
    regime_type: str = "any"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "confidence",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
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
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        # Guard: symbol must be in EQ_INDEX group
        symbol = str(features.get("symbol", ""))
        base = resolve_eq_index_base(symbol)
        if base is None:
            return no_signal()

        # Guard: cross_asset data must be present and ready
        xa = frames.get("cross_asset") or {}
        if not xa.get("ready"):
            return no_signal()

        # Guard: low_vol_flag means spread std is near-zero — signal unreliable
        if xa.get("low_vol_flag", False):
            return no_signal()

        # Determine active pair and its spread_z
        active_pair = xa.get("active_pair", "ES_NQ")
        if active_pair == "ES_NQ":
            spread_z = float(xa.get("es_nq_spread_z", 0.0) or 0.0)
        else:
            spread_z = float(xa.get("es_rty_spread_z", 0.0) or 0.0)

        # Guard: threshold gate (strict >)
        if abs(spread_z) <= _FIRE_THRESHOLD:
            return no_signal()

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

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "spread_z_score": round(min(1.0, (abs(spread_z) - _FIRE_THRESHOLD) / 3.0), 4),
            "pairs_confirming_score": round(min(1.0, pairs_confirming / 2.0), 4),
            "regime_prob_score": round(min(1.0, hmm_regime_prob), 4),
        }

        confidence = compose_confidence(conf)

        # Frame trade for stop/target computation
        df = frames.get("main")
        if df is None or len(df) < 2:
            return no_signal()

        atr = float(get_atr_with_floor_from_frames(frames) or 0.0)
        if atr <= 0:
            return no_signal()

        entry_price = float(df["close"].iloc[-1])

        signal_type = (
            "cross_asset_divergence_long" if direction == 1 else "cross_asset_divergence_short"
        )
        tf = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry_price,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )

        if not tf.viable:
            return no_signal()

        # regime_context as str (not dict)
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        supporting_factors: list[str] = [
            f"active_pair={active_pair}",
            f"spread_z={spread_z:.3f}",
            f"pairs_confirming={pairs_confirming}",
            f"eq_vol_imbalance={eq_vol_imbalance:.2f}",
            f"hmm_regime={hmm_regime}",
            f"hmm_regime_prob={hmm_regime_prob:.3f}",
        ]
        if xa.get("eq_corr_break") is not None:
            supporting_factors.append(f"eq_corr_break={xa['eq_corr_break']:.3f}")
        if xa.get("data_quality_score") is not None:
            supporting_factors.append(f"data_quality_score={xa['data_quality_score']:.3f}")

        # exhaustion: not applicable — spike/divergence signals are regime-independent;
        # Phase 49 will learn gate behavior from shadow data
        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting_factors,
            factor_scores=factor_scores,
        )
        signal["setup_variant"] = setup_variant
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return no_signal()


plugin = CrossAssetDivergencePlugin()
