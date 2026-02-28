"""Rules-based signal aggregator with CIS-augmented conflict resolution.

Takes raw signal dicts from trading setup plugins and selects a winner.
When features are provided, uses CISScorer to override the direction decision.
Falls back to priority-based rules, majority voting, and regime tiebreaking
when CIS is neutral (abs(score) <= 0.35 or buckets_agreeing < 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cis_scorer import CISScorer

# Regime eligibility: maps plugin name → allowed hmm_regime values.
# Plugins not listed here are allowed in any regime.
# Gate is skipped entirely when hmm_regime_prob < 0.55 or hmm_regime_duration < 3
# (uncertain or newly-started regime — don't suppress on weak evidence).
REGIME_ELIGIBILITY: dict[str, list[int]] = {
    "trad_TrendFollowing":    [1, 2],  # trending only
    "trad_MomentumBreakout":  [1, 2],
    "trad_LiquidityHunt":     [1, 2],
    "trad_MTFAlignment":      [1, 2],
    "trad_MeanReversion":     [0],     # ranging only
    "trad_VWAPDeviation":     [0],
}

_REGIME_PROB_MIN = 0.55   # minimum confidence to trust regime label
_REGIME_DUR_MIN = 3       # minimum bars before regime is considered stable

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


def aggregate(
    signals: list[dict],
    *,
    trend_regime: float = 0.0,
    features: dict[str, Any] | None = None,
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

    Returns
    -------
    AggregatedResult with selected signal and metadata.
    """
    # Apply regime eligibility filter before scoring.
    # Only filters when regime is confident (prob >= 0.55) and stable (duration >= 3).
    if features is not None:
        hmm_regime = features.get("hmm_regime")
        hmm_regime_prob = features.get("hmm_regime_prob", 0.0)
        hmm_regime_duration = features.get("hmm_regime_duration", 0)
        regime_gate_active = (
            hmm_regime is not None
            and float(hmm_regime_prob) >= _REGIME_PROB_MIN
            and int(hmm_regime_duration) >= _REGIME_DUR_MIN
        )
        if regime_gate_active:
            current_regime = int(hmm_regime)
            signals = [
                s for s in signals
                if s.get("setup_plugin") not in REGIME_ELIGIBILITY
                or current_regime in REGIME_ELIGIBILITY[s["setup_plugin"]]
            ]

    # Build plugin_outputs for CIS scorer from all signals (regardless of active/inactive)
    plugin_outputs: dict[str, dict] = {s["setup_plugin"]: s for s in signals if "setup_plugin" in s}

    # Run CIS if features provided
    cis_result = None
    if features is not None:
        scorer = CISScorer()
        cis_result = scorer.score(features, plugin_outputs)

    # Filter out inactive signals
    active = [
        s
        for s in signals
        if s.get("direction") != 0 and s.get("signal_type") != "none"
    ]

    all_ranked = _build_all_ranked(active)

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

    # CIS override path: fires when threshold met and agreeing buckets >= 3
    if cis_result is not None and cis_result.direction != 0:
        return _aggregate_via_cis(active, cis_result, all_ranked, cis_kwargs)

    # Fallback path: priority / majority / regime tiebreak
    return _aggregate_fallback(active, trend_regime, all_ranked, cis_kwargs)


def _aggregate_via_cis(
    active: list[dict],
    cis_result: Any,
    all_ranked: list[dict],
    cis_kwargs: dict,
) -> AggregatedResult:
    """Select winner using CIS direction (Phase B CIS override path)."""
    cis_direction = cis_result.direction  # +1 or -1

    # Gather signals matching CIS direction, sorted by priority
    matching = [s for s in active if s.get("direction", 0) == cis_direction]
    opposing = [s for s in active if s.get("direction", 0) != cis_direction]

    def _sort_by_priority(group: list[dict]) -> list[dict]:
        return sorted(
            group,
            key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0),
            reverse=True,
        )

    if matching:
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
    else:
        # CIS fires but no plugin matches direction — synthesize a minimal signal
        # using the highest-priority signal in any direction, overriding its direction
        all_sorted = _sort_by_priority(active)
        template = all_sorted[0]
        selected = {**template, "direction": cis_direction}
        matching = [selected]
        opposing = [s for s in active if s is not template]

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
        resolution_method="cis",
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

    def _sort_by_priority(group: list[dict]) -> list[dict]:
        return sorted(
            group,
            key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0),
            reverse=True,
        )

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


def _build_all_ranked(active: list[dict]) -> list[dict]:
    """Build ranked list of all active signals, sorted by priority descending."""
    ranked = sorted(
        active,
        key=lambda s: SETUP_PRIORITY.get(s.get("setup_plugin", ""), 0),
        reverse=True,
    )
    return [
        {**sig, "composite_rank": i + 1} for i, sig in enumerate(ranked)
    ]
