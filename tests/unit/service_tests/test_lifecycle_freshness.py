"""Tests for QUAL-03 signal freshness decay in signal_lifecycle_service.

Freshness decay is applied in-memory per bar — the original confidence stored
in signal_ledger is never mutated. Only effective_confidence (for evaluation
purposes) is computed with the exponential decay factor.
"""

import math
from datetime import UTC

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_expected_freshness(bars_since: int, half_life: int) -> float:
    """Compute expected exponential freshness factor."""
    lambda_decay = math.log(2) / half_life
    return math.exp(-lambda_decay * bars_since)


# ---------------------------------------------------------------------------
# Tests for _compute_freshness_decay() in signal_lifecycle_service
# ---------------------------------------------------------------------------


class TestFreshnessDecayComputation:
    """_compute_freshness_decay(bars_since, timeframe) → float in [0, 1]."""

    @pytest.mark.unit
    def test_freshness_at_zero_bars_is_one(self):
        """At bars_since=0, freshness=1.0 (no time elapsed since signal fire)."""
        from services.signal_lifecycle_service import _compute_freshness_decay

        freshness = _compute_freshness_decay(bars_since=0, timeframe="1m")
        assert freshness == pytest.approx(1.0, abs=0.0001)

    @pytest.mark.unit
    def test_freshness_at_half_life_is_approx_half(self):
        """At bars_since=half_life_bars, freshness≈0.5 (exponential half-life property)."""
        from services.signal_lifecycle_service import (
            FRESHNESS_HALF_LIFE_BARS,
            _compute_freshness_decay,
        )

        for tf, half_life in FRESHNESS_HALF_LIFE_BARS.items():
            freshness = _compute_freshness_decay(bars_since=half_life, timeframe=tf)
            assert freshness == pytest.approx(
                0.5, abs=0.001
            ), f"Freshness at half_life={half_life} bars for {tf} should be ~0.5, got {freshness}"

    @pytest.mark.unit
    def test_freshness_at_double_half_life_is_approx_quarter(self):
        """At bars_since=2*half_life, freshness≈0.25 (two halvings)."""
        from services.signal_lifecycle_service import (
            FRESHNESS_HALF_LIFE_BARS,
            _compute_freshness_decay,
        )

        tf = "5m"
        half_life = FRESHNESS_HALF_LIFE_BARS[tf]
        freshness = _compute_freshness_decay(bars_since=2 * half_life, timeframe=tf)
        assert freshness == pytest.approx(0.25, abs=0.002)

    @pytest.mark.unit
    def test_freshness_decreases_monotonically(self):
        """Freshness strictly decreases as bars_since increases."""
        from services.signal_lifecycle_service import _compute_freshness_decay

        tf = "1m"
        prev = 1.0
        for bars in [0, 5, 10, 20, 40]:
            freshness = _compute_freshness_decay(bars_since=bars, timeframe=tf)
            assert (
                freshness <= prev + 1e-9
            ), f"Freshness must not increase: bars={bars}, freshness={freshness}, prev={prev}"
            prev = freshness

    @pytest.mark.unit
    def test_freshness_never_negative(self):
        """Freshness is always >= 0.0 even at very large bars_since."""
        from services.signal_lifecycle_service import _compute_freshness_decay

        freshness = _compute_freshness_decay(bars_since=1000, timeframe="1m")
        assert freshness >= 0.0


# ---------------------------------------------------------------------------
# Tests for effective_confidence computation (in-memory, no DB mutation)
# ---------------------------------------------------------------------------


