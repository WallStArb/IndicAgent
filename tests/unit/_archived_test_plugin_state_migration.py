"""Unit tests for indicator_service plugin state migration on futures roll.

Tests _adjust_price_state() and _handle_roll_event() behavior:
- Price-sensitive plugins have roll_gap added to price levels
- Volume-neutral plugins are copied verbatim
- Old key is removed, new key is created
- Malformed events are skipped, not crashed
"""
from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── _adjust_price_state helper ────────────────────────────────────────────────


def _make_service() -> Any:
    """Construct a bare IndicatorComputeAgent with just the attrs needed for migration tests."""
    from services.indicator_compute_agent import IndicatorComputeAgent

    svc = IndicatorComputeAgent.__new__(IndicatorComputeAgent)
    # BaseAgent attributes required by __new__ pattern (see CLAUDE.md)
    svc._stop_event = asyncio.Event()
    svc.name = "test"
    svc._i1_plugin_states = {}
    svc._i1_plugin_states_locks = {}
    svc.logger = MagicMock()
    return svc


def _make_roll_event(
    base_symbol: str = "ES",
    old_contract: str = "ESM6",
    new_contract: str = "ESU6",
    roll_gap: float = 2.5,
) -> dict:
    """Create a valid RollEvent payload matching the RollEvent schema.

    Note: The implementation reads event.get("roll_gap", 0.0) directly,
    not from the parsed RollEvent.roll_gap_price. We include both
    keys to satisfy both the schema validator and the implementation.
    """
    return {
        "symbol": base_symbol,
        "old_contract": old_contract,
        "new_contract": new_contract,
        "roll_gap_price": roll_gap,
        "roll_gap": roll_gap,  # Implementation reads this directly
        "roll_gap_pct": roll_gap / 1000.0,  # approximate
        "detection_ts": datetime.now(UTC),
        "volume_zscore": 1.5,
        "confirmation_count": 3,
    }


class TestAdjustPriceState:
    """Tests for the _adjust_price_state helper."""

    def test_adjusts_float_values(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"upper": 4200.0, "lower": 4150.0, "middle": 4175.0}
        result = _adjust_price_state(state, 2.5)
        assert result["upper"] == pytest.approx(4202.5)
        assert result["lower"] == pytest.approx(4152.5)
        assert result["middle"] == pytest.approx(4177.5)

    def test_adjusts_int_values(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"level": 4200}
        result = _adjust_price_state(state, 1.0)
        assert result["level"] == pytest.approx(4201.0)

    def test_adjusts_list_of_floats(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"levels": [4100.0, 4200.0, 4300.0]}
        result = _adjust_price_state(state, 5.0)
        assert result["levels"] == pytest.approx([4105.0, 4205.0, 4305.0])

    def test_recurses_into_nested_dict(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"bands": {"upper": 4200.0, "lower": 4100.0}}
        result = _adjust_price_state(state, 10.0)
        assert result["bands"]["upper"] == pytest.approx(4210.0)
        assert result["bands"]["lower"] == pytest.approx(4110.0)

    def test_leaves_non_numeric_unchanged(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"label": "trend_up", "direction": 1, "upper": 4200.0}
        result = _adjust_price_state(state, 2.0)
        assert result["label"] == "trend_up"
        assert result["upper"] == pytest.approx(4202.0)

    def test_does_not_mutate_original(self) -> None:
        from services.indicator_compute_agent import _adjust_price_state

        state = {"upper": 4200.0}
        _adjust_price_state(state, 10.0)
        assert state["upper"] == 4200.0  # original unchanged


