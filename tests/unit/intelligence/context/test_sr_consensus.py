import pandas as pd

from src.intelligence.context.sr_consensus import plugin


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