class TestEffectiveConfidenceComputation:
    """effective_confidence = stored_confidence * freshness (in-memory only)."""

    @pytest.mark.unit
    def test_effective_confidence_at_zero_bars_equals_stored(self):
        """At bars_since=0, effective_confidence == stored_confidence."""
        from services.signal_lifecycle_service import (
            _compute_freshness_decay,
        )

        stored_confidence = 0.82
        freshness = _compute_freshness_decay(bars_since=0, timeframe="5m")
        effective = round(stored_confidence * freshness, 4)
        assert effective == pytest.approx(stored_confidence, abs=0.0001)

    @pytest.mark.unit
    def test_effective_confidence_at_half_life_is_half_stored(self):
        """At half_life bars, effective_confidence ≈ stored_confidence / 2."""
        from services.signal_lifecycle_service import (
            FRESHNESS_HALF_LIFE_BARS,
            _compute_freshness_decay,
        )

        stored_confidence = 0.8
        tf = "1m"
        half_life = FRESHNESS_HALF_LIFE_BARS[tf]
        freshness = _compute_freshness_decay(bars_since=half_life, timeframe=tf)
        effective = round(stored_confidence * freshness, 4)
        assert effective == pytest.approx(stored_confidence * 0.5, abs=0.001)

    @pytest.mark.unit
    def test_original_confidence_not_mutated(self):
        """Computing effective_confidence must not mutate the original signal dict."""
        from services.signal_lifecycle_service import (
            FRESHNESS_HALF_LIFE_BARS,
            _compute_freshness_decay,
        )

        sig = {
            "signal_id": "test-123",
            "confidence": 0.75,
            "status": "active",
        }
        original_confidence = sig["confidence"]

        tf = "5m"
        half_life = FRESHNESS_HALF_LIFE_BARS[tf]
        freshness = _compute_freshness_decay(bars_since=half_life, timeframe=tf)
        # Compute effective_confidence without touching sig
        effective = round(sig["confidence"] * freshness, 4)

        # Original signal dict must be unchanged
        assert (
            sig["confidence"] == original_confidence
        ), f"Original confidence {original_confidence} was mutated to {sig['confidence']}"
        # But effective_confidence is different
        assert effective != pytest.approx(original_confidence, abs=0.01)

    @pytest.mark.unit
    def test_freshness_decay_uses_bars_elapsed(self):
        """Freshness decay result depends on bars_since passed in (mock _bars_elapsed pattern)."""
        from services.signal_lifecycle_service import _compute_freshness_decay

        # Simulate: if _bars_elapsed returns 0 vs 10 — different results
        f0 = _compute_freshness_decay(bars_since=0, timeframe="1m")
        f10 = _compute_freshness_decay(bars_since=10, timeframe="1m")
        assert f0 > f10, "Freshness must decrease as bars_since increases"

    @pytest.mark.unit
    def test_freshness_for_unknown_tf_uses_fallback(self):
        """Unknown timeframe falls back to a sensible default (no crash)."""
        from services.signal_lifecycle_service import _compute_freshness_decay

        # Should not raise; uses fallback half_life
        freshness = _compute_freshness_decay(bars_since=5, timeframe="4h")
        assert 0.0 < freshness <= 1.0


# ---------------------------------------------------------------------------
# Integration tests: _compute_freshness_decay() wired into _evaluate_signals_against_bar()
# ---------------------------------------------------------------------------


