import pytest
from src.intelligence.plugins import PluginRegistry


def _make_registry_with(indicator_names=(), pattern_names=()):
    reg = PluginRegistry()
    for n in indicator_names:
        class FakePlugin:
            name = n
        reg.indicators[n] = FakePlugin()
    for n in pattern_names:
        class FakePlugin:
            name = n
        reg.patterns[n] = FakePlugin()
    return reg


def test_validate_tier_passes_when_all_names_registered():
    reg = _make_registry_with(indicator_names=["RSI", "ATR"], pattern_names=["smc_FVG"])
    reg.validate_tier(["RSI", "ATR"], "I1")
    reg.validate_tier(["smc_FVG"], "SMC")


def test_validate_tier_raises_on_unknown_indicator():
    reg = _make_registry_with(indicator_names=["RSI"])
    with pytest.raises(ValueError, match="I1.*typo_plugin"):
        reg.validate_tier(["RSI", "typo_plugin"], "I1")


def test_validate_tier_raises_on_unknown_pattern():
    reg = _make_registry_with(pattern_names=["smc_FVG"])
    with pytest.raises(ValueError, match="SMC.*missing_plugin"):
        reg.validate_tier(["smc_FVG", "missing_plugin"], "SMC")


def test_validate_tier_raises_on_empty_registry():
    reg = PluginRegistry()
    with pytest.raises(ValueError, match="I1.*RSI"):
        reg.validate_tier(["RSI"], "I1")


def test_validate_tier_empty_list_always_passes():
    reg = PluginRegistry()
    reg.validate_tier([], "I1")
