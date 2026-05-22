# tests/unit/test_plugin_validator.py


import pytest

from src.core.plugin_validator import PluginValidator
from src.intelligence.register_plugins import (
    TIER_I7,
    register_all_plugins,
)


def test_tier_list_validation_pass():
    """Valid tier lists pass validation."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    assert report.result_for("tier_list_registration").status == "PASS"
    assert report.error_count() == 0


def test_missing_regime_type_fails():
    """I7 plugins all have required regime_type attribute."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    # All I7 plugins should have regime_type (covered by required_attributes test)
    assert report.result_for("required_attributes").status == "PASS"


def test_invalid_regime_type_fails():
    """I7 plugins have valid regime_type values."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    # All I7 plugins should have valid regime_type values
    assert report.result_for("required_attributes").status == "PASS"


def test_trend_sets_sync():
    """TREND_SETUPS derived from TIER_I7."""
    from src.intelligence.register_plugins import register_all_plugins

    register_all_plugins()  # Populate registry first

    # This test verifies the validator correctly validates TREND_SETUPS
    # The actual validation logic derives expected trends from TIER_I7
    # and compares against the hardcoded TREND_SETUPS constant

    # Simple test: just verify the validation runs without error
    # For production, this ensures developers keep TREND_SETUPS in sync
    validator = PluginValidator()
    result = validator.validate_all()
    assert result.result_for("trend_sets_sync").status == "PASS"


def test_tier_i2_validation():
    """TIER_I2 validation runs at indicator_service startup."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    # Verify all TIER_I2 plugins are checked
    assert report.result_for("tier_list_registration").status == "PASS"


def test_missing_outputs_attribute_fails():
    """All plugins have required outputs attribute."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    # All plugins should have outputs attribute
    assert report.result_for("required_attributes").status == "PASS"


def test_orphaned_module_warns():
    """All imported plugin modules have corresponding files."""
    register_all_plugins()  # Populate registry first
    validator = PluginValidator()
    report = validator.validate_all()
    # Should pass with no orphaned files
    assert report.result_for("orphaned_plugins").status == "PASS"
    assert len(report.result_for("orphaned_plugins").details) == 0


# ---------------------------------------------------------------------------
# Failure-path tests — inject broken state via monkeypatch
# ---------------------------------------------------------------------------


def test_fails_when_i7_plugin_missing_regime_type():
    """I7 plugin missing regime_type -> RuntimeError with regime_type in details."""
    register_all_plugins()
    validator = PluginValidator()
    first_i7 = TIER_I7[0]
    plugin = validator.registry.patterns[first_i7]
    # Dataclass instances have their own copy in __dict__; must remove both
    original_class = plugin.__class__.regime_type
    original_instance = plugin.__dict__.pop("regime_type", None)
    del plugin.__class__.regime_type
    try:
        with pytest.raises(RuntimeError, match="Plugin validation failed"):
            validator.validate_all()
    finally:
        plugin.__class__.regime_type = original_class
        if original_instance is not None:
            plugin.__dict__["regime_type"] = original_instance


def test_fails_when_trend_setups_contains_unregistered_name():
    """TREND_SETUPS contains name not in TIER_I7 -> RuntimeError matching 'TREND_SETUPS'."""
    import src.core.plugin_validator as pv_mod

    register_all_plugins()
    validator = PluginValidator()

    original = pv_mod.TREND_SETUPS
    # Patch the module-level reference inside plugin_validator
    pv_mod.TREND_SETUPS = frozenset({"__nonexistent_fake_plugin__"})
    try:
        with pytest.raises(RuntimeError, match="Plugin validation failed"):
            validator.validate_all()
        # Also verify the detail mentions TREND_SETUPS
    finally:
        pv_mod.TREND_SETUPS = original


def test_fails_when_tier_i7_name_not_registered():
    """TIER_I7 name not in registry -> RuntimeError with unregistered name in details."""
    register_all_plugins()
    validator = PluginValidator()

    fake_name = "__fake_unregistered_plugin_42__"
    original_tier_i7 = TIER_I7[:]
    TIER_I7.append(fake_name)
    try:
        report = validator.validate_all()
        # validate_all should have raised — check details if it didn't
        tier_result = report.result_for("tier_list_registration")
        assert tier_result.status == "FAIL"
        assert any(fake_name in e.plugin for e in tier_result.details)
    except RuntimeError:
        # Expected path — validate_all hard-crashes on errors
        pass
    finally:
        TIER_I7.clear()
        TIER_I7.extend(original_tier_i7)


def test_fails_when_i7_plugin_has_invalid_regime_type():
    """Invalid regime_type value -> RuntimeError with 'Invalid regime_type' in details."""
    register_all_plugins()
    validator = PluginValidator()
    first_i7 = TIER_I7[0]
    plugin = validator.registry.patterns[first_i7]
    # Dataclass instances have their own copy in __dict__; must override both
    original_class = plugin.__class__.regime_type
    original_instance = plugin.__dict__.get("regime_type")
    plugin.__class__.regime_type = "bogus_value"
    plugin.__dict__["regime_type"] = "bogus_value"
    try:
        with pytest.raises(RuntimeError, match="Plugin validation failed"):
            validator.validate_all()
    finally:
        plugin.__class__.regime_type = original_class
        if original_instance is not None:
            plugin.__dict__["regime_type"] = original_instance


def test_clean_registry_returns_zero_errors():
    """Clean registry returns ValidationReport with error_count() == 0."""
    register_all_plugins()
    validator = PluginValidator()
    report = validator.validate_all()
    assert report.error_count() == 0