class TestFreshnessDecayWiring:
    """Integration tests confirming _compute_freshness_decay() is called inside
    _evaluate_signals_against_bar() and that effective_confidence is used at
    both exit paths.

    Test A (RED → GREEN): signal_quality at exit must reflect effective_confidence
    (decayed by freshness), not raw stored confidence.

    Test B (GREEN throughout): update_signal_status is never called with a
    'confidence' keyword argument — stored DB value is immutable.
    """

    def _make_service(self):
        """Build a SignalLifecycleService instance via __new__ (bypasses __init__)."""
        from unittest.mock import MagicMock

        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService.__new__(SignalLifecycleService)
        svc.db_manager = MagicMock()
        svc.db_manager.execute_command = MagicMock(return_value=None)
        svc.active_signals_count = MagicMock()
        svc.point_values = {"ES": 50.0}
        svc._mae = {}
        svc._mfe = {}
        svc._activated_at = {}
        svc._market_mae = {}
        svc._market_mfe = {}
        svc._market_activated_at = {}
        svc._resolved_market = set()
        # Chandelier + staleness + shadow tracking state (added in 32-02)
        svc._chandelier_state = {}
        svc._staleness_consecutive = {}
        svc._shadow_signals = {}
        svc.env_prefix = "test:"
        svc.env_name = "test"
        svc._kafka_producer = None  # KAFKA-08: service uses Kafka; None disables publish
        svc._pending_tasks = set()
        svc.lifecycle_transitions_total = MagicMock()
        svc.logger = MagicMock()
        return svc

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_freshness_decay_called_in_active_exit(self):
        """signal_quality at exit uses effective_confidence (decayed), not raw confidence.

        Signal fires at half_life bars before bar_time on 1m TF.
        With confidence=1.0 and freshness≈0.5, signal_quality should be ≈ pnl_r * 0.5.
        Before the fix: signal_quality == pnl_r * 1.0 → test FAILS (RED).
        After the fix: signal_quality == pnl_r * 0.5 → test PASSES (GREEN).
        """
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from services.signal_lifecycle_service import FRESHNESS_HALF_LIFE_BARS

        svc = self._make_service()

        tf = "1m"
        half_life = FRESHNESS_HALF_LIFE_BARS[tf]  # 20
        bar_time = datetime(2026, 3, 13, 12, 0, 0, tzinfo=UTC)
        signal_ts = bar_time - timedelta(seconds=half_life * 60)  # exactly half_life bars ago

        signal_id = "test-fresh-001"
        svc._activated_at[signal_id] = signal_ts

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 4000.0,
            "stop_loss": 3990.0,
            "targets": [4010.0, 4020.0],
            "entry_zone_low": 3998.0,
            "entry_zone_high": 4002.0,
            "confidence": 1.0,
            "timeframe": tf,
            "symbol": "ES",
            "timestamp": signal_ts,
            "ttl_bars": 100,
        }

        # Bar that triggers target_1 hit (high=4015 >= target_1=4010) → positive pnl_r
        bar = {"high": 4015.0, "low": 4001.0, "close": 4012.0}

        with patch(
            "services.signal_lifecycle_service.record_zone_resolution",
            new_callable=AsyncMock,
        ) as mock_update:
            await svc._evaluate_signals_against_bar(
                symbol="ES",
                timeframe=tf,
                bar=bar,
                bar_time=bar_time,
                all_active=[sig],
            )

        assert mock_update.called, "record_zone_resolution must be called on exit"
        kwargs = mock_update.call_args.kwargs
        signal_quality = kwargs.get("signal_quality")
        pnl_r = kwargs.get("pnl_r")

        assert signal_quality is not None, "signal_quality must be set on exit"
        assert pnl_r is not None, "pnl_r must be set on exit"

        # At half_life bars, freshness ≈ 0.5; effective_confidence = 1.0 * 0.5 = 0.5
        # signal_quality should ≈ pnl_r * 0.5 (not pnl_r * 1.0)
        expected = max(0.0, round(float(pnl_r) * 0.5, 4))
        assert signal_quality == pytest.approx(expected, abs=0.05), (
            f"signal_quality={signal_quality} should be ≈ pnl_r*0.5={expected} "
            f"(pnl_r={pnl_r}); got pnl_r*1.0={max(0.0, round(float(pnl_r)*1.0, 4))} instead"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_freshness_decay_does_not_mutate_signal_ledger_confidence(self):
        """update_signal_status must never receive a 'confidence' keyword argument.

        The stored confidence in signal_ledger is ground truth for ML training
        and must never be overwritten with effective_confidence.

        This test should PASS both before and after the fix.
        """
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from services.signal_lifecycle_service import FRESHNESS_HALF_LIFE_BARS

        svc = self._make_service()

        tf = "1m"
        half_life = FRESHNESS_HALF_LIFE_BARS[tf]
        bar_time = datetime(2026, 3, 13, 12, 0, 0, tzinfo=UTC)
        signal_ts = bar_time - timedelta(seconds=half_life * 60)

        signal_id = "test-fresh-002"
        svc._activated_at[signal_id] = signal_ts

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 4000.0,
            "stop_loss": 3990.0,
            "targets": [4010.0, 4020.0],
            "entry_zone_low": 3998.0,
            "entry_zone_high": 4002.0,
            "confidence": 0.85,
            "timeframe": tf,
            "symbol": "ES",
            "timestamp": signal_ts,
            "ttl_bars": 100,
        }

        bar = {"high": 4015.0, "low": 4001.0, "close": 4012.0}

        with patch(
            "services.signal_lifecycle_service.record_zone_resolution",
            new_callable=AsyncMock,
        ) as mock_update:
            await svc._evaluate_signals_against_bar(
                symbol="ES",
                timeframe=tf,
                bar=bar,
                bar_time=bar_time,
                all_active=[sig],
            )

        assert mock_update.called, "record_zone_resolution must be called on exit"
        kwargs = mock_update.call_args.kwargs

        assert "confidence" not in kwargs, (
            f"record_zone_resolution must NOT receive 'confidence' kwarg — "
            f"stored DB confidence is immutable. Got kwargs keys: {list(kwargs.keys())}"
        )
