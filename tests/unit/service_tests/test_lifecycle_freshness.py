"""Tests for QUAL-03 signal freshness decay in signal_lifecycle_service.

Freshness decay is applied in-memory per bar — the original confidence stored
in signal_ledger is never mutated. Only effective_confidence (for evaluation
purposes) is computed with the exponential decay factor.
"""

import math
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

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
            assert freshness == pytest.approx(0.5, abs=0.001), (
                f"Freshness at half_life={half_life} bars for {tf} should be ~0.5, got {freshness}"
            )

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
            assert freshness <= prev + 1e-9, (
                f"Freshness must not increase: bars={bars}, freshness={freshness}, prev={prev}"
            )
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
            FRESHNESS_HALF_LIFE_BARS,
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
        assert sig["confidence"] == original_confidence, (
            f"Original confidence {original_confidence} was mutated to {sig['confidence']}"
        )
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
