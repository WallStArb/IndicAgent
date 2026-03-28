"""Unit tests for pipeline timing observability (TDD — written before implementation).

Tests cover:
- bar_close_ts utility function
- IntelligenceEvent timing field optionality
- Per-source timing field behaviour (live vs backfill)
- feature_writer_agent INSERT param generation
"""

from datetime import UTC, datetime, timedelta

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_event(source: str = "live", bar_close_ts=None, i1_computed_at=None, computed_at=None):
    """Build a minimal IntelligenceEvent for timing tests."""
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

    kwargs = dict(
        ts=datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="1m",
        source=source,
        bar=OHLCVBar(o=5100.0, h=5105.0, l=5098.0, c=5103.0, v=1000),
        i1=I1Indicators(rsi_14=55.0),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )
    if bar_close_ts is not None:
        kwargs["bar_close_ts"] = bar_close_ts
    if i1_computed_at is not None:
        kwargs["i1_computed_at"] = i1_computed_at
    if computed_at is not None:
        kwargs["computed_at"] = computed_at
    return IntelligenceEvent(**kwargs)


# ── bar_close_ts utility ──────────────────────────────────────────────────────


def test_bar_close_ts_1m_returns_ts_unchanged():
    """For 1m bars, bar_close_ts equals ts (bar already closes on the minute)."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "1m")
    assert result == ts


def test_bar_close_ts_5m_returns_ts_plus_5_minutes():
    """For 5m bars, bar_close_ts = ts + 5 minutes (ts is period start)."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "5m")
    assert result == ts + timedelta(minutes=5)


def test_bar_close_ts_15m_returns_ts_plus_15_minutes():
    """For 15m bars, bar_close_ts = ts + 15 minutes."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "15m")
    assert result == ts + timedelta(minutes=15)


def test_bar_close_ts_1h_returns_ts_plus_1_hour():
    """For 1h bars, bar_close_ts = ts + 1 hour."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "1h")
    assert result == ts + timedelta(hours=1)


def test_bar_close_ts_4h_returns_ts_plus_4_hours():
    """For 4h bars, bar_close_ts = ts + 4 hours."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "4h")
    assert result == datetime(2026, 1, 15, 13, 30, 0, tzinfo=UTC)


def test_bar_close_ts_1d_returns_ts_plus_24_hours():
    """For 1d bars, bar_close_ts = ts + 24 hours."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "1d")
    assert result == datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC)


def test_bar_close_ts_unknown_tf_returns_ts_unchanged():
    """Unknown timeframe falls back to 0 offset (returns ts unchanged)."""
    from src.core.service_utils import bar_close_ts

    ts = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    result = bar_close_ts(ts, "2h")
    assert result == ts


# ── IntelligenceEvent timing fields are optional ──────────────────────────────


def test_intelligence_event_timing_fields_optional():
    """IntelligenceEvent constructs successfully without any timing fields."""
    event = _make_event()
    assert event.bar_close_ts is None
    assert event.i1_computed_at is None
    assert event.computed_at is None


def test_intelligence_event_timing_fields_accept_datetime():
    """All three timing fields accept datetime values."""
    now = datetime(2026, 1, 15, 13, 0, 0, 450000, tzinfo=UTC)
    event = _make_event(
        bar_close_ts=datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC),
        i1_computed_at=now,
        computed_at=now,
    )
    assert event.bar_close_ts == datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    assert event.i1_computed_at == now
    assert event.computed_at == now


# ── Timing fields: live vs backfill behaviour ─────────────────────────────────


def test_timing_fields_none_for_backfill():
    """For backfill events, i1_computed_at and computed_at must be None.

    This test verifies the contract: backfill code sets source='backfill'
    and leaves i1_computed_at/computed_at as None.
    """
    event = _make_event(
        source="backfill",
        bar_close_ts=datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC),
        i1_computed_at=None,
        computed_at=None,
    )
    assert event.source == "backfill"
    assert event.i1_computed_at is None
    assert event.computed_at is None


def test_timing_fields_set_for_live():
    """For live events, computed_at must be a non-None datetime."""
    now = datetime.now(UTC)
    event = _make_event(
        source="live",
        bar_close_ts=datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC),
        i1_computed_at=now,
        computed_at=now,
    )
    assert event.source == "live"
    assert event.computed_at is not None
    assert isinstance(event.computed_at, datetime)


def test_backfill_bar_close_ts_always_set():
    """Backfill events must have bar_close_ts set (source-independent field)."""
    bct = datetime(2026, 1, 15, 13, 5, 0, tzinfo=UTC)
    event = _make_event(source="backfill", bar_close_ts=bct)
    assert event.bar_close_ts == bct


# ── feature_writer_agent: INSERT param tuple ────────────────────────────────


def _make_record(source: str = "live", bar_close_ts=None, i1_computed_at=None, computed_at=None):
    """Build a minimal BarIntelligenceRecord for timing tests."""
    from src.intelligence.schemas import BarIntelligenceRecord

    event = _make_event(
        source=source,
        bar_close_ts=bar_close_ts,
        i1_computed_at=i1_computed_at,
        computed_at=computed_at,
    )
    return BarIntelligenceRecord(
        intelligence=event,
        ranked_signals=[],
        signals_evaluated=0,
        signals_after_quality=0,
        signals_after_regime=0,
        signals_after_tod=0,
        signals_after_calibration=0,
        ledger_written=False,
        i7_computed_at=datetime(2026, 1, 15, 13, 0, 1, tzinfo=UTC),
        pipeline_latency_ms=0.0,
    )


def test_feature_writer_writes_timing_columns_none_when_absent():
    """Without timing fields, _record_to_insert_params returns None for timing positions."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_record(source="backfill")
    params = _record_to_insert_params(record)
    # bar_close_ts at $16 (idx 15), i1_computed_at at $17 (idx 16), computed_at at $18 (idx 17)
    assert params[15] is None  # bar_close_ts
    assert params[16] is None  # i1_computed_at
    assert params[17] is None  # computed_at


def test_feature_writer_writes_timing_columns_present_for_live():
    """With timing fields set, _record_to_insert_params returns them at expected positions."""
    from services.feature_writer_agent import _record_to_insert_params

    bct = datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC)
    i1_at = datetime(2026, 1, 15, 13, 0, 0, 450000, tzinfo=UTC)
    comp_at = datetime(2026, 1, 15, 13, 0, 1, 120000, tzinfo=UTC)
    record = _make_record(
        source="live", bar_close_ts=bct, i1_computed_at=i1_at, computed_at=comp_at
    )
    params = _record_to_insert_params(record)
    assert params[15] == bct
    assert params[16] == i1_at
    assert params[17] == comp_at
