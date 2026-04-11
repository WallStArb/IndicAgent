"""Tests for group synthesis pure helpers."""


def test_asset_groups_covers_all_20_contracts():
    from services.ai_narrative_service import ASSET_GROUPS

    all_symbols = [sym for syms in ASSET_GROUPS.values() for sym in syms]
    expected = {
        "ESH6",
        "NQH6",
        "RTYH6",
        "YMH6",  # equity
        "CLJ6",
        "BZJ6",
        "NGJ6",  # energy
        "GCJ6",
        "SIH6",
        "HGH6",
        "PLJ6",  # metals
        "ZNH6",
        "ZFH6",
        "ZBH6",
        "ZTH6",  # rates
        "VXH6",  # volatility — in equity group
        "ZSH6",
        "ZCH6",
        "ZWH6",  # ag
    }
    # All contracts appear in exactly one group
    assert set(all_symbols) == expected
    assert len(all_symbols) == len(expected)  # no duplicates


def test_symbol_to_group_lookup():
    from services.ai_narrative_service import SYMBOL_TO_GROUP

    assert SYMBOL_TO_GROUP["ESH6"] == "equity"
    assert SYMBOL_TO_GROUP["CLJ6"] == "energy"
    assert SYMBOL_TO_GROUP["GCJ6"] == "metals"
    assert SYMBOL_TO_GROUP["ZNH6"] == "rates"
    assert SYMBOL_TO_GROUP["ZSH6"] == "ag"


def test_build_group_synthesis_prompt_contains_key_info():
    from services.ai_narrative_service import build_group_synthesis_prompt

    signals = {
        "ESH6:5m": {
            "symbol": "ESH6",
            "timeframe": "5m",
            "direction": 1,
            "direction_label": "Bullish",
            "confidence": 0.82,
            "setup_plugin": "trad_TrendFollowing",
            "regime_context": "trending_up",
        },
        "NQH6:5m": {
            "symbol": "NQH6",
            "timeframe": "5m",
            "direction": -1,
            "direction_label": "Bearish",
            "confidence": 0.74,
            "setup_plugin": "trad_MeanReversion",
            "regime_context": "ranging",
        },
    }
    prompt = build_group_synthesis_prompt("equity", signals)
    assert "equity" in prompt.lower()
    assert "ESH6" in prompt
    assert "NQH6" in prompt
    assert "Bullish" in prompt
    assert "Bearish" in prompt
    assert "/no_think" in prompt


def test_build_group_synthesis_prompt_empty_signals():
    """Empty signals dict still returns a valid (minimal) prompt."""
    from services.ai_narrative_service import build_group_synthesis_prompt

    prompt = build_group_synthesis_prompt("ag", {})
    assert "ag" in prompt.lower()
    assert "no signals" in prompt.lower() or len(prompt) > 10


def test_extract_group_fingerprint():
    from services.ai_narrative_service import extract_group_fingerprint

    signals = {
        "ESH6:5m": {"direction": 1, "regime_context": "trending_up"},
        "NQH6:15m": {"direction": -1, "regime_context": "ranging"},
        "RTYH6:1h": {"direction": 0, "regime_context": "low_vol"},  # zero → excluded
    }
    fp = extract_group_fingerprint(signals)
    assert fp == {
        "ESH6:5m": (1, "trending_up"),
        "NQH6:15m": (-1, "ranging"),
    }
    # direction=0 should not appear — no actionable state
    assert "RTYH6:1h" not in fp
