"""Tests for BarGapRequest schema."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.schemas.market_events import BarGapRequest

VALID_GAP_REQUEST_PAYLOAD: dict = {
    "symbol": "CL",
    "tf": "5m",
    "start_ts": datetime(2026, 3, 28, 9, 30, 0, tzinfo=UTC),
    "end_ts": datetime(2026, 3, 28, 9, 45, 0, tzinfo=UTC),
}


def test_bar_gap_request_validates_correct_payload():
    req = BarGapRequest.model_validate(VALID_GAP_REQUEST_PAYLOAD)
    assert req.symbol == "CL"
    assert req.tf == "5m"
    assert req.start_ts == datetime(2026, 3, 28, 9, 30, 0, tzinfo=UTC)
    assert req.end_ts == datetime(2026, 3, 28, 9, 45, 0, tzinfo=UTC)
