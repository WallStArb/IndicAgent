"""Tests for BarMessage bar_id UUID field and IntelligenceEvent propagation.

Phase 68-03: End-to-end bar_id trace from provider to DB.
"""

from uuid import UUID, uuid4

from src.core.schemas.bar_message import BarMessage, SessionType
from src.intelligence.schemas import (
    I1Indicators,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)


def _make_bar(**overrides) -> BarMessage:
    """Helper to build a minimal BarMessage with sensible defaults."""
    defaults = dict(
        ts="2026-04-12T12:00:00+00:00",
        symbol="ES",
        tf="1m",
        open=5800.0,
        high=5801.0,
        low=5799.0,
        close=5800.5,
        volume=1000,
        source="ibkr_named",
        session_type=SessionType.RTH,
    )
    defaults.update(overrides)
    return BarMessage(**defaults)


def _make_event(**overrides) -> IntelligenceEvent:
    """Helper to build a minimal IntelligenceEvent with all required sub-models."""
    defaults = dict(
        ts="2026-04-12T12:00:00+00:00",
        symbol="ES",
        tf="1m",
        bar=OHLCVBar(o=5800.0, h=5801.0, l=5799.0, c=5800.5, v=1000),
        i1=I1Indicators(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )
    defaults.update(overrides)
    return IntelligenceEvent(**defaults)


class TestBarMessageBarId:
    """BarMessage.bar_id: UUID auto-generated via default_factory=uuid4."""

    def test_bar_id_auto_generated(self):
        """BarMessage() with no bar_id argument auto-generates a UUID."""
        bar = _make_bar()
        assert bar.bar_id is not None

    def test_bar_id_is_uuid_type(self):
        """BarMessage.bar_id is a UUID type, not str."""
        bar = _make_bar()
        assert isinstance(bar.bar_id, UUID)

    def test_two_bars_have_different_bar_ids(self):
        """Two BarMessage instances have different bar_ids (uuid4 uniqueness)."""
        bar1 = _make_bar()
        bar2 = _make_bar()
        assert bar1.bar_id != bar2.bar_id

    def test_bar_id_serialized_in_model_dump(self):
        """BarMessage serialization (model_dump) includes bar_id as UUID."""
        bar = _make_bar()
        dumped = bar.model_dump()
        assert "bar_id" in dumped
        assert isinstance(dumped["bar_id"], UUID)

    def test_bar_id_in_json_serialization(self):
        """BarMessage JSON serialization includes bar_id as string."""
        bar = _make_bar()
        json_str = bar.model_dump_json()
        import json

        parsed = json.loads(json_str)
        assert "bar_id" in parsed
        assert isinstance(parsed["bar_id"], str)
        # Verify the string is a valid UUID
        UUID(parsed["bar_id"])

    def test_explicit_bar_id_preserved(self):
        """Explicitly provided bar_id is preserved (not overwritten)."""
        explicit_id = uuid4()
        bar = _make_bar(bar_id=explicit_id)
        assert bar.bar_id == explicit_id


class TestIntelligenceEventBarId:
    """IntelligenceEvent.bar_id: UUID | None for backward compat during transition."""

    def test_intelligence_event_accepts_bar_id(self):
        """IntelligenceEvent accepts bar_id: UUID field."""
        bar = _make_bar()
        event = _make_event(bar_id=bar.bar_id)
        assert event.bar_id == bar.bar_id

    def test_intelligence_event_bar_id_defaults_none(self):
        """IntelligenceEvent.bar_id defaults to None for backward compat."""
        event = _make_event()
        assert event.bar_id is None

    def test_intelligence_event_bar_id_none_explicit(self):
        """IntelligenceEvent.bar_id can be explicitly set to None."""
        event = _make_event(bar_id=None)
        assert event.bar_id is None
