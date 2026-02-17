"""Rules-based signal aggregator with conflict resolution.

Takes raw signal dicts from trading setup plugins and selects a winner
using priority-based rules, majority voting, and regime tiebreaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


def _pick_with_method(group: list[dict]) -> dict:
    """Return the first element of a priority-sorted group."""
    return group[0]


def aggregate(
    signals: list[dict], *, trend_regime: float = 0.0
) -> AggregatedResult:
    """Aggregate signals from trading setup plugins into a single result.

    Parameters
    ----------
    signals:
        List of signal.v1 dicts from setup plugins.
    trend_regime:
        Current trend regime score (positive=bullish, negative=bearish).

    Returns
    -------
    AggregatedResult with selected signal and metadata.
    """
    # Filter out inactive signals
    active = [
        s
        for s in signals
        if s.get("direction") != 0 and s.get("signal_type") != "none"
    ]

    if not active:
        return AggregatedResult(
            selected_signal=None,
            all_ranked=[],
            resolution_method="no_signal",
            num_signals_fired=0,
            num_agreeing=0,
            num_conflicting=0,
        )

    # Group by direction
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

    # Resolve which side wins
    winner_group: list[dict]
    loser_group: list[dict]
    method: str

    if longs and not shorts:
        # Case A: only longs
        winner_group = longs
        loser_group = []
        method = "sole" if len(longs) == 1 else "priority"
    elif shorts and not longs:
        # Case A: only shorts
        winner_group = shorts
        loser_group = []
        method = "sole" if len(shorts) == 1 else "priority"
    else:
        # Case B: mixed directions
        if len(longs) > len(shorts):
            winner_group = longs
            loser_group = shorts
            method = "majority"
        elif len(shorts) > len(longs):
            winner_group = shorts
            loser_group = longs
            method = "majority"
        else:
            # Tied — use regime tiebreak
            if trend_regime > _REGIME_TIEBREAK_THRESHOLD:
                winner_group = longs
                loser_group = shorts
                method = "regime_tiebreak"
            elif trend_regime < -_REGIME_TIEBREAK_THRESHOLD:
                winner_group = shorts
                loser_group = longs
                method = "regime_tiebreak"
            else:
                # No clear winner
                all_ranked = _build_all_ranked(active)
                return AggregatedResult(
                    selected_signal=None,
                    all_ranked=all_ranked,
                    resolution_method="no_signal",
                    num_signals_fired=len(active),
                    num_agreeing=0,
                    num_conflicting=len(active),
                )

    # Pick winner from winning group
    selected = _pick_with_method(winner_group)

    # Enrich: boost confidence
    extra_agreeing = len(winner_group) - 1
    boosted_confidence = min(
        1.0,
        selected.get("confidence", 0.0) + _CONFIDENCE_BOOST_PER_AGREE * extra_agreeing,
    )
    selected = {**selected, "confidence": round(boosted_confidence, 4)}

    # Merge supporting_factors from all same-direction signals (deduplicated, order-preserving)
    seen: set[str] = set()
    merged_factors: list[str] = []
    for sig in winner_group:
        for factor in sig.get("supporting_factors", []):
            if factor not in seen:
                seen.add(factor)
                merged_factors.append(factor)
    selected = {**selected, "supporting_factors": merged_factors}

    # Build all_ranked
    all_ranked = _build_all_ranked(active)

    return AggregatedResult(
        selected_signal=selected,
        all_ranked=all_ranked,
        resolution_method=method,
        num_signals_fired=len(active),
        num_agreeing=len(winner_group),
        num_conflicting=len(loser_group),
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
