"""Rules-based signal aggregator with CIS-augmented conflict resolution.

Takes raw signal dicts from trading setup plugins and selects a winner.
When features are provided, uses CISScorer to override the direction decision.
Falls back to priority-based rules, majority voting, and regime tiebreaking
when CIS is neutral (abs(score) <= 0.35 or buckets_agreeing < 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .cis_scorer import CISScorer

# Regime type map: maps regime_type attribute value → allowed hmm_regime int values.
# Plugins declare their regime_type attribute; this dict maps it to allowed regimes.
# 0 = ranging, 1 = trend-up, 2 = trend-down.
_REGIME_MAP: dict[str, list[int]] = {
    "trend": [1, 2],
    "mean_reversion": [0],
    "any": [0, 1, 2],
}

# Plugin priority: higher value = higher priority
SETUP_PRIORITY: dict[str, int] = {
    "trad_MeanReversion": 1,
    "trad_SqueezeExpansion": 2,
    "trad_TrendFollowing": 3,
    "trad_MTFAlignment": 4,
    "trad_LiquiditySweepReclaim": 5,
}

_CONFIDENCE_BOOST_PER_AGREE = 0.05
_REGIME_TIEBREAK_THRESHOLD = 0.4

# Trend setup names (I7 plugins that require a trending market for edge).
# Mean-reversion setups: all TIER_I7 names NOT in this set.
# Used by _build_all_ranked() to route hurst_trend_quality vs hurst_mr_quality.
TREND_SETUPS: frozenset[str] = frozenset(
    {
        "trad_TrendFollowing",
        "trad_MTFAlignment",
        "trad_MomentumBreakout",
        "trad_SqueezeExpansion",
        "trad_LiquidityHunt",
        "trad_ORB15",                 # new — trend continuation setup
        "trad_ORB30",                 # new — trend continuation setup
        "trad_SecondLegContinuation", # new — trend continuation
        "trad_VCP",                   # new — momentum/trend compression
        "trad_LVNBreakout",           # new — trend expansion through thin volume
        "trad_OFIContinuation",       # new — sustained directional OFI in trend
    }
)


@dataclass
class AggregatedResult:
    """Result of signal aggregation."""

    selected_signal: dict | None
    all_ranked: list[dict] = field(default_factory=list)
    resolution_method: str = "no_signal"
    num_signals_fired: int = 0
    num_agreeing: int = 0
    num_conflicting: int = 0
    # CIS fields — populated when features= kwarg is provided
    cis_score: float | None = None
    bucket_scores: dict | None = None
    weights_version: int | None = None


def _pick_with_method(group: list[dict]) -> dict:
    """Return the first element of a priority-sorted group."""
    return group[0]


def _regime_gate_signals(
    signals: list[dict],
    regime_data: dict[str, Any] | None,
    *,
    prob_min: float = 0.30,
    dur_min: int = 1,
) -> None:
    """Tag each signal dict with regime_eligible and suppression_reason in-place.

    If regime_data is None (absent or authority TF not yet seen), skips the gate
    and marks all signals as eligible. This avoids suppressing on absent data.

    Gate priority order:
    1. prob check: if hmm_regime_prob < prob_min → suppression_reason="regime_prob"
    2. duration check: hmm_regime_duration < dur_min → suppression_reason="regime_duration"
    3. type check: if int(hmm_regime) not in allowed → suppression_reason="regime_type"
    4. else: eligible=True

    Defaults (0.30/1) are safety floors per SHADOW-01/D-02 — not quality filters.
    """
    if regime_data is None:
        for sig in signals:
            sig["regime_eligible"] = True
            sig["suppression_reason"] = None
        return

    hmm_regime = regime_data.get("hmm_regime")
    hmm_regime_prob = float(regime_data.get("hmm_regime_prob", 0.0))
    hmm_regime_duration = int(regime_data.get("hmm_regime_duration", 0))

    for sig in signals:
        plugin_regime_type = sig.get("regime_type", "any")
        allowed = _REGIME_MAP.get(plugin_regime_type, [0, 1, 2])

        # Priority: prob check first, then duration, then type
        if hmm_regime_prob < prob_min:
            sig["regime_eligible"] = False
            sig["suppression_reason"] = "regime_prob"
        elif hmm_regime_duration < dur_min:
            sig["regime_eligible"] = False
            sig["suppression_reason"] = "regime_duration"
        elif hmm_regime is not None and int(hmm_regime) not in allowed:
            sig["regime_eligible"] = False
            sig["suppression_reason"] = "regime_type"
        else:
            sig["regime_eligible"] = True
            sig["suppression_reason"] = None


def aggregate(
    signals: list[dict],
    *,
    trend_regime: float = 0.0,
    features: dict[str, Any] | None = None,
    regime_data: dict[str, Any] | None = None,
    perf_weights: dict[str, float] | None = None,
    drift_penalty: float = 1.0,
    calibration_curves: dict[tuple[str, str], tuple[list[float], list[float]]] | None = None,
    timeframe: str = "",
) -> AggregatedResult:
    """Aggregate signals from trading setup plugins into a single result.

    When *features* is provided, runs CISScorer to compute a 6-bucket weighted
    directional score. If CIS fires (abs(score) > 0.35 and buckets_agreeing >= 3),
    it overrides the winner-pick direction. Falls back to priority/majority/regime
    tiebreak when CIS is neutral or features is None.

    Parameters
    ----------
    signals:
        List of signal.v1 dicts from setup plugins.
    trend_regime:
        Current trend regime score (positive=bullish, negative=bearish).
    features:
        Optional flat feature dict for CIS bucket scoring. When provided,
        CIS result is always attached to AggregatedResult (even if fallback).
    regime_data:
        Optional higher-TF HMM regime cache entry for slow-clock gating.
        Dict with keys: hmm_regime, hmm_regime_prob, hmm_regime_duration.
        When None, the regime gate is skipped (no suppression on absent data).

    Returns
    -------
    AggregatedResult with selected signal and metadata.
    All fired signals (eligible + suppressed) appear in all_ranked.
    Suppressed signals have regime_eligible=False and suppression_reason set.
    """
    # Tag each signal with regime eligibility (in-place mutation).
    # Uses regime_data (higher-TF, slow-clock) not features (same-TF, noisy).
    _regime_gate_signals(signals, regime_data)

    # Build plugin_outputs for CIS scorer from all signals (regardless of active/inactive)
    plugin_outputs: dict[str, dict] = {s["setup_plugin"]: s for s in signals if "setup_plugin" in s}

    # Run CIS if features provided (CIS still uses same-TF features, unchanged)
    cis_result = None
    if features is not None:
        scorer = CISScorer()
        cis_result = scorer.score(features, plugin_outputs)

    # Build all_ranked from ALL fired signals (eligible + suppressed as shadow entries).
    # active is derived from all_ranked so signals carry adjusted_rank for winner selection.
    all_fired = [s for s in signals if s.get("direction") != 0 and s.get("signal_type") != "none"]
    all_ranked = _build_all_ranked(
        all_fired,
        perf_weights=perf_weights,
        features=features,
        drift_penalty=drift_penalty,
        calibration_curves=calibration_curves,
        timeframe=timeframe,
    )
    # CRITICAL INVARIANT: active must ALWAYS be derived from all_ranked, never from raw signals.
    # _build_all_ranked() copies signal dicts and sets adjusted_rank — raw signals never have
    # adjusted_rank set. Deriving active from raw signals silently makes perf_weights have zero
    # effect on winner selection. See: CLAUDE.md "Aggregator active must come from all_ranked"
    active = [s for s in all_ranked if s.get("regime_eligible", True)]

    # Attach CIS metadata to result (even if no signal)
    cis_kwargs: dict[str, Any] = {}
    if cis_result is not None:
        cis_kwargs = {
            "cis_score": cis_result.cis_score,
            "bucket_scores": cis_result.bucket_scores,
            "weights_version": cis_result.weights_version,
        }

    if not active:
        return AggregatedResult(
            selected_signal=None,
            all_ranked=all_ranked,
            resolution_method="no_signal",
            num_signals_fired=0,
            num_agreeing=0,
            num_conflicting=0,
            **cis_kwargs,
        )

    # CIS override path: fires when threshold met and agreeing buckets >= 3.
    # Falls through when CIS fires but no regime-eligible plugin matches its direction
    # (CIS never synthesizes a signal — returns None in that case).
    if cis_result is not None and cis_result.direction != 0:
        result = _aggregate_via_cis(active, cis_result, all_ranked, cis_kwargs)
        if result is not None:
            return result

    # Fallback path: priority / majority / regime tiebreak
    return _aggregate_fallback(active, trend_regime, all_ranked, cis_kwargs)


def _sort_by_priority(group: list[dict]) -> list[dict]:
    # Sort ascending by adjusted_rank (always set by _build_all_ranked before this is called).
    # Stable sort preserves the tiebreak order established in _build_all_ranked.
    return sorted(group, key=lambda s: s["adjusted_rank"])


def _aggregate_via_cis(
    active: list[dict],
    cis_result: Any,
    all_ranked: list[dict],
    cis_kwargs: dict,
) -> AggregatedResult | None:
    """Select winner using CIS direction (Phase B CIS override path).

    Returns None when CIS fires but no regime-eligible plugins match its direction.
    The caller falls through to _aggregate_fallback in that case — CIS never
    manufactures a signal by flipping a plugin's direction.
    """
    cis_direction = cis_result.direction  # +1 or -1

    # Gather signals matching CIS direction, sorted by priority
    matching = [s for s in active if s.get("direction", 0) == cis_direction]
    opposing = [s for s in active if s.get("direction", 0) != cis_direction]

    if not matching:
        # CIS fired but no plugin agrees — do not synthesize; caller falls back.
        return None

    matching = _sort_by_priority(matching)
    selected = _pick_with_method(matching)

    # Confidence boost from agreeing plugins
    extra_agreeing = len(matching) - 1
    boosted_confidence = min(
        1.0,
        selected.get("confidence", 0.0) + _CONFIDENCE_BOOST_PER_AGREE * extra_agreeing,
    )
    selected = {**selected, "confidence": round(boosted_confidence, 4)}

    # Merge supporting_factors
    seen: set[str] = set()
    merged_factors: list[str] = []
    for sig in matching:
        for factor in sig.get("supporting_factors", []):
            if factor not in seen:
                seen.add(factor)
                merged_factors.append(factor)
    selected = {**selected, "supporting_factors": merged_factors}

    # Attach CIS fields to selected signal
    selected = {
        **selected,
        "cis_score": cis_result.cis_score,
        "bucket_scores": cis_result.bucket_scores,
        "weights_version": cis_result.weights_version,
    }

    return AggregatedResult(
        selected_signal=selected,
        all_ranked=all_ranked,
        resolution_method="cis_override",
        num_signals_fired=len(active),
        num_agreeing=len(matching),
        num_conflicting=len(opposing),
        **cis_kwargs,
    )


def _aggregate_fallback(
    active: list[dict],
    trend_regime: float,
    all_ranked: list[dict],
    cis_kwargs: dict,
) -> AggregatedResult:
    """Fallback winner-pick: priority / majority / regime tiebreak."""
    longs = [s for s in active if s.get("direction", 0) > 0]
    shorts = [s for s in active if s.get("direction", 0) < 0]

    longs = _sort_by_priority(longs)
    shorts = _sort_by_priority(shorts)

    winner_group: list[dict]
    loser_group: list[dict]
    method: str

    if longs and not shorts:
        winner_group = longs
        loser_group = []
        method = "sole" if len(longs) == 1 else "priority"
    elif shorts and not longs:
        winner_group = shorts
        loser_group = []
        method = "sole" if len(shorts) == 1 else "priority"
    else:
        if len(longs) > len(shorts):
            winner_group = longs
            loser_group = shorts
            method = "majority"
        elif len(shorts) > len(longs):
            winner_group = shorts
            loser_group = longs
            method = "majority"
        else:
            if trend_regime > _REGIME_TIEBREAK_THRESHOLD:
                winner_group = longs
                loser_group = shorts
                method = "regime_tiebreak"
            elif trend_regime < -_REGIME_TIEBREAK_THRESHOLD:
                winner_group = shorts
                loser_group = longs
                method = "regime_tiebreak"
            else:
                return AggregatedResult(
                    selected_signal=None,
                    all_ranked=all_ranked,
                    resolution_method="no_signal",
                    num_signals_fired=len(active),
                    num_agreeing=0,
                    num_conflicting=len(active),
                    **cis_kwargs,
                )

    selected = _pick_with_method(winner_group)

    extra_agreeing = len(winner_group) - 1
    boosted_confidence = min(
        1.0,
        selected.get("confidence", 0.0) + _CONFIDENCE_BOOST_PER_AGREE * extra_agreeing,
    )
    selected = {**selected, "confidence": round(boosted_confidence, 4)}

    seen: set[str] = set()
    merged_factors: list[str] = []
    for sig in winner_group:
        for factor in sig.get("supporting_factors", []):
            if factor not in seen:
                seen.add(factor)
                merged_factors.append(factor)
    selected = {**selected, "supporting_factors": merged_factors}

    # Attach CIS fields to selected signal if available
    if cis_kwargs:
        selected = {
            **selected,
            "cis_score": cis_kwargs.get("cis_score"),
            "bucket_scores": cis_kwargs.get("bucket_scores"),
            "weights_version": cis_kwargs.get("weights_version"),
        }

    return AggregatedResult(
        selected_signal=selected,
        all_ranked=all_ranked,
        resolution_method=method,
        num_signals_fired=len(active),
        num_agreeing=len(winner_group),
        num_conflicting=len(loser_group),
        **cis_kwargs,
    )


def _build_all_ranked(
    fired: list[dict],
    perf_weights: dict[str, float] | None = None,
    features: dict[str, Any] | None = None,
    drift_penalty: float = 1.0,
    calibration_curves: dict[tuple[str, str], tuple[list[float], list[float]]] | None = None,
    timeframe: str = "",
) -> list[dict]:
    """Build ranked list of all fired signals (eligible + suppressed).

    When perf_weights is provided and non-empty:
      adjusted_rank = perf_multiplier (primary key, ascending: 0.5=best → 1.5=worst).
      Tiebreak within equal multipliers: SETUP_PRIORITY descending (higher priority wins).
      Setups absent from perf_weights get multiplier=1.0 (neutral).

    When perf_weights is None or empty:
      Falls back to SETUP_PRIORITY descending (original behavior).
      adjusted_rank is set to a negative SETUP_PRIORITY value so ascending sort
      still puts the highest-priority setup first.

    When features is provided:
      Each signal's confidence is multiplied by hurst_q * entropy_q BEFORE
      adjusted_rank assignment.  Trend setups use hurst_trend_quality; mean-
      reversion setups use hurst_mr_quality.  Both default to 1.0 when absent.

    When drift_penalty < 1.0 (QUAL-09 KS drift):
      Applied AFTER Hurst × Entropy multipliers and BEFORE adjusted_rank assignment.
      DRIFT_PENALTIES: none=1.0, warning=0.85, critical=0.70.
      When "none" (default 1.0), confidence is unchanged.

    composite_rank is always assigned 1-based by SETUP_PRIORITY desc for observability.
    """
    # 1. Sort by SETUP_PRIORITY descending to assign composite_rank (observability only)
    priority_sorted = sorted(
        fired,
        key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0),
        reverse=True,
    )
    # EFF-01: In-place mutation avoids creating 36+ new dict objects per bar
    for i, sig in enumerate(priority_sorted):
        sig["composite_rank"] = i + 1
    with_ranks = priority_sorted

    # 1b. Apply quality multiplier before adjusted_rank assignment.
    #     Uses min(hurst_q, entropy_q) instead of multiplication — both Hurst and entropy
    #     measure market structure/predictability (correlated, not orthogonal), so multiplying
    #     them compounds penalties catastrophically. min() takes the worse of the two signals
    #     without the 2x amplification of dependent measures.
    #     CRITICAL: applied BEFORE step 2 so confident signals still compete first,
    #     just with reduced absolute confidence (per RESEARCH.md Pitfall 2).
    if features:
        # Cache feature access before loop (EFF-02: eliminates 180+ lookups/bar)
        hurst_trend_q = float(features.get("hurst_trend_quality", 1.0))
        hurst_mr_q = float(features.get("hurst_mr_quality", 1.0))
        entropy_q = float(features.get("entropy_quality", 1.0))

        for sig in with_ranks:
            plugin_name = sig.get("setup_plugin", "")
            hurst_q = hurst_trend_q if plugin_name in TREND_SETUPS else hurst_mr_q
            quality = min(hurst_q, entropy_q)
            sig["confidence"] = round(float(sig.get("confidence", 0.0)) * quality, 4)

    # 1c. Apply KS drift penalty (QUAL-09) after Hurst × Entropy, before adjusted_rank.
    #     penalty=1.0 (severity="none") is a no-op. Applies uniformly to all signals
    #     on this symbol/TF when the feature distribution has shifted from baseline.
    if drift_penalty != 1.0:
        for sig in with_ranks:
            sig["confidence"] = round(float(sig.get("confidence", 0.0)) * drift_penalty, 4)

    # 1d. Apply calibrated_confidence as sort key when isotonic curve exists (CAL-03).
    #     calibrated_confidence is added as a NEW field — confidence is NOT mutated.
    #     Applied as FINAL step after all quality multipliers (Hurst, entropy, drift).
    #     Only the winning signal's calibrated_confidence is stored in signal_ledger;
    #     non-winner entries get NULL there. Here we set it for ranking purposes only.
    #
    #     OPTIMIZATION (Phase 48): Batch interpolate per plugin instead of per-signal.
    #     Reduces np.interp calls from 36 to ~6 per bar (group by plugin_name).
    if calibration_curves and timeframe:
        # Group signals by plugin for batch interpolation
        signals_by_plugin: dict[str, list[dict[str, Any]]] = {}
        for sig in with_ranks:
            plugin_name = sig.get("setup_plugin", "")
            if plugin_name not in signals_by_plugin:
                signals_by_plugin[plugin_name] = []
            signals_by_plugin[plugin_name].append(sig)

        # Apply calibration per plugin (one np.interp per plugin instead of per signal)
        for plugin_name, plugin_signals in signals_by_plugin.items():
            curve = calibration_curves.get((plugin_name, timeframe))
            if curve is not None:
                breakpoints, values = curve
                # Batch interpolate all signals for this plugin
                raw_confs = np.array([float(sig.get("confidence", 0.0)) for sig in plugin_signals])
                calibrated_confs = np.interp(raw_confs, breakpoints, values)
                # Assign back to signals
                for sig, cal_conf in zip(plugin_signals, calibrated_confs):
                    sig["calibrated_confidence"] = round(float(cal_conf), 4)
            else:
                # No calibration curve for this plugin
                for sig in plugin_signals:
                    sig["calibrated_confidence"] = None
    else:
        for sig in with_ranks:
            sig["calibrated_confidence"] = None

    # 2. Assign adjusted_rank
    weights = perf_weights or {}
    for sig in with_ranks:
        plugin_name = sig.get("setup_plugin", "")
        if weights:
            # perf_multiplier is the primary key (ascending: 0.5=best, 1.5=worst).
            multiplier = weights.get(plugin_name, 1.0)
            sig["adjusted_rank"] = round(multiplier, 4)
        else:
            # No perf data: sort by SETUP_PRIORITY descending.
            # Negate so ascending sort puts highest-priority first.
            sig["adjusted_rank"] = round(-SETUP_PRIORITY.get(plugin_name, 0), 4)

    # 3. Sort by calibrated_confidence (desc) when available, else by adjusted_rank (asc).
    #    Tiebreak: adjusted_rank ascending, then SETUP_PRIORITY descending.
    return sorted(
        with_ranks,
        key=lambda s: (
            # Primary: calibrated_confidence when available (invert: higher = better)
            -(s.get("calibrated_confidence") or 0.0)
            if s.get("calibrated_confidence") is not None
            else -(s.get("confidence", 0.0)),
            # Tiebreak: adjusted_rank ascending (lower = better), then priority desc
            s["adjusted_rank"],
            -SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0) if weights else 0,
        ),
    )
