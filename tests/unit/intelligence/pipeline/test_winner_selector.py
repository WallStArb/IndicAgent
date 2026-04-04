"""Unit tests for select_winner pure function."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.intelligence.enums.signal_status import SignalStatus
from src.intelligence.pipeline.winner_selector import _CONFIDENCE_BOOST_PER_AGREE, select_winner


def make_signal(
    confidence=0.8,
    plugin="trad_TrendFollowing",
    direction=1,
    regime_type="trend",
    regime_eligible=True,
    adjusted_rank=3,
):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": direction,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
        "regime_eligible": regime_eligible,
        "adjusted_rank": adjusted_rank,
    }


def test_returns_none_on_empty_list():
    """Empty signal list → (None, [], 'no_signal')."""
    winner, all_ranked, method = select_winner([])
    assert winner is None
    assert all_ranked == []
    assert method == "no_signal"


def test_no_active_returns_none():
    """All regime_eligible=False → (None, signals, 'no_signal')."""
    signals = [
        make_signal(regime_eligible=False),
        make_signal(regime_eligible=False),
    ]
    winner, all_ranked, method = select_winner(signals)
    assert winner is None
    assert len(all_ranked) == 2
    assert method == "no_signal"


def test_cis_override_selects_matching():
    """CIS direction 1 → winner selected from direction=1 signals."""
    cis_result = MagicMock(direction=1)
    signals = [
        make_signal(direction=1, plugin="trad_TrendFollowing", adjusted_rank=3),
        make_signal(direction=-1, plugin="trad_MeanReversion", adjusted_rank=1),
    ]
    winner, all_ranked, method = select_winner(signals, cis_result)
    assert winner is not None
    assert winner["direction"] == 1
    assert method == "cis_override"
    assert winner["status"] == SignalStatus.PENDING.value


def test_fallback_majority_direction():
    """No CIS result → majority direction wins, sorted by adjusted_rank."""
    signals = [
        make_signal(direction=1, plugin="trad_TrendFollowing", adjusted_rank=3),
        make_signal(direction=1, plugin="trad_MTFAlignment", adjusted_rank=4),
        make_signal(direction=-1, plugin="trad_MeanReversion", adjusted_rank=1),
    ]
    winner, all_ranked, method = select_winner(signals, None)
    assert winner is not None
    assert winner["direction"] == 1
    assert method == "priority_majority"
    assert winner["status"] == SignalStatus.PENDING.value


def test_confidence_boost_per_agree():
    """3 matching signals → boost = 0.05 * 2 extra agreeing applied to lowest-rank winner."""
    cis_result = MagicMock(direction=1)
    # adjusted_rank=2 is lowest → this signal is selected as winner
    base_conf = 0.5
    signals = [
        make_signal(confidence=0.7, direction=1, plugin="trad_TrendFollowing", adjusted_rank=3),
        make_signal(confidence=0.6, direction=1, plugin="trad_MTFAlignment", adjusted_rank=4),
        make_signal(confidence=base_conf, direction=1, plugin="trad_SqueezeExpansion", adjusted_rank=2),
    ]
    winner, _, method = select_winner(signals, cis_result)
    # 3 matching → 2 extra agreeing → boost = 0.05 * 2 = 0.10
    expected_conf = round(base_conf + _CONFIDENCE_BOOST_PER_AGREE * 2, 4)
    assert method == "cis_override"
    assert winner["confidence"] == expected_conf


def test_cis_direction_no_match_falls_back():
    """CIS direction with no matching signals → fallback to majority."""
    cis_result = MagicMock(direction=-1)  # No -1 signals
    signals = [
        make_signal(direction=1, plugin="trad_TrendFollowing", adjusted_rank=3),
        make_signal(direction=1, plugin="trad_MTFAlignment", adjusted_rank=4),
    ]
    winner, _, method = select_winner(signals, cis_result)
    assert winner is not None
    assert method == "priority_majority"


def test_no_cis_result_falls_back():
    """cis_result=None → falls back gracefully to priority_majority."""
    signals = [make_signal(direction=1, plugin="trad_TrendFollowing", adjusted_rank=3)]
    winner, _, method = select_winner(signals, None)
    assert winner is not None
    assert method == "priority_majority"
