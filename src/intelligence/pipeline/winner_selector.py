"""Winner Selector pipeline stage — pure function.

Selects winning signal using CIS override or priority/majority tiebreak.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.intelligence.enums.signal_status import SignalStatus
from src.intelligence.trading.cis_scorer import CISScorer

_CONFIDENCE_BOOST_PER_AGREE = 0.05


def select_winner(
    signals: list[dict],
    cis_scorer: CISScorer,
    features: dict | None = None,
) -> tuple[dict | None, list[dict], str]:
    """Select winning signal from all ranked signals for a bar.

    Parameters
    ----------
    signals:
        All ranked signals for this bar. Each must have "regime_eligible",
        "direction", "adjusted_rank", "setup_plugin", "confidence".
    cis_scorer:
        CISScorer instance. score() called with features and plugin_outputs.
    features:
        Feature dict for CIS scoring. Defaults to None (from signals[0] features).

    Returns
    -------
    tuple[dict | None, list[dict], str]
        (winner_signal_dict, all_ranked_signals, resolution_method)
        - winner_signal_dict: None when no signals or all suppressed
        - all_ranked_signals: input signals unchanged
        - resolution_method: "no_signal" | "cis_override" | "priority_majority"
    """
    if not signals:
        return None, [], "no_signal"

    # Separate active (eligible) from suppressed
    active = [s for s in signals if s.get("regime_eligible", True)]

    if not active:
        return None, signals, "no_signal"

    # Attempt CIS override
    if features is None:
        features = signals[0].get("features") or {}

    cis_result = None
    try:
        plugin_outputs = {s["setup_plugin"]: s for s in signals if "setup_plugin" in s}
        cis_result = cis_scorer.score(features, plugin_outputs)
    except Exception:
        cis_result = None

    if cis_result is not None and getattr(cis_result, "direction", 0) != 0:
        winner, method = _aggregate_via_cis(active, cis_result, signals)
        if winner is not None:
            return winner, signals, method

    winner, method = _aggregate_fallback(active, signals)
    return winner, signals, method


def _aggregate_via_cis(
    active: list[dict],
    cis_result: Any,
    all_ranked: list[dict],
) -> tuple[dict | None, str]:
    """Select winner matching CIS direction, boost by agreeing count."""
    cis_direction = cis_result.direction
    matching = [s for s in active if s.get("direction", 0) == cis_direction]

    if not matching:
        return None, "no_match"

    matching_sorted = sorted(matching, key=lambda s: s.get("adjusted_rank", 999))
    selected = dict(matching_sorted[0])

    extra_agreeing = len(matching) - 1
    boosted = min(
        1.0,
        float(selected.get("confidence", 0.0)) + _CONFIDENCE_BOOST_PER_AGREE * extra_agreeing,
    )
    selected["confidence"] = round(boosted, 4)
    selected["status"] = SignalStatus.PENDING.value

    return selected, "cis_override"


def _aggregate_fallback(
    active: list[dict],
    all_ranked: list[dict],
) -> tuple[dict | None, str]:
    """Select winner by majority direction, then adjusted_rank sort."""
    by_direction: dict[int, list[dict]] = defaultdict(list)
    for s in active:
        by_direction[s.get("direction", 0)].append(s)

    longs = len(by_direction.get(1, []))
    shorts = len(by_direction.get(-1, []))

    majority_group = by_direction[1] if longs >= shorts else by_direction[-1]
    if not majority_group:
        return None, "no_signal"

    sorted_group = sorted(majority_group, key=lambda s: s.get("adjusted_rank", 999))
    selected = dict(sorted_group[0])
    selected["status"] = SignalStatus.PENDING.value

    return selected, "priority_majority"
