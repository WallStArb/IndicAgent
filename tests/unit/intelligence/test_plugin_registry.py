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


def test_tier_constants_are_lists_of_strings():
    from src.intelligence.register_plugins import (
        TIER_I1,
        TIER_I3,
        TIER_I4,
        TIER_I5,
        TIER_I6,
        TIER_I7,
        TIER_SMC,
    )

    for tier_name, lst in [
        ("TIER_I1", TIER_I1),
        ("TIER_I3", TIER_I3),
        ("TIER_I4", TIER_I4),
        ("TIER_I5", TIER_I5),
        ("TIER_SMC", TIER_SMC),
        ("TIER_I6", TIER_I6),
        ("TIER_I7", TIER_I7),
    ]:
        assert isinstance(lst, list), f"{tier_name} must be a list"
        assert all(isinstance(n, str) for n in lst), f"{tier_name} must contain strings"
        assert len(lst) > 0, f"{tier_name} must not be empty"


def test_tier_constants_match_registry():
    """Every name in a TIER_* constant must be registered after register_all_plugins()."""
    import src.intelligence.plugins as plugins_module
    import src.intelligence.register_plugins as rp_module
    from src.intelligence.plugins import PluginRegistry
    from src.intelligence.register_plugins import (
        TIER_I1,
        TIER_I3,
        TIER_I4,
        TIER_I5,
        TIER_I6,
        TIER_I7,
        TIER_SMC,
        register_all_plugins,
    )

    reg = PluginRegistry()
    original_plugins = plugins_module.registry
    original_rp = rp_module.registry
    plugins_module.registry = reg
    rp_module.registry = reg
    try:
        register_all_plugins()
        for tier_name, tier_list in [
            ("TIER_I1", TIER_I1),
            ("TIER_I3", TIER_I3),
            ("TIER_I4", TIER_I4),
            ("TIER_I5", TIER_I5),
            ("TIER_SMC", TIER_SMC),
            ("TIER_I6", TIER_I6),
            ("TIER_I7", TIER_I7),
        ]:
            reg.validate_tier(tier_list, tier_name)
    finally:
        plugins_module.registry = original_plugins
        rp_module.registry = original_rp


def test_tier_i1_has_28_plugins():
    from src.intelligence.register_plugins import TIER_I1

    assert len(TIER_I1) == 28, f"Expected 28 I1 plugins, got {len(TIER_I1)}: {TIER_I1}"


def test_tier_smc_has_13_plugins():
    from src.intelligence.register_plugins import TIER_SMC

    assert len(TIER_SMC) == 16, f"Expected 16 SMC plugins, got {len(TIER_SMC)}: {TIER_SMC}"


def test_tier_i7_has_35_plugins():
    from src.intelligence.register_plugins import TIER_I7

    assert len(TIER_I7) == 35, f"Expected 35 I7 plugins, got {len(TIER_I7)}: {TIER_I7}"
