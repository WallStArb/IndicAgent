"""Tests for signal orchestrator helper functions."""
import pytest
from datetime import datetime, timezone


# ── _parse_intelligence_event ─────────────────────────────────────────────────

def _make_valid_event_json() -> bytes:
    """Return bytes of a valid IntelligenceEvent JSON for test fixtures."""
    from src.intelligence.schemas import (
        IntelligenceEvent,
        OHLCVBar,
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        SMCContext,
        I6Confluence,
    )
    event = IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.25, h=5105.50, l=5098.75, c=5103.00, v=12345),
        i1=I1Indicators(rsi_14=58.3, atr_14=12.5),
        i3=I3Structure(
            nearest_support=5080.0,
            nearest_resistance=5120.0,
            trend_strength=0.65,
            swing_pattern=1.0,
        ),
        i4=I4Context(
            trend_regime=0.65,
            trend_confidence=0.8,
            vol_regime=0.5,
            vol_percentile=60.0,
        ),
        i5=I5Patterns(squeeze_active=0.0, rsi_div_bullish=False),
        smc=SMCContext(bos_detected=False, hmm_regime=1.0),
        i6=I6Confluence(ctf_score=0.75),
    )
    return event.model_dump_json().encode()


def test_parse_intelligence_event_returns_typed_event():
    """Valid IntelligenceEvent JSON in b'event' field returns IntelligenceEvent."""
    from services.signal_orchestrator_service import _parse_intelligence_event
    from src.intelligence.schemas import IntelligenceEvent

    fields = {b"event": _make_valid_event_json()}
    result = _parse_intelligence_event(fields)

    assert result is not None
    assert isinstance(result, IntelligenceEvent)
    assert result.symbol == "ESH6"
    assert result.tf == "5m"
    assert result.bar.o == pytest.approx(5100.25)
    assert result.bar.v == 12345
    assert result.i4.trend_regime == pytest.approx(0.65)
    assert result.i1.rsi_14 == pytest.approx(58.3)


def test_parse_intelligence_event_returns_none_on_missing_event_field():
    """Empty fields dict returns None without crashing."""
    from services.signal_orchestrator_service import _parse_intelligence_event

    result = _parse_intelligence_event({})
    assert result is None


def test_parse_intelligence_event_returns_none_on_malformed_json():
    """Garbled JSON bytes returns None and logs warning."""
    from services.signal_orchestrator_service import _parse_intelligence_event

    result = _parse_intelligence_event({b"event": b"not-valid-json{{{"})
    assert result is None


def test_parse_intelligence_event_returns_none_on_validation_error():
    """Valid JSON but fails Pydantic validation returns None."""
    from services.signal_orchestrator_service import _parse_intelligence_event

    # Omitting required fields causes ValidationError
    bad_json = b'{"schema_version": "1.0", "symbol": "ESH6"}'
    result = _parse_intelligence_event({b"event": bad_json})
    assert result is None


# ── build_ledger_entries ──────────────────────────────────────────────────────

def _make_signal(plugin: str, direction: int, rank: int) -> dict:
    return {
        "type": "signal.v1",
        "symbol": "ESH6",
        "timeframe": "5m",
        "timestamp": "2026-02-18T10:00:00",
        "signal_type": "trend_following",
        "setup_plugin": plugin,
        "direction": direction,
        "entry_price": 5103.0,
        "stop_loss": 5083.0,
        "targets": [5123.0, 5143.0, 5163.0],
        "confidence": 0.72,
        "risk_reward_ratio": 1.0,
        "regime_context": "trending_bull",
        "confluence_score": 0.8,
        "supporting_factors": ["trend_regime"],
        "invalidation_conditions": [],
        "ttl_bars": 20,
        "composite_rank": rank,
    }


def test_build_ledger_entries_winner_has_was_selected_true():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_TrendFollowing", 1, 1)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner],
        resolution_method="sole",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    features = {"trend_regime": 0.65, "ctf_score": 0.8}

    entries = build_ledger_entries(result, "ESH6", "5m", ts, features)

    assert len(entries) == 1
    assert entries[0].was_selected is True
    assert entries[0].symbol == "ESH6"
    assert entries[0].timeframe == "5m"
    assert entries[0].resolution_method == "sole"
    assert entries[0].num_signals_bar == 1


def test_build_ledger_entries_loser_has_was_selected_false():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_LiquiditySweepReclaim", 1, 1)
    loser = _make_signal("trad_TrendFollowing", 1, 2)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner, loser],
        resolution_method="priority",
        num_signals_fired=2,
        num_agreeing=2,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    entries = build_ledger_entries(result, "ESH6", "5m", ts, {})

    assert len(entries) == 2
    assert entries[0].was_selected is True   # rank 1
    assert entries[1].was_selected is False  # rank 2


def test_build_ledger_entries_no_signal_all_false():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    sig1 = _make_signal("trad_TrendFollowing", 1, 1)
    sig2 = _make_signal("trad_MeanReversion", -1, 2)
    result = AggregatedResult(
        selected_signal=None,
        all_ranked=[sig1, sig2],
        resolution_method="no_signal",
        num_signals_fired=2,
        num_agreeing=0,
        num_conflicting=2,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    entries = build_ledger_entries(result, "ESH6", "5m", ts, {})

    assert len(entries) == 2
    assert all(e.was_selected is False for e in entries)


def test_build_ledger_entries_snapshots_market_context():
    from services.signal_orchestrator_service import build_ledger_entries, MARKET_CONTEXT_KEYS
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_TrendFollowing", 1, 1)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner],
        resolution_method="sole",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    features = {k: 0.5 for k in MARKET_CONTEXT_KEYS}
    features["extra_field"] = 99.9

    entries = build_ledger_entries(result, "ESH6", "5m", ts, features)

    ctx = entries[0].market_context
    assert "extra_field" not in ctx
    for k in MARKET_CONTEXT_KEYS:
        assert k in ctx


def test_build_ledger_entries_returns_empty_when_no_ranked():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    result = AggregatedResult(
        selected_signal=None,
        all_ranked=[],
        resolution_method="no_signal",
        num_signals_fired=0,
        num_agreeing=0,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert build_ledger_entries(result, "ESH6", "5m", ts, {}) == []
