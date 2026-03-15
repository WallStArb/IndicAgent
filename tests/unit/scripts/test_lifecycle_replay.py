"""Tests for lifecycle_replay.py — unit tests using synthetic data, no DB."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))


# ── Helpers ────────────────────────────────────────────────────────────────


def _sig(signal_id="sig-001", direction=1, entry=5100.0, stop=5085.0,
         targets=None, ttl_bars=10, ts_offset_secs=0,
         market_entry_price=5100.0, status="pending"):
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=ts_offset_secs)
    return {
        "signal_id": signal_id,
        "status": status,
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": targets or [5115.0, 5130.0, 5145.0],
        "ttl_bars": ttl_bars,
        "point_value": 50.0,
        "timestamp": ts,
        "symbol": "ES",
        "timeframe": "1m",
        "entry_zone_low": entry - 5.0,
        "entry_zone_high": entry + 5.0,
        "market_entry_price": market_entry_price,
        "confidence": 0.8,
        "confluence_score": 0.7,
        "regime_context": "bullish",
        "cis_score": None, "bucket_scores": None, "weights_version": None,
    }


def _bar(ts, high, low, close, open_=None):
    return {
        "timestamp": ts,
        "open": open_ or close,
        "high": high,
        "low": low,
        "close": close,
    }


BASE_TS = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)


# ── Import helpers ─────────────────────────────────────────────────────────


def _get_replay():
    from production.scripts import lifecycle_replay
    return lifecycle_replay


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBarTimestampUsed:
    def test_no_datetime_now_in_replay_module(self):
        """Replay must use bar.timestamp for temporal fields — not datetime.now()."""
        import inspect
        replay = _get_replay()
        source = inspect.getsource(replay)
        # datetime.now() calls are forbidden in the core replay logic
        # (allowed only in logging/stats which don't touch signal fields)
        assert "datetime.now(" not in source or source.count("datetime.now(") == 0


@pytest.mark.unit
class TestGapDetection:
    def test_gap_detected_when_bar_delayed(self):
        """2-bar gap after signal → replay_gap_bars = 2."""
        replay = _get_replay()
        sig_ts = BASE_TS
        bar_ts = BASE_TS + timedelta(seconds=180)  # 3 min later on 1m TF = 2 missing bars
        gap = replay.compute_gap_bars(sig_ts, bar_ts, tf_seconds=60)
        assert gap == 2

    def test_no_gap_immediate_next_bar(self):
        replay = _get_replay()
        sig_ts = BASE_TS
        bar_ts = BASE_TS + timedelta(seconds=60)  # exactly 1 bar later
        gap = replay.compute_gap_bars(sig_ts, bar_ts, tf_seconds=60)
        assert gap == 0

    def test_no_gap_within_1_5x_threshold(self):
        replay = _get_replay()
        sig_ts = BASE_TS
        bar_ts = BASE_TS + timedelta(seconds=89)  # < 1.5 × 60s threshold
        gap = replay.compute_gap_bars(sig_ts, bar_ts, tf_seconds=60)
        assert gap == 0


@pytest.mark.unit
class TestEndOfBarsHandling:
    def test_ttl_expired_signals_get_resolved(self):
        """Signals remaining after bar stream ends are resolved as TTL expired."""
        replay = _get_replay()
        sig = _sig(signal_id="s1", ttl_bars=5)
        last_bar = _bar(BASE_TS + timedelta(seconds=600), 5103.0, 5097.0, 5100.0)
        # 10 bars elapsed (600s / 60s = 10) → TTL=5 exceeded → resolved
        result = replay.resolve_at_end_of_bars(sig, last_bar, tf_seconds=60,
                                               zone_mfe=0.0, market_mfe=-0.1)
        assert result["zone_outcome"] in ("never_activated", "ttl_expired_ahead", "ttl_expired_behind")
        assert result["market_outcome"] in ("ttl_expired_ahead", "ttl_expired_behind")

    def test_end_of_bars_uses_last_bar_timestamp(self):
        """exit_at must be last_bar.timestamp, not datetime.now()."""
        replay = _get_replay()
        sig = _sig(signal_id="s2", ttl_bars=3)
        last_ts = BASE_TS + timedelta(seconds=300)
        last_bar = _bar(last_ts, 5103.0, 5097.0, 5100.0)
        result = replay.resolve_at_end_of_bars(sig, last_bar, tf_seconds=60,
                                               zone_mfe=0.5, market_mfe=0.5)
        assert result["exit_at"] == last_ts


@pytest.mark.unit
class TestChronologicalOrdering:
    def test_earlier_signal_activates_before_later_signal(self):
        """Signal with earlier timestamp must be added to live_signals first."""
        replay = _get_replay()
        # sig_early fires at 10:00, sig_late fires at 10:02
        sig_early = _sig("s-early", ts_offset_secs=0)   # ts = 10:00:00
        sig_late = _sig("s-late", ts_offset_secs=120)   # ts = 10:02:00

        # bar_ts = 10:01 → sig_early (10:00 < 10:01) is active, sig_late (10:02 < 10:01) is not
        bar_ts = BASE_TS + timedelta(seconds=60)

        live = replay.get_signals_active_at(
            [sig_early, sig_late],
            bar_ts=bar_ts,
        )
        assert any(s["signal_id"] == "s-early" for s in live)
        assert not any(s["signal_id"] == "s-late" for s in live)


@pytest.mark.unit
class TestNodataHandling:
    def test_zero_bars_available_produces_null_market_outcome(self):
        """No bars available after signal.timestamp → market track all NULL."""
        replay = _get_replay()
        result = replay.handle_no_data(sig=_sig("s1"))
        assert result["market_entry_outcome"] is None
        assert result["market_entry_exit_price"] is None

    def test_zero_bars_zone_outcome_is_never_activated(self):
        replay = _get_replay()
        result = replay.handle_no_data(sig=_sig("s1"))
        assert result["zone_outcome"] == "never_activated"


@pytest.mark.unit
class TestMarketOutcomeNeverActivatedInvariant:
    def test_market_outcome_never_never_activated(self):
        """market_entry_outcome must never be 'never_activated'."""
        replay = _get_replay()
        # Simulate a signal that ran through all bars with no zone activation
        sig = _sig(ttl_bars=3, market_entry_price=5100.0)
        last_bar = _bar(BASE_TS + timedelta(seconds=300), 5097.0, 5093.0, 5094.0)
        result = replay.resolve_at_end_of_bars(sig, last_bar, tf_seconds=60,
                                               zone_mfe=0.0, market_mfe=0.0)
        assert result["market_outcome"] != "never_activated"


@pytest.mark.unit
class TestBarsInTradeConstraint:
    def test_bars_in_trade_le_ttl(self):
        """market_entry_bars_in_trade can never exceed TTL."""
        replay = _get_replay()
        sig = _sig(ttl_bars=5, market_entry_price=5100.0)
        last_bar = _bar(BASE_TS + timedelta(seconds=300), 5097.0, 5093.0, 5094.0)
        result = replay.resolve_at_end_of_bars(sig, last_bar, tf_seconds=60,
                                               zone_mfe=0.0, market_mfe=0.0)
        if result["market_entry_bars_in_trade"] is not None:
            assert result["market_entry_bars_in_trade"] <= sig["ttl_bars"]


@pytest.mark.unit
class TestTrackComparisonInvariants:
    def test_zone_target_full_market_never_activated_is_impossible(self):
        """Zone target_full + market never_activated cannot coexist. Market always fills."""
        from production.scripts.lifecycle_replay import validate_track_pair
        with pytest.raises(ValueError):
            validate_track_pair(zone_outcome="target_full",
                                market_outcome="never_activated")

    def test_zone_never_activated_market_target_full_is_valid(self):
        from production.scripts.lifecycle_replay import validate_track_pair
        # Should not raise
        validate_track_pair(zone_outcome="never_activated",
                            market_outcome="target_full")
