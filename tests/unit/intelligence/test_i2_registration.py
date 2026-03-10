"""Tests for TIER_I2 registration in register_plugins.py."""


def test_tier_i2_constant_exists():
    from src.intelligence.register_plugins import TIER_I2

    assert len(TIER_I2) == 11  # was 9; +ExhaustionScore +AccelerationRegime


def test_tier_i2_all_registered():
    from src.intelligence.plugins import registry
    from src.intelligence.register_plugins import TIER_I2, register_all_plugins

    register_all_plugins()
    for name in TIER_I2:
        assert name in registry.patterns or name in registry.indicators, f"{name} not registered"
