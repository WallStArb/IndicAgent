"""Tests for signal orchestrator helper functions."""
import pytest
from datetime import datetime, timezone


# ── parse_intelligence_message ────────────────────────────────────────────────

def test_parse_message_extracts_bar_fields():
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.25",
        b"high": b"5105.50",
        b"low": b"5098.75",
        b"close": b"5103.00",
        b"volume": b"12345",
        b"trend_regime": b"0.65",
        b"atr_14": b"12.5",
    }
    bar, features = parse_intelligence_message(msg)

    assert bar["open"] == 5100.25
    assert bar["high"] == 5105.50
    assert bar["low"] == 5098.75
    assert bar["close"] == 5103.00
    assert bar["volume"] == 12345
    assert "trend_regime" not in bar


def test_parse_message_extracts_feature_fields():
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.0",
        b"high": b"5105.0",
        b"low": b"5099.0",
        b"close": b"5103.0",
        b"volume": b"10000",
        b"trend_regime": b"0.65",
        b"atr_14": b"12.5",
        b"rsi_14": b"58.3",
    }
    bar, features = parse_intelligence_message(msg)

    assert features["trend_regime"] == 0.65
    assert features["atr_14"] == 12.5
    assert features["rsi_14"] == 58.3
    assert "open" not in features
    assert "symbol" not in features


def test_parse_message_handles_non_numeric_feature():
    """Non-numeric feature values are stored as strings (don't crash)."""
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.0",
        b"high": b"5105.0",
        b"low": b"5099.0",
        b"close": b"5103.0",
        b"volume": b"10000",
        b"trend_regime": b"0.65",
        b"hmm_regime_state": b"trending",
    }
    bar, features = parse_intelligence_message(msg)
    assert features["hmm_regime_state"] == "trending"


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
