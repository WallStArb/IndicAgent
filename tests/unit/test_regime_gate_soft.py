"""Unit tests for three-band regime gate soft multiplier (Phase 82 Plan 04).

Tests cover:
- All three bands (suppress / soft / full)
- Boundary conditions at prob_min and prob_soft_max
- Entropy interaction in soft band
- Division-by-zero safety when prob_soft_max == prob_min
- Prometheus counter increments per band
- Settings wire-through (REGIME_PROB_SOFT_MAX, REGIME_PROB_MIN)

No external dependencies (DB, Kafka, network) — purely in-memory.
"""

from __future__ import annotations

import asyncio
import math
from unittest.mock import MagicMock, patch

from src.config.settings import Settings
from src.intelligence.pipeline.regime_gate import (
    SOFT_BAND_FLOOR,
    _entropy_multiplier,
    apply_regime_gate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(prob: float, conf: float = 1.0) -> tuple[list[dict], dict]:
    """Return (signals, regime_data) shaped for apply_regime_gate."""
    signals = [
        {
            "signal_id": "test-sig-001",
            "setup_plugin": "TestPlugin",
            "regime_type": "any",
            "confidence": conf,
            "calibrated_confidence": conf,
        }
    ]
    regime_data = {
        "hmm_regime": 1,
        "hmm_regime_prob": prob,
        "hmm_regime_duration": 5,
    }
    return signals, regime_data


def _run(coro):
    """Run an async function synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test _entropy_multiplier directly
# ---------------------------------------------------------------------------


def test_entropy_multiplier_boundary_low():
    """At prob == prob_min, multiplier should equal SOFT_BAND_FLOOR (0.5)."""
    m = _entropy_multiplier(0.30, None, 0.30, 0.55)
    assert abs(m - SOFT_BAND_FLOOR) < 1e-3, f"Expected ~{SOFT_BAND_FLOOR}, got {m}"


def test_entropy_multiplier_boundary_high():
    """At prob just below prob_soft_max, multiplier should be approximately 1.0."""
    m = _entropy_multiplier(0.5499, None, 0.30, 0.55)
    assert abs(m - 1.0) < 1e-2, f"Expected ~1.0, got {m}"


def test_entropy_multiplier_division_safety():
    """When prob_soft_max == prob_min, should return a finite float (no ZeroDivisionError)."""
    m = _entropy_multiplier(0.30, None, 0.30, 0.30)
    assert math.isfinite(m), f"Expected finite float, got {m}"


# ---------------------------------------------------------------------------
# Integration tests via apply_regime_gate
# ---------------------------------------------------------------------------


def test_suppress_below_prob_min():
    """Signal with hmm_regime_prob < REGIME_PROB_MIN is suppressed."""
    signals, regime_data = _make_signal(prob=0.25)
    result = _run(apply_regime_gate(signals, regime_data, prob_min=0.30, prob_soft_max=0.55))
    assert len(result) == 1
    s = result[0]
    assert s["regime_eligible"] is False
    assert s["suppression_reason"] == "regime_prob"


def test_soft_band_attenuates_confidence():
    """Signal in soft band: eligible but calibrated_confidence strictly less than input."""
    signals, regime_data = _make_signal(prob=0.42, conf=1.0)
    # No entropy in regime_data — only prob-based attenuation
    result = _run(apply_regime_gate(signals, regime_data, prob_min=0.30, prob_soft_max=0.55))
    assert len(result) == 1
    s = result[0]
    assert s["regime_eligible"] is True
    assert s.get("suppression_reason") is None
    assert (
        s["calibrated_confidence"] < 1.0
    ), f"Expected attenuation, calibrated_confidence={s['calibrated_confidence']}"


def test_soft_band_eligible_with_high_entropy_further_reduces():
    """High entropy (uniform 3-state = log2(3)) reduces confidence further than zero-entropy."""
    prob = 0.42
    signals_zero_entropy, regime_zero = _make_signal(prob=prob, conf=1.0)
    regime_zero["hmm_regime_entropy"] = 0.0

    signals_high_entropy, regime_high = _make_signal(prob=prob, conf=1.0)
    regime_high["hmm_regime_entropy"] = math.log2(3)

    result_zero = _run(
        apply_regime_gate(signals_zero_entropy, regime_zero, prob_min=0.30, prob_soft_max=0.55)
    )
    result_high = _run(
        apply_regime_gate(signals_high_entropy, regime_high, prob_min=0.30, prob_soft_max=0.55)
    )

    conf_zero = result_zero[0]["calibrated_confidence"]
    conf_high = result_high[0]["calibrated_confidence"]

    assert (
        conf_high < conf_zero
    ), f"High entropy should reduce confidence further: zero={conf_zero}, high={conf_high}"


def test_full_band_unchanged_confidence():
    """Signal with hmm_regime_prob >= REGIME_PROB_SOFT_MAX: confidence exactly 1.0."""
    signals, regime_data = _make_signal(prob=0.70, conf=1.0)
    result = _run(apply_regime_gate(signals, regime_data, prob_min=0.30, prob_soft_max=0.55))
    assert len(result) == 1
    s = result[0]
    assert s["regime_eligible"] is True
    # calibrated_confidence should not be modified by the soft path
    assert s.get("calibrated_confidence", 1.0) == 1.0


def test_counter_increments_in_soft_band():
    """Counter.labels(band='soft').inc() is called when processing a soft-band signal."""
    signals, regime_data = _make_signal(prob=0.42, conf=1.0)

    with patch(
        "src.intelligence.pipeline.regime_gate.REGIME_SOFT_GATE_SIGNALS_TOTAL"
    ) as mock_counter:
        mock_label_obj = MagicMock()
        mock_counter.labels.return_value = mock_label_obj

        _run(apply_regime_gate(signals, regime_data, prob_min=0.30, prob_soft_max=0.55))

        # Verify labels(band="soft") was called and inc() invoked
        called_with_soft = any(
            call_args == ((), {"band": "soft"})
            for call_args in [(args, kwargs) for args, kwargs in mock_counter.labels.call_args_list]
        )
        assert (
            called_with_soft
        ), f"Expected labels(band='soft') call, got: {mock_counter.labels.call_args_list}"
        assert mock_label_obj.inc.called


def test_settings_wire_through():
    """Settings.REGIME_PROB_SOFT_MAX == 0.55 and Settings.REGIME_PROB_MIN == 0.30."""
    s = Settings()
    assert s.REGIME_PROB_SOFT_MAX == 0.55
    assert s.regime_prob_min == 0.30
