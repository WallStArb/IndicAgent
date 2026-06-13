"""Tests for MacroContextPlugin.compute_full — I4 macro context plugin."""

from __future__ import annotations

from src.intelligence.context.macro_context import MacroContextPlugin


def test_compute_full_returns_all_five_fields_when_ready() -> None:
    """compute_full with ready cross_asset returns all 5 fields with correct types."""
    plugin = MacroContextPlugin()
    frames = {
        "cross_asset": {
            "ready": True,
            "ftq_score": 0.65,
            "ftq_regime": "risk_off",
            "yield_curve_slope": -0.12,
            "yield_curve_regime": "inverted",
            "corr_z": 1.45,
        }
    }
    result = plugin.compute_full(frames)

    assert result["ftq_score"] == 0.65
    assert isinstance(result["ftq_score"], float)
    assert result["ftq_regime"] == "risk_off"
    assert isinstance(result["ftq_regime"], str)
    assert result["yield_curve_slope"] == -0.12
    assert isinstance(result["yield_curve_slope"], float)
    assert result["yield_curve_regime"] == "inverted"
    assert isinstance(result["yield_curve_regime"], str)
    assert result["corr_z"] == 1.45
    assert isinstance(result["corr_z"], float)


def test_compute_full_returns_empty_when_not_ready() -> None:
    """compute_full with ready=False returns {}."""
    plugin = MacroContextPlugin()
    frames = {
        "cross_asset": {
            "ready": False,
            "ftq_score": 0.65,
        }
    }
    result = plugin.compute_full(frames)
    assert result == {}


def test_compute_full_returns_empty_when_no_cross_asset_key() -> None:
    """compute_full with no cross_asset key in frames returns {}."""
    plugin = MacroContextPlugin()
    result = plugin.compute_full({"features": {"atr": 1.2}})
    assert result == {}


def test_compute_full_preserves_none_field_values() -> None:
    """Per D-06: None values in cross_asset are preserved, not coerced to 0.0."""
    plugin = MacroContextPlugin()
    frames = {
        "cross_asset": {
            "ready": True,
            "ftq_score": None,
            "ftq_regime": None,
            "yield_curve_slope": None,
            "yield_curve_regime": None,
            "corr_z": None,
        }
    }
    result = plugin.compute_full(frames)

    assert result["ftq_score"] is None
    assert result["ftq_regime"] is None
    assert result["yield_curve_slope"] is None
    assert result["yield_curve_regime"] is None
    assert result["corr_z"] is None
