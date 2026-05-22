"""Tests for RollEvent and BarGapRequest schemas and topic_roll_events stream key.

Covers:
- RollEvent validates correct payloads with all 8 fields
- RollEvent rejects payloads with missing required fields
- RollEvent parses ISO-8601 string for detection_ts
- RollEvent.model_dump() returns dict with all 8 keys
- BarGapRequest validates correct payloads with 4 fields
- topic_roll_events returns correct topic string for dev and prod envs
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.schemas.market_events import BarGapRequest, RollEvent
from src.core.stream_keys import topic_roll_events

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DETECTION_TS = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

VALID_ROLL_PAYLOAD: dict = {
    "symbol": "ES",
    "old_contract": "ESH6",
    "new_contract": "ESM6",
    "roll_gap_price": -25.5,
    "roll_gap_pct": -0.0045,
    "detection_ts": DETECTION_TS,
    "volume_zscore": 2.87,
    "confirmation_count": 3,
}

VALID_GAP_REQUEST_PAYLOAD: dict = {
    "symbol": "CL",
    "tf": "5m",
    "start_ts": datetime(2026, 3, 28, 9, 30, 0, tzinfo=UTC),
    "end_ts": datetime(2026, 3, 28, 9, 45, 0, tzinfo=UTC),
}


# ---------------------------------------------------------------------------
# RollEvent tests
# ---------------------------------------------------------------------------


def test_roll_event_validates_correct_payload():
    """RollEvent.model_validate accepts all 8 fields and returns typed model."""
    event = RollEvent.model_validate(VALID_ROLL_PAYLOAD)

    assert event.symbol == "ES"
    assert event.old_contract == "ESH6"
    assert event.new_contract == "ESM6"
    assert event.roll_gap_price == -25.5
    assert event.roll_gap_pct == -0.0045
    assert event.detection_ts == DETECTION_TS
    assert event.volume_zscore == 2.87
    assert event.confirmation_count == 3


def test_roll_event_rejects_missing_symbol():
    """RollEvent.model_validate raises ValidationError when required field is missing."""
    payload = {k: v for k, v in VALID_ROLL_PAYLOAD.items() if k != "symbol"}
    with pytest.raises(ValidationError):
        RollEvent.model_validate(payload)


def test_roll_event_parses_iso_string_detection_ts():
    """RollEvent accepts ISO-8601 string for detection_ts and parses to datetime."""
    payload = {**VALID_ROLL_PAYLOAD, "detection_ts": "2026-03-28T12:00:00Z"}
    event = RollEvent.model_validate(payload)
    # Pydantic v2 parses Z suffix as UTC
    assert event.detection_ts.year == 2026
    assert event.detection_ts.month == 3
    assert event.detection_ts.day == 28
    assert event.detection_ts.hour == 12
    assert event.detection_ts.minute == 0


def test_roll_event_model_dump_returns_all_9_keys():
    """RollEvent.model_dump() returns a dict with exactly the 9 expected keys."""
    event = RollEvent.model_validate(VALID_ROLL_PAYLOAD)
    dumped = event.model_dump()

    expected_keys = {
        "symbol",
        "old_contract",
        "new_contract",
        "roll_gap_price",
        "roll_gap_pct",
        "detection_ts",
        "volume_zscore",
        "confirmation_count",
        "detection_method",
    }
    assert set(dumped.keys()) == expected_keys


def test_roll_event_detection_method_defaults_to_volume():
    """RollEvent without detection_method defaults to 'volume'."""
    event = RollEvent.model_validate(VALID_ROLL_PAYLOAD)
    assert event.detection_method == "volume"


def test_roll_event_accepts_calendar_method():
    """RollEvent accepts detection_method='calendar'."""
    payload = {**VALID_ROLL_PAYLOAD, "detection_method": "calendar"}
    event = RollEvent.model_validate(payload)
    assert event.detection_method == "calendar"


def test_roll_event_rejects_invalid_detection_method():
    """RollEvent rejects unknown detection_method values."""
    payload = {**VALID_ROLL_PAYLOAD, "detection_method": "magic"}
    with pytest.raises(ValidationError):
        RollEvent.model_validate(payload)


# ---------------------------------------------------------------------------
# BarGapRequest tests
# ---------------------------------------------------------------------------


def test_bar_gap_request_validates_correct_payload():
    """BarGapRequest.model_validate accepts all 4 fields and returns typed model."""
    req = BarGapRequest.model_validate(VALID_GAP_REQUEST_PAYLOAD)

    assert req.symbol == "CL"
    assert req.tf == "5m"
    assert req.start_ts == datetime(2026, 3, 28, 9, 30, 0, tzinfo=UTC)
    assert req.end_ts == datetime(2026, 3, 28, 9, 45, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# topic_roll_events tests
# ---------------------------------------------------------------------------


def test_topic_roll_events_development():
    """topic_roll_events returns correct topic string for development env."""
    assert topic_roll_events("development") == "development.market.events.roll"


def test_topic_roll_events_production():
    """topic_roll_events returns correct topic string for production env."""
    assert topic_roll_events("production") == "production.market.events.roll"
