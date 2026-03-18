"""Unit tests for confidence_calibrator.py — CAL-01, CAL-02."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from src.intelligence.ml.confidence_calibrator import (
    _compute_ece,
    _fit_curve,
    run_calibration_update,
    _MIN_SAMPLE_SIZE,
)


def _make_rows(n: int, win_fraction: float = 0.6) -> list[dict]:
    """Generate n fake signal_ledger rows with alternating wins/losses."""
    rows = []
    for i in range(n):
        is_win = (i / n) < win_fraction
        rows.append(
            {
                "setup_plugin": "trad_TrendFollowing",
                "timeframe": "1m",
                "confidence": round(0.3 + 0.5 * (i / max(n - 1, 1)), 4),
                "outcome": "target_1" if is_win else "stopped_in_trade",
            }
        )
    return rows


def test_fit_curve_returns_correct_shapes():
    rows = _make_rows(150)
    confidences = [r["confidence"] for r in rows]
    win_labels = [1.0 if r["outcome"] == "target_1" else 0.0 for r in rows]
    bp, vals, ece = _fit_curve(confidences, win_labels)
    assert isinstance(bp, list)
    assert isinstance(vals, list)
    assert len(bp) == len(vals)
    assert 0.0 <= ece <= 1.0


def test_ece_perfect_calibration():
    """Perfect calibration: confidence = fraction of wins → ECE ≈ 0."""
    import numpy as np

    n = 1000
    confidences = np.linspace(0.0, 1.0, n)
    # win_label[i] = 1 if random < confidence[i] — approximate perfect calibration
    rng = np.random.default_rng(42)
    win_labels = (rng.random(n) < confidences).astype(float)
    ece = _compute_ece(confidences, win_labels)
    assert ece < 0.1  # perfect calibration produces near-zero ECE


@pytest.mark.asyncio
async def test_run_calibration_update_skips_below_min_sample():
    """Groups with N < 100 should not upsert any rows, but should clear all curves."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=_make_rows(50))
    db_manager.execute_command = AsyncMock()

    await run_calibration_update(db_manager)
    # No upsert, but one DELETE (clear all stale curves since no trained keys)
    assert db_manager.execute_command.call_count == 1
    delete_sql = db_manager.execute_command.call_args[0][0]
    assert "DELETE FROM confidence_calibration" in delete_sql


@pytest.mark.asyncio
async def test_run_calibration_update_trains_when_sufficient():
    """Groups with N >= 100 should upsert calibration curve and delete stale rows."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=_make_rows(120))
    db_manager.execute_command = AsyncMock()

    await run_calibration_update(db_manager)
    # 2 calls: 1 upsert + 1 stale-row DELETE
    assert db_manager.execute_command.call_count == 2
    upsert_call = db_manager.execute_command.call_args_list[0]
    assert upsert_call[0][1] == "trad_TrendFollowing"
    assert upsert_call[0][2] == "1m"
    assert isinstance(upsert_call[0][3], list)  # breakpoints
    assert isinstance(upsert_call[0][4], list)  # values
    # Second call is DELETE
    delete_call = db_manager.execute_command.call_args_list[1]
    assert "DELETE FROM confidence_calibration" in delete_call[0][0]


@pytest.mark.asyncio
async def test_run_calibration_update_isolates_exceptions():
    """Exception inside calibrator must not propagate to caller."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(side_effect=RuntimeError("DB down"))

    # Should not raise
    await run_calibration_update(db_manager)


@pytest.mark.asyncio
async def test_run_calibration_update_empty_rows_returns_early():
    """No rows → no execute_command calls."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=[])
    db_manager.execute_command = AsyncMock()

    await run_calibration_update(db_manager)
    db_manager.execute_command.assert_not_called()
