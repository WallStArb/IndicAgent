"""Behavior tests for TransformRecorder wiring in pipeline stages.

Verifies:
- Each stage emits correct (transform_id, dag_order, segment_key) records
- No-recorder path produces output identical to pre-Phase-72 behavior
- Missing signal_id skips record() without crashing
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.quality_gate import apply_quality_gate
from src.intelligence.pipeline.ranker import rank_signals
from src.intelligence.pipeline.regime_gate import apply_regime_gate
from src.intelligence.pipeline.tod_adjuster import apply_tod_adjustment

# ---------------------------------------------------------------------------
# quality_gate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_gate_no_recorder_unchanged():
    """No-recorder path: confidence = min(hurst_q, entropy_q) * drift_penalty."""
    sigs = [{"signal_id": "s1", "confidence": 1.0, "regime_type": "trend"}]
    thresholds = {"hurst_quality": 0.5, "entropy_quality": 0.8, "drift_penalty": 0.9}
    out = await apply_quality_gate(sigs, thresholds)
    # min(0.5, 0.8) * 0.9 = 0.45
    assert abs(out[0]["confidence"] - 0.45) < 1e-6
    assert out[0]["quality_score"] == round(0.5 * 0.9, 4)


@pytest.mark.asyncio
async def test_quality_gate_emits_two_records():
    """With recorder, single signal → exactly 2 record() calls."""
    rec = AsyncMock()
    sigs = [{"signal_id": "s1", "confidence": 1.0, "regime_type": "trend"}]
    thresholds = {"hurst_quality": 0.5, "entropy_quality": 0.8, "drift_penalty": 0.9}
    await apply_quality_gate(sigs, thresholds, tf="5m", recorder=rec)
    assert rec.record.await_count == 2
    transform_ids = {call.kwargs["transform_id"] for call in rec.record.await_args_list}
    assert transform_ids == {"hurst_quality", "drift_penalty"}
    dag_orders = {call.kwargs["dag_order"] for call in rec.record.await_args_list}
    assert dag_orders == {0, 1}


@pytest.mark.asyncio
async def test_quality_gate_segment_key_format():
    """segment_key must be '{regime_type}.{tf}'."""
    rec = AsyncMock()
    sigs = [{"signal_id": "s1", "confidence": 1.0, "regime_type": "mean_reversion"}]
    thresholds = {"hurst_quality": 0.6, "entropy_quality": 0.7, "drift_penalty": 1.0}
    await apply_quality_gate(sigs, thresholds, tf="15m", recorder=rec)
    for call in rec.record.await_args_list:
        assert call.kwargs["segment_key"] == "mean_reversion.15m"


# ---------------------------------------------------------------------------
# regime_gate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regime_gate_records_multiplier_zero_when_suppressed():
    """Suppressed signal → multiplier=0.0 in regime_gate record."""
    rec = AsyncMock()
    # hmm_regime=0 (ranging) but plugin is trend type → suppressed
    regime_data = {"hmm_regime": 0, "hmm_regime_prob": 0.8, "hmm_regime_duration": 5}
    sigs = [{"signal_id": "s1", "confidence": 0.7, "regime_type": "trend"}]
    out = await apply_regime_gate(sigs, regime_data, recorder=rec)
    assert out[0]["regime_eligible"] is False
    assert rec.record.await_count == 1
    call_kwargs = rec.record.await_args_list[0].kwargs
    assert call_kwargs["transform_id"] == "regime_gate"
    assert call_kwargs["dag_order"] == 2
    assert call_kwargs["multiplier"] == 0.0


@pytest.mark.asyncio
async def test_regime_gate_records_multiplier_one_when_eligible():
    """Eligible signal → multiplier=1.0 in regime_gate record."""
    rec = AsyncMock()
    # hmm_regime=1 (trending), prob=0.9, dur=3 → trend plugin eligible
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.9, "hmm_regime_duration": 3}
    sigs = [{"signal_id": "s1", "confidence": 0.7, "regime_type": "trend"}]
    out = await apply_regime_gate(sigs, regime_data, recorder=rec)
    assert out[0]["regime_eligible"] is True
    call_kwargs = rec.record.await_args_list[0].kwargs
    assert call_kwargs["multiplier"] == 1.0


# ---------------------------------------------------------------------------
# tod_adjuster tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tod_records_segment_includes_hour():
    """segment_key must be '{regime_type}.{tf}.{hour_et}'."""
    rec = AsyncMock()
    sigs = [
        {
            "signal_id": "s1",
            "confidence": 0.8,
            "regime_type": "trend",
            "regime_type_at_fire": "trend",
        }
    ]
    await apply_tod_adjustment(sigs, {}, tf="5m", hour_et=14, recorder=rec)
    assert rec.record.await_count == 1
    call_kwargs = rec.record.await_args_list[0].kwargs
    assert call_kwargs["transform_id"] == "tod"
    assert call_kwargs["dag_order"] == 3
    assert call_kwargs["segment_key"] == "trend.5m.14"


@pytest.mark.asyncio
async def test_tod_no_recorder_unchanged():
    """No-recorder path: confidence multiplied by tod_multiplier."""
    sigs = [
        {
            "signal_id": "s1",
            "confidence": 1.0,
            "regime_type": "any",
            "regime_type_at_fire": "any",
        }
    ]
    # hour_et=15 → prior 1.10 for "any"
    out = await apply_tod_adjustment(sigs, {}, tf="1m", hour_et=15)
    assert abs(out[0]["confidence"] - 1.1) < 1e-6
    assert abs(out[0]["tod_multiplier"] - 1.1) < 1e-6


# ---------------------------------------------------------------------------
# calibrator tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calibrator_records_ratio():
    """Calibrator records ratio = calibrated / raw."""
    rec = AsyncMock()
    import numpy as np

    # Build a simple calibration curve: interp at 0.5 → 0.4
    breakpoints = np.array([0.0, 1.0])
    values = np.array([0.0, 0.8])  # linear, so interp(0.5) = 0.4
    cal_curves = {("MyPlugin", "5m", "*"): (breakpoints, values)}
    sigs = [{"signal_id": "s1", "confidence": 0.5, "setup_plugin": "MyPlugin"}]
    out = await apply_calibration(sigs, cal_curves, tf="5m", recorder=rec)
    calibrated = out[0]["confidence"]
    assert abs(calibrated - 0.4) < 1e-4
    assert rec.record.await_count == 1
    call_kwargs = rec.record.await_args_list[0].kwargs
    assert call_kwargs["transform_id"] == "isotonic"
    assert call_kwargs["dag_order"] == 4
    assert abs(call_kwargs["multiplier"] - (0.4 / 0.5)) < 1e-4


@pytest.mark.asyncio
async def test_calibrator_skips_record_when_raw_zero():
    """Calibrator must NOT call record() when raw_confidence == 0 (div-by-zero guard)."""
    rec = AsyncMock()
    sigs = [{"signal_id": "s1", "confidence": 0.0, "setup_plugin": "MyPlugin"}]
    await apply_calibration(sigs, {}, tf="5m", recorder=rec)
    assert rec.record.await_count == 0


# ---------------------------------------------------------------------------
# ranker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ranker_records_perf_multiplier():
    """Ranker records perf_multiplier=0.85 with transform_id=perf_weight, dag_order=5."""
    rec = AsyncMock()
    perf_weights = {("TrendFollowing", "5m", "*"): 0.85}
    sigs = [{"signal_id": "s1", "confidence": 0.8, "setup_plugin": "TrendFollowing"}]
    out = await rank_signals(sigs, perf_weights, tf="5m", recorder=rec)
    assert out[0]["perf_multiplier"] == 0.85
    assert rec.record.await_count == 1
    call_kwargs = rec.record.await_args_list[0].kwargs
    assert call_kwargs["transform_id"] == "perf_weight"
    assert call_kwargs["dag_order"] == 5
    assert abs(call_kwargs["multiplier"] - 0.85) < 1e-6


# ---------------------------------------------------------------------------
# no signal_id → skip record() (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_signal_id_skips_record():
    """Signal dict without signal_id → recorder.record never called (no crash)."""
    rec = AsyncMock()
    sigs = [{"confidence": 0.8, "regime_type": "trend"}]  # no signal_id
    thresholds = {"hurst_quality": 0.9, "entropy_quality": 0.9, "drift_penalty": 0.9}
    await apply_quality_gate(sigs, thresholds, tf="5m", recorder=rec)
    assert rec.record.await_count == 0