class TestHandleRollEvent:
    """Tests for IndicatorService._handle_roll_event()."""

    def _populate_states(self, svc: Any) -> None:
        """Seed _i1_plugin_states with bollinger and rsi states for old symbol."""
        svc._i1_plugin_states = {
            ("bollinger_bands", "ESM6", "1m"): {"upper": 5200.0, "lower": 5100.0, "middle": 5150.0},
            ("rsi", "ESM6", "1m"): {"prev_gain": 1.5, "prev_loss": 0.8, "count": 14},
            ("macd", "ESM6", "1m"): {"fast_ema": 5150.0, "slow_ema": 5140.0},
            ("bollinger_bands", "ESM6", "5m"): {"upper": 5210.0, "lower": 5090.0, "middle": 5150.0},
        }

    def test_price_sensitive_plugin_adjusted(self) -> None:
        svc = _make_service()
        self._populate_states(svc)
        event = _make_roll_event(roll_gap=2.5)
        asyncio.run(svc._handle_roll_event(event))
        new_bb = svc._i1_plugin_states.get(("bollinger_bands", "ESU6", "1m"))
        assert new_bb is not None
        assert new_bb["upper"] == pytest.approx(5202.5)
        assert new_bb["lower"] == pytest.approx(5102.5)
        assert new_bb["middle"] == pytest.approx(5152.5)

    def test_volume_neutral_plugin_copied_verbatim(self) -> None:
        svc = _make_service()
        self._populate_states(svc)
        event = _make_roll_event(roll_gap=2.5)
        asyncio.run(svc._handle_roll_event(event))
        new_rsi = svc._i1_plugin_states.get(("rsi", "ESU6", "1m"))
        assert new_rsi is not None
        assert new_rsi["prev_gain"] == 1.5
        assert new_rsi["prev_loss"] == 0.8
        assert new_rsi["count"] == 14

    def test_old_key_deleted(self) -> None:
        svc = _make_service()
        self._populate_states(svc)
        event = _make_roll_event(roll_gap=2.5)
        asyncio.run(svc._handle_roll_event(event))
        old_keys = [k for k in svc._i1_plugin_states if "ESM6" in k]
        assert len(old_keys) == 0

    def test_new_key_created_for_all_timeframes(self) -> None:
        svc = _make_service()
        self._populate_states(svc)
        event = _make_roll_event(roll_gap=1.0)
        asyncio.run(svc._handle_roll_event(event))
        # Both 1m and 5m should be migrated
        new_keys = [k for k in svc._i1_plugin_states if "ESU6" in k]
        tfs = {k[2] for k in new_keys}
        assert "1m" in tfs
        assert "5m" in tfs

    def test_ignores_non_roll_event_type(self) -> None:
        svc = _make_service()
        svc._i1_plugin_states = {
            ("bollinger_bands", "ESM6", "1m"): {"upper": 5200.0},
        }
        # Malformed event — missing required fields — parse_roll_event returns None
        event = {"foo": "bar"}
        asyncio.run(svc._handle_roll_event(event))
        # State should be unchanged
        assert ("bollinger_bands", "ESM6", "1m") in svc._i1_plugin_states

    def test_malformed_event_missing_fields_logged_not_crashed(self) -> None:
        svc = _make_service()
        svc._i1_plugin_states = {}
        # Malformed event — missing required fields
        event = {"foo": "bar"}
        # Should not raise
        asyncio.run(svc._handle_roll_event(event))

    def test_no_old_key_gracefully_skipped(self) -> None:
        svc = _make_service()
        svc._i1_plugin_states = {}
        event = _make_roll_event(
            base_symbol="NQ",
            old_contract="NQM6",
            new_contract="NQU6",
            roll_gap=5.0,
        )
        asyncio.run(svc._handle_roll_event(event))  # No state to migrate — should not crash

    def test_default_roll_gap_zero(self) -> None:
        svc = _make_service()
        svc._i1_plugin_states = {
            ("bollinger_bands", "ESM6", "1m"): {"upper": 5200.0, "lower": 5100.0},
        }
        # Create a valid RollEvent with roll_gap_price = 0
        event = _make_roll_event(roll_gap=0.0)
        asyncio.run(svc._handle_roll_event(event))
        new_bb = svc._i1_plugin_states.get(("bollinger_bands", "ESU6", "1m"))
        assert new_bb is not None
        assert new_bb["upper"] == pytest.approx(5200.0)
