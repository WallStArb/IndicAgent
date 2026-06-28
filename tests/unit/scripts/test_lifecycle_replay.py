"""Tests for lifecycle_replay.py — unit tests using synthetic data, no DB."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.debug.replay import debug_lifecycle_replay as lifecycle_replay

# ── Helpers ────────────────────────────────────────────────────────────────


def _sig(
    signal_id="sig-001",
    direction=1,
    entry=5100.0,
    stop=5085.0,
    targets=None,
    ttl_bars=10,
    ts_offset_secs=0,
    market_entry_price=5100.0,
    status="pending",
):
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
        "cis_score": None,
        "bucket_scores": None,
        "weights_version": None,
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
        result = replay.resolve_at_end_of_bars(
            sig, last_bar, tf_seconds=60, zone_mfe=0.0, market_mfe=-0.1
        )
        assert result["zone_outcome"] in (
            "never_activated",
            "ttl_expired_ahead",
            "ttl_expired_behind",
        )
        assert result["market_entry_outcome"] in ("ttl_expired_ahead", "ttl_expired_behind")

    def test_end_of_bars_uses_last_bar_timestamp(self):
        """exit_at is capped by TTL — min(last_bar, signal.timestamp + ttl)."""
        replay = _get_replay()
        sig = _sig(signal_id="s2", ttl_bars=10)
        last_ts = BASE_TS + timedelta(seconds=300)
        last_bar = _bar(last_ts, 5103.0, 5097.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, last_bar, tf_seconds=60, zone_mfe=0.5, market_mfe=0.5
        )
        # ttl_bars=10 → 600s, last_ts=300s → min(300, 600) = 300 (last_ts wins)
        assert result["exit_at"] == last_ts


@pytest.mark.unit
class TestChronologicalOrdering:
    def test_earlier_signal_activates_before_later_signal(self):
        """Signal with earlier timestamp must be added to live_signals first."""
        replay = _get_replay()
        # sig_early fires at 10:00, sig_late fires at 10:02
        sig_early = _sig("s-early", ts_offset_secs=0)  # ts = 10:00:00
        sig_late = _sig("s-late", ts_offset_secs=120)  # ts = 10:02:00

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
        result = replay.resolve_at_end_of_bars(
            sig, last_bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        assert result["market_entry_outcome"] != "never_activated"


@pytest.mark.unit
class TestBarsInTradeConstraint:
    def test_bars_in_trade_le_ttl(self):
        """market_entry_bars_in_trade can never exceed TTL."""
        replay = _get_replay()
        sig = _sig(ttl_bars=5, market_entry_price=5100.0)
        last_bar = _bar(BASE_TS + timedelta(seconds=300), 5097.0, 5093.0, 5094.0)
        result = replay.resolve_at_end_of_bars(
            sig, last_bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        if result["market_entry_bars_in_trade"] is not None:
            assert result["market_entry_bars_in_trade"] <= sig["ttl_bars"]


@pytest.mark.unit
class TestTrackComparisonInvariants:
    def test_zone_target_full_market_never_activated_is_impossible(self):
        """Zone target_full + market never_activated cannot coexist. Market always fills."""
        from scripts.debug.replay.debug_lifecycle_replay import validate_track_pair

        with pytest.raises(ValueError):
            validate_track_pair(zone_outcome="target_full", market_outcome="never_activated")

    def test_zone_never_activated_market_target_full_is_valid(self):
        from scripts.debug.replay.debug_lifecycle_replay import validate_track_pair

        # Should not raise
        validate_track_pair(zone_outcome="never_activated", market_outcome="target_full")


# ── Chunk 1: TF_TTL_BARS constant location ────────────────────────────────


@pytest.mark.unit
class TestTTLConstants:
    def test_tf_ttl_bars_available_in_service_utils(self):
        from src.core.service_utils import TF_TTL_BARS

        assert TF_TTL_BARS["1m"] == 20
        assert TF_TTL_BARS["5m"] == 12
        assert TF_TTL_BARS["15m"] == 10
        assert TF_TTL_BARS["1h"] == 8
        assert TF_TTL_BARS["4h"] == 6
        assert TF_TTL_BARS["1d"] == 4

    def test_replay_imports_from_service_utils(self):
        """Replay must not define its own TF_TTL_BARS — must import from service_utils."""
        import inspect

        source = inspect.getsource(lifecycle_replay)
        assert "TF_TTL_BARS: dict" not in source  # no local definition
        assert "TF_TTL_BARS" in source  # it is used


# ── Chunk 2: TTL injection + bars_in_trade ────────────────────────────────


@pytest.mark.unit
class TestTTLInjection:
    def test_1m_signal_uses_ttl_20_after_injection(self):
        from src.core.service_utils import TF_TTL_BARS

        sig = _sig(signal_id="ttl-test-1")
        sig.pop("ttl_bars", None)
        sig["ttl_bars"] = TF_TTL_BARS.get("1m", 10)
        assert sig["ttl_bars"] == 20

    def test_15m_signal_uses_ttl_10_after_injection(self):
        from src.core.service_utils import TF_TTL_BARS

        sig = _sig()
        sig.pop("ttl_bars", None)
        sig["ttl_bars"] = TF_TTL_BARS.get("15m", 10)
        assert sig["ttl_bars"] == 10

    def test_resolve_at_end_of_bars_respects_injected_ttl(self):
        replay = _get_replay()
        sig = _sig(signal_id="ttl-eob", ttl_bars=20)
        last_bar = _bar(BASE_TS + timedelta(minutes=25), 5110, 5090, 5100)
        result = replay.resolve_at_end_of_bars(
            sig,
            last_bar,
            tf_seconds=60,
            zone_mfe=0.5,
            market_mfe=0.3,
            zone_activated=False,
            market_entry_price=5100.0,
        )
        # market_bit = min(bars_elapsed, ttl_bars) = min(25, 20) = 20
        assert result["market_entry_bars_in_trade"] == 20

    def test_handle_no_data_uses_injected_ttl(self):
        replay = _get_replay()
        sig = _sig(signal_id="no-data-ttl", ttl_bars=20)
        result = replay.handle_no_data(sig)
        expected_exit = sig["timestamp"] + timedelta(seconds=20 * 60)
        assert result["exit_at"] == expected_exit
        assert result["zone_exit_at"] == expected_exit


# ── Chunk 3: expires_at wall-clock TTL (Phase 107.5) ──────────────────────


@pytest.mark.unit
class TestExpiresAtWallClock:
    def test_resolve_not_yet_expired_returns_none_outcome(self):
        """Signal with expires_at in the future should not be forced to resolve."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-future")
        sig["expires_at"] = BASE_TS + timedelta(hours=2)
        bar = _bar(BASE_TS + timedelta(minutes=30), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.5, market_mfe=0.3
        )
        assert result["zone_outcome"] is None
        assert result["exit_at"] is None

    def test_resolve_expired_with_expires_at_uses_it(self):
        """Signal past expires_at should resolve using expires_at as exit_ts."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-past")
        sig["expires_at"] = BASE_TS + timedelta(minutes=5)
        bar = _bar(BASE_TS + timedelta(minutes=10), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig,
            bar,
            tf_seconds=60,
            zone_mfe=0.5,
            market_mfe=0.3,
            zone_activated=True,
            market_entry_price=5100.0,
        )
        assert result["zone_outcome"] == "ttl_expired_ahead"
        assert result["exit_at"] == sig["expires_at"]

    def test_resolve_no_expires_at_falls_back_to_ttl_bars(self):
        """Signal without expires_at uses ttl_bars * tf_seconds."""
        replay = _get_replay()
        sig = _sig(signal_id="exp-none", ttl_bars=10)
        sig.pop("expires_at", None)
        bar = _bar(BASE_TS + timedelta(minutes=15), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        # exit_at = min(bar_ts, sig_ts + 10*60s) = min(15min, 10min) = 10min
        expected_exit = sig["timestamp"] + timedelta(seconds=10 * 60)
        assert result["exit_at"] == expected_exit

    def test_handle_no_data_uses_expires_at(self):
        """handle_no_data with expires_at uses it as exit_ts."""
        replay = _get_replay()
        sig = _sig(signal_id="nodata-exp")
        sig["expires_at"] = BASE_TS + timedelta(hours=1)
        result = replay.handle_no_data(sig)
        assert result["exit_at"] == sig["expires_at"]

    def test_handle_no_data_fallback_ttl_bars(self):
        """handle_no_data without expires_at falls back to ttl_bars computation."""
        replay = _get_replay()
        sig = _sig(signal_id="nodata-ttl", ttl_bars=60)
        sig.pop("expires_at", None)
        result = replay.handle_no_data(sig)
        expected_exit = sig["timestamp"] + timedelta(seconds=60 * 60)
        assert result["exit_at"] == expected_exit

    def test_not_yet_expired_not_counted_as_processed(self):
        """Not-yet-expired signals should NOT increment processed count.

        This is a critical invariant: resolve_at_end_of_bars returning
        {zone_outcome: None} means the caller should skip the write
        and not count it as processed.
        """
        replay = _get_replay()
        sig = _sig(signal_id="exp-skip")
        sig["expires_at"] = BASE_TS + timedelta(hours=2)
        bar = _bar(BASE_TS + timedelta(minutes=30), 5110.0, 5090.0, 5100.0)
        result = replay.resolve_at_end_of_bars(
            sig, bar, tf_seconds=60, zone_mfe=0.0, market_mfe=0.0
        )
        # The result must be skip-compatible: no zone_outcome, no exit_at
        assert result["zone_outcome"] is None
        # Caller code in _process_symbol_tf checks result["zone_outcome"] is not None
        # before incrementing stats["processed"] — this test documents that contract.
