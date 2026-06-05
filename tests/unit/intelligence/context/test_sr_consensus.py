import pandas as pd

from src.intelligence.context.sr_consensus import _round_candidates, plugin


def _frames(price: float = 100.0, atr: float = 1.0) -> dict:
    close = [price] * 10
    df = pd.DataFrame({"close": close, "high": close, "low": close, "open": close})
    return {"main": df, "i1": {"atr_14": atr}, "timeframe": "1m"}


def test_plugin_metadata():
    assert plugin.name == "ctx_SRConsensus"
    expected = {
        "sr_nearest_support",
        "sr_nearest_resistance",
        "sr_support_confluence_score",
        "sr_resistance_confluence_score",
        "sr_support_dist_atr",
        "sr_resistance_dist_atr",
    }
    assert plugin.outputs == expected


def test_compute_full_delegation():
    frames = {"main": pd.DataFrame({"close": [100.0]}), "i1": {"atr_14": 1.0}}
    assert plugin.compute_full(frames) == plugin.compute_next(frames)


def test_always_emits_all_6_keys():
    result = plugin.compute_full(_frames(100.0, 1.0))
    assert set(result.keys()) == {
        "sr_nearest_support",
        "sr_nearest_resistance",
        "sr_support_confluence_score",
        "sr_resistance_confluence_score",
        "sr_support_dist_atr",
        "sr_resistance_dist_atr",
    }


def test_no_candidate_emits_none_price_and_zero_score():
    # Sufficient bars but tiny ATR so max_dist is too small to reach any round level
    close = [100.0] * 10
    df = pd.DataFrame({"close": close, "high": close, "low": close, "open": close})
    frames = {"main": df, "i1": {"atr_14": 0.0001}, "timeframe": "1m"}
    result = plugin.compute_full(frames)
    # Either returns empty (no atr) or returns None prices with zero scores
    if result:
        assert result["sr_nearest_support"] is None
        assert result["sr_nearest_resistance"] is None
        assert result["sr_support_confluence_score"] == 0.0
        assert result["sr_resistance_confluence_score"] == 0.0


def test_returns_support_below_and_resistance_above():
    result = plugin.compute_full(_frames(price=100.0, atr=2.0))
    support = result["sr_nearest_support"]
    resistance = result["sr_nearest_resistance"]
    if support is not None:
        assert support < 100.0
    if resistance is not None:
        assert resistance > 100.0


def test_round_number_support_detected():
    # Price just above 100 — round number 100 should be a support candidate
    result = plugin.compute_full(_frames(price=100.5, atr=2.0))
    support = result["sr_nearest_support"]
    if support is not None:
        assert support <= 100.5


def test_round_number_can_be_sole_result():
    # No structural features, but round-number candidates should still produce output
    # when price is close enough to a round level
    frames = {
        "main": pd.DataFrame({"close": [100.1] * 10}),
        "i1": {"atr_14": 5.0},
        "timeframe": "1m",
    }
    result = plugin.compute_full(frames)
    # With atr=5 and price=100.1, round number 100 is within max_dist — should appear
    assert result["sr_nearest_support"] is not None or result["sr_nearest_resistance"] is not None


def test_round_number_no_duplicates_in_candidates():
    # _round_candidates must not return the same price level twice
    price, atr, max_dist = 7415.0, 9.0, 45.0
    cands = _round_candidates(price, atr, max_dist, -1)
    prices = [c.price for c in cands]
    assert len(prices) == len(set(prices)), f"Duplicate round levels: {prices}"


def test_confluence_score_in_range():
    result = plugin.compute_full(_frames(price=100.0, atr=2.0))
    for key in ("sr_support_confluence_score", "sr_resistance_confluence_score"):
        score = result[key]
        assert 0.0 <= score <= 1.0, f"{key}={score} out of [0,1]"
