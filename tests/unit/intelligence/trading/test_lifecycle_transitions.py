"""Tests for lifecycle transition types and serialization."""

from datetime import UTC, datetime

import pytest

from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    from_dict,
    to_dict,
)

# ---------------------------------------------------------------------------
# TransitionType enum
# ---------------------------------------------------------------------------


class TestTransitionType:
    def test_activation_value(self):
        assert TransitionType.ACTIVATION == "activation"

    def test_exit_value(self):
        assert TransitionType.EXIT == "exit"

    def test_chandelier_update_value(self):
        assert TransitionType.CHANDELIER_UPDATE == "chandelier_update"

    def test_mae_mfe_update_value(self):
        assert TransitionType.MAE_MFE_UPDATE == "mae_mfe_update"

    def test_shadow_outcome_value(self):
        assert TransitionType.SHADOW_OUTCOME == "shadow_outcome"

    def test_all_values_distinct(self):
        values = [t.value for t in TransitionType]
        assert len(values) == len(set(values))

    def test_from_string(self):
        assert TransitionType("activation") is TransitionType.ACTIVATION


# ---------------------------------------------------------------------------
# to_dict / from_dict roundtrip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip_activation(self):
        ts = datetime(2026, 4, 10, 14, 30, 0, tzinfo=UTC)
        t = LifecycleTransition(
            transition_type=TransitionType.ACTIVATION,
            signal_id="sig-001",
            symbol="ESM6",
            timeframe="1m",
            bar_ts=ts,
            data={"entry_price": 5500.0},
        )
        d = to_dict(t)
        result = from_dict(d)

        assert result.transition_type == TransitionType.ACTIVATION
        assert result.signal_id == "sig-001"
        assert result.symbol == "ESM6"
        assert result.timeframe == "1m"
        assert result.bar_ts == ts
        assert result.data == {"entry_price": 5500.0}

    def test_roundtrip_exit(self):
        ts = datetime(2026, 4, 10, 15, 0, 0, tzinfo=UTC)
        t = LifecycleTransition(
            transition_type=TransitionType.EXIT,
            signal_id="sig-002",
            symbol="NQM6",
            timeframe="5m",
            bar_ts=ts,
            data={"outcome": "stopped_out", "pnl_r": -1.5},
        )
        d = to_dict(t)
        result = from_dict(d)

        assert result.transition_type == TransitionType.EXIT
        assert result.data["outcome"] == "stopped_out"
        assert result.data["pnl_r"] == -1.5

    def test_roundtrip_with_empty_data(self):
        ts = datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
        t = LifecycleTransition(
            transition_type=TransitionType.CHANDELIER_UPDATE,
            signal_id="sig-003",
            symbol="GCM6",
            timeframe="15m",
            bar_ts=ts,
        )
        d = to_dict(t)
        result = from_dict(d)

        assert result.transition_type == TransitionType.CHANDELIER_UPDATE
        assert result.data == {}

    def test_to_dict_isoformat(self):
        ts = datetime(2026, 4, 10, 14, 30, 0, tzinfo=UTC)
        t = LifecycleTransition(
            transition_type=TransitionType.MAE_MFE_UPDATE,
            signal_id="sig-004",
            symbol="ESM6",
            timeframe="1m",
            bar_ts=ts,
        )
        d = to_dict(t)
        assert d["bar_ts"] == "2026-04-10T14:30:00+00:00"

    def test_from_dict_naive_timestamp_gets_utc(self):
        """Naive timestamps should be treated as UTC."""
        d = {
            "transition_type": "activation",
            "signal_id": "sig-005",
            "symbol": "ESM6",
            "timeframe": "1m",
            "bar_ts": "2026-04-10T14:30:00",
        }
        result = from_dict(d)
        assert result.bar_ts.tzinfo == UTC

    def test_from_dict_aware_timestamp_preserved(self):
        """Already timezone-aware timestamps should be preserved as-is."""
        d = {
            "transition_type": "activation",
            "signal_id": "sig-006",
            "symbol": "ESM6",
            "timeframe": "1m",
            "bar_ts": "2026-04-10T14:30:00+00:00",
        }
        result = from_dict(d)
        assert result.bar_ts.tzinfo is not None
        assert result.bar_ts == datetime(2026, 4, 10, 14, 30, 0, tzinfo=UTC)

    def test_from_dict_missing_data_defaults_empty(self):
        d = {
            "transition_type": "shadow_outcome",
            "signal_id": "sig-007",
            "symbol": "ESM6",
            "timeframe": "1m",
            "bar_ts": "2026-04-10T14:30:00+00:00",
        }
        result = from_dict(d)
        assert result.data == {}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestFromDictErrors:
    def test_invalid_transition_type_raises_value_error(self):
        d = {
            "transition_type": "not_a_real_type",
            "signal_id": "sig-bad",
            "symbol": "ESM6",
            "timeframe": "1m",
            "bar_ts": "2026-04-10T14:30:00+00:00",
        }
        with pytest.raises(ValueError, match="Invalid transition_type"):
            from_dict(d)
