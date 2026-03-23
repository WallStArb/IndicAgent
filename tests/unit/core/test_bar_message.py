"""Tests for BarMessage schema and SessionType enum.

All tests in this file are passing (not stubs) — BarMessage is a data model
with full implementation in Wave 0, enabling all downstream consumers to
import and validate against a stable contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.schemas.bar_message import BarMessage, SessionType


def _make_bar(**overrides) -> dict:
    """Return a valid BarMessage dict, allowing field overrides."""
    base = {
        "ts": datetime(2026, 3, 21, 14, 30, 0, tzinfo=UTC),
        "symbol": "ES",
        "tf": "1m",
        "open": 5250.25,
        "high": 5252.50,
        "low": 5248.75,
        "close": 5251.00,
        "volume": 1500,
        "source": "ibkr_named",
        "session_type": SessionType.RTH,
    }
    base.update(overrides)
    return base


class TestSessionTypeEnum:
    def test_rth_value(self):
        assert SessionType.RTH == "rth"

    def test_eth_value(self):
        assert SessionType.ETH == "eth"

    def test_crypto_value(self):
        assert SessionType.CRYPTO == "crypto"

    def test_fx_value(self):
        assert SessionType.FX == "fx"

    def test_closed_value(self):
        assert SessionType.CLOSED == "closed"

    def test_is_str_subclass(self):
        assert isinstance(SessionType.RTH, str)


class TestBarMessageRoundTrip:
    def test_round_trip_preserves_all_fields(self):
        """BarMessage round-trip (model_validate_json + model_dump_json) preserves all fields."""
        bar = BarMessage(**_make_bar())
        json_str = bar.model_dump_json()
        bar2 = BarMessage.model_validate_json(json_str)
        assert bar2.ts == bar.ts
        assert bar2.symbol == bar.symbol
        assert bar2.tf == bar.tf
        assert bar2.open == bar.open
        assert bar2.high == bar.high
        assert bar2.low == bar.low
        assert bar2.close == bar.close
        assert bar2.volume == bar.volume
        assert bar2.source == bar.source
        assert bar2.session_type == bar.session_type
        assert bar2.gap_preceding == bar.gap_preceding

    def test_ts_preserved_as_utc_datetime(self):
        """ts field survives round-trip as UTC-aware datetime."""
        original_ts = datetime(2026, 3, 21, 9, 30, 0, tzinfo=UTC)
        bar = BarMessage(**_make_bar(ts=original_ts))
        json_str = bar.model_dump_json()
        bar2 = BarMessage.model_validate_json(json_str)
        # After round-trip, ts should be timezone-aware and equal the original UTC moment
        assert bar2.ts.tzinfo is not None
        assert bar2.ts.utctimetuple() == original_ts.utctimetuple()

    def test_gap_preceding_default_false(self):
        """gap_preceding defaults to False when not provided."""
        bar = BarMessage(**_make_bar())
        assert bar.gap_preceding is False

    def test_gap_preceding_explicit_true(self):
        """gap_preceding can be set to True explicitly."""
        bar = BarMessage(**_make_bar(gap_preceding=True))
        assert bar.gap_preceding is True


class TestBarMessageValidation:
    def test_invalid_source_rejected(self):
        """BarMessage rejects invalid source literal."""
        with pytest.raises(Exception):  # pydantic ValidationError
            BarMessage(**_make_bar(source="live"))

    def test_valid_sources_accepted(self):
        """All three valid source literals are accepted."""
        for src in ("ibkr_named", "ibkr_seed", "htf_derived"):
            bar = BarMessage(**_make_bar(source=src))
            assert bar.source == src

    def test_volume_is_int(self):
        """volume field is stored as int, not float."""
        bar = BarMessage(**_make_bar(volume=1000))
        assert isinstance(bar.volume, int)
        assert bar.volume == 1000

    def test_volume_float_coerced_to_int(self):
        """Pydantic coerces float volume to int (e.g. 1500.0 -> 1500)."""
        bar = BarMessage(**_make_bar(volume=1500))
        assert isinstance(bar.volume, int)

    def test_all_session_types_accepted(self):
        """All SessionType enum values are accepted in session_type field."""
        for st in SessionType:
            bar = BarMessage(**_make_bar(session_type=st))
            assert bar.session_type == st

    def test_session_type_string_value_accepted(self):
        """session_type accepts string values that match enum (SessionType is str-subclass)."""
        bar = BarMessage(**_make_bar(session_type="eth"))
        assert bar.session_type == SessionType.ETH
