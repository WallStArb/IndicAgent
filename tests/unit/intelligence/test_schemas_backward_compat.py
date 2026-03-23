"""Backward compatibility tests for IntelligenceEvent schema.

Tests verify that the Phase 44.1 additions (session_type, pipeline_latency_ms)
do not break any existing consumers constructing IntelligenceEvent without those
fields. They also verify the new fields serialize and deserialize correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

UTC = UTC


def _make_base_event_kwargs() -> dict:
    """Return kwargs for a minimal valid IntelligenceEvent (all required fields)."""
    from src.intelligence.schemas import (
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        OHLCVBar,
        SMCContext,
    )

    return {
        "ts": datetime(2026, 3, 21, 14, 30, 0, tzinfo=UTC),
        "symbol": "ES",
        "tf": "1m",
        "bar": OHLCVBar(o=5250.25, h=5252.50, l=5248.75, c=5251.00, v=1500),
        "i1": I1Indicators(rsi_14=58.3, atr_14=12.5),
        "i3": I3Structure(
            nearest_support=5200.0,
            nearest_resistance=5300.0,
            trend_strength=0.65,
            swing_pattern=1.0,
        ),
        "i4": I4Context(
            trend_regime=0.65,
            trend_confidence=0.8,
            vol_regime=0.5,
            vol_percentile=60.0,
        ),
        "i5": I5Patterns(squeeze_active=0.0, rsi_div_bullish=False),
        "smc": SMCContext(bos_detected=False, hmm_regime=1.0),
        "i6": I6Confluence(ctf_score=0.75),
    }


class TestIntelligenceEventDefaults:
    def test_no_session_type_or_latency_succeeds(self):
        """IntelligenceEvent with no session_type/pipeline_latency_ms args succeeds (defaults work)."""
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event is not None

    def test_default_session_type_is_rth(self):
        """Default session_type is RTH."""
        from src.core.schemas.bar_message import SessionType
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event.session_type == SessionType.RTH

    def test_default_pipeline_latency_is_zero(self):
        """Default pipeline_latency_ms is 0.0."""
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event.pipeline_latency_ms == 0.0


class TestIntelligenceEventNewFields:
    def test_eth_session_type_round_trips(self):
        """IntelligenceEvent with session_type=SessionType.ETH and pipeline_latency_ms=42.5 round-trips correctly."""
        from src.core.schemas.bar_message import SessionType
        from src.intelligence.schemas import IntelligenceEvent

        kwargs = _make_base_event_kwargs()
        kwargs["session_type"] = SessionType.ETH
        kwargs["pipeline_latency_ms"] = 42.5

        event = IntelligenceEvent(**kwargs)
        json_str = event.model_dump_json()
        event2 = IntelligenceEvent.model_validate_json(json_str)

        assert event2.session_type == SessionType.ETH
        assert event2.pipeline_latency_ms == pytest.approx(42.5)

    def test_session_type_field_importable_from_bar_message(self):
        """SessionType used in IntelligenceEvent is the same class as in bar_message."""
        from src.core.schemas.bar_message import SessionType as BM_ST
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        # The field should be an instance of the SessionType from bar_message
        assert isinstance(event.session_type, BM_ST)


class TestIntelligenceEventBackwardCompat:
    def test_all_tier_fields_still_validate(self):
        """IntelligenceEvent with all existing tier fields (i1, i2, i3, i4, i5, smc, i6) still validates."""
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event.i1 is not None
        assert event.i3 is not None
        assert event.i4 is not None
        assert event.i5 is not None
        assert event.smc is not None
        assert event.i6 is not None

    def test_extra_forbid_rejects_unknown_field(self):
        """IntelligenceEvent extra='forbid' still rejects unknown top-level fields."""
        from src.intelligence.schemas import IntelligenceEvent

        kwargs = _make_base_event_kwargs()
        kwargs["unknown_future_field"] = "should_fail"

        with pytest.raises(Exception):  # pydantic ValidationError
            IntelligenceEvent(**kwargs)

    def test_schema_version_still_default(self):
        """schema_version default is still '1.0'."""
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event.schema_version == "1.0"

    def test_bar_field_accessible(self):
        """Existing bar field (OHLCVBar) is still accessible after schema extension."""
        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        assert event.bar.o == pytest.approx(5250.25)
        assert event.bar.v == 1500

    def test_event_round_trips_without_new_fields_in_payload(self):
        """Event serialized before Phase 44.1 (no session_type/pipeline_latency_ms) can still
        be deserialized with defaults applied."""
        import json

        from src.intelligence.schemas import IntelligenceEvent

        event = IntelligenceEvent(**_make_base_event_kwargs())
        payload = json.loads(event.model_dump_json())

        # Simulate old payload that doesn't include the new fields
        payload.pop("session_type", None)
        payload.pop("pipeline_latency_ms", None)

        event2 = IntelligenceEvent.model_validate(payload)
        assert event2 is not None
        assert event2.session_type.value == "rth"
        assert event2.pipeline_latency_ms == 0.0
