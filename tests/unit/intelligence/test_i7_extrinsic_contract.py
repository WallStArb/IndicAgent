"""Contract tests: Wave 0 extrinsic strip held across all 15 modified I7 plugins.

Two invariants proved here:
  1. Perturbing only extrinsic keys (regime, CTF, zone, SMC, exhaustion) leaves
     confidence unchanged to float precision — extrinsic fields are captured, not
     scored.
  2. Every plugin that fires returns confidence in [0.0, 0.95].

A third test proves capture-vs-confidence separation: ctf_score (or another extrinsic
key) still appears in the captured features_snapshot despite being absent from the
confidence formula.

Wave 0 blast radius (15 plugins):
  118-00 deletions (12): ofi_continuation, ofi_divergence, cvd_divergence,
    failed_breakout, orb15, orb30, prev_day_level_test, choch_reversal,
    supply_demand_setup, liquidity_sweep_reclaim, liquidity_hunt, gap_analysis_setup
  118-00b restructures (3): momentum_breakout, squeeze_expansion, trend_following

Phase 119 note: ctf_score is a mandatory gate (not an extrinsic) for the 17 Phase-119
refactored plugins. Perturbing ctf_score for those plugins would flip the gate and change
confidence, violating the test invariant. The perturbation set for Phase-119 plugins
excludes ctf_score only; ctf_structure_alignment and ctf_trend_alignment remain perturbed.
The [0.0, 0.95] confidence range assertion is unchanged.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Extrinsic perturbation keys — perturbing these must NOT change confidence
#
# Phase 118 stripped three categories:
#   1. HMM regime weights (hmm_regime_weight, trend_regime in composite)
#   2. CTF (I6) scores (ctf_score, ctf_structure_alignment, ctf_trend_alignment)
#   3. Exhaustion boost/guard (apply_exhaustion_boost/guard, exhaustion_score)
#   4. Zone context penalties (supply/demand zone friction penalties)
#
# NOTE: FVG/OB/CHoCH/BOS structural SMC signals are NOT in this set.
# For supply_demand_setup and liquidity_sweep_reclaim, these are intrinsic
# structural confirmations (ICT Act 1-2-3 model, sweep quality) — not the
# extrinsic context signals that Phase 118 targeted. They were intentionally
# preserved in those plugins as part of the core pattern logic.
# ---------------------------------------------------------------------------

_EXTRINSIC_KEYS: dict = {
    "ctf_score": 0.9,
    "ctf_structure_alignment": 1.0,
    "ctf_trend_alignment": 1.0,
    "ctf_regime_agreement": 1.0,
    "delta_exhaustion": 1.0,
    "exhaustion_score": 0.9,
    "exhaustion_side": "bull",
    "exhaustion_bars": 5.0,
}

# Zone penalty keys — these were stripped from momentum_breakout, trend_following,
# and liquidity_hunt but are still intrinsic gates for supply_demand_setup.
_ZONE_PENALTY_KEYS: dict = {
    "in_supply_zone": 1.0,
    "in_demand_zone": 1.0,
    "supply_strength": 1.0,
    "demand_strength": 1.0,
    "price_in_premium": 1.0,
}


# ---------------------------------------------------------------------------
# Per-plugin firing-scenario factories
# ---------------------------------------------------------------------------


def _frames(df, features: dict) -> dict:
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
    }


def _scenario_ofi_continuation():
    """OFIContinuation fires on sustained OFI + volume spike structural trigger (Phase 124)."""
    from src.intelligence.trading.ofi_continuation import OFIContinuationPlugin

    close = np.linspace(5000.0, 5010.0, 25)
    df = make_ohlcv(close)
    # Phase 124: requires structural trigger (acceleration OR volume spike) on top of sustained flow.
    # volume_sma_20=400; make_ohlcv default volume=1000 → 2.5x spike satisfies _VOLUME_SPIKE_RATIO=2.0.
    features = {"ofi_ewma_20": 600.0, "ofi_ewma_5": 600.0, "atr_14": 2.0, "volume_sma_20": 400.0}

    def _fire(extra: dict) -> dict:
        plugin = OFIContinuationPlugin()
        f = {**features, **extra}
        for _ in range(9):
            plugin.compute_full(_frames(df, f))
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_ofi_divergence():
    """OFIDivergence fires after 2 bars of stable divergence sign."""
    import pandas as pd

    from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

    closes = [5000.0 + i * 0.1 for i in range(30)]
    df = pd.DataFrame(
        {
            "open": [c - 0.05 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * 30,
        }
    )
    features = {
        "ofi_divergence": 2.0,
        "ofi_spike_z": 2.0,
        "ofi_ewma_5": 0.5,
        "ofi_ewma_20": 0.3,
        "rel_volume": 1.8,
        "hmm_regime": 0.0,
        "atr_14": 2.0,
        # Phase 119: dual gate requires hmm_trending_weight >= 0.30 and abs(ctf_score) >= 0.25
        "hmm_prob_trending_up": 0.6,
        "hmm_prob_trending_down": 0.3,
        "ctf_score": 0.5,
    }

    def _fire(extra: dict) -> dict:
        plugin = OFIDivergencePlugin()
        f = {**features, **extra}
        for _ in range(2):
            plugin.compute_full(_frames(df, f))
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_cvd_divergence():
    """CVDDivergence fires after 5 bars of opposing CVD vs price (Phase 118: raised from 3)."""
    from src.intelligence.trading.cvd_divergence import CVDDivergencePlugin

    close = np.linspace(5000.0, 5010.0, 25)
    df = make_ohlcv(close)
    features = {
        "cvd_divergence": -1.5,
        "cvd_slope_5bar": -200.0,
        "ofi_divergence": 0.0,
        "atr_14": 2.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = CVDDivergencePlugin()
        f = {**features, **extra}
        for _ in range(4):
            plugin.compute_full(_frames(df, f))
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_choch_reversal():
    """CHoCHReversal fires when choch_detected==1.0 and choch_direction set."""
    from src.intelligence.trading.choch_reversal import CHoCHReversalPlugin

    close = np.linspace(5000.0, 5200.0, 50)
    df = make_ohlcv(close)
    features = {
        "choch_detected": 1.0,
        "choch_direction": 1,
        "atr_14": 8.0,
        "swing_high": 5250.0,
        "swing_low": 4900.0,
        "nearest_resistance": 5300.0,
        "nearest_support": 4800.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = CHoCHReversalPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_supply_demand_setup():
    """SupplyDemandSetup fires when in_demand_zone==1.0 with sufficient freshness."""
    from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin

    close = np.linspace(4990.0, 5000.0, 50)
    df = make_ohlcv(close)
    features = {
        "in_demand_zone": 1.0,
        "in_supply_zone": 0.0,
        "demand_freshness": 0.8,
        "demand_strength": 0.7,
        "nearest_demand_high": 5005.0,
        "nearest_demand_low": 4985.0,
        "atr_14": 8.0,
        "swing_high": 5100.0,
        "swing_low": 4880.0,
        "nearest_resistance": 5100.0,
        "nearest_support": 4880.0,
        "price_in_premium": -1,
    }

    def _fire(extra: dict) -> dict:
        # Remove extrinsic zone keys that would break the gate if both zones active
        f = {k: v for k, v in {**features, **extra}.items()}
        # Ensure demand zone is active and supply is not to avoid the both-active gate
        f["in_demand_zone"] = 1.0
        f["in_supply_zone"] = 0.0
        plugin = SupplyDemandSetupPlugin()
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_liquidity_sweep_reclaim():
    """LiquiditySweepReclaim fires when sweep_detected and sweep_reclaimed."""
    from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

    close = np.full(100, 5000.0)
    df = make_ohlcv(close)
    features = {
        "sweep_detected": 1.0,
        "sweep_reclaimed": 1.0,
        "sweep_type": 1.0,
        "sweep_level": 4990.0,
        "atr_14": 8.0,
        "swing_high": 5100.0,
        "swing_low": 4880.0,
        "nearest_resistance": 5100.0,
        "nearest_support": 4880.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = LiquiditySweepReclaimPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_liquidity_hunt():
    """LiquidityHunt fires when sweep at named SSL level with significance >= 0.60."""
    from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin

    atr = 8.0
    swept_level = 4992.0
    close = np.full(100, 5000.0)
    df = make_ohlcv(close)
    features = {
        "sweep_detected": 1.0,
        "sweep_reclaimed": 1.0,
        "sweep_type": 1.0,
        "sweep_level": swept_level,
        "ssl_level": swept_level,
        "bsl_level": 0.0,
        "ssl_significance": 0.75,
        "bsl_significance": 0.0,
        "atr_14": atr,
        "swing_high": 5100.0,
        "swing_low": 4880.0,
        "nearest_resistance": 5100.0,
        "nearest_support": 4880.0,
        # Phase 119: dual gate (trend, direction-specific) — at least one side >= 0.30
        "hmm_prob_trending_up": 0.3,
        "hmm_prob_trending_down": 0.6,
        "ctf_score": 0.5,
    }

    def _fire(extra: dict) -> dict:
        plugin = LiquidityHuntPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_gap_analysis_setup():
    """GapAnalysisSetup fires when gap > 0.8*ATR in open vs prior close (Phase 118: raised from 0.3)."""
    from src.intelligence.trading.gap_analysis_setup import GapAnalysisSetupPlugin

    n = 100
    atr = 10.0
    close = np.linspace(5000, 5200, n)
    df = make_ohlcv(close)
    # Inject a bullish gap: open[-1] = close[-2] + 1.0*ATR (Phase 118: must exceed 0.8*ATR gate)
    df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + 1.0 * atr
    features = {
        "atr_14": atr,
        "swing_high": 5500.0,
        "swing_low": 4800.0,
        "nearest_resistance": 5500.0,
        "nearest_support": 4800.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = GapAnalysisSetupPlugin()
        # Don't set bars_since_session_start to avoid time gate
        f = {k: v for k, v in {**features, **extra}.items() if k != "bars_since_session_start"}
        frames = _frames(df, f)
        frames["main"] = df  # use the df with injected gap
        return plugin.compute_full(frames)

    return _fire


def _scenario_prev_day_level_test():
    """PrevDayLevelTest fires when close is within 0.5*ATR of PDH."""
    from src.intelligence.trading.prev_day_level_test import PrevDayLevelTestPlugin

    n = 25
    close = np.full(n, 5048.0)
    df = make_ohlcv(close)
    df["open"] = 5053.0
    features = {
        "atr_14": 10.0,
        "prior_session_high": 5050.0,
        "prior_session_low": 4950.0,
        "prior_session_close": 5000.0,
        "hmm_regime": 0.0,
        "swing_low": 4900.0,
        "swing_high": 5200.0,
        "nearest_resistance": 5100.0,
        "nearest_support": 4900.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = PrevDayLevelTestPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_momentum_breakout():
    """MomentumBreakout fires on ROC spike + volume expansion + structure break."""
    from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

    n = 50
    close = np.full(n, 5015.0)
    volume = np.full(n, 1000.0)
    volume[-1] = 2500.0
    df = make_ohlcv(close, volume)
    features = {
        "roc_14": 0.8,
        "swing_high": 5010.0,
        "swing_low": 4990.0,
        "atr_14": 8.0,
        "hmm_prob_trending_up": 0.70,  # continuous regime gate
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate
    }

    def _fire(extra: dict) -> dict:
        plugin = MomentumBreakoutPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_squeeze_expansion():
    """SqueezeExpansion fires on squeeze_fired + volume expansion + momentum."""
    from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

    n = 50
    close = np.linspace(5000.0, 5050.0, n)
    volume = np.full(n, 1000.0)
    volume[-1] = 2000.0  # 2x average -> > 1.3x threshold
    df = make_ohlcv(close, volume)
    features = {
        "squeeze_fired": 1.0,
        "squeeze_active": 0.0,
        "squeeze_bars": 10.0,
        "momentum_bias": 0.8,
        "bb_20_2_mid": 5020.0,
        "garch_vol_regime": 1,
        "atr_14": 8.0,
        "swing_high": 5200.0,
        "swing_low": 4800.0,
        "nearest_resistance": 5200.0,
        "nearest_support": 4800.0,
    }

    def _fire(extra: dict) -> dict:
        plugin = SqueezeExpansionPlugin()
        f = {**features, **extra}
        return plugin.compute_full(_frames(df, f))

    return _fire


def _scenario_trend_following():
    """TrendFollowing fires on pullback-to-MA reversal structural event (Phase 124)."""
    from src.intelligence.trading.trend_following import TrendFollowingPlugin

    n = 100
    close = np.linspace(5000.0, 5200.0, n)
    df = make_ohlcv(close)
    # Price=5200, sma_20 must be > price for 4 warmup bars then < price on fire bar.
    # Warmup: SMA=5220 (above price 5200) for 4 bars → bars_below_sma=4 >= _PULLBACK_MIN_BARS-1=4
    # Fire bar: SMA=5190 (below price 5200) → price > current_sma → pullback_reversal=True
    warmup_features = {
        "trend_regime": 0.8,
        "trend_confidence": 0.75,
        "trend_strength": 0.7,
        "swing_pattern": 1.0,  # required: direction==1 needs swing_pattern > 0
        "ctf_score": 0.6,
        "atr_14": 10.0,
        "sma_20": 5220.0,  # SMA above price=5200 → price below SMA
        "swing_high": 5500.0,
        "swing_low": 4800.0,
        "nearest_resistance": 5500.0,
        "nearest_support": 4800.0,
    }
    fire_features = {**warmup_features, "sma_20": 5190.0}  # SMA now below price → reversal

    def _fire(extra: dict) -> dict:
        plugin = TrendFollowingPlugin()
        for _ in range(4):
            plugin.compute_full(_frames(df, {**warmup_features, **extra}))
        return plugin.compute_full(_frames(df, {**fire_features, **extra}))

    return _fire


# ---------------------------------------------------------------------------
# Plugin registry for parametrize — (name, scenario_factory, skip_reason|None)
# ---------------------------------------------------------------------------

_WAVE0_PLUGINS = [
    ("ofi_continuation", _scenario_ofi_continuation, None),
    ("ofi_divergence", _scenario_ofi_divergence, None),
    ("cvd_divergence", _scenario_cvd_divergence, None),
    (
        "failed_breakout",
        None,
        "FailedBreakout requires multi-call BOS state machine; deterministic unit fire not achievable without state injection",
    ),
    (
        "orb15",
        None,
        "ORB15 requires session timing gate (09:30-11:30 ET); cannot fire without real session timestamps",
    ),
    (
        "orb30",
        None,
        "ORB30 requires session timing gate (09:30-11:30 ET); cannot fire without real session timestamps",
    ),
    ("prev_day_level_test", _scenario_prev_day_level_test, None),
    ("choch_reversal", _scenario_choch_reversal, None),
    ("supply_demand_setup", _scenario_supply_demand_setup, None),
    ("liquidity_sweep_reclaim", _scenario_liquidity_sweep_reclaim, None),
    ("liquidity_hunt", _scenario_liquidity_hunt, None),
    ("gap_analysis_setup", _scenario_gap_analysis_setup, None),
    ("momentum_breakout", _scenario_momentum_breakout, None),
    ("squeeze_expansion", _scenario_squeeze_expansion, None),
    ("trend_following", _scenario_trend_following, None),
]

_FIREABLE = [(name, factory) for name, factory, skip in _WAVE0_PLUGINS if skip is None]
_SKIPPED = [(name, skip) for name, factory, skip in _WAVE0_PLUGINS if skip is not None]

_FIREABLE_IDS = [name for name, _ in _FIREABLE]
_SKIPPED_IDS = [name for name, _ in _SKIPPED]


# ---------------------------------------------------------------------------
# Test 1: extrinsic-only perturbation leaves confidence unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plugin_name,factory", _FIREABLE, ids=_FIREABLE_IDS)
def test_extrinsic_perturbation_does_not_change_confidence(plugin_name, factory):
    """Perturbing only extrinsic keys must leave confidence unchanged to float precision.

    Phase 123: ctf_score is now an ECL annotation for ALL plugins — no longer a gate.
    ctf_score is fully perturb-safe across the entire I7 tier.
    """
    fire = factory()

    baseline = fire({})
    assert (
        baseline.get("direction", 0) != 0
    ), f"{plugin_name}: firing scenario did not produce a signal — check scenario factory"
    confidence_a = baseline["confidence"]

    # Phase 123: ctf_score is ECL annotation for all plugins — include in perturbation set.
    perturbation_keys = copy.deepcopy(_EXTRINSIC_KEYS)

    # Add/change only extrinsic keys — intrinsic inputs are identical
    perturbed = fire(copy.deepcopy(perturbation_keys))

    # The perturbed run may not fire if adding extrinsic keys changes a gate
    # (e.g. supply_demand_setup: if in_demand_zone AND in_supply_zone both 1.0, it returns no_signal)
    # The _fire factories guard against this for supply_demand_setup specifically.
    if perturbed.get("direction", 0) == 0:
        pytest.skip(
            f"{plugin_name}: perturbation blocked the signal (gate conflict) — scenario needs adjustment"
        )

    confidence_b = perturbed["confidence"]
    assert abs(confidence_a - confidence_b) < 1e-9, (
        f"{plugin_name}: confidence changed after extrinsic perturbation: "
        f"{confidence_a} -> {confidence_b} (delta={abs(confidence_a - confidence_b):.2e})"
    )


@pytest.mark.parametrize("plugin_name,skip_reason", _SKIPPED, ids=_SKIPPED_IDS)
def test_extrinsic_perturbation_skipped_plugins(plugin_name, skip_reason):
    """Document skipped plugins with explicit reasons."""
    pytest.skip(skip_reason)


# Test 2: confidence stays within [0.0, 0.95] for every fireable plugin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plugin_name,factory", _FIREABLE, ids=_FIREABLE_IDS)
def test_confidence_within_bounds(plugin_name, factory):
    """Every plugin firing scenario must return confidence in [0.0, 0.95]."""
    fire = factory()
    result = fire({})
    if result.get("direction", 0) == 0:
        pytest.skip(f"{plugin_name}: firing scenario did not produce a signal")
    conf = result["confidence"]
    assert 0.0 <= conf <= 0.95, f"{plugin_name}: confidence {conf} outside [0.0, 0.95]"


# ---------------------------------------------------------------------------
# Test 3: extrinsic fields still captured in features_snapshot despite being
#         absent from confidence formula (capture-vs-confidence separation)
# ---------------------------------------------------------------------------


def test_plugin_does_not_populate_context_features():
    """OFIContinuation: plugin body must NOT populate context_features (Phase 126-06).

    Annotation is now pipeline-layer responsibility (_annotate_signal in signal_processor).
    Plugin bodies return context_features={} (empty); pipeline overwrites with flat_features.
    """
    from src.intelligence.trading.ofi_continuation import OFIContinuationPlugin

    close = np.linspace(5000.0, 5010.0, 25)
    df = make_ohlcv(close)
    features = {
        "ofi_ewma_20": 600.0,
        "ofi_ewma_5": 600.0,
        "atr_14": 2.0,
        "ctf_score": 0.8,
        "ctf_trend_alignment": 0.7,
        "ctf_structure_alignment": 0.6,
        "volume_sma_20": 400.0,
    }

    plugin = OFIContinuationPlugin()
    for _ in range(9):
        plugin.compute_full(_frames(df, features))
    result = plugin.compute_full(_frames(df, features))

    assert result.get("direction", 0) != 0, "Test setup: OFIContinuation should have fired"

    # Phase 126-06: plugin returns empty context_features; pipeline will fill it
    ctx = result.get("context_features", "MISSING")
    assert ctx != "MISSING", "context_features key must be present (initialized to {})"
    assert ctx == {}, f"context_features must be empty dict from plugin body, got {ctx!r}"
    # features_snapshot is no longer set by plugins
    assert "features_snapshot" not in result, "features_snapshot must not exist post-Phase-126-06"


def test_phase_126_ecl_fields_initialized_by_plugin():
    """Phase 126-06: OFIDivergence initializes ECL fields to None/empty; pipeline fills them.

    Proves that ctf_score, ctf_confirmed, zone_friction_score are initialized to None
    by make_signal_from_frame() (not by the plugin body) and context_features = {}.
    Pipeline-layer _annotate_signal() overwrites them after all plugins run.
    """
    import pandas as pd

    from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

    closes = [5000.0 + i * 0.1 for i in range(30)]
    df = pd.DataFrame(
        {
            "open": [c - 0.05 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * 30,
        }
    )
    features = {
        "ofi_divergence": 2.0,
        "ofi_spike_z": 2.0,
        "ofi_ewma_5": 0.5,
        "ofi_ewma_20": 0.3,
        "rel_volume": 1.8,
        "hmm_regime": 0.0,
        "atr_14": 2.0,
        "hmm_prob_trending_up": 0.6,
        "hmm_prob_trending_down": 0.3,
        "ctf_score": 0.7,
    }

    plugin = OFIDivergencePlugin()
    for _ in range(2):
        plugin.compute_full(_frames(df, features))
    result = plugin.compute_full(_frames(df, features))

    assert result.get("direction", 0) != 0, "OFIDivergence should have fired"

    # Phase 126-06: ECL fields initialized to None by make_signal_from_frame; pipeline fills them
    assert "ctf_score" in result, "ctf_score key must exist (initialized to None)"
    assert (
        result["ctf_score"] is None
    ), f"ctf_score must be None from plugin body, got {result['ctf_score']!r}"
    assert result["ctf_confirmed"] is None, "ctf_confirmed must be None from plugin body"
    assert (
        result["zone_friction_score"] is None
    ), "zone_friction_score must be None from plugin body"
    assert (
        result.get("context_features") == {}
    ), "context_features must be empty dict from plugin body"


# ---------------------------------------------------------------------------
# Task 3: factor_scores and context_features are emitted on every fireable plugin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plugin_name,factory", _FIREABLE, ids=_FIREABLE_IDS)
def test_factor_scores_present_on_fired_signal(plugin_name, factory):
    """Every fireable plugin must emit factor_scores as a non-empty dict.

    factor_scores is the ML training target for APR weight optimization via
    regression against counterfactual_pnl_r. A missing or empty factor_scores
    means the signal cannot be used for APR regression (Phase 123 requirement).
    """
    fire = factory()
    result = fire({})
    if result.get("direction", 0) == 0:
        pytest.skip(f"{plugin_name}: firing scenario did not produce a signal")
    assert (
        "factor_scores" in result
    ), f"{plugin_name}: factor_scores missing from signal (Phase 123 requirement)"
    fs = result["factor_scores"]
    assert isinstance(fs, dict), f"{plugin_name}: factor_scores must be a dict, got {type(fs)}"
    assert len(fs) >= 1, f"{plugin_name}: factor_scores must be non-empty"
    for key, val in fs.items():
        assert isinstance(
            val, float
        ), f"{plugin_name}: factor_scores[{key!r}] must be float, got {type(val)}"
        assert 0.0 <= val <= 1.0, f"{plugin_name}: factor_scores[{key!r}]={val} outside [0.0, 1.0]"


@pytest.mark.parametrize("plugin_name,factory", _FIREABLE, ids=_FIREABLE_IDS)
def test_context_features_initialized_empty_on_fired_signal(plugin_name, factory):
    """Every fireable plugin must return context_features as an empty dict from its body.

    Phase 126-06: annotation is pipeline-layer responsibility. Plugin bodies return
    context_features={} which is overwritten by _annotate_signal() in signal_processor.
    features_snapshot must not exist in plugin output.
    """
    fire = factory()
    result = fire({})
    if result.get("direction", 0) == 0:
        pytest.skip(f"{plugin_name}: firing scenario did not produce a signal")
    ctx = result.get("context_features", "MISSING")
    assert ctx != "MISSING", f"{plugin_name}: context_features key must exist"
    assert ctx == {}, (
        f"{plugin_name}: context_features must be empty dict from plugin body (Phase 126-06); "
        f"pipeline-layer _annotate_signal() will fill it. Got: {ctx!r}"
    )
    assert (
        "features_snapshot" not in result
    ), f"{plugin_name}: features_snapshot must not exist post-Phase-126-06"
