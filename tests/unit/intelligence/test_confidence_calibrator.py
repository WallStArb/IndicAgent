"""Unit tests for confidence_calibrator.py — CAL-01, CAL-02."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.ml.confidence_calibrator import (
    _compute_ece,
    _fit_curve,
    _run_cis_calibration,
    run_calibration_update,
)


def _make_rows(n: int, win_fraction: float = 0.6, symbol: str = "ES") -> list[dict]:
    """Generate n fake signal_ledger rows with alternating wins/losses.

    Uses key "x_input" to match the SQL alias `cis_score AS x_input` in
    run_calibration_update() (Phase 112 CR-03 fix). Uses boolean "is_win" to
    match the migrated 3-table read `(counterfactual_pnl_r > 0) AS is_win`
    (Phase 127-00: 8-class outcome collapsed to 2-class win/loss).
    """
    rows = []
    for i in range(n):
        is_win = (i / n) < win_fraction
        rows.append(
            {
                "setup_plugin": "trad_TrendFollowing",
                "timeframe": "1m",
                "symbol": symbol,
                "x_input": round(0.3 + 0.5 * (i / max(n - 1, 1)), 4),
                "is_win": is_win,
            }
        )
    return rows


def test_fit_curve_returns_correct_shapes():
    rows = _make_rows(150)
    confidences = [r["x_input"] for r in rows]
    win_labels = [1.0 if r["is_win"] else 0.0 for r in rows]
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
    """Groups with N < 100: no upserts, but two DELETEs (one per-plugin, one CIS)."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=_make_rows(50))
    db_manager.execute_command = AsyncMock()

    await run_calibration_update(db_manager)
    # 2 DELETE calls: clear confidence_calibration + clear CIS calibration_curves
    assert db_manager.execute_command.call_count == 2
    sqls = [c[0][0] for c in db_manager.execute_command.call_args_list]
    assert any("DELETE FROM confidence_calibration" in s for s in sqls)
    assert any("DELETE FROM calibration_curves" in s for s in sqls)


@pytest.mark.asyncio
async def test_run_calibration_update_trains_when_sufficient():
    """Groups with N >= 100: per-plugin upsert + stale DELETE + CIS upsert + CIS DELETE."""
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=_make_rows(120))
    db_manager.execute_command = AsyncMock()

    await run_calibration_update(db_manager)
    # 4 calls: per-plugin upsert, per-plugin stale DELETE, CIS upsert, CIS stale DELETE
    assert db_manager.execute_command.call_count == 4
    calls = db_manager.execute_command.call_args_list
    # First call: per-plugin upsert to confidence_calibration
    upsert_call = calls[0]
    assert upsert_call[0][1] == "trad_TrendFollowing"
    assert upsert_call[0][2] == "1m"
    assert isinstance(upsert_call[0][3], list)  # breakpoints
    assert isinstance(upsert_call[0][4], list)  # values
    # Second call: per-plugin stale DELETE
    assert "DELETE FROM confidence_calibration" in calls[1][0][0]
    # Third call: CIS upsert to calibration_curves
    cis_upsert = calls[2]
    assert cis_upsert[0][1] == "_cis_"
    assert cis_upsert[0][2] == "1m"  # timeframe
    assert cis_upsert[0][3] == "ES"  # symbol
    assert isinstance(cis_upsert[0][4], dict)  # curve_data with breakpoints/values
    # Fourth call: CIS stale DELETE
    assert "DELETE FROM calibration_curves" in calls[3][0][0]
    assert "setup_plugin = '_cis_'" in calls[3][0][0]


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


@pytest.mark.asyncio
async def test_run_cis_calibration_writes_to_calibration_curves():
    """CIS pass writes rows with setup_plugin='_cis_' to calibration_curves table."""
    db_manager = MagicMock()
    db_manager.execute_command = AsyncMock()
    rows = _make_rows(120, symbol="NQ")

    await _run_cis_calibration(db_manager, rows)

    # 2 calls: upsert + stale DELETE
    assert db_manager.execute_command.call_count == 2
    upsert = db_manager.execute_command.call_args_list[0]
    assert "INSERT INTO calibration_curves" in upsert[0][0]
    assert upsert[0][1] == "_cis_"
    assert upsert[0][2] == "1m"  # timeframe
    assert upsert[0][3] == "NQ"  # symbol
    assert isinstance(upsert[0][4], dict)
    assert "breakpoints" in upsert[0][4]
    assert "values" in upsert[0][4]


@pytest.mark.asyncio
async def test_run_cis_calibration_clears_on_no_trained_keys():
    """When no group meets N>=100, all CIS rows are deleted."""
    db_manager = MagicMock()
    db_manager.execute_command = AsyncMock()
    rows = _make_rows(50, symbol="ES")  # below threshold

    await _run_cis_calibration(db_manager, rows)

    assert db_manager.execute_command.call_count == 1
    delete_sql = db_manager.execute_command.call_args[0][0]
    assert "DELETE FROM calibration_curves" in delete_sql
    assert "setup_plugin = '_cis_'" in delete_sql


@pytest.mark.asyncio
async def test_run_cis_calibration_multiple_symbols():
    """Each (timeframe, symbol) pair gets its own curve row."""
    db_manager = MagicMock()
    db_manager.execute_command = AsyncMock()
    rows = _make_rows(120, symbol="ES") + _make_rows(120, symbol="NQ")

    await _run_cis_calibration(db_manager, rows)

    # 2 upserts (one per symbol) + 1 stale DELETE
    assert db_manager.execute_command.call_count == 3
    symbols_written = {c[0][3] for c in db_manager.execute_command.call_args_list[:2]}
    assert symbols_written == {"ES", "NQ"}
